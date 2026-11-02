#!/usr/bin/env python3
"""Synthetic admission/wiring controls, never target-driver qualification."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mdio_gate', ROOT / '.github/scripts/verify-mdio-lifecycle-repairs.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class Admission(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.dp, self.ssdk = [self.root / n for n in ['source', 'dp', 'ssdk']]
        self.profile = copy.deepcopy(json.loads(gate.PROFILE.read_text()))
        for group, tree in [('dp', self.dp), ('ssdk', self.ssdk)]:
            item = self.profile[group]
            package = self.source / 'package/qca-nss' / item['package']
            for entries, base in [(item['prepared_files'], tree), (item['patches'], package / 'patches')]:
                for name in entries:
                    target = base / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(('TESTONLY admission bytes:' + name).encode())
                    entries[name] = gate.sha(target.read_bytes())
            package.joinpath('Makefile').write_text('TESTONLY recipe')
            item['recipe_sha256'] = gate.sha(package.joinpath('Makefile').read_bytes())
        for name in self.profile['assets']:
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('TESTONLY asset')
            self.profile['assets'][name] = gate.sha(target.read_bytes())

    def admit(self):
        return gate.admit(self.source, self.dp, self.ssdk, self.profile)

    def reject(self):
        with self.assertRaises((ValueError, OSError)):
            self.admit()

    def test_consistent_admission_does_not_run_code(self):
        self.assertEqual(self.admit(), self.profile)

    def test_prepared_drift(self):
        (self.ssdk / 'src/init/ssdk_plat.c').write_text('changed')
        self.reject()

    def test_patch_drift(self):
        path = self.source / 'package/qca-nss/qca-ssdk/patches'
        (path / sorted(self.profile['ssdk']['patches'])[-1]).write_text('changed')
        self.reject()

    def test_patch_added(self):
        (self.source / 'package/qca-nss/qca-ssdk/patches/048-unreviewed.patch').write_text('extra')
        self.reject()

    def test_patch_missing(self):
        path = self.source / 'package/qca-nss/qca-nss-dp/patches'
        (path / sorted(self.profile['dp']['patches'])[-1]).unlink()
        self.reject()

    def test_recipe_drift(self):
        (self.source / 'package/qca-nss/qca-ssdk/Makefile').write_text('unreviewed release')
        self.reject()

    def test_test_asset_drift(self):
        (self.source / 'tests/test-ssdk-phy-node-leases.py').write_text('changed')
        self.reject()

    def test_prepared_symlink(self):
        path = self.ssdk / 'src/init/ssdk_dts.c'
        other = self.root / 'outside'; path.rename(other); path.symlink_to(other)
        self.reject()

    def test_parent_symlink(self):
        path = self.ssdk / 'src'; other = self.root / 'outside'
        path.rename(other); path.symlink_to(other)
        self.reject()

    def test_incomplete_inventory(self):
        self.profile['ssdk']['prepared_files'].pop('src/init/ssdk_plat.c')
        self.reject()

    def test_boolean_schema(self):
        self.profile['schema'] = True; self.reject()

    def test_unknown_profile(self):
        self.profile['profile'] = 'accept_old_or_new'; self.reject()

    def test_duplicate_json_field(self):
        with self.assertRaises(ValueError):
            json.loads('{"schema":1,"schema":1}', object_pairs_hook=gate.unique)


class Wiring(unittest.TestCase):
    def test_actual_discovery_zero_one_multiple_and_nested(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        step = workflow.split('      - name: Validate reviewed MDIO lifecycle source and host regressions\n', 1)[1].split('\n      - ', 1)[0]
        script = '\n'.join(line[10:] for line in step.split('        run: |\n', 1)[1].splitlines()) + '\n'
        for dp_count, ssdk_count, nested in [(0, 1, False), (1, 0, False), (2, 1, False),
                                             (1, 2, False), (1, 1, False), (1, 1, True)]:
            with self.subTest(dp=dp_count, ssdk=ssdk_count, nested=nested), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                prepared = root / 'build_dir/target-aarch64_cortex-a53_musl/linux-qualcommax_ipq807x'
                prepared.mkdir(parents=True)
                for stem, count in [('qca-nss-dp', dp_count), ('qca-ssdk', ssdk_count)]:
                    for i in range(count): (prepared / (stem + '-' + str(i))).mkdir()
                if nested: (prepared / 'old/quarantine/qca-nss-dp-stale').mkdir(parents=True)
                binary = root / 'bin'; binary.mkdir()
                recorder = binary / 'python3'
                # Records the CLI handoff only; does not fake a driver regression result.
                recorder.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$MDIO_TEST_RECORD"\n')
                recorder.chmod(0o755)
                record = root / 'argv'
                env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
                           GITHUB_WORKSPACE=str(ROOT), MDIO_TEST_RECORD=str(record))
                ran = subprocess.run([os.environ.get('AX6_TEST_BASH', shutil.which('bash')), '-s'],
                                     input=script, cwd=root, env=env, text=True, capture_output=True)
                expected = dp_count == ssdk_count == 1
                self.assertEqual(ran.returncode == 0, expected, ran.stderr)
                self.assertEqual(record.exists(), expected)
                if expected:
                    args = record.read_text().splitlines()
                    self.assertEqual(args[args.index('--dp') + 1], str(prepared.relative_to(root) / 'qca-nss-dp-0'))
                    self.assertEqual(args[args.index('--ssdk') + 1], str(prepared.relative_to(root) / 'qca-ssdk-0'))

    def test_real_prepared_trees_and_preserved_order(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        call = 'python3 "$GITHUB_WORKSPACE/.github/scripts/verify-mdio-lifecycle-repairs.py"'
        self.assertEqual(workflow.count(call), 1)
        self.assertIn('--source-root . --dp "$lifecycle_dp_source" --ssdk "$lifecycle_ssdk_source" --cc cc', workflow)
        marker = '      - name: Validate reviewed MDIO lifecycle source and host regressions\n'
        self.assertEqual(workflow.count(marker), 1)
        step = workflow.split(marker, 1)[1].split('\n      - ', 1)[0]
        self.assertIn(call, step)
        self.assertIn('test "${#lifecycle_dp_sources[@]}" -eq 1', step)
        self.assertIn('test "${#lifecycle_ssdk_sources[@]}" -eq 1', step)
        self.assertLess(workflow.index('make target/linux/prepare V=s'), workflow.index(call))
        self.assertLess(workflow.index('make package/qca-nss/qca-ssdk/prepare V=s'), workflow.index(call))
        self.assertLess(workflow.index('make package/qca-nss/qca-nss-dp/prepare V=s'), workflow.index(call))
        self.assertIn('python3 -B tests/test-mdio-lifecycle-gate.py', (ROOT / '.github/workflows/lint.yml').read_text())


if __name__ == '__main__':
    unittest.main()
