#!/usr/bin/env python3
"""Gate configuration/process controls, not native or device qualification."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('probe40_gate', ROOT / '.github/scripts/verify-ssdk-probe-resource.py')
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)


class Tests(unittest.TestCase):
    def reject(self, edit, message):
        original = M.base.load
        data = copy.deepcopy(original(M.PROFILE))
        edit(data)
        with patch.object(M.base, 'load', side_effect=lambda p: data if Path(p) == M.PROFILE else original(p)):
            with self.assertRaisesRegex(ValueError, message): M.configuration()

    def test_exact_profile_and_actual_source_delta(self):
        data = M.configuration()
        self.assertEqual(len(data['prepared_files']), 692)
        self.assertEqual({p for p, value in data['prepared_files'].items()
                          if value != M.old.configuration()['prepared_files'][p]}, {'src/init/ssdk_init.c'})
        self.assertEqual(sum(p.startswith('package/qca-nss/qca-ssdk/patches/') for p in data['source_assets']), 40)
        self.assertNotEqual(data['source_commit'], data['accepted39_commit'])

    def test_other_function_drift_rejected(self):
        self.reject(lambda d: d['prepared_files'].__setitem__('src/hsl/hsl_dev.c', '0' * 64), 'only reviewed probe')

    def test_missing_actual_file_rejected(self):
        self.reject(lambda d: d['prepared_files'].pop('src/init/ssdk_init.c'), 'only reviewed probe')

    def test_unknown_actual_file_rejected(self):
        self.reject(lambda d: d['prepared_files'].__setitem__('src/foreign.c', '0' * 64), 'only reviewed probe')

    def test_immutable39_contract_rejected(self):
        self.reject(lambda d: d.__setitem__('accepted39_contract_sha256', '0' * 64), 'immutable SSDK39')

    def test_immutable39_gate_rejected(self):
        self.reject(lambda d: d.__setitem__('accepted39_gate_sha256', '0' * 64), 'immutable SSDK39')

    def test_wrong_prefix_identity_rejected(self):
        self.reject(lambda d: d.__setitem__('accepted39_commit', '0' * 40), 'accepted39 identity')

    def test_wrong052_rejected(self):
        self.reject(lambda d: d['source_assets'].__setitem__(M.PATCH, '0' * 64), 'fixed052')

    def test_exact_process_and_contamination(self):
        M.exact(0, b'PASS\n', b'', b'PASS\n', b'', 0)
        M.exact(86, b'', b'MARK\n', b'', b'MARK\n', 86)
        for code, out, err in [(False, b'PASS\n', b''), (1, b'PASS\n', b''), (-6, b'PASS\n', b''),
                               (None, b'PASS\n', b''), (0, b'PASS\nextra', b''),
                               (0, b'PASS\n', b'AddressSanitizer'), (0, b'', b'')]:
            with self.assertRaises(ValueError): M.exact(code, out, err, b'PASS\n', b'', 0)

    def test_actual_gate_and_frozen_parent_are_separate(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        self.assertIn('--accepted39-source-root "$GITHUB_WORKSPACE/core-accepted39-source"', workflow)
        self.assertIn('path: core-accepted39-source\n          persist-credentials: false', workflow)
        self.assertIn('--source-root . --dp "$lifecycle_dp_source" --ssdk "$lifecycle_ssdk_source"', workflow)
        self.assertLess(workflow.index('make target/linux/prepare V=s'), workflow.index('Validate reviewed MDIO'))
        text = Path(M.__file__).read_text()
        self.assertLess(text.index('base.export_inputs(out,'), text.index("'full actual SSDK40 source'"))
        self.assertIn("'actual unchanged39/38 parent'", text)
        self.assertIn("'exact052 reverse to frozen39'", text)
        self.assertIn("base.prepared_partition(original, out, 'ssdk', data['prepared_files'])", text)

    def test_linux_preflight_and_ncurses_actual_payload_gate(self):
        lint = (ROOT / '.github/workflows/lint.yml').read_text()
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        self.assertIn('verify-ssdk-probe-resource.py --print-source-ref', lint)
        self.assertIn('--sanitizer-preflight --source-root ssdk-sanitizer-source --cc gcc-11', lint)
        self.assertIn('verify-ncurses-rootfs.py', workflow)
        self.assertIn('--retain-packages core-flow-evidence/ncurses/offline-packages', workflow)


if __name__ == '__main__':
    unittest.main()
