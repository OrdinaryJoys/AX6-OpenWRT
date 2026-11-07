#!/usr/bin/env python3
"""Synthetic admission/receipt controls only; never native or target qualification."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('current_layers', ROOT / '.github/scripts/verify-ax6-current-layers.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class FixedContract(unittest.TestCase):
    def test_actual_fixed_contract_and_policies(self):
        data = gate.configuration()
        self.assertEqual(data['expected_counts'], {'i2c': [32, 23, 6], 'tunip': [58, 22, 10, 4]})
        self.assertNotEqual(data['source_commit'], data['legacy_test_commit'])
        policy = gate.load(gate.POLICY)
        self.assertEqual(len(policy['i2c']['commands']), 94)
        self.assertEqual(len(policy['tunip']['commands']), 125)
        for kind in ('i2c', 'tunip'):
            commands = policy[kind]['commands']
            self.assertEqual(len({r['label'] for r in commands}), len(commands))
            for row in commands:
                if row['label'].endswith('/compile'):
                    self.assertEqual(row['argv'][0], '<CC>')
                    self.assertIn('-Werror', row['argv'])
                    self.assertIn('-fsanitize=address,undefined', row['argv'])

    def reject(self, field, value, marker):
        data = copy.deepcopy(gate.load(gate.CONTRACT))
        data[field] = value
        original = gate.load
        with mock.patch.object(gate, 'load', side_effect=lambda p: data if p == gate.CONTRACT else original(p)):
            with self.assertRaisesRegex(ValueError, marker):
                gate.configuration()

    def test_schema_bool(self):
        self.reject('schema', True, 'current profile')

    def test_moving_current_ref(self):
        self.reject('source_commit', 'main', 'fixed source identity')

    def test_moving_legacy_ref(self):
        self.reject('legacy_test_commit', 'main', 'fixed source identity')

    def test_policy_drift(self):
        self.reject('native_obligations_sha256', '0' * 64, 'fixed build contract drift')

    def test_old_profile_drift(self):
        self.reject('base_mdio_profile_sha256', '0' * 64, 'fixed build contract drift')

    def test_legacy_profile_drift(self):
        self.reject('legacy_mdio_profile_sha256', '0' * 64, 'fixed build contract drift')

    def test_legacy_nss_profile_drift(self):
        self.reject('legacy_nss_profile_sha256', '0' * 64, 'fixed build contract drift')

    def test_historical_checkout_cannot_replace_current(self):
        self.reject('source_commit', gate.load(gate.CONTRACT)['legacy_test_commit'],
                    'current source cannot be historical test checkout')

    def test_profile_not_frozen(self):
        self.reject('frozen', False, 'current profile')


class SourceData(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'actual.c').write_bytes(b'TESTONLY source bytes\n')

    def test_code_and_metadata_partition(self):
        (self.root / 'version.date').write_bytes(b'123\n')
        stamp = '.prepared_' + 'a' * 32 + '_' + 'b' * 32
        (self.root / stamp).write_bytes(b'')
        code, meta = gate.partition(self.root)
        self.assertEqual(set(code), {'actual.c'})
        self.assertEqual(set(meta), {'version.date', stamp})

    def prepare_markers(self, completed=b'', check=b''):
        stamp = '.prepared_' + 'a' * 32 + '_' + 'b' * 32
        (self.root / stamp).write_bytes(completed)
        (self.root / (stamp + '_check')).write_bytes(check)
        return stamp

    def test_actual_openwrt_prepare_pair(self):
        stamp = self.prepare_markers()
        code, meta = gate.partition(self.root)
        self.assertEqual(code, {'actual.c': gate.sha(b'TESTONLY source bytes\n')})
        self.assertEqual(set(meta), {stamp, stamp + '_check'})

    def test_nonempty_prepare_check_rejected(self):
        self.prepare_markers(check=b'x')
        with self.assertRaisesRegex(ValueError, 'invalid stamp metadata'):
            gate.partition(self.root)

    def test_nonempty_completion_with_check_rejected(self):
        self.prepare_markers(completed=b'x')
        with self.assertRaisesRegex(ValueError, 'invalid stamp metadata'):
            gate.partition(self.root)

    def test_orphan_prepare_check_rejected(self):
        stamp = self.prepare_markers()
        (self.root / stamp).unlink()
        with self.assertRaisesRegex(ValueError, 'unmatched prepare check metadata'):
            gate.partition(self.root)

    def test_wrong_completion_identity_rejected(self):
        stamp = self.prepare_markers()
        (self.root / stamp).rename(self.root / ('.prepared_' + 'c' * 32 + '_' + 'd' * 32))
        with self.assertRaisesRegex(ValueError, 'unmatched prepare check metadata'):
            gate.partition(self.root)

    def test_duplicate_prepare_check_rejected(self):
        self.prepare_markers()
        (self.root / ('.prepared_' + 'c' * 32 + '_' + 'd' * 32 + '_check')).write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'invalid stamp metadata'):
            gate.partition(self.root)

    def test_malformed_check_remains_code(self):
        self.prepare_markers()
        name = '.prepared_not-a-hash_check'
        (self.root / name).write_bytes(b'')
        self.assertIn(name, gate.partition(self.root)[0])

    def test_nested_check_remains_code(self):
        stamp = self.prepare_markers()
        directory = self.root / 'nested'
        directory.mkdir()
        (directory / (stamp + '_check')).write_bytes(b'')
        self.assertIn('nested/' + stamp + '_check', gate.partition(self.root)[0])

    def test_check_symlink_rejected(self):
        stamp = self.prepare_markers()
        (self.root / (stamp + '_check')).unlink()
        (self.root / (stamp + '_check')).symlink_to(self.root / stamp)
        with self.assertRaisesRegex(ValueError, 'nonregular input'):
            gate.partition(self.root)

    def test_dirty_stamp(self):
        (self.root / ('.prepared_' + 'a' * 32 + '_' + 'b' * 32)).write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'invalid stamp metadata'):
            gate.partition(self.root)

    def test_duplicate_stamp(self):
        for char in ('a', 'b'):
            (self.root / ('.prepared_' + char * 32 + '_' + char * 32)).write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'invalid stamp metadata'):
            gate.partition(self.root)

    def test_version_metadata(self):
        (self.root / 'version.date').write_bytes(b'123')
        with self.assertRaisesRegex(ValueError, 'invalid version metadata'):
            gate.partition(self.root)

    def test_unknown_hidden_is_code_not_silently_ignored(self):
        (self.root / '.extra').write_bytes(b'foreign')
        self.assertIn('.extra', gate.partition(self.root)[0])

    def test_symlink_inventory(self):
        (self.root / 'alias').symlink_to(self.root / 'actual.c')
        with self.assertRaisesRegex(ValueError, 'nonregular input'):
            gate.partition(self.root)

    def test_symlink_root(self):
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe input root'):
            gate.path(self.root / 'alias', 'actual.c')

    def test_escape_path(self):
        with self.assertRaisesRegex(ValueError, 'unsafe input path'):
            gate.path(self.root, '../actual.c')

    def test_snapshot_missing_file_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing regular input'):
            gate.copy_code(self.root, self.root / 'snapshot', {'missing.c': '0' * 64})

    def test_snapshot_is_complete(self):
        expected = {'actual.c': gate.sha((self.root / 'actual.c').read_bytes())}
        gate.copy_code(self.root, self.root / 'snapshot', expected)
        self.assertEqual(gate.inventory(self.root / 'snapshot'), expected)

    def test_code_snapshot_keeps_all_code_and_leaves_admitted_metadata_in_place(self):
        stamp = self.prepare_markers()
        code, metadata = gate.partition(self.root)
        with tempfile.TemporaryDirectory() as output:
            snapshot = Path(output) / 'driver'
            gate.copy_code(self.root, snapshot, code)
            self.assertEqual(gate.inventory(snapshot), code)
            self.assertEqual(gate.partition(self.root), (code, metadata))
            self.assertEqual(set(metadata), {stamp, stamp + '_check'})

    def test_prepared_evidence_roundtrip_includes_hidden_markers(self):
        stamp = self.prepare_markers()
        expected = {'actual.c': gate.sha(b'TESTONLY source bytes\n')}
        with tempfile.TemporaryDirectory() as output:
            out = Path(output)
            code, meta = gate.prepared_partition(self.root, out, 'ssdk', expected)
            self.assertEqual(code, expected)
            receipt = gate.load(out / 'PREPARED-ssdk.json')
            self.assertEqual(receipt['status'], 'CAPTURED_NOT_ADMISSION_OR_RUNTIME')
            self.assertEqual(receipt['difference'], {'missing': [], 'extra': [], 'changed': []})
            self.assertEqual({r['origin'] for r in receipt['files']}, {'actual.c', stamp, stamp + '_check'})
            for row in receipt['files']:
                self.assertEqual((out / row['file']).read_bytes(), (self.root / row['origin']).read_bytes())
                self.assertNotIn('.prepared', row['file'])
                self.assertEqual(gate.sha((out / row['file']).read_bytes()), row['sha256'])
            self.assertEqual(meta, receipt['recipe_metadata'])

    def test_prepared_evidence_preserves_actual_drift(self):
        expected = {'actual.c': gate.sha(b'older source'), 'gone.c': gate.sha(b'missing')}
        (self.root / '.foreign').write_bytes(b'foreign')
        with tempfile.TemporaryDirectory() as output:
            out = Path(output)
            code, _ = gate.prepared_partition(self.root, out, 'ssdk', expected)
            receipt = gate.load(out / 'PREPARED-ssdk.json')
            self.assertEqual(receipt['difference'], {'missing': ['gone.c'], 'extra': ['.foreign'],
                                                     'changed': ['actual.c']})
            with self.assertRaisesRegex(ValueError, 'actual full SSDK38 code'):
                gate.need(code == expected, 'actual full SSDK38 code')

    def test_bad_metadata_saved_before_rejection(self):
        self.prepare_markers(check=b'foreign')
        with tempfile.TemporaryDirectory() as output:
            out = Path(output)
            with self.assertRaisesRegex(ValueError, 'invalid stamp metadata'):
                gate.prepared_partition(self.root, out, 'ssdk')
            receipt = gate.load(out / 'PREPARED-ssdk.json')
            self.assertEqual(receipt['status'], 'INCOMPLETE')
            self.assertEqual(receipt['error'], 'invalid stamp metadata')
            self.assertEqual(len(receipt['files']), 3)

    def test_prepared_evidence_immutable_end_input(self):
        original = gate.partition
        def mutate(root):
            code, meta = original(root)
            (root / 'actual.c').write_bytes(b'changed during inspection')
            return code, meta
        with tempfile.TemporaryDirectory() as output, mock.patch.object(gate, 'partition', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'prepared evidence end stability'):
                gate.prepared_partition(self.root, Path(output), 'ssdk')

    def test_prepared_evidence_label_cannot_escape(self):
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaisesRegex(ValueError, 'fixed prepared evidence label'):
                gate.prepared_partition(self.root, Path(output), '../escape')

    def test_three_exact_phy_controls_exported_without_native_execution(self):
        exports = {}
        for name, raw in [('marker-valid', b''), ('both-valid', b''), ('marker-nonempty', b'x')]:
            file = self.root / 'legacy37/ssdk049-phy-ops/metadata-controls' / name / '.prepared_deadbeef'
            file.parent.mkdir(parents=True)
            file.write_bytes(raw)
        rows = gate.add_phy_controls(self.root, exports)
        self.assertEqual(len(rows), 3)
        self.assertEqual({row['origin'] for row in rows}, {'HIDDEN-CONTROL/marker-valid',
                         'HIDDEN-CONTROL/both-valid', 'HIDDEN-CONTROL/marker-nonempty'})
        for row in rows:
            self.assertNotIn('.prepared', row['file'])
            self.assertEqual(gate.sha((self.root / row['file']).read_bytes()), row['sha256'])

    def test_wrong_phy_control_not_exported(self):
        file = self.root / 'legacy37/ssdk049-phy-ops/metadata-controls/marker-valid/.prepared_deadbeef'
        file.parent.mkdir(parents=True)
        file.write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError, 'fixed PHY metadata export'):
            gate.add_phy_controls(self.root, {})


class ExactPatchOutput(unittest.TestCase):
    def setUp(self):
        self.canonical = b'patching file src/init/ssdk_phy_i2c.c\n'
        self.digest = gate.sha(self.canonical)

    def test_gnu_spelling(self):
        gate.exact_patch_stdout(self.canonical, 'reverse050', self.digest)

    def test_apple_spelling(self):
        gate.exact_patch_stdout(b"patching file 'src/init/ssdk_phy_i2c.c'\n", 'reverse050', self.digest)

    def test_wrong_path(self):
        with self.assertRaisesRegex(ValueError, 'native exact patch output'):
            gate.exact_patch_stdout(b'patching file foreign.c\n', 'reverse050', self.digest)

    def test_offset_diagnostic(self):
        with self.assertRaisesRegex(ValueError, 'native exact patch output'):
            gate.exact_patch_stdout(self.canonical + b'Hunk succeeded with offset 1\n', 'reverse050', self.digest)

    def test_extra_newline(self):
        with self.assertRaisesRegex(ValueError, 'native exact patch output'):
            gate.exact_patch_stdout(self.canonical + b'\n', 'reverse050', self.digest)

    def test_unreviewed_expected_digest(self):
        with self.assertRaisesRegex(ValueError, 'native exact patch output'):
            gate.exact_patch_stdout(self.canonical, 'reverse050', '0' * 64)

    def test_full_patch_corpus_both_tools_and_frozen_spellings(self):
        names = {'reverse050': 'src/init/ssdk_phy_i2c.c', 'forward050': 'src/init/ssdk_phy_i2c.c',
                 'roundtrip-reverse': 'tunipip6/nss_connmgr_tunipip6_sysctl.c',
                 'roundtrip-forward': 'tunipip6/nss_connmgr_tunipip6_sysctl.c'}
        for label, name in names.items():
            variants = [('patching file ' + name + '\n').encode(), ("patching file '" + name + "'\n").encode()]
            for raw in variants:
                for recorded in variants:
                    with self.subTest(label=label, raw=raw, recorded=recorded):
                        gate.exact_patch_stdout(raw, label, gate.sha(recorded))


class LegacyReceipt(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        child = self.root / 'suite/RESULTS.json'
        child.parent.mkdir()
        child.write_bytes(b'{"scope":"TESTONLY receipt parser control, no native execution"}\n')
        self.data = {'status': 'PASS_FROZEN_HOST_COMMAND_INPUTS_NOT_RUNTIME',
                     'profile_sha256': gate.sha(gate.BASE_NSS.read_bytes()), 'runtime_approved': False,
                     'source_receipt_sha256': gate.sha(child.read_bytes()),
                     'verified': {'positive_count': 20, 'source_negatives': 22, 'commands': 76,
                                  'source_and_regular_commands': 73, 'numeric_model_commands': 3}}

    def verify(self):
        (self.root / 'RESULTS.json').write_text(json.dumps(self.data))
        return gate.verify_legacy(self.root, 'nss')

    def test_consistent_test_only_receipt(self):
        self.assertEqual(self.verify()['scope'], 'HISTORICAL_PREFIX_ONLY_NOT_CURRENT_LAYER')

    def test_wrong_status(self):
        self.data['status'] = 'INCOMPLETE'
        with self.assertRaisesRegex(ValueError, 'legacy NSS qualification'):
            self.verify()

    def test_missing_semantic_negative(self):
        self.data['verified']['source_negatives'] = 21
        with self.assertRaisesRegex(ValueError, 'legacy NSS complete suite'):
            self.verify()

    def test_bool_count(self):
        self.data['verified']['commands'] = True
        with self.assertRaisesRegex(ValueError, 'legacy NSS complete suite'):
            self.verify()

    def test_child_replaced(self):
        (self.root / 'suite/RESULTS.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'legacy NSS child receipt binding'):
            self.verify()

    def test_mdio_bool_child_exit_rejected(self):
        labels = ['dp019', 'ssdk044', 'ssdk045', 'ssdk046', 'ssdk047',
                  'ssdk048-lookup', 'ssdk048-cache', 'ssdk049-phy-ops']
        rows = []
        for label in labels:
            child = self.root / label / 'RESULTS.json'
            child.parent.mkdir()
            child.write_bytes(b'TESTONLY child receipt; no native execution\n')
            rows.append({'label': label, 'returncode': 0, 'receipt_sha256': gate.sha(child.read_bytes())})
        rows[0]['returncode'] = False
        (self.root / 'RESULTS.json').write_text(json.dumps({
            'status': 'PASS_HOST_REGRESSIONS_NOT_SHARED_RETIREMENT_OR_RUNTIME',
            'profile_sha256': gate.sha(gate.LEGACY_MDIO.read_bytes()), 'shared_UK_SD_PHY_retirement': 'OPEN',
            'device_or_performance_qualification': False, 'results': rows}))
        with self.assertRaisesRegex(ValueError, 'legacy MDIO child receipt binding'):
            gate.verify_legacy(self.root, 'mdio')


class SyntheticReceipt(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'input.c').write_bytes(b'TESTONLY input; never compiled\n')
        self.out = self.root / 'receipt'
        self.out.mkdir()
        self.policy = {'fields': {'synthetic_control_count': 1},
                       'inputs': {'input.c': gate.sha((self.source / 'input.c').read_bytes())}, 'commands': []}
        self.data = {'status': 'PASS_HOST_I2C_IO_ONLY', 'sanitize': True, 'LSan': 'NOT_VERIFIED',
                     'end_input_stability': True, 'synthetic_control_count': 1,
                     'inputs': {str(self.source / n): h for n, h in self.policy['inputs'].items()}, 'commands': []}
        self.add('synthetic/run', 86, '', 'I2C_IO CONTROL\n', None)

    def add(self, label, rc, stdout, stderr, sanitizer):
        self.policy['commands'].append({'label': label, 'argv': ['<OUT>/program.host', 'case'],
                                       'returncode': rc, 'stdout_sha256': gate.sha(stdout.encode()),
                                       'stderr_sha256': None if sanitizer else gate.sha(stderr.encode()),
                                       'sanitizer': sanitizer, 'ASAN_OPTIONS': 'fixed-test', 'UBSAN_OPTIONS': 'fixed-test'})
        self.data['commands'].append({'label': label, 'command': [str(self.out / 'program.host'), 'case'],
                                      'returncode': rc, 'stdout': stdout, 'stderr': stderr,
                                      'ASAN_OPTIONS': 'fixed-test', 'UBSAN_OPTIONS': 'fixed-test'})

    def save(self):
        for row in self.data['commands']:
            stem = self.out / 'logs' / row['label']
            stem.parent.mkdir(parents=True, exist_ok=True)
            for stream in ('stdout', 'stderr'):
                stem.with_suffix('.' + stream).write_bytes(row[stream].encode())
            stem.with_suffix('.json').write_text(json.dumps(row))
        generated = gate.inventory(self.out)
        generated.pop('RESULTS.json', None)
        self.data['generated'] = generated
        (self.out / 'RESULTS.json').write_text(json.dumps(self.data))

    def verify(self):
        self.save()
        return gate.verify_native(self.out, 'i2c', self.source, 'cc', self.policy)

    def reject(self, marker):
        with self.assertRaisesRegex(ValueError, marker):
            self.verify()

    def test_consistent_synthetic_receipt_is_not_executed(self):
        self.assertFalse(self.verify()['runtime_approved'])

    def test_bool_exit(self):
        self.policy['commands'][0]['returncode'] = 0
        self.data['commands'][0]['returncode'] = False
        self.reject('native precise command exit')

    def test_arbitrary_nonzero_exit(self):
        self.data['commands'][0]['returncode'] = 1
        self.reject('native precise command exit')

    def test_timeout(self):
        self.data['commands'][0]['timeout'] = True
        self.reject('native precise command exit')

    def test_missing_command(self):
        self.data['commands'].clear()
        self.reject('native command inventory')

    def test_extra_command(self):
        self.data['commands'].append(copy.deepcopy(self.data['commands'][0]))
        self.reject('native command inventory')

    def test_changed_command(self):
        self.data['commands'][0]['command'].append('foreign')
        self.reject('native exact command')

    def test_wrong_marker(self):
        self.data['commands'][0]['stderr'] = 'I2C_IO WRONG\n'
        self.reject('native exact stream')

    def test_noisy_stdout(self):
        self.data['commands'][0]['stdout'] = 'noise\n'
        self.reject('native exact stream')

    def test_input_drift(self):
        (self.source / 'input.c').write_bytes(b'changed')
        self.reject('fixed input drift')

    def test_untyped_obligation(self):
        self.data['synthetic_control_count'] = True
        self.reject('native fixed obligations')

    def test_partial_status(self):
        self.data['status'] = 'INCOMPLETE'
        self.reject('complete current native status')

    def test_sanitizer_cannot_be_disabled(self):
        self.data['sanitize'] = False
        self.reject('complete current native status')

    def test_competing_sanitizer_rejected(self):
        self.add('synthetic/asan', 97, '', 'ERROR: AddressSanitizer: heap-buffer-overflow\n', 'asan')
        self.data['commands'][-1]['stderr'] += 'runtime error: unrelated\n'
        self.reject('native directed sanitizer activation')


class Wiring(unittest.TestCase):
    def test_actual_prepared_is_checked_before_historical_prefix_mode(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        self.assertEqual(workflow.count('--current-layers --legacy-source-root "$GITHUB_WORKSPACE/core-legacy-source"'), 1)
        self.assertIn('verify-ssdk-retirement-admission.py', workflow)
        self.assertIn('ref: ${{ steps.prefix-contract.outputs.accepted_ref }}', workflow)
        self.assertIn('path: core-accepted-source\n          persist-credentials: false', workflow)
        self.assertIn('ref: ${{ steps.prefix-contract.outputs.legacy_ref }}', workflow)
        self.assertIn('path: core-legacy-source\n          persist-credentials: false', workflow)
        self.assertLess(workflow.index('Checkout test-only historical prefix'), workflow.index('Validate reviewed MDIO'))
        actual = 'python3 "$GITHUB_WORKSPACE/.github/scripts/verify-nss-root-host.py"'
        historical = 'python3 "$GITHUB_WORKSPACE/.github/scripts/verify-nss-command-inputs.py"'
        self.assertEqual(workflow.count(actual), 1)
        self.assertEqual(workflow.count(historical), 1)
        self.assertLess(workflow.index(actual), workflow.index(historical))
        self.assertIn('--source-root . --driver "${command_drivers[0]}"', workflow)
        self.assertIn('--source-root "$GITHUB_WORKSPACE/core-accepted-source" --driver "$evidence/root-host/driver25-prefix" --clients "${command_clients[0]}"', workflow)
        self.assertNotIn('--source-root "$GITHUB_WORKSPACE/core-accepted-source" --driver "${command_drivers[0]}"', workflow)

    def test_lint_runs_admission_controls(self):
        self.assertIn('python3 -B tests/test-current-layer-integration.py', (ROOT / '.github/workflows/lint.yml').read_text())

    def test_prefix_controls_export_before_current_native(self):
        code = (ROOT / '.github/scripts/verify-ax6-current-layers.py').read_text()
        self.assertLess(code.index('            add_phy_controls(out, exports)'),
                        code.index("        invoke('current-layer-native', native)"))


if __name__ == '__main__':
    unittest.main()
