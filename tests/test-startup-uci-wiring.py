#!/usr/bin/env python3
"""Fail-closed startup fixture and actual-rootfs CI wiring checks."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tests/build-startup-uci-host.py'


class Wiring(unittest.TestCase):
    def test_cli_core_dependency_and_strict_flags(self):
        spec = importlib.util.spec_from_file_location('startup_uci_build', HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.C_FILES, ['libuci.c', 'file.c', 'util.c', 'delta.c', 'parse.c', 'cli.c'])
        self.assertEqual(module.INCLUDED_C_FILES, ['list.c'])
        text = HELPER.read_text()
        self.assertIn("'-Werror'", text)
        self.assertIn('completed.returncode or completed.stdout or completed.stderr', text)
        self.assertNotIn('shell=True', text)

    def run_rejection(self, pin, existing_output):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recipe = base / 'source/package/system/uci/Makefile'
            recipe.parent.mkdir(parents=True)
            recipe.write_text('PKG_SOURCE_VERSION:=' + pin + '\n')
            output = base / 'output'
            if existing_output:
                output.mkdir()
                (output / 'preserve').write_text('unchanged')
            args = [sys.executable, '-B', str(HELPER), '--source-root', str(base / 'source'),
                    '--output', str(output), '--uci-git-root', str(base / 'absent-git')]
            result = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((output / 'uci-native').exists())
            if existing_output:
                self.assertEqual((output / 'preserve').read_text(), 'unchanged')
            else:
                self.assertFalse(output.exists())
            return result.stderr

    def test_pin_drift_rejected_before_external_commands(self):
        self.assertIn('UCI package pin differs', self.run_rejection('0' * 40, False))

    def test_existing_output_is_not_overwritten(self):
        self.assertIn('output must be fresh', self.run_rejection('66127cd76c5d0bd46d5a90302cc6110f53a4e2f8', True))

    def test_both_workflows_execute_real_uci(self):
        for file in ['lint.yml', 'build-AX6-NSS.yml']:
            text = (ROOT / '.github/workflows' / file).read_text()
            self.assertIn('python3 -B tests/build-startup-uci-host.py', text)
            self.assertIn('--shell \'busybox ash\'', text)
            self.assertIn('path: startup-uci-evidence/', text)
            self.assertIn('python3 -B tests/test-startup-uci-wiring.py', text)

    def test_final_rootfs_uses_extracted_service_after_cmp(self):
        text = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        compare = 'cmp AX6-IPQ/files/etc/init.d/ax6-boot-guard image-verify/ax6-boot-guard.init'
        actual = '--service image-verify/ax6-boot-guard.init'
        self.assertEqual(text.count(compare), 1)
        self.assertEqual(text.count(actual), 1)
        self.assertLess(text.index(compare), text.index(actual))
        self.assertIn('tee image-verify/startup-real-uci.json', text)

    def test_real_ecm_function_and_installed_payload_are_both_checked(self):
        for file in ['lint.yml', 'build-AX6-NSS.yml']:
            text = (ROOT / '.github/workflows' / file).read_text()
            self.assertIn('python3 -B tests/test-ecm-real-uci.py --source-root', text)
        build = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        self.assertIn('--init "$rps_fixture/package/qca-nss/qca-nss-ecm/files/qca-nss-ecm.init"', build)
        self.assertIn('tee image-verify/ecm-real-uci.json', build)

    def test_fixture_rejects_host_delta_and_records_service_identity(self):
        text = (ROOT / 'tests/test-startup-real-uci.py').read_text()
        self.assertIn("Path('/tmp/.uci').exists()", text)
        self.assertIn('service.read_bytes()', text)
        self.assertIn("'-C', str(config2), '-t', str(delta)", text)
        self.assertIn("'missing-required', 'pending', 'parse-error'", text)


if __name__ == '__main__':
    unittest.main()
