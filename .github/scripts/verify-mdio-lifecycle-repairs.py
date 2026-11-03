#!/usr/bin/env python3
"""Fixed reviewed input admission and real-source host regressions; not runtime acceptance."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / '.github/ax6-mdio-lifecycle-contract.json'
CACHE_CASES = '''readiness normal primary-only duplicate replacement rename all-slots identity-hw reader
stop replay-success replay-api-error replay-fail-0 replay-fail-1 replay-fail-2
admission bounds copy-bounds legacy tombstone g3-missing g3-no-phy g3-success dsa sysfs
fdb-new fdb-expire fdb-missing property-domain mark-states mark-reject mark-failed-register
mark-reregister external-disconnected external-skip-stale-first'''.split()
CACHE_PROFILES = {'hppe', 'hppe-dsa', 'appe-dsa', 'mp', 'mp-dsa'}
CACHE_NEGATIVES = dict(zip('''old-publisher property-wrong-row unregister-missing one-cell-put
put-locked duplicate-hold stale-primary first-slot-only chip-before-retire tombstone-fallback
forget-managed pin-unlocked stop-accepting failed-replay-no-sweep unowned-unregister g3-no-put
g3-postput dsa-no-put rename-switch-missing ready-always ready-never unknown-legacy-denied
duplicate-notifier sysfs-old-cast mark-no-bit mark-ignore-live mark-ignore-device mark-ignore-chip
mark-ignore-variant mark-ignore-init mark-ignore-cpu mark-ignore-port-cap mark-forget-stop
invert-connected-publisher'''.split(), '''DISCONNECTED_STATUS PROPERTY_ROW_ISOLATION UNREGISTER_REFS
UNREGISTER_REFS PUT_UNDER_CACHE_LOCK DUP_REGISTER_REF STALE_EVENT_REPLACEMENT MATCH_ALL_CELLS
HARDWARE_ON_RETIRE LEGACY_AFTER_RETIRE LEGACY_AFTER_RETIRE READ_PIN_AFTER_UNLOCK STOP_NO_PUBLISH
FAILED_REPLAY_CURRENT_LEAK NOTIFIER_ACQUISITION_LEDGER G3_NO_PHY_PUT PHY_MAP_AFTER_PUT
DSA_READER_BALANCE SWITCH_RENAME COLD_READY LIVE_READY NAME_AVAILABLE NOTIFIER_DUPLICATE_OWNER
FAL_OUTPUT_ALIGNMENT LEGACY_AFTER_RETIRE MARK_COLD MARK_REJECT_DEVICE MARK_REJECT_CHIP
MARK_REJECT_VARIANT MARK_REJECT_UNINITIALIZED MARK_REJECT_CPU MARK_REJECT_PORT
LEGACY_AFTER_RETIRE DISCONNECTED_STATUS'''.split()))
PHY_CASES = '''registration invalid-registration unregister-live prepare-slot getters old-phy-no-own
old-phy-own borrowed-heap empty-device invalid-cleanup callback-exit aqua-repeated aqua-retry
aqua-foreign aqua-hw-error irq-restore concurrent-writers'''.split()
PHY_NEGATIVES = {
    'overwrite-foreign': ('registration', 'register-no-replace'),
    'same-object-not-idempotent': ('registration', 'register-idempotent'),
    'unregister-matching-live': ('unregister-live', 'unregister-live'),
    'unregister-ignores-identity': ('unregister-live', 'unregister-stale'),
    'prepare-clears-borrowed': ('prepare-slot', 'prepare-occupied'),
    'prepare-frees-borrowed': ('prepare-slot', 'ops-not-owned'),
    'cleanup-clears-global': ('old-phy-no-own', 'peer-visible'),
    'cleanup-frees-global': ('borrowed-heap', 'ops-not-owned'),
    'cleanup-clears-peer': ('old-phy-own', 'peer-state'),
    'cleanup-keeps-local-bitmap': ('old-phy-own', 'local-state'),
    'cleanup-clears-before-exit': ('callback-exit', 'exit-local'),
    'register-without-lock': ('registration', 'register-locked'),
    'getter-without-lock': ('getters', 'getter-locked'),
    'prepare-without-lock': ('prepare-slot', 'prepare-locked'),
    'unregister-without-lock': ('unregister-live', 'unregister-locked'),
    'getter-rejects-last-port': ('getters', 'getter-valid'),
    'ignore-registration-error': ('aqua-retry', 'hw-after-registration'),
    'discard-hw-error': ('aqua-hw-error', 'hw-first-error'),
    'failed-once-latch': ('aqua-retry', 'hw-after-registration'),
    'wrong-field-mapping': ('aqua-repeated', 'mapping'),
}


def need(ok, why):
    if not ok:
        raise ValueError(why)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate profile key')
        result[key] = value
    return result


def path(root, name):
    relative = PurePosixPath(name)
    need(not relative.is_absolute() and '..' not in relative.parts and relative.parts, 'unsafe relative path')
    target = root
    for part in relative.parts:
        target = target / part
        need(not target.is_symlink(), 'symlink input: ' + name)
    need(target.is_file(), 'missing input: ' + name)
    return target


def check(root, entries):
    for name, digest in entries.items():
        need(re.fullmatch('[0-9a-f]{64}', digest) is not None, 'bad digest')
        need(sha(path(root, name).read_bytes()) == digest, 'input drift: ' + name)


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes())
            for p in sorted(root.rglob('*')) if p.is_file()}


def inventory_sha(entries):
    return sha(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode())


def admit(source, dp, ssdk, profile):
    need(type(profile['schema']) is int and profile['schema'] == 1 and
         profile['profile'] == 'DP19_SSDK37_EXTERNAL_AND_MODULE_OPS_LEASES', 'unknown profile')
    check(source, profile['assets'])
    for label, tree, count in [('dp', dp, 19), ('ssdk', ssdk, 37)]:
        item = profile[label]
        package = source / 'package/qca-nss' / ('qca-nss-dp' if label == 'dp' else 'qca-ssdk')
        patches = sorted((package / 'patches').glob('*.patch'))
        need(len(patches) == count and {p.name for p in patches} == set(item['patches']), 'patch inventory')
        check(package / 'patches', item['patches'])
        need(sha(path(package, 'Makefile').read_bytes()) == item['recipe_sha256'], 'recipe drift')
        need(len(item['prepared_files']) == (80 if label == 'dp' else 692), 'incomplete prepared profile')
        check(tree, item['prepared_files'])
    return profile


def reverse(source, current, item, output, stem):
    """Copy only reviewed regular inputs, then undo known patches with full-result hashes."""
    tree = output / stem
    tree.mkdir()
    for relative in item['prepared_files']:
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path(current, relative), target)
    result = {}
    for step in item['reverse_steps']:
        patch = path(source / 'package/qca-nss' / item['package'] / 'patches', step['patch'])
        command = ['patch', '-R', '-p1', '--batch', '--fuzz=0', '-V', 'none']
        ran = subprocess.run(command, cwd=tree, input=patch.read_bytes(), capture_output=True, timeout=60)
        (output / (step['label'] + '.reverse.stdout')).write_bytes(ran.stdout)
        (output / (step['label'] + '.reverse.stderr')).write_bytes(ran.stderr)
        (output / (step['label'] + '.reverse.json')).write_text(json.dumps({
            'command': command, 'cwd': str(tree), 'patch_sha256': sha(patch.read_bytes()),
            'returncode': ran.returncode, 'stdout_sha256': sha(ran.stdout),
            'stderr_sha256': sha(ran.stderr)}, indent=2) + '\n')
        need(ran.returncode == 0 and not ran.stderr and not re.search(
             rb'offset|fuzz|FAILED|reject|malformed|Reversed', ran.stdout, re.I), 'exact baseline reverse: ' + step['label'])
        need(inventory_sha(inventory(tree)) == step['inventory_sha256'], 'baseline whole-tree mismatch')
        if step['keep']:
            destination = output / step['label']
            shutil.copytree(tree, destination)
            result[step['label']] = destination
    return result


def recorded_process(directory, row, rc, stdout, stderr):
    need(type(row['returncode']) is int and row['returncode'] == rc and
         row['timeout'] is False, 'recorded process exit/timeout')
    for stream, expected in [('stdout', stdout), ('stderr', stderr)]:
        raw = path(directory, row[stream + '_file']).read_bytes()
        need(raw == expected and sha(raw) == row[stream + '_sha256'],
             'recorded raw process stream: ' + stream)


def verify_external_cache(directory, data):
    need(data['status'] == 'PASS_HOST_CURRENT_CACHE_AND_EXTERNAL_ADMISSION_NOT_RUNTIME' and
         data['scope'] == 'ACTUAL_CURRENT_CACHE_C_HOST_MODEL_NOT_REAL_KERNEL', 'cache receipt scope')
    expected = {(p, c) for p in CACHE_PROFILES for c in CACHE_CASES}
    observed = {(r['profile'], r['case']) for r in data['positives']}
    need(len(CACHE_CASES) == 35 and len(CACHE_NEGATIVES) == 34 and
         observed == expected and len(data['positives']) == len(expected) == 175,
         'complete external/cache positive inventory')
    for row in data['positives']:
        recorded_process(directory, row, 0, ('PASS ' + row['case'] + '\n').encode(), b'')
    negatives = {row['label']: row for row in data['negatives']}
    need(set(negatives) == set(CACHE_NEGATIVES) and len(data['negatives']) == 34,
         'complete external/cache negative inventory')
    for name, row in negatives.items():
        marker = CACHE_NEGATIVES[name]
        need(row['marker'] == marker, 'external/cache marker: ' + name)
        recorded_process(directory, row, 86, b'', ('SSDK_CACHE ' + marker + '\n').encode())
    labels = {'candidate-' + p for p in CACHE_PROFILES} | {'mutant-' + n for n in negatives}
    need({r['label'] for r in data['compiles']} == labels and len(data['compiles']) == 39,
         'external/cache compilation inventory')
    for row in data['compiles']:
        recorded_process(directory, row, 0, b'', b'')
        need(sha(path(directory, row['label'] + '.c').read_bytes()) == row['c_sha256'],
             'external/cache generated C')


def verify_external_lookup(directory, data):
    need(data['status'] == 'PASS_HOST_LOOKUP_ADMISSION_NOT_SHARED_LIFECYCLE' and
         data['concurrent_reader_retirement_verified'] is False, 'lookup receipt scope')
    labels = {'candidate', 'old-zero-slot-witness'} | {
        group + '-' + name for group in ('port', 'device') for name in (
            'omit-connected', 'invert-connected', 'wrong-key', 'skip-last', 'skip-first',
            'wrong-slot', 'false-found', 'writes-peer')}
    need({r['label'] for r in data['records']} == labels and len(data['records']) == 18,
         'complete external lookup inventory')
    for row in data['records']:
        label = row['label']
        need(type(row['compile_returncode']) is int and row['compile_returncode'] == 0,
             'external lookup clean compilation')
        need(not path(directory, label + '.compile.stdout').read_bytes() and
             not path(directory, label + '.compile.stderr').read_bytes(), 'lookup compiler output')
        positive = label == 'candidate'
        reason = None if positive else ('foreign-state' if label.endswith('writes-peer') else
                 'device-result' if label.startswith('device-') else 'port-result')
        need(row['expected_marker'] == reason and type(row['returncode']) is int and
             row['returncode'] == (0 if positive else 86), 'lookup exact return/marker')
        need(sha(path(directory, label + '.c').read_bytes()) == row['c_sha256'] and
             sha(path(directory, label + '.host').read_bytes()) == row['binary_sha256'], 'lookup C/binary bytes')
        expected = (b'scenarios=8192 connected_first_match_only=1 runtime_retirement=0\n', b'') if positive else (
            b'', ('EXTERNAL_LOOKUP:' + reason + '\n').encode())
        for stream, raw in zip(('stdout', 'stderr'), expected):
            need(path(directory, label + '.' + stream).read_bytes() == raw and
                 row[stream + '_sha256'] == sha(raw), 'lookup exact raw result')


def verify_phy_ops(directory, data):
    need(data['status'] == 'PASS_SCOPED_HOST_ONLY' and
         data['scope'] == 'ACTUAL_FUNCTIONS_HOST_SUBSTITUTES_ONLY' and
         data['target_kernel_runtime_approved'] is False and
         data['UK_witness'] == 'KNOWN_OPEN_NOT_REPAIRED_NOT_EXECUTED_OR_RECLASSIFIED', 'PHY receipt scope')
    profiles = {'full', 'mini', 'full-i2c', 'mini-i2c'}
    need(data['expected_case_names'] == PHY_CASES and data['positive_cases'] == 68 and
         data['runtime_mutants'] == 80 and data['old_counterexample_runs'] == 8, 'PHY campaign inventory')

    def process(row, label, rc, stdout, stderr):
        need(type(row['returncode']) is int and row['returncode'] == rc and
             row['stdout'] == stdout and row['stderr'] == stderr, 'PHY precise process: ' + label)
        raw = json.loads(path(directory, label + '.json').read_text(), object_pairs_hook=unique)
        need(raw == row, 'PHY raw process receipt differs')
        for stream, expected in [('stdout', stdout), ('stderr', stderr)]:
            need(path(directory, label + '.' + stream).read_text() == expected, 'PHY raw stream: ' + label)

    def compiled(row, label):
        process(row['compile'], label + '.compile', 0, '', '')
        need(sha(path(directory, label + '.c').read_bytes()) == row['generated_c_sha256'] and
             sha(path(directory, label + '.host').read_bytes()) == row['binary_sha256'], 'PHY generated C/binary')

    need({r['profile'] for r in data['positives']} == profiles and len(data['positives']) == 4,
         'PHY positive profiles')
    for row in data['positives']:
        label = row['profile'] + '-positive'
        need(type(row['cases']) is int and row['cases'] == 17, 'PHY positive case count')
        compiled(row, label)
        process(row['run'], label + '.run', 0, ''.join('PASS ' + c + '\n' for c in PHY_CASES), '')
    need({(r['profile'], r['name']) for r in data['negatives']} ==
         {(p, n) for p in profiles for n in PHY_NEGATIVES} and len(data['negatives']) == 80,
         'PHY exact negative profiles/names')
    for row in data['negatives']:
        case, marker = PHY_NEGATIVES[row['name']]
        need((row['case'], row['marker']) == (case, marker), 'PHY negative case/marker')
        label = row['profile'] + '-mutant-' + row['name']
        compiled(row, label)
        process(row['run'], label + '.run', 86, '', 'PHY_OPS ' + marker + '\n')
    need({(r['profile'], r['case']) for r in data['old_counterexamples']} ==
         {(p, c) for p in profiles for c in ('old-phy-no-own', 'old-phy-own')} and
         len(data['old_counterexamples']) == 8, 'PHY old source witnesses')
    for row in data['old_counterexamples']:
        label = row['profile'] + '-old36'
        compiled(row, label)
        need(row['marker'] == 'ops-not-owned', 'PHY old source marker')
        process(row['run'], label + '-' + row['case'] + '.run', 86, '', 'PHY_OPS ops-not-owned\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--dp', required=True, type=Path)
    parser.add_argument('--ssdk', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cc', required=True)
    args = parser.parse_args()
    profile = json.loads(PROFILE.read_text(), object_pairs_hook=unique)
    admit(args.source_root, args.dp, args.ssdk, profile)
    args.output.mkdir(parents=True, exist_ok=False)
    baselines = {}
    for label, tree in [('dp', args.dp), ('ssdk', args.ssdk)]:
        baselines.update(reverse(args.source_root, tree, profile[label], args.output, label + '-reverse-work'))
    cases = [
        ('test-dp-bridge-owner.py', args.dp, 'dp18', 'dp019', 10),
        ('test-ssdk-i2c-node-owner.py', args.ssdk, 'ssdk31', 'ssdk044', 10),
        ('test-ssdk-mdio-node-leases.py', args.ssdk, 'ssdk32', 'ssdk045', 16),
        ('test-ssdk-phy-node-leases.py', args.ssdk, 'ssdk33', 'ssdk046', 28),
        ('test-ssdk-mdio-table-admission.py', args.ssdk, None, 'ssdk047', 12),
    ]
    results = []
    for script, tree, baseline, label, count in cases:
        command = [sys.executable, '-B', str(args.source_root / 'tests' / script), str(tree),
                   '--cc', args.cc, '--sanitize', '--output', str(args.output / label)]
        if baseline:
            command += ['--baseline', str(baselines[baseline])]
        ran = subprocess.run(command, capture_output=True, timeout=1200)
        (args.output / (label + '.stdout')).write_bytes(ran.stdout)
        (args.output / (label + '.stderr')).write_bytes(ran.stderr)
        need(ran.returncode == 0 and not ran.stderr, 'real-source suite failed: ' + label)
        receipt = args.output / label / 'RESULTS.json'
        data = json.loads(receipt.read_text(), object_pairs_hook=unique)
        need(len(data['records']) == count and data['records'][0]['returncode'] == 0 and
             sum(r['returncode'] == 86 for r in data['records']) ==
             {'dp019': 9, 'ssdk044': 9, 'ssdk045': 13, 'ssdk046': 20, 'ssdk047': 11}[label],
             'incomplete suite: ' + label)
        results.append({'label': label, 'command': command, 'receipt_sha256': sha(receipt.read_bytes()),
                        'records': count, 'returncode': ran.returncode})
    for script, label, verifier in [
        ('test-ssdk-external-switch-lookups.py', 'ssdk048-lookup', verify_external_lookup),
        ('test-ssdk-external-cache-admission.py', 'ssdk048-cache', verify_external_cache)]:
        directory = args.output / label
        command = [sys.executable, '-B', str(args.source_root / 'tests' / script), str(args.ssdk),
                   '--cc', args.cc, '--sanitize', '--baseline', str(baselines['ssdk35']),
                   '--output', str(directory)]
        ran = subprocess.run(command, capture_output=True, timeout=1200)
        (args.output / (label + '.stdout')).write_bytes(ran.stdout)
        (args.output / (label + '.stderr')).write_bytes(ran.stderr)
        need(ran.returncode == 0 and not ran.stderr, 'real external source suite failed: ' + label)
        receipt = directory / 'RESULTS.json'
        verifier(directory, json.loads(receipt.read_text(), object_pairs_hook=unique))
        results.append({'label': label, 'command': command, 'returncode': 0,
                        'receipt_sha256': sha(receipt.read_bytes())})
    directory = args.output / 'ssdk049-phy-ops'
    command = [sys.executable, '-B', str(args.source_root / 'tests/test-ssdk-phy-ops-lifetime.py'),
               '--baseline', str(baselines['ssdk36']), '--prepared', str(args.ssdk),
               '--cc', args.cc, '--sanitize', '--output', str(directory)]
    ran = subprocess.run(command, capture_output=True, timeout=1200)
    (args.output / 'ssdk049-phy-ops.stdout').write_bytes(ran.stdout)
    (args.output / 'ssdk049-phy-ops.stderr').write_bytes(ran.stderr)
    need(ran.returncode == 0 and not ran.stderr, 'actual PHY ownership source suite')
    receipt = directory / 'RESULTS.json'
    data = json.loads(receipt.read_text(), object_pairs_hook=unique)
    verify_phy_ops(directory, data)
    comparison_file = path(directory, 'PREPARED-COMPARISON.json')
    comparison = json.loads(comparison_file.read_text(), object_pairs_hook=unique)
    need(data['receipt_mode'] == 'ACTUAL_PREPARED37_EQUALS_FROZEN36_PLUS049_ALL692_TEXT_ONLY' and
         sha(comparison_file.read_bytes()) == data['comparison_receipt_sha256'] and
         comparison['status'] == 'PASS_TEXT_EQUALITY_ONLY' and
         comparison['files'] == profile['ssdk']['prepared_files'] and
         comparison['actual_prepared_path'] == str(args.ssdk.resolve()) and
         comparison['extraction_source'] == 'CLI_ACTUAL_PREPARED_NOT_DERIVED_COPY',
         'PHY test must use actual admitted prepared source, not a replay-only copy')
    results.append({'label': 'ssdk049-phy-ops', 'command': command, 'returncode': 0,
                    'receipt_sha256': sha(receipt.read_bytes())})
    admit(args.source_root, args.dp, args.ssdk, profile)
    report = {'status': 'PASS_HOST_REGRESSIONS_NOT_SHARED_RETIREMENT_OR_RUNTIME',
              'profile_sha256': sha(PROFILE.read_bytes()), 'results': results,
              'shared_UK_SD_PHY_retirement': 'OPEN', 'device_or_performance_qualification': False}
    (args.output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
