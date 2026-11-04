#!/usr/bin/env python3
"""Pure gate/control tests, not a simulated kernel or driver result."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ssdk39_gate', ROOT / '.github/scripts/verify-ssdk-retirement-admission.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class ReceiptControls(unittest.TestCase):
    """Synthetic receipt-reader controls; no native compilation result is claimed."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.common = ['-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-O1', '-g']
        self.data = {'probe_source_sha256': {}}
        self.controls = {'activation': [{'name': 'asan', 'instrumentation': 'address', 'exit': 97},
                                       {'name': 'ubsan', 'instrumentation': 'undefined', 'exit': 98}],
                         'crossed': [{'actual': 'asan', 'rejected_as': 'ubsan'}, {'actual': 'ubsan', 'rejected_as': 'asan'}],
                         'oracle_rejections': 24, 'disabled': [{'name': 'asan', 'returncode': 0}, {'name': 'ubsan', 'returncode': 0}]}
        self.put('RESULTS.json', {'sanitizer_controls': self.controls})
        for kind, flag, code, diagnostic in [('asan', 'address', 97, b'ERROR: AddressSanitizer: heap-buffer-overflow\nWRITE of size 1\n'),
                                             ('ubsan', 'undefined', 98, b"runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'\n")]:
            c = self.root/('canary-'+kind+'.c'); c.write_bytes(b'receipt fixture, not executable C')
            self.data['probe_source_sha256'][kind] = m.sha(c.read_bytes())
            for disabled in (False, True):
                label = ('disabled-' if disabled else 'canary-')+kind
                flags = self.common + ([] if disabled else ['-fsanitize='+flag, '-fno-omit-frame-pointer'])
                self.put(label+'-compile.argv.json', {'argv': ['cc', *flags, str(c), '-o', str(self.root/(label+'.host'))]})
                self.put(label+'-compile.exit.json', {'returncode': 0})
                self.put(label+'-compile.stdout', b''); self.put(label+'-compile.stderr', b'')
                self.put(label+'-run.argv.json', {'argv': [str(self.root/(label+'.host'))],
                    'ASAN_OPTIONS': f'detect_leaks=0:halt_on_error=1:abort_on_error=0:exitcode={code}',
                    'UBSAN_OPTIONS': f'halt_on_error=1:abort_on_error=0:print_stacktrace=1:exitcode={code}'})
                self.put(label+'-run.exit.json', {'returncode': 0 if disabled else code})
                self.put(label+'-run.stdout', b''); self.put(label+'-run.stderr', b'' if disabled else diagnostic)

    def put(self, name, raw):
        (self.root/name).write_bytes(raw if isinstance(raw, bytes) else json.dumps(raw).encode())

    def check(self):
        m.sanitizer_receipts(self.root, self.data, 'cc', False)

    def test_exact_receipt_shape(self):
        self.check()

    def test_gcc11_commuted_overflow_receipt_and_wrong_identity(self):
        for operands in (b'2147483647 + 1', b'1 + 2147483647'):
            self.put('canary-ubsan-run.stderr', b'probe.c:2:77: runtime error: signed integer overflow: ' +
                     operands + b" cannot be represented in type 'int'\n")
            self.check()
        for expression in (b'21474836470 + 1', b'2147483647 + 10', b'1 + 21474836470',
                           b'2147483647 - 1', b'1 * 2147483647'):
            self.put('canary-ubsan-run.stderr', b'runtime error: signed integer overflow: ' + expression +
                     b" cannot be represented in type 'int'\n")
            with self.assertRaisesRegex(ValueError, 'isolated detector'): self.check()

    def test_actual_cloud_wrong_detector_diagnostic(self):
        self.put('canary-asan-run.stderr', b'runtime error: store to address with insufficient space for char')
        with self.assertRaisesRegex(ValueError, 'isolated detector'): self.check()

    def test_dual_probe_instrumentation_rejected(self):
        path = self.root/'canary-asan-compile.argv.json'; data = json.loads(path.read_bytes())
        data['argv'][data['argv'].index('-fsanitize=address')] = '-fsanitize=address,undefined'
        self.put(path.name, data)
        with self.assertRaisesRegex(ValueError, 'instrumentation argv'): self.check()

    def test_disabled_probe_cannot_be_instrumented(self):
        path = self.root/'disabled-asan-compile.argv.json'; data = json.loads(path.read_bytes())
        data['argv'].insert(1, '-fsanitize=address'); self.put(path.name, data)
        with self.assertRaisesRegex(ValueError, 'instrumentation argv'): self.check()

    def test_bool_exit_and_compile_warning_rejected(self):
        self.put('canary-asan-run.exit.json', {'returncode': True})
        with self.assertRaises(ValueError): self.check()
        self.put('canary-asan-run.exit.json', {'returncode': 97})
        self.put('canary-asan-compile.stderr', b'warning')
        with self.assertRaisesRegex(ValueError, 'clean compilation'): self.check()

    def test_environment_and_c_body_are_bound(self):
        path = self.root/'canary-asan-run.argv.json'; data = json.loads(path.read_bytes())
        original = dict(data)
        data['UBSAN_OPTIONS'] = data['UBSAN_OPTIONS'].replace('abort_on_error=0:', '')
        self.put(path.name, data)
        with self.assertRaisesRegex(ValueError, 'argv/environment'): self.check()
        self.put(path.name, original)
        self.put('canary-asan.c', b'changed probe')
        with self.assertRaisesRegex(ValueError, 'fixed probe C'): self.check()

    def test_missing_disabled_or_oracle_controls_rejected(self):
        self.controls['disabled'].pop(); self.put('RESULTS.json', {'sanitizer_controls': self.controls})
        with self.assertRaisesRegex(ValueError, 'disabled detector inventory'): self.check()
        self.controls['disabled'].append({'name': 'ubsan', 'returncode': 0})
        self.controls['oracle_rejections'] = True
        self.put('RESULTS.json', {'sanitizer_controls': self.controls})
        with self.assertRaisesRegex(ValueError, 'activation/crossed/oracle'): self.check()


class Gate(unittest.TestCase):
    def test_probe_identity_and_actual_failure_are_distinct(self):
        asan = b'ERROR: AddressSanitizer: heap-buffer-overflow\nWRITE of size 1\n'
        ubsan = b"runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'\n"
        self.assertTrue(m.probe_ok(97, b'', asan, 'asan'))
        self.assertTrue(m.probe_ok(98, b'', ubsan, 'ubsan'))
        for code in (0, 1, -6, True, '97', None, 86):
            self.assertFalse(m.probe_ok(code, b'', asan, 'asan'))
        self.assertFalse(m.probe_ok(97, b'noise', asan, 'asan'))
        self.assertFalse(m.probe_ok(97, b'', b'runtime error: store to address with insufficient space', 'asan'))
        self.assertFalse(m.probe_ok(97, b'', asan + ubsan, 'asan'))
        self.assertFalse(m.probe_ok(98, b'', asan, 'ubsan'))

    def test_preflight_runs_before_toolchain_and_in_full_lint(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        self.assertLess(workflow.index('--sanitizer-preflight'), workflow.index('Build target toolchain before rpcd components'))
        lint = (ROOT / '.github/workflows/lint.yml').read_text()
        self.assertIn('ref: ${{ steps.ssdk-sanitizer-contract.outputs.source_ref }}', lint)
        self.assertIn('test "$(gcc-11 -dumpversion)" = 11', lint)
        self.assertIn('--sanitizer-preflight --source-root ssdk-sanitizer-source --cc gcc-11', lint)
        self.assertIn('path: ssdk-sanitizer-source\n          persist-credentials: false', lint)

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
