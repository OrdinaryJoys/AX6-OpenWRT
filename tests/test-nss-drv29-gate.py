#!/usr/bin/env python3
"""Local gate controls; fixture results are not DRV29 host admission."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('drv29_gate', ROOT / '.github/scripts/verify-nss-drv29.py')
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class Admission(unittest.TestCase):
    def test_active_contract_and_firmware_lock_match(self):
        profile = GATE.configuration()
        GATE.current_lock(profile)
        prepared, patches = GATE.expectations(profile, GATE.frozen.configuration())
        self.assertEqual(len(patches), 31)
        self.assertEqual(len(prepared[29]), 487)

    def test_reviewed_prior_and_independent_delta(self):
        old = GATE.frozen.configuration()
        prior = old['current_code_files'] | GATE.frozen.AUXILIARY
        for _, _, _, name, digest, _ in GATE.PRIOR:
            prior[name] = digest
        changed = {'nss_init.c': 'a' * 64}
        added = {'nss_conn_table.c': 'b' * 64}
        profile = {'changed_files': changed, 'added_files': added, 'patch_name': '033-unit.patch',
                   'patch_sha256': 'c' * 64, 'inventory_sha256': GATE.base.invhash(prior | changed | added)}
        trees, patches = GATE.expectations(profile, old)
        self.assertEqual(GATE.base.invhash(trees[32]), '670eafd37122a56970c069f2c278230a223551c9340266d5c7d3edc10a3234d4')
        self.assertEqual(trees[29], prior | changed | added)
        self.assertEqual(trees[27], old['current_code_files'] | GATE.frozen.AUXILIARY)
        self.assertEqual(len(patches), 31)
        for change, pattern in [
            ({'inventory_sha256': 'd' * 64}, 'independent final inventory'),
            ({'changed_files': {'new.c': 'd' * 64}}, 'delta shape'),
            ({'added_files': {'nss_init.c.orig': 'd' * 64}}, 'delta shape'),
        ]:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, pattern):
                GATE.expectations(profile | change, old)

    def test_unsealed_or_modified_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'profile.json'
            profile.write_text('{}\n')
            for digest in (None, 'a' * 64):
                with patch.object(GATE, 'PROFILE', profile), patch.object(GATE, 'PROFILE_SHA256', digest):
                    with self.assertRaisesRegex(ValueError, 'not sealed'):
                        GATE.configuration()

    def test_patch_reverse_rejects_relocated_hunk_even_if_inventory_would_match(self):
        for offset in ('', 'offset line\n'):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / 'source'
                source.mkdir()
                (source / 'x.c').write_text(offset + 'keep one\nnew\nkeep two\n')
                diff = root / '033-example.patch'
                diff.write_text('--- a/x.c\n+++ b/x.c\n@@ -1,3 +1,3 @@\n keep one\n-old\n+new\n keep two\n')
                expected = {'x.c': GATE.sha((offset + 'keep one\nold\nkeep two\n').encode())}
                args = (root, {'commands': []}, diff.name, diff, source, root / 'target',
                        GATE.base.inventory(source), expected, 'patch')
                if offset:
                    with self.assertRaisesRegex(ValueError, 'no fuzz or offsets'):
                        GATE.reverse(*args)
                else:
                    GATE.reverse(*args)
                    self.assertEqual(GATE.base.inventory(root / 'target'), expected)
                self.assertIn('new', (source / 'x.c').read_text())

    def test_old_gate_gets_frozen_executable_and_explicit_lock(self):
        def fake_child(output, result, label, argv):
            self.assertEqual(label, 'frozen-drv27')
            self.assertEqual(argv[3:7], ['--source-root', output / 'old-source',
                                         '--driver', output / 'driver27-prefix'])
            workspace = argv[2].parents[2]
            GATE.base.check(workspace, GATE.FROZEN)
            self.assertEqual((workspace / GATE.LOCK).read_text(),
                             'SOURCE_COMMIT=' + GATE.OLD_COMMIT + '\nSOURCE_QCA_NSS_DRV_PKG_RELEASE=27\n')
            raise ValueError('frozen child rejected')

        with tempfile.TemporaryDirectory() as tmp, patch.object(GATE, 'command', fake_child):
            output = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'frozen child rejected'):
                GATE.historical_root(output, {}, output / 'old-source', output / 'driver27-prefix')


class Workflow(unittest.TestCase):
    NAME = '      - name: Validate frozen NSS command input source and host regressions\n'

    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()

    def test_pre_gate_precedes_history_and_single_compile(self):
        text = self.workflow
        self.assertIn('ref: ' + GATE.OLD_COMMIT + '\n          path: core-drv27-source\n', text)
        self.assertIn('python3 -B .github/scripts/verify-nss-drv29.py --check-lock', text)
        self.assertIn('--output "$evidence/drv29"', text)
        self.assertIn('--driver "$evidence/drv29/root-host/driver25-prefix"', text)
        self.assertIn('compile-ax6-with-evidence.sh "$(nproc)" ../build-evidence --once', text)
        self.assertIn('test "$GITHUB_REF" != refs/heads/main', text)
        self.assertIn('test "$VARIANT_INPUT" = stock', text)
        self.assertIn('test "$SSH_INPUT" = false', text)
        self.assertNotIn('contents: write', text)
        for left, right in [(self.NAME, 'verify-nss-drv29.py"'), ('verify-nss-drv29.py"', 'verify-nss-command-inputs.py"'),
                            ('verify-nss-command-inputs.py"', '      - name: Compile firmware')]:
            self.assertLess(text.index(left), text.index(right))

    def test_pre_gate_failure_stops_before_command_gate(self):
        block = self.workflow.split(self.NAME, 1)[1].split('\n      - ', 1)[0]
        script = '\n'.join(line[10:] for line in block.split('        run: |\n', 1)[1].splitlines()) + '\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'build_dir/target-aarch64_cortex-a53_musl/linux-qualcommax_ipq807x'
            for name in ('qca-nss-drv-1', 'qca-nss-clients-1', 'linux-6.18.38/kernel'):
                (target / name).mkdir(parents=True)
            (target / 'linux-6.18.38/kernel/sysctl.c').touch()
            cmd = root / 'python3'
            cmd.write_text('#!/bin/sh\nprintf "%s\\n" "${1##*/}" >> "$TRACE"\n'
                           'case "$1" in */verify-nss-drv29.py) exit 19;; esac\n')
            cmd.chmod(0o755)
            env = dict(os.environ, GITHUB_WORKSPACE=str(root), PATH=str(root) + os.pathsep + os.environ['PATH'],
                       TRACE=str(root / 'trace'))
            bash = os.environ.get('AX6_TEST_BASH') or shutil.which('bash')
            if Path('/opt/homebrew/bin/bash').exists() and 'AX6_TEST_BASH' not in os.environ:
                bash = '/opt/homebrew/bin/bash'
            ran = subprocess.run([bash, '-s'], input=script, cwd=root, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(ran.returncode, 19, ran.stderr)
            self.assertEqual((root / 'trace').read_text(), 'verify-nss-drv29.py\n')


if __name__ == '__main__':
    unittest.main()
