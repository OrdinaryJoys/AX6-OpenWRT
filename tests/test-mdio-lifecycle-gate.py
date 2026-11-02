#!/usr/bin/env python3
"""Synthetic admission/wiring controls, never target-driver qualification."""
import copy
import importlib.util
import json
from pathlib import Path
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
    def test_real_prepared_trees_and_preserved_order(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        call = 'python3 "$GITHUB_WORKSPACE/.github/scripts/verify-mdio-lifecycle-repairs.py"'
        self.assertEqual(workflow.count(call), 1)
        self.assertIn('--source-root . --dp "$nss_dp_dir" --ssdk "$ssdk_dir" --cc cc', workflow)
        self.assertLess(workflow.index('make target/linux/prepare V=s'), workflow.index(call))
        self.assertLess(workflow.index('make package/qca-nss/qca-ssdk/prepare V=s'), workflow.index(call))
        self.assertLess(workflow.index('make package/qca-nss/qca-nss-dp/prepare V=s'), workflow.index(call))
        self.assertIn('python3 -B tests/test-mdio-lifecycle-gate.py', (ROOT / '.github/workflows/lint.yml').read_text())


if __name__ == '__main__':
    unittest.main()
