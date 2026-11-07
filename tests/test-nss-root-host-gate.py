#!/usr/bin/env python3
"""Gate-detector and workflow controls only, not native DRV/runtime tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('root_host_gate', ROOT / '.github/scripts/verify-nss-root-host.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class Contract(unittest.TestCase):
    def test_fixed_source_and_prefix_sets(self):
        data = M.configuration()
        self.assertEqual(len(data['current_code_files']), 484)
        self.assertEqual(len(data['prefix25_code_files']), 480)
        self.assertEqual(set(data['current_code_files']) - set(data['prefix25_code_files']),
                         {'nss_coredump.h', 'nss_debugfs.h', 'nss_freq_work.h', 'nss_sysctl.h'})
        self.assertEqual(data['exact_noncompiled_auxiliary'], M.AUXILIARY)
        self.assertEqual(M.base.invhash(data['prefix25_code_files'] | M.AUXILIARY),
                         '8725c8ee568d698941659db9ac546c165b7817cb4787d8fe73ea163ecc19f4ce')

    def test_frozen_profile_rejects_any_refreshed_input(self):
        for field in ('driver_release', 'reviewed_inventory_sha256', 'current_code_files',
                      'prefix25_code_files', 'exact_noncompiled_auxiliary', 'patches'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                data = M.base.load(M.PROFILE)
                data[field] = 'unknown drift'
                file = Path(directory) / 'profile.json'
                file.write_text(json.dumps(data))
                with patch.object(M, 'PROFILE', file), self.assertRaisesRegex(ValueError, 'frozen root-host contract bytes'):
                    M.configuration()

    def test_lock_rejects_missing_duplicate_old_or_noncommit(self):
        valid = 'SOURCE_COMMIT=' + 'a' * 40 + '\nSOURCE_QCA_NSS_DRV_PKG_RELEASE=27\n'
        bad = [valid.replace('=27', '=25'), valid + 'SOURCE_COMMIT=' + 'b' * 40 + '\n',
               valid.replace('a' * 40, 'branch'), valid.replace('SOURCE_COMMIT=', 'OTHER=')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.github').mkdir()
            file = root / '.github/ax6-nss-lock.env'
            with patch.object(M, 'ROOT', root):
                file.write_text(valid)
                self.assertEqual(M.lock_identity(), 'a' * 40)
                for text in bad:
                    file.write_text(text)
                    with self.assertRaises(ValueError): M.lock_identity()

    def test_only_actual_prepare_metadata_is_partitioned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'input.c').write_text('source datum\n')
            (root / 'nss_init.c.orig').write_text('noncompiled datum\n')
            (root / 'version.date').write_text('1770000000\n')
            marker = '.prepared_' + 'a' * 32 + '_' + 'b' * 32
            (root / marker).write_bytes(b'')
            (root / (marker + '_check')).write_bytes(b'')
            code, metadata = M.base.partition(root)
            self.assertEqual(set(code), {'input.c', 'nss_init.c.orig'})
            self.assertEqual(set(metadata), {'version.date', marker, marker + '_check'})
            (root / marker).write_bytes(b'not empty')
            with self.assertRaisesRegex(ValueError, 'invalid stamp'): M.base.partition(root)

    def test_unknown_orig_is_not_ignored_and_symlinks_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'unknown.c.orig').write_bytes(b'not metadata')
            code, _ = M.base.partition(root)
            self.assertIn('unknown.c.orig', code)
            (root / 'foreign').symlink_to(root / 'unknown.c.orig')
            with self.assertRaisesRegex(ValueError, 'nonregular input'): M.base.partition(root)

    def test_actual_root_gate_precedes_exact_prefix_command_gate(self):
        text = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        root = 'python3 "$GITHUB_WORKSPACE/.github/scripts/verify-nss-root-host.py"'
        prior = 'python3 "$GITHUB_WORKSPACE/.github/scripts/verify-nss-command-inputs.py"'
        self.assertEqual(text.count(root), 1)
        self.assertEqual(text.count(prior), 1)
        self.assertLess(text.index(root), text.index(prior))
        self.assertIn('--source-root . --driver "${command_drivers[0]}"', text)
        self.assertIn('--driver "$evidence/root-host/driver25-prefix"', text)
        self.assertLess(text.index('test_root_control_contract.py'), text.index(root))
        self.assertLess(text.index(prior), text.index('      - name: Compile firmware'))

    def test_platform_actual_prepared_and_immutable_assets_are_separate(self):
        text = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        for item in ('--print-source-ref', '--print-prefix40-ref',
                     'path: core-platform41-source\n          persist-credentials: false',
                     'path: core-platform40-source\n          persist-credentials: false',
                     '--source-root "$GITHUB_WORKSPACE/core-platform41-source"',
                     '--accepted40-source-root "$GITHUB_WORKSPACE/core-platform40-source"',
                     '--ssdk "$lifecycle_ssdk_source" --cc cc'):
            self.assertIn(item, text)
        self.assertIn("if: github.ref == 'refs/heads/main' && env.VARIANT_TAG == 'STOCK'", text)
        self.assertIn('python3 -B tests/test-nss-root-host-gate.py', (ROOT / '.github/workflows/lint.yml').read_text())

    def test_early_frozen40_preflight_never_uses_new_firmware_source(self):
        text = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        call = '--sanitizer-preflight --source-root "$GITHUB_WORKSPACE/core-platform40-source" --cc gcc-11'
        self.assertEqual(text.count(call), 1)
        self.assertNotIn('--sanitizer-preflight --source-root openwrt', text)
        self.assertLess(text.index('path: core-platform40-source'), text.index(call))
        self.assertLess(text.index(call), text.index('      - name: Compile firmware'))


if __name__ == '__main__':
    unittest.main()
