#!/usr/bin/env python3
"""Pure gate/control tests, not a simulated kernel or driver result."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ssdk39_gate', ROOT / '.github/scripts/verify-ssdk-retirement-admission.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class Gate(unittest.TestCase):
    def test_positive_exact_and_pollution(self):
        raw = b'{"status":"PASS","cases":266,"shared_uk_order":"OPEN"}\n'
        m.positive(0, raw, b'')
        for code, out, err in [(False, raw, b''), (1, raw, b''), ('0', raw, b''), (None, raw, b''),
                               (0, raw, b'warning'), (0, raw.replace(b'266', b'226'), b''),
                               (0, raw.replace(b'OPEN', b'CLOSED'), b''),
                               (0, raw.replace(b'266', b'266,"cases":266'), b'')]:
            with self.subTest(code=code, out=out, err=err):
                with self.assertRaises(ValueError): m.positive(code, out, err)

    def test_precise_negative_rejects_nonsemantic_failures(self):
        raw = b'RETIRE:fixed\n'; m.negative(86, b'', raw, 'fixed')
        for code, out, err in [(1, b'', raw), (-6, b'', raw), (True, b'', raw), ('86', b'', raw),
                               (None, b'', raw), (86, b'noise', raw), (86, b'', raw + raw),
                               (86, b'', raw + b'AddressSanitizer\n'), (86, b'', b'RETIRE:other\n')]:
            with self.subTest(code=code, out=out, err=err):
                with self.assertRaises(ValueError): m.negative(code, out, err, 'fixed')

    def test_fixed_source_and_full_tree_policy(self):
        d = m.configuration(); old = m.base.configuration()
        self.assertEqual(len(d['prepared_files']), 692)
        self.assertEqual(len(d['native_markers']), 23)
        self.assertEqual(sum(n.startswith('package/qca-nss/qca-ssdk/patches/') for n in d['source_assets']), 39)
        self.assertNotEqual(d['source_commit'], d['baseline_commit'])
        self.assertEqual(d['baseline_commit'], old['source_commit'])
        self.assertEqual({n for n in d['prepared_files'] if d['prepared_files'][n] != old['ssdk']['current_files'][n]},
                         {'src/sal/sd/sd.c', 'include/sal/sd/sd.h', 'src/hsl/hsl_dev.c', 'src/init/ssdk_init.c'})

    def test_prefix_and_actual_source_are_separate(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        self.assertIn('--source-root . --dp "$lifecycle_dp_source" --ssdk "$lifecycle_ssdk_source"', workflow)
        self.assertIn('--baseline-source-root "$GITHUB_WORKSPACE/core-accepted-source"', workflow)
        self.assertIn('path: core-accepted-source\n          persist-credentials: false', workflow)
        self.assertIn('git -C openwrt fetch --depth 1 origin "$SOURCE_COMMIT"', workflow)
        self.assertLess(workflow.index('make target/linux/prepare V=s'), workflow.index('Validate reviewed MDIO'))
        code = (ROOT / '.github/scripts/verify-ssdk-retirement-admission.py').read_text()
        self.assertLess(code.index("base.export_inputs(output, exports)"), code.index("'actual full SSDK39 code'"))
        self.assertIn("'full frozen38 prefix'", code)
        self.assertIn("'actual accepted38 parent result'", code)


if __name__ == '__main__': unittest.main()
