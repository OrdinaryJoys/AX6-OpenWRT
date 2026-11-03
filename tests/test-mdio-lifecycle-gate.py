#!/usr/bin/env python3
"""Synthetic admission/wiring controls, never target-driver qualification."""
import copy
import difflib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
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

    def test_previous35_profile_is_not_accepted_as_current(self):
        self.profile['profile'] = 'DP19_SSDK35_ARGUMENTS_AND_OF_LEASES'; self.reject()

    def test_previous36_profile_is_not_accepted_as_current(self):
        self.profile['profile'] = 'DP19_SSDK36_EXTERNAL_ADMISSION_AND_OF_LEASES'; self.reject()

    def test_new_external_test_assets_are_bound(self):
        required = {'tests/test-ssdk-external-switch-lookups.py',
                    'tests/test-ssdk-external-cache-admission.py',
                    'tests/test-ssdk-netdev-cache.py',
                    'tests/ssdk-netdev-cache/host-fixture.c',
                    'tests/ssdk_source_prepare.py', 'tests/edma_patch_context.py'}
        required.update({'tests/test-ssdk-phy-ops-lifetime.py',
                         'tests/ssdk-phy-ops-lifetime/source.py',
                         'tests/ssdk-phy-ops-lifetime/mutations.py',
                         'tests/ssdk-phy-ops-lifetime/fixture.c',
                         'tests/nss-dp-containment/extract_prepared_c.py'})
        self.assertTrue(required <= self.profile['assets'].keys())
        self.assertEqual(len(self.profile['ssdk']['patches']), 37)
        phy = self.profile['ssdk']['reverse_steps'][0]
        self.assertEqual((phy['patch'], phy['label'], phy['keep']),
                         ('049-module-lifetime-shared-phy-ops.patch', 'ssdk36', True))
        self.assertEqual(phy['inventory_sha256'],
                         '5fc401cccd3338163a1035af6c177ff095f36c450e805f7b7c8a8d5591e020f8')
        first = self.profile['ssdk']['reverse_steps'][1]
        self.assertEqual((first['patch'], first['label'], first['keep']),
                         ('048-exclude-unconnected-external-switch-lookups.patch', 'ssdk35', True))
        self.assertEqual(first['inventory_sha256'],
                         'b11eb85e015e2bb0d7cd5ae91b6c902f473b3a3b7cdeb6c8e7bc3a9528560fd2')

    def test_duplicate_json_field(self):
        with self.assertRaises(ValueError):
            json.loads('{"schema":1,"schema":1}', object_pairs_hook=gate.unique)


