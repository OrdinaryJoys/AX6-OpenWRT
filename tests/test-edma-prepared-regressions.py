#!/usr/bin/env python3
"""Admission/oracle/wiring controls only; synthetic text never qualifies driver C."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get('AX6_TEST_BASH', shutil.which('bash'))
SCRIPT = ROOT / '.github/scripts/verify-edma-prepared-regressions.py'
SPEC = importlib.util.spec_from_file_location('edma_gate_controls', SCRIPT)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def regression_step():
    workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
    marker = '      - name: Regression assertions — 007/008, 012, 018/019 (P0-D.3-5)\n'
    if workflow.count(marker) != 1:
        raise ValueError('unique actual regression step required')
    step = workflow.split(marker, 1)[1].split('\n      - ', 1)[0]
    script = step.split('        run: |\n', 1)[1]
    return '\n'.join(line[10:] if line.startswith('          ') else line
                     for line in script.splitlines()) + '\n'


class Admission(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='edma-admission-only-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.prepared = self.root / 'source', self.root / 'prepared'
        self.profile = copy.deepcopy(json.loads(gate.PROFILE.read_text()))
        # Deliberately not valid C or Python: only the byte-admission layer runs.
        for group, root in (('patches', self.source / 'package/qca-nss/qca-nss-dp/patches'),
                            ('prepared_files', self.prepared), ('test_assets', self.source)):
            for name in self.profile[group]:
                data = ('TESTONLY admission bytes: ' + name + '\n').encode()
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                self.profile[group][name] = gate.sha(data)
        recipe = self.source / 'package/qca-nss/qca-nss-dp/Makefile'
        recipe.write_text('PKG_SOURCE_VERSION:=' + self.profile['upstream_pin'] + '\n')
        self.path = self.root / 'profile.json'
        self.save()
        self.scope = patch.object(gate, 'PROFILE', self.path)
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def save(self):
        self.path.write_text(json.dumps(self.profile))

    def rejected(self):
        with self.assertRaises((ValueError, OSError)):
            gate.admit(self.source, self.prepared)

    def test_consistent_bytes_admitted_but_not_executed(self):
        self.assertEqual(gate.admit(self.source, self.prepared), self.profile)

    def test_each_prepared_file_drift_rejected(self):
        for name in gate.FILES:
            with self.subTest(name=name):
                path = self.prepared / name
                old = path.read_bytes()
                path.write_bytes(old + b'changed\n')
                self.rejected()
                path.write_bytes(old)

    def test_each_test_asset_drift_rejected(self):
        for name in gate.ASSETS:
            path = self.source / name
            old = path.read_bytes()
            path.write_bytes(old + b'changed\n')
            self.rejected()
            path.write_bytes(old)

    def test_missing_prepared_file(self):
        (self.prepared / sorted(gate.FILES)[0]).unlink()
        self.rejected()

    def test_symlink_even_with_correct_bytes(self):
        p = self.prepared / sorted(gate.FILES)[0]
        saved = self.root / 'outside'
        p.rename(saved)
        p.symlink_to(saved)
        self.rejected()

    def test_changed_patch(self):
        p = self.source / 'package/qca-nss/qca-nss-dp/patches' / sorted(self.profile['patches'])[0]
        p.write_text('changed')
        self.rejected()

    def test_missing_patch(self):
        p = self.source / 'package/qca-nss/qca-nss-dp/patches' / sorted(self.profile['patches'])[0]
        p.unlink()
        self.rejected()

    def test_extra_patch(self):
        (self.source / 'package/qca-nss/qca-nss-dp/patches/019-unreviewed.patch').write_text('new')
        self.rejected()

    def test_patch_symlink(self):
        p = self.source / 'package/qca-nss/qca-nss-dp/patches' / sorted(self.profile['patches'])[0]
        saved = self.root / 'outside'
        p.rename(saved)
        p.symlink_to(saved)
        self.rejected()

    def test_wrong_pin(self):
        (self.source / 'package/qca-nss/qca-nss-dp/Makefile').write_text('PKG_SOURCE_VERSION:=bad\n')
        self.rejected()

    def test_duplicate_pin(self):
        p = self.source / 'package/qca-nss/qca-nss-dp/Makefile'
        p.write_text(p.read_text() * 2)
        self.rejected()

    def test_unknown_profile(self):
        self.profile['profile'] = 'ACCEPT_OLD_OR_NEW'
        self.save()
        self.rejected()

    def test_boolean_schema(self):
        self.profile['schema'] = True
        self.save()
        self.rejected()

    def test_incomplete_prepared_contract(self):
        self.profile['prepared_files'].pop(sorted(gate.FILES)[0])
        self.save()
        self.rejected()

    def test_incomplete_test_assets(self):
        self.profile['test_assets'].pop(sorted(gate.ASSETS)[0])
        self.save()
        self.rejected()

    def test_duplicate_json_key(self):
        self.path.write_text(self.path.read_text().replace('"schema": 1', '"schema": 1, "schema": 1'))
        self.rejected()


class Oracles(unittest.TestCase):
    def test_negative_valid_and_valid_prefix(self):
        for prefix in ('', gate.irq_expected().splitlines()[0] + '\n'):
            self.assertTrue(gate.semantic_rejection(
                {'returncode': 86, 'stdout': prefix, 'stderr': 'EXPECTED\n'},
                'EXPECTED', gate.irq_expected()))

    def test_negative_pollution_and_wrong_exit_rejected(self):
        good = {'returncode': 86, 'stdout': '', 'stderr': 'EXPECTED\n'}
        for key, value in [('returncode', x) for x in (0, 1, 97, -11, 'timeout', False, True)] + [
            ('stdout', 'unrelated\n'), ('stdout', 'PASS partial'),
            ('stderr', ''), ('stderr', 'WRONG\n'),
            ('stderr', 'EXPECTED\nAddressSanitizer: error\n')]:
            row = dict(good)
            row[key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(gate.semantic_rejection(row, 'EXPECTED', gate.irq_expected()))

    def test_positive_exact_irq_inventory(self):
        row = {'returncode': 0, 'stdout': gate.irq_expected(), 'stderr': ''}
        self.assertTrue(gate.positive_result(row, True))
        for field, value in [('stdout', ''), ('stdout', row['stdout'][:-1]),
                             ('stdout', row['stdout'] + 'PASS extra\n'),
                             ('returncode', False), ('returncode', 1), ('stderr', 'noise')]:
            changed = dict(row)
            changed[field] = value
            self.assertFalse(gate.positive_result(changed, True))

    def test_tx_complete_balanced_nonzero_summary(self):
        good = 'cases=74 checks=100 maps=20 unmaps=20 zero_unmaps=1 frees=21\n'
        self.assertTrue(gate.positive_result({'returncode': 0, 'stdout': good, 'stderr': ''}))
        for value in ('', good.replace('maps=20', 'maps=0'), good.replace('cases=74', 'cases=0'),
                      good.replace('checks=100', 'checks=0'), good.replace('unmaps=20', 'unmaps=19'),
                      good.replace('zero_unmaps=1', 'zero_unmaps=0'),
                      good.replace('zero_unmaps=1', 'zero_unmaps=99'), good + 'extra\n'):
            self.assertFalse(gate.positive_result({'returncode': 0, 'stdout': value, 'stderr': ''}))


class Workflow(unittest.TestCase):
    def test_actual_step_uses_semantics_and_preserves_other_boundaries(self):
        step = regression_step()
        call = 'python3 "$GITHUB_WORKSPACE/.github/scripts/verify-edma-prepared-regressions.py"'
        self.assertEqual(step.count(call), 1)
        for old in ('tx_dma_store', 'tx_irqs = 0, rxfill_irqs = 0',
                    'netif_napi_add(netdev,'):
            self.assertNotIn(old, step)
        self.assertIn('--source-root . --dp "$dp_src" --cc cc', step)
        self.assertIn('core-flow-evidence/edma-prepared-regressions', step)
        self.assertLess(step.index('007 TXmod'), step.index(call))
        self.assertLess(step.index(call), step.index('012 fused'))
        for boundary in ('napi_gro_receive', 'NETIF_F_GRO', 'edma_handle_rx_irq',
                         'netif_napi_del', 'stats_enable = 1', 'dma_mapping_error'):
            self.assertIn(boundary, step)
        self.assertNotIn('|| true', step)
        self.assertNotIn('set +e', step)

    def test_selector_rejects_zero_or_multiple_real_directories(self):
        for count in (0, 2):
            with tempfile.TemporaryDirectory(prefix='edma-step-selection-') as tmp:
                root = Path(tmp)
                linux = root / 'build_dir/target-aarch64_cortex-a53_musl/linux-qualcommax_ipq807x'
                linux.mkdir(parents=True)
                for i in range(count):
                    (linux / ('qca-nss-dp-' + str(i))).mkdir()
                    (linux / ('qca-nss-drv-' + str(i))).mkdir()
                p = subprocess.run([BASH, '-c', regression_step()], cwd=root,
                                   env=dict(os.environ, GITHUB_WORKSPACE=str(ROOT)),
                                   capture_output=True, text=True, timeout=10)
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIn('Expected one prepared qca-nss-dp', p.stdout)
                self.assertNotIn('All regression assertions passed.', p.stdout)

    def test_missing_edma_rejected(self):
        with tempfile.TemporaryDirectory(prefix='edma-step-missing-') as tmp:
            root = Path(tmp)
            linux = root / 'build_dir/target-aarch64_cortex-a53_musl/linux-qualcommax_ipq807x'
            (linux / 'qca-nss-dp-one').mkdir(parents=True)
            (linux / 'qca-nss-drv-one').mkdir()
            p = subprocess.run([BASH, '-c', regression_step()], cwd=root,
                               env=dict(os.environ, GITHUB_WORKSPACE=str(ROOT)),
                               capture_output=True, text=True, timeout=10)
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertIn('no EDMA v1 implementation', p.stdout)

    def test_lint_runs_controls_and_historical_008_check_retained(self):
        lint = (ROOT / '.github/workflows/lint.yml').read_text()
        self.assertIn('python3 -B tests/test-edma-prepared-regressions.py', lint)
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        self.assertIn('sh tests/test-edma-correctness-prerequisites.sh', workflow)


if __name__ == '__main__':
    unittest.main(verbosity=2)
