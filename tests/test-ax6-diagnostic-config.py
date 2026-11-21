#!/usr/bin/env python3
"""Exact configuration-boundary controls; no firmware build or device actions."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / '.github/scripts/verify-ax6-diagnostic-config.py'
SPEC = importlib.util.spec_from_file_location('diagnostic_config', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
# Independent acceptance contract: do not derive the oracle from the checker.
REQUESTED = ('DEBUG_FS', 'KALLSYMS', 'PERF_EVENTS', 'FTRACE', 'FUNCTION_TRACER',
             'DYNAMIC_FTRACE', 'FUNCTION_GRAPH_TRACER', 'KPROBES', 'KPROBE_EVENTS')
GENERATED = ('DEBUG_FS', 'KALLSYMS', 'PERF_EVENTS', 'FTRACE', 'FUNCTION_TRACER',
             'DYNAMIC_FTRACE', 'FUNCTION_GRAPH_TRACER', 'KPROBES', 'KPROBE_EVENTS',
             'STACKTRACE')
TOP = ''.join(f'CONFIG_KERNEL_{name}=y\n' for name in REQUESTED)
KERNEL = ''.join(f'CONFIG_{name}=y\n' for name in GENERATED)
OPTIONS = ''.join(f'config KERNEL_{name}\n\tbool\n' for name in REQUESTED)


def workflow_steps():
    document = yaml.load((ROOT / '.github/workflows/build-AX6-NSS.yml').read_text(),
                         Loader=yaml.BaseLoader)
    matches = [job['steps'] for job in document['jobs'].values()
               if any(step.get('id') == 'compile_firmware' for step in job['steps'])]
    if len(matches) != 1:
        raise AssertionError('expected one firmware job')
    return matches[0]


def generated_gate(steps):
    matches = [(index, step) for index, step in enumerate(steps)
               if 'python3 .github/scripts/verify-ax6-diagnostic-config.py' in step.get('run', '')]
    if len(matches) != 1:
        raise AssertionError('expected one generated gate')
    index, step = matches[0]
    if step.get('if') != 'success()':
        raise AssertionError('generated gate must cover STOCK and EXPAND')
    run = step['run']
    for argument in ('--top-config openwrt/.config',
                     '--kernel-config build-evidence/kernel-evidence/kernel.config',
                     '--kernel-options openwrt/config/Config-kernel.in', '--require-generated'):
        if argument not in run:
            raise AssertionError('missing generated gate argument: ' + argument)
    if run.index('collect-ax6-kernel-evidence.py') > run.index('verify-ax6-diagnostic-config.py'):
        raise AssertionError('generated gate must follow collection')
    if 'VARIANT_TAG' in run or 'compiled_stock_dtbs' in run:
        raise AssertionError('common gate must not be stock-only')
    compile_index = next(i for i, item in enumerate(steps) if item.get('id') == 'compile_firmware')
    upload_index = next(i for i, item in enumerate(steps)
                        if item.get('name') == 'Preserve compile attempts even after failure')
    if not compile_index < index < upload_index:
        raise AssertionError('generated gate must follow compile and precede evidence upload')
    return step


class DiagnosticConfig(unittest.TestCase):
    def test_checker_cannot_shrink_the_independent_contract(self):
        self.assertEqual(MODULE.REQUESTED, REQUESTED)
        self.assertEqual(MODULE.GENERATED, GENERATED)

    def test_actual_stock_and_expand_requests(self):
        for name in ('stock', 'expand'):
            with self.subTest(profile=name):
                result = MODULE.validate((ROOT / f'AX6-IPQ/.config-{name}').read_text())
                self.assertEqual(result['status'], 'PASS_REQUESTED_CONFIG_ONLY')
                self.assertFalse(result['generated_config_checked'])

    def test_complete_generated_config_is_not_runtime_acceptance(self):
        result = MODULE.validate(TOP, KERNEL, OPTIONS)
        self.assertEqual(result['status'], 'PASS_CONFIG_ONLY')
        self.assertEqual(result['runtime_probe_usable'], 'NOT_VERIFIED')

    def test_old_bare_namespace_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'bare diagnostic'):
            MODULE.validate(KERNEL)

    def test_every_top_symbol_is_required(self):
        for name in REQUESTED:
            for replacement in ('', f'# CONFIG_KERNEL_{name} is not set\n', f'CONFIG_KERNEL_{name}=m\n'):
                with self.subTest(symbol=name, replacement=replacement), self.assertRaisesRegex(ValueError, name):
                    MODULE.validate(TOP.replace(f'CONFIG_KERNEL_{name}=y\n', replacement))

    def test_every_generated_symbol_is_required(self):
        for name in GENERATED:
            for replacement in ('', f'# CONFIG_{name} is not set\n', f'CONFIG_{name}=m\n'):
                with self.subTest(symbol=name, replacement=replacement), self.assertRaisesRegex(ValueError, name):
                    MODULE.validate(TOP, KERNEL.replace(f'CONFIG_{name}=y\n', replacement))

    def test_duplicate_same_or_conflicting_value_is_rejected(self):
        for suffix in ('CONFIG_KERNEL_KPROBES=y\n', '# CONFIG_KERNEL_KPROBES is not set\n'):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'duplicate'):
                MODULE.validate(TOP + suffix)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            MODULE.validate(TOP, KERNEL + 'CONFIG_KPROBES=y\n')

    def test_prefix_and_comment_decoys_do_not_satisfy_symbols(self):
        for decoy in ('# CONFIG_KERNEL_KPROBES=y\n', 'CONFIG_KERNEL_KPROBES_EXTRA=y\n'):
            with self.subTest(decoy=decoy), self.assertRaisesRegex(ValueError, 'KPROBES'):
                MODULE.validate(TOP.replace('CONFIG_KERNEL_KPROBES=y\n', decoy))

    def test_undeclared_top_option_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown OpenWrt'):
            MODULE.validate(TOP, KERNEL, OPTIONS.replace('config KERNEL_KPROBES\n', 'config OTHER\n'))

    def test_cli_cannot_claim_generated_without_input(self):
        process = subprocess.run([sys.executable, '-B', str(PATH), '--top-config', '/nonexistent',
                                  '--require-generated'], capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertIn('requires --kernel-config', process.stderr)

    def test_cli_missing_generated_config_fails_with_evidence(self):
        with tempfile.TemporaryDirectory(prefix='ax6-diagnostic-config-') as directory:
            root = Path(directory)
            (root / 'top').write_text(TOP)
            process = subprocess.run([sys.executable, '-B', str(PATH), '--top-config', str(root / 'top'),
                                      '--kernel-config', str(root / 'missing'), '--require-generated',
                                      '--output', str(root / 'result.json')], capture_output=True, text=True)
            self.assertEqual(process.returncode, 1)
            self.assertIn('"status": "FAIL"', (root / 'result.json').read_text())

    def test_generated_gate_is_wired_after_kernel_evidence(self):
        steps = workflow_steps()
        generated_gate(steps)
        stock = next(step for step in steps if 'compiled_stock_dtbs' in step.get('run', ''))
        self.assertEqual(stock['if'], "success() && env.VARIANT_TAG == 'STOCK'")
        self.assertNotIn('verify-ax6-diagnostic-config.py', stock['run'])

    def test_stock_only_generated_gate_is_rejected(self):
        steps = workflow_steps()
        step = generated_gate(steps)
        step['if'] = "success() && env.VARIANT_TAG == 'STOCK'"
        with self.assertRaisesRegex(AssertionError, 'cover STOCK and EXPAND'):
            generated_gate(steps)

    def test_request_gate_runs_after_defconfig_before_compile(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        configure = workflow.index('make defconfig 2>&1 | tee defconfig.log')
        gate = workflow.index('python3 ../.github/scripts/verify-ax6-diagnostic-config.py', configure)
        compile_step = workflow.index('      - name: Compile firmware', configure)
        self.assertLess(configure, gate)
        self.assertLess(gate, compile_step)
        self.assertIn('--top-config .config --kernel-options config/Config-kernel.in', workflow[gate:compile_step])
        lint = (ROOT / '.github/workflows/lint.yml').read_text()
        self.assertIn('python3 -B tests/test-ax6-diagnostic-config.py', lint)


if __name__ == '__main__':
    unittest.main(verbosity=2)