class Wiring(unittest.TestCase):
    def test_actual_discovery_zero_one_multiple_and_nested(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        step = workflow.split('      - name: Validate reviewed MDIO lifecycle source and host regressions\n', 1)[1].split('\n      - ', 1)[0]
        script = '\n'.join(line[10:] for line in step.split('        run: |\n', 1)[1].splitlines()) + '\n'
        for dp_count, ssdk_count, nested in [(0, 1, False), (1, 0, False), (2, 1, False),
                                             (1, 2, False), (1, 1, False), (1, 1, True)]:
            with self.subTest(dp=dp_count, ssdk=ssdk_count, nested=nested), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                prepared = root / 'build_dir/target-aarch64_cortex-a53_musl/linux-qualcommax_ipq807x'
                prepared.mkdir(parents=True)
                for stem, count in [('qca-nss-dp', dp_count), ('qca-ssdk', ssdk_count)]:
                    for i in range(count): (prepared / (stem + '-' + str(i))).mkdir()
                if nested: (prepared / 'old/quarantine/qca-nss-dp-stale').mkdir(parents=True)
                binary = root / 'bin'; binary.mkdir()
                recorder = binary / 'python3'
                # Records the CLI handoff only; does not fake a driver regression result.
                recorder.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$MDIO_TEST_RECORD"\n')
                recorder.chmod(0o755)
                record = root / 'argv'
                env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
                           GITHUB_WORKSPACE=str(ROOT), MDIO_TEST_RECORD=str(record))
                ran = subprocess.run([os.environ.get('AX6_TEST_BASH', shutil.which('bash')), '-s'],
                                     input=script, cwd=root, env=env, text=True, capture_output=True)
                expected = dp_count == ssdk_count == 1
                self.assertEqual(ran.returncode == 0, expected, ran.stderr)
                self.assertEqual(record.exists(), expected)
                if expected:
                    args = record.read_text().splitlines()
                    self.assertEqual(args[args.index('--dp') + 1], str(prepared.relative_to(root) / 'qca-nss-dp-0'))
                    self.assertEqual(args[args.index('--ssdk') + 1], str(prepared.relative_to(root) / 'qca-ssdk-0'))

    def test_real_prepared_trees_and_preserved_order(self):
        workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
        call = 'python3 "$GITHUB_WORKSPACE/.github/scripts/verify-mdio-lifecycle-repairs.py"'
        self.assertEqual(workflow.count(call), 1)
        self.assertIn('--source-root . --dp "$lifecycle_dp_source" --ssdk "$lifecycle_ssdk_source" --cc cc', workflow)
        marker = '      - name: Validate reviewed MDIO lifecycle source and host regressions\n'
        self.assertEqual(workflow.count(marker), 1)
        step = workflow.split(marker, 1)[1].split('\n      - ', 1)[0]
        self.assertIn(call, step)
        self.assertIn('test "${#lifecycle_dp_sources[@]}" -eq 1', step)
        self.assertIn('test "${#lifecycle_ssdk_sources[@]}" -eq 1', step)
        self.assertLess(workflow.index('make target/linux/prepare V=s'), workflow.index(call))
        self.assertLess(workflow.index('make package/qca-nss/qca-ssdk/prepare V=s'), workflow.index(call))
        self.assertLess(workflow.index('make package/qca-nss/qca-nss-dp/prepare V=s'), workflow.index(call))
        self.assertIn('python3 -B tests/test-mdio-lifecycle-gate.py', (ROOT / '.github/workflows/lint.yml').read_text())


class ExactReverse(unittest.TestCase):
    """Real patch subprocess on synthetic text, not a simulated driver result."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.current, self.output = [self.root / n for n in ('source','current','output')]
        self.current.mkdir(); self.output.mkdir()
        self.before = ''.join('unchanged-%02d\n' % i for i in range(20))
        self.after = self.before.replace('unchanged-10', 'reviewed-replacement')
        self.patch = self.source / 'package/qca-nss/test-only/patches/001-roundtrip.patch'
        self.patch.parent.mkdir(parents=True)
        self.patch.write_text(''.join(difflib.unified_diff(self.before.splitlines(True),
                              self.after.splitlines(True), fromfile='a/input.c', tofile='b/input.c', n=3)))
        (self.current / 'input.c').write_text(self.after)
        self.item = {'package':'test-only','prepared_files':{'input.c':gate.sha(self.after.encode())},
                     'reverse_steps':[{'patch':self.patch.name,'label':'baseline','keep':True,
                                       'inventory_sha256':gate.inventory_sha({'input.c':gate.sha(self.before.encode())})}]}

    def reverse(self):
        return gate.reverse(self.source, self.current, self.item, self.output, 'work')

    def test_balanced_interior_reverse_preserves_full_baseline(self):
        result = self.reverse()
        self.assertEqual((result['baseline'] / 'input.c').read_text(), self.before)
        receipt = json.loads((self.output / 'baseline.reverse.json').read_text())
        self.assertEqual(receipt['returncode'], 0)
        self.assertIn('--fuzz=0', receipt['command'])

    def test_altered_changed_line_is_rejected(self):
        (self.current / 'input.c').write_text(self.after.replace('reviewed-replacement','unreviewed'))
        with self.assertRaisesRegex(ValueError, 'exact baseline reverse'): self.reverse()

    def test_context_mismatch_cannot_use_fuzz(self):
        (self.current / 'input.c').write_text(self.after.replace('unchanged-07','altered-context'))
        with self.assertRaisesRegex(ValueError, 'exact baseline reverse'): self.reverse()

    def test_unchanged_foreign_bytes_cannot_bypass_inventory(self):
        (self.current / 'input.c').write_text(self.after.replace('unchanged-00','foreign-modification'))
        with self.assertRaisesRegex(ValueError, 'baseline whole-tree mismatch'): self.reverse()


class CacheReceipt(unittest.TestCase):
    """Synthetic receipt-parser controls only; no synthetic C is executed."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = {'status': 'PASS_HOST_CURRENT_CACHE_AND_EXTERNAL_ADMISSION_NOT_RUNTIME',
                     'scope': 'ACTUAL_CURRENT_CACHE_C_HOST_MODEL_NOT_REAL_KERNEL',
                     'positives': [], 'negatives': [], 'compiles': []}
        for profile in gate.CACHE_PROFILES:
            for case in gate.CACHE_CASES:
                self.data['positives'].append({'profile': profile, 'case': case,
                    **self.record(profile + '-' + case, 0, ('PASS ' + case + '\n').encode(), b'')})
        for label, marker in gate.CACHE_NEGATIVES.items():
            self.data['negatives'].append({'label': label, 'marker': marker,
                **self.record('negative-' + label, 86, b'', ('SSDK_CACHE ' + marker + '\n').encode())})
        for label in {'candidate-' + p for p in gate.CACHE_PROFILES} | {
                'mutant-' + n for n in gate.CACHE_NEGATIVES}:
            raw = ('TESTONLY receipt data; not C ' + label).encode()
            (self.root / (label + '.c')).write_bytes(raw)
            self.data['compiles'].append({'label': label, 'c_sha256': gate.sha(raw),
                **self.record(label + '.compile', 0, b'', b'')})

    def record(self, name, rc, stdout, stderr):
        result = {'returncode': rc, 'timeout': False}
        for stream, raw in [('stdout', stdout), ('stderr', stderr)]:
            filename = name + '.' + stream
            (self.root / filename).write_bytes(raw)
            result[stream + '_file'] = filename
            result[stream + '_sha256'] = gate.sha(raw)
        return result

    def reject(self):
        with self.assertRaises((ValueError, OSError, KeyError)):
            gate.verify_external_cache(self.root, self.data)

    def test_exact_receipt_and_raw_bytes(self):
        gate.verify_external_cache(self.root, self.data)

    def test_missing_positive(self):
        self.data['positives'].pop(); self.reject()

    def test_duplicate_positive(self):
        self.data['positives'][-1] = self.data['positives'][0]; self.reject()

    def test_missing_negative(self):
        self.data['negatives'].pop(); self.reject()

    def test_wrong_runtime_marker(self):
        self.data['negatives'][0]['marker'] = 'wrong'; self.reject()

    def test_crash_is_not_a_semantic_negative(self):
        self.data['negatives'][0]['returncode'] = -11; self.reject()

    def test_boolean_zero_exit_is_not_an_integer_success(self):
        self.data['positives'][0]['returncode'] = False; self.reject()

    def test_timeout(self):
        self.data['positives'][0]['timeout'] = True; self.reject()

    def test_modified_raw_stdout_even_with_new_hash(self):
        row = self.data['positives'][0]
        raw = b'PASS wrong\n'
        (self.root / row['stdout_file']).write_bytes(raw)
        row['stdout_sha256'] = gate.sha(raw)
        self.reject()

    def test_sanitizer_noise_cannot_pass_by_updating_hash(self):
        row = self.data['negatives'][0]
        raw = (self.root / row['stderr_file']).read_bytes() + b'AddressSanitizer: crash\n'
        (self.root / row['stderr_file']).write_bytes(raw)
        row['stderr_sha256'] = gate.sha(raw)
        self.reject()

    def test_missing_or_failed_compilation(self):
        self.data['compiles'][0]['returncode'] = 1; self.reject()

    def test_generated_C_mutation(self):
        row = self.data['compiles'][0]
        (self.root / (row['label'] + '.c')).write_text('changed')
        self.reject()

    def test_untrusted_parent_path(self):
        self.data['positives'][0]['stdout_file'] = '../outside'
        self.reject()


class PhyReceipt(unittest.TestCase):
    """Synthetic receipt parsing only; these files are never native executables."""
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.cc = 'TESTONLY_CC_NOT_EXECUTED'
        self.flags = ['-std=gnu11', '-O1', '-g', '-pthread', '-Wall', '-Wextra', '-Werror',
                      '-Wno-unused-parameter', '-DIN_AQUANTIA_PHY']
        self.profile_flags = {'full': [], 'mini': ['-DIN_PORTCONTROL_MINI'],
                              'full-i2c': ['-DIN_PHY_I2C_MODE'],
                              'mini-i2c': ['-DIN_PORTCONTROL_MINI', '-DIN_PHY_I2C_MODE']}
        self.data = {'status': 'PASS_SCOPED_HOST_ONLY', 'scope': 'ACTUAL_FUNCTIONS_HOST_SUBSTITUTES_ONLY',
                     'target_kernel_runtime_approved': False,
                     'UK_witness': 'KNOWN_OPEN_NOT_REPAIRED_NOT_EXECUTED_OR_RECLASSIFIED',
                     'expected_case_names': gate.PHY_CASES, 'positive_cases': 68,
                     'runtime_mutants': 80, 'old_counterexample_runs': 8,
                     'positives': [], 'negatives': [], 'old_counterexamples': []}
        def process(label, rc, stdout='', stderr='', command=None):
            row = {'command': command, 'returncode': rc, 'stdout': stdout, 'stderr': stderr}
            self.persist(row, label)
            return row
        self.process = process
        def compiled(label, profile, instrumentation='address,undefined', text=b'TESTONLY C'):
            c_file, binary = self.root / (label + '.c'), self.root / (label + '.host')
            c_file.write_bytes(text)
            (self.root / (label + '.host')).write_bytes(b'TESTONLY NOT EXECUTABLE')
            command = [self.cc, *self.flags, '-fsanitize=' + instrumentation, '-fno-sanitize-recover=all',
                       '-fno-omit-frame-pointer', *self.profile_flags[profile], str(c_file), '-o', str(binary)]
            return {'generated_c_sha256': gate.sha(text),
                    'binary_sha256': gate.sha(b'TESTONLY NOT EXECUTABLE'),
                    'compile': process(label + '.compile', 0, command=command)}
        self.data['compiler'] = process('compiler', 0, 'TESTONLY compiler identity; never executed\n',
                                        command=[self.cc, '--version'])
        self.data['runtime_environment'] = {
            'ASAN_OPTIONS': 'detect_leaks=0:halt_on_error=1:abort_on_error=0:exitcode=97',
            'UBSAN_OPTIONS': 'halt_on_error=1:abort_on_error=0:print_stacktrace=1:exitcode=97'}
        for profile in ('full', 'mini', 'full-i2c', 'mini-i2c'):
            label = profile + '-positive'
            self.data['positives'].append(dict(profile=profile, cases=17,
                run=process(label + '.run', 0, ''.join('PASS ' + c + '\n' for c in gate.PHY_CASES),
                            command=[str(self.root / (label + '.host'))]), **compiled(label, profile)))
            for name, (case, marker) in gate.PHY_NEGATIVES.items():
                label = profile + '-mutant-' + name
                self.data['negatives'].append(dict(profile=profile, name=name, case=case, marker=marker,
                    run=process(label + '.run', 86, stderr='PHY_OPS ' + marker + '\n',
                                command=[str(self.root / (label + '.host')), case]), **compiled(label, profile)))
            for case in ('old-phy-no-own', 'old-phy-own'):
                label = profile + '-old36'
                self.data['old_counterexamples'].append(dict(profile=profile, case=case, marker='ops-not-owned',
                    run=process(label + '-' + case + '.run', 86, stderr='PHY_OPS ops-not-owned\n',
                                command=[str(self.root / (label + '.host')), case]), **compiled(label, profile)))
        examples = {
            'asan': {'returncode': 97, 'stdout': '',
                     'stderr': 'ERROR: AddressSanitizer: heap-buffer-overflow\nWRITE of size 4\n'},
            'ubsan': {'returncode': 98, 'stdout': '',
                      'stderr': 'runtime error: signed integer overflow: 2147483647 + 1\n'}}
        bodies = {
            'asan': b'#include <stdlib.h>\nint main(void){volatile int i=2;volatile int *p=malloc(sizeof(int));p[i]=1;free((void*)p);return 0;}\n',
            'ubsan': b'#include <limits.h>\nint main(void){volatile int n=INT_MAX;volatile int r=n+1;(void)r;return 0;}\n'}
        self.data['canaries'] = {}
        for kind, instrumentation, code in [('asan', 'address', 97), ('ubsan', 'undefined', 98)]:
            label = 'canary-' + kind
            self.data['canaries'][kind] = dict(instrumentation=instrumentation,
                environment={'ASAN_OPTIONS': f'detect_leaks=0:halt_on_error=1:abort_on_error=0:exitcode={code}',
                             'UBSAN_OPTIONS': f'halt_on_error=1:abort_on_error=0:exitcode={code}'},
                run=process(label + '.run', code, stderr=examples[kind]['stderr'],
                            command=[str(self.root / (label + '.host'))]),
                **compiled(label, 'full', instrumentation, bodies[kind]))
        controls = []
        for kind, good in examples.items():
            for key, value in [('returncode', 0), ('returncode', 1), ('returncode', -6),
                               ('returncode', 86), ('returncode', True), ('returncode', str(good['returncode'])),
                               ('returncode', 'timeout'), ('stdout', 'noise\n'), ('stderr', ''),
                               ('stderr', 'runtime error: unrelated\n'),
                               ('stderr', 'AddressSanitizer: DEADLYSIGNAL\n'),
                               ('stderr', examples['ubsan' if kind == 'asan' else 'asan']['stderr'])]:
                controls.append({'kind': kind, 'field': key, 'value': value})
        self.data['sanitizer_oracle_controls'] = {'valid': 2, 'rejected_pollution': 24, 'controls': controls}

    def persist(self, row, label):
        (self.root / (label + '.json')).write_text(json.dumps(row))
        (self.root / (label + '.stdout')).write_text(row['stdout'])
        (self.root / (label + '.stderr')).write_text(row['stderr'])

    def verify(self):
        gate.verify_phy_ops(self.root, self.data, self.cc)

    def reject(self):
        with self.assertRaises((ValueError, OSError, KeyError)):
            self.verify()

    def test_complete_receipt(self):
        self.verify()

    def test_missing_or_duplicate_mutant(self):
        self.data['negatives'][-1] = self.data['negatives'][0]
        self.reject()

    def test_boolean_exit(self):
        self.data['positives'][0]['run']['returncode'] = False
        self.reject()

    def test_wrong_marker(self):
        self.data['negatives'][0]['marker'] = 'other'
        self.reject()

    def test_sanitizer_exit_not_semantic(self):
        self.data['negatives'][0]['run']['returncode'] = 97
        self.reject()

    def test_rehashed_fake_stream(self):
        row = self.data['negatives'][0]
        label = row['profile'] + '-mutant-' + row['name'] + '.run'
        row['run'] = self.process(label, 86, stderr='PHY_OPS ' + row['marker'] + '\nnoise\n',
                                  command=row['run']['command'])
        self.reject()

    def test_raw_stream_must_match_record(self):
        (self.root / 'full-positive.run.stdout').write_text('changed')
        self.reject()

    def test_generated_c_drift(self):
        (self.root / 'mini-positive.c').write_text('changed')
        self.reject()

    def test_old_counterexample_not_optional(self):
        self.data['old_counterexamples'].pop()
        self.reject()

    def test_open_boundary_not_silently_closed(self):
        self.data['target_kernel_runtime_approved'] = True
        self.reject()

    def test_missing_canaries(self):
        del self.data['canaries']; self.reject()

    def test_empty_canaries(self):
        self.data['canaries'] = {}; self.reject()

    def test_unexpected_canary(self):
        self.data['canaries']['extra'] = self.data['canaries']['asan']; self.reject()

    def test_wrong_canary_instrumentation_label(self):
        self.data['canaries']['asan']['instrumentation'] = 'address,undefined'; self.reject()

    def test_combined_canary_compile_rejected_even_with_updated_raw_record(self):
        row = self.data['canaries']['asan']['compile']
        row['command'][10] = '-fsanitize=address,undefined'
        self.persist(row, 'canary-asan.compile'); self.reject()

    def test_ubsan_diagnostic_is_not_asan_activation(self):
        row = self.data['canaries']['asan']['run']
        row['stderr'] = 'runtime error: store to address with insufficient space\n'
        self.persist(row, 'canary-asan.run'); self.reject()

    def test_asan_diagnostic_is_not_ubsan_activation(self):
        row = self.data['canaries']['ubsan']['run']
        row['stderr'] = 'ERROR: AddressSanitizer: heap-buffer-overflow\nWRITE of size 4\n'
        self.persist(row, 'canary-ubsan.run'); self.reject()

    def test_canary_requires_directed_fault(self):
        row = self.data['canaries']['asan']['run']; row['stderr'] = 'ERROR: AddressSanitizer: heap-buffer-overflow\n'
        self.persist(row, 'canary-asan.run'); self.reject()

    def test_canary_mixed_diagnostic_rejected(self):
        row = self.data['canaries']['asan']['run']; row['stderr'] += 'runtime error: competing\n'
        self.persist(row, 'canary-asan.run'); self.reject()

    def test_canary_requires_exact_exit(self):
        row = self.data['canaries']['ubsan']['run']; row['returncode'] = 97
        self.persist(row, 'canary-ubsan.run'); self.reject()

    def test_canary_stdout_must_be_empty(self):
        row = self.data['canaries']['asan']['run']; row['stdout'] = 'noise\n'
        self.persist(row, 'canary-asan.run'); self.reject()

    def test_canary_raw_stream_mismatch(self):
        (self.root / 'canary-asan.run.stderr').write_text('changed'); self.reject()

    def test_canary_source_cannot_be_changed_with_updated_hash(self):
        (self.root / 'canary-asan.c').write_bytes(b'TESTONLY different probe')
        self.data['canaries']['asan']['generated_c_sha256'] = gate.sha(b'TESTONLY different probe')
        self.reject()

    def test_canary_binary_drift(self):
        (self.root / 'canary-ubsan.host').write_bytes(b'changed'); self.reject()

    def test_canary_source_symlink(self):
        target = self.root / 'canary-asan.c'; target.rename(self.root / 'outside')
        target.symlink_to(self.root / 'outside'); self.reject()

    def test_canary_environment_must_be_fixed(self):
        self.data['canaries']['asan']['environment']['UBSAN_OPTIONS'] = 'halt_on_error=0'; self.reject()

    def test_formal_environment_must_be_fixed(self):
        self.data['runtime_environment']['ASAN_OPTIONS'] = 'halt_on_error=0'; self.reject()

    def test_missing_canary_oracle(self):
        del self.data['sanitizer_oracle_controls']; self.reject()

    def test_incomplete_canary_oracle(self):
        self.data['sanitizer_oracle_controls']['controls'].pop(); self.reject()

    def test_canary_oracle_boolean_is_not_integer(self):
        self.data['sanitizer_oracle_controls']['controls'][1]['value'] = True; self.reject()

    def test_formal_compile_must_keep_both_sanitizers(self):
        row = self.data['positives'][0]['compile']; row['command'][10] = '-fsanitize=address'
        self.persist(row, 'full-positive.compile'); self.reject()

    def test_appended_disable_flag_rejected(self):
        row = self.data['positives'][0]['compile']; row['command'].insert(11, '-fno-sanitize=address')
        self.persist(row, 'full-positive.compile'); self.reject()

    def test_wrong_profile_compile_rejected(self):
        row = self.data['positives'][1]['compile']; row['command'].remove('-DIN_PORTCONTROL_MINI')
        self.persist(row, 'mini-positive.compile'); self.reject()

    def test_compiler_identity_is_bound_to_cli(self):
        self.data['compiler']['command'][0] = 'other-compiler'
        self.persist(self.data['compiler'], 'compiler'); self.reject()

    def test_compile_output_campaign_root_must_match(self):
        row = self.data['positives'][1]['compile']
        row['command'][-3] = '/other/mini-positive.c'; row['command'][-1] = '/other/mini-positive.host'
        self.persist(row, 'mini-positive.compile'); self.reject()

    def test_run_case_command_is_bound(self):
        row = self.data['negatives'][0]['run']; row['command'][-1] = 'unrelated-case'
        self.persist(row, 'full-mutant-overwrite-foreign.run'); self.reject()

    def test_compile_argv_not_a_string(self):
        self.data['positives'][0]['compile']['command'] = 'TESTONLY bad shape'; self.reject()

    def test_floating_point_count_not_accepted(self):
        self.data['positive_cases'] = 68.0; self.reject()


if __name__ == '__main__':
    unittest.main()
