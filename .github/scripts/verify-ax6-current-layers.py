#!/usr/bin/env python3
"""Qualify fixed current layers plus explicit historical-prefix host regressions."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / '.github/ax6-current-layer-contract.json'
POLICY = ROOT / '.github/ax6-current-native-obligations.json'
BASE_MDIO = ROOT / '.github/ax6-mdio-lifecycle-contract.json'
LEGACY_MDIO = ROOT / '.github/ax6-mdio-gcc11-legacy-contract.json'
BASE_NSS = ROOT / '.github/ax6-nss-command-contract.json'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def load(path):
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def path(root, relative):
    need(root.is_dir() and not root.is_symlink(), 'unsafe input root')
    name = PurePosixPath(relative)
    need(relative == str(name) and name.parts and not name.is_absolute() and
         '..' not in name.parts and '.git' not in name.parts, 'unsafe input path')
    target = root
    for part in name.parts:
        target /= part
        need(not target.is_symlink(), 'symlink input')
    need(target.is_file(), 'missing regular input: ' + relative)
    return target


def inventory(root):
    need(root.is_dir() and not root.is_symlink(), 'unsafe inventory root')
    result = {}
    for item in sorted(root.rglob('*')):
        need(not item.is_symlink() and (item.is_file() or item.is_dir()), 'nonregular input')
        if item.is_file():
            result[item.relative_to(root).as_posix()] = sha(item.read_bytes())
    return result


def invhash(rows):
    return sha(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode())


def partition(root):
    code, metadata = {}, {}
    stamps = {}
    for name, digest in inventory(root).items():
        raw = path(root, name).read_bytes()
        if name == 'version.date':
            need(re.fullmatch(rb'[0-9]{1,19}\n', raw) is not None, 'invalid version metadata')
            metadata[name] = digest
        elif (match := re.fullmatch(r'(\.prepared_[0-9a-f]{32}_[0-9a-f]{32})(_check)?', name)):
            suffix = match.group(2) or ''
            need(not raw and suffix not in stamps, 'invalid stamp metadata')
            stamps[suffix] = match.group(1)
            metadata[name] = digest
        else:
            code[name] = digest
    # package.mk keeps the start marker after publishing the matching completion stamp.
    need('_check' not in stamps or stamps.get('') == stamps['_check'], 'unmatched prepare check metadata')
    return code, metadata


def prepared_partition(root, out, label, expected=None):
    need(label in ('ssdk', 'dp', 'driver', 'clients'), 'fixed prepared evidence label')
    destination = out / 'PREPARED-INPUTS' / label
    destination.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'INCOMPLETE', 'actual_prepared_path': str(root), 'files': []}
    try:
        before = inventory(root)
        for number, (name, digest) in enumerate(before.items()):
            raw = path(root, name).read_bytes()
            need(sha(raw) == digest, 'prepared evidence input stability')
            file = destination / ('%04d.data' % number)
            file.write_bytes(raw)
            receipt['files'].append({'origin': name, 'file': file.relative_to(out).as_posix(),
                                     'bytes': len(raw), 'sha256': digest})
        code, metadata = partition(root)
        receipt.update(code_files=code, recipe_metadata=metadata)
        if expected is not None:
            receipt['difference'] = {
                'missing': sorted(set(expected) - set(code)),
                'extra': sorted(set(code) - set(expected)),
                'changed': sorted(n for n in set(code) & set(expected) if code[n] != expected[n])}
        need(inventory(root) == before, 'prepared evidence end stability')
        receipt['status'] = 'CAPTURED_NOT_ADMISSION_OR_RUNTIME'
        return code, metadata
    except Exception as error:
        receipt['error'] = str(error)
        raise
    finally:
        (out / ('PREPARED-' + label + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')


def check(root, rows):
    for name, digest in rows.items():
        need(sha(path(root, name).read_bytes()) == digest, 'fixed input drift: ' + name)


def configuration():
    data = load(CONTRACT)
    need(type(data['schema']) is int and data['schema'] == 1 and data['frozen'] is True and
         data['profile'] == 'CURRENT_SSDK38_CLIENTS27_WITH_FROZEN_PREFIX_REGRESSIONS', 'current profile')
    for key in ('source_commit', 'legacy_test_commit'):
        need(re.fullmatch('[0-9a-f]{40}', data[key]) is not None, 'fixed source identity')
    need(data['source_commit'] != data['legacy_test_commit'], 'current source cannot be historical test checkout')
    for file, key in [(POLICY, 'native_obligations_sha256'), (BASE_MDIO, 'base_mdio_profile_sha256'),
                      (LEGACY_MDIO, 'legacy_mdio_profile_sha256'), (BASE_NSS, 'legacy_nss_profile_sha256')]:
        need(sha(file.read_bytes()) == data[key], 'fixed build contract drift')
    return data


def copy_code(original, destination, expected):
    need(not destination.exists(), 'fresh code snapshot')
    destination.mkdir()
    for name in expected:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path(original, name).read_bytes())
    need(inventory(destination) == expected, 'complete code snapshot')


def normalized_argv(argv, source, output, cc, label):
    need(type(argv) is list and all(isinstance(s, str) and s and '\x00' not in s for s in argv), 'native argv')
    normalized = []
    for index, arg in enumerate(argv):
        if index == 0 and label.endswith('/compile'):
            need(arg == cc, 'native compiler identity')
            arg = '<CC>'
        elif index == 0 and (label.startswith('roundtrip-') or label in ('reverse050', 'forward050')):
            need(Path(arg).name in ('patch', 'gpatch'), 'native patch tool')
            arg = '<PATCH>'
        elif arg.startswith(str(output) + '/'):
            arg = '<OUT>/' + arg[len(str(output)) + 1:]
        elif arg.startswith(str(source) + '/'):
            arg = '<SOURCE>/' + arg[len(str(source)) + 1:]
        normalized.append(arg)
    return normalized


def export_inputs(out, exports):
    (out / 'INPUT-BLOBS').mkdir(exist_ok=True)
    rows = []
    for number, (origin, file) in enumerate(sorted(exports.items())):
        need(file.is_file() and not file.is_symlink(), 'fixed evidence input')
        raw = file.read_bytes()
        name = 'INPUT-BLOBS/%04d.data' % number
        (out / name).write_bytes(raw)
        rows.append({'origin': origin, 'file': name, 'bytes': len(raw), 'sha256': sha(raw)})
    need({p.name for p in (out / 'INPUT-BLOBS').iterdir()} ==
         {'%04d.data' % n for n in range(len(rows))}, 'exact input export inventory')
    (out / 'INPUT-EXPORT.json').write_text(json.dumps({
        'scope': 'FIXED_NONHIDDEN_INPUTS_ONLY', 'files': rows}, indent=2) + '\n')
    return rows


def exact_patch_stdout(raw, label, digest):
    names = {'reverse050': 'src/init/ssdk_phy_i2c.c', 'forward050': 'src/init/ssdk_phy_i2c.c',
             'roundtrip-reverse': 'tunipip6/nss_connmgr_tunipip6_sysctl.c',
             'roundtrip-forward': 'tunipip6/nss_connmgr_tunipip6_sysctl.c'}
    name = names[label]
    canonical = ('patching file ' + name + '\n').encode()
    quoted = ("patching file '" + name + "'\n").encode()
    # Apple patch quotes the same fixed path; neither spelling permits extra diagnostics.
    need(digest in (sha(canonical), sha(quoted)) and raw in (canonical, quoted), 'native exact patch output')


def verify_legacy(directory, kind):
    data = load(path(directory, 'RESULTS.json'))
    if kind == 'mdio':
        need(data['status'] == 'PASS_HOST_REGRESSIONS_NOT_SHARED_RETIREMENT_OR_RUNTIME' and
             data['profile_sha256'] == sha(LEGACY_MDIO.read_bytes()) and
             data['device_or_performance_qualification'] is False and
             data['shared_UK_SD_PHY_retirement'] == 'OPEN', 'legacy MDIO qualification')
        labels = ['dp019', 'ssdk044', 'ssdk045', 'ssdk046', 'ssdk047',
                  'ssdk048-lookup', 'ssdk048-cache', 'ssdk049-phy-ops']
        need([row['label'] for row in data['results']] == labels, 'legacy MDIO complete suites')
        for row in data['results']:
            need(type(row['returncode']) is int and row['returncode'] == 0 and
                 sha(path(directory, row['label'] + '/RESULTS.json').read_bytes()) == row['receipt_sha256'],
                 'legacy MDIO child receipt binding')
    else:
        need(data['status'] == 'PASS_FROZEN_HOST_COMMAND_INPUTS_NOT_RUNTIME' and
             data['profile_sha256'] == sha(BASE_NSS.read_bytes()) and data['runtime_approved'] is False,
             'legacy NSS qualification')
        expected = {'positive_count': 20, 'source_negatives': 22, 'commands': 76,
                    'source_and_regular_commands': 73, 'numeric_model_commands': 3}
        need(all(type(data['verified'][key]) is int and data['verified'][key] == value
                 for key, value in expected.items()), 'legacy NSS complete suite')
        need(sha(path(directory, 'suite/RESULTS.json').read_bytes()) == data['source_receipt_sha256'],
             'legacy NSS child receipt binding')
    return {'status': data['status'], 'receipt_sha256': sha(path(directory, 'RESULTS.json').read_bytes()),
            'scope': 'HISTORICAL_PREFIX_ONLY_NOT_CURRENT_LAYER'}


def legacy_input_hashes(legacy):
    mdio, nss = load(LEGACY_MDIO), load(BASE_NSS)
    rows = dict(mdio['assets'])

    def merge(entries):
        for name, digest in entries.items():
            need(name not in rows or rows[name] == digest, 'conflicting historical input contract')
            rows[name] = digest

    merge(nss['assets'])
    reference = nss['source_profile']
    merge({reference['path']: reference['sha256']})
    check(legacy, {reference['path']: reference['sha256']})
    source_profile = load(path(legacy, reference['path']))
    for label in ('dp', 'ssdk'):
        item = mdio[label]
        prefix = 'package/qca-nss/' + item['package']
        merge({prefix + '/Makefile': item['recipe_sha256']})
        merge({prefix + '/patches/' + name: digest for name, digest in item['patches'].items()})
    for label in ('driver', 'clients'):
        item = source_profile[label]
        prefix = 'package/qca-nss/' + item['package']
        merge({prefix + '/Makefile': nss['recipes'][label]})
        merge({prefix + '/patches/' + name: digest for name, digest in item['patches'].items()})
    check(legacy, rows)
    return rows


def add_phy_controls(out, exports):
    for label, expected in [('marker-valid', b''), ('both-valid', b''), ('marker-nonempty', b'x')]:
        file = out / 'legacy37/ssdk049-phy-ops/metadata-controls' / label / '.prepared_deadbeef'
        need(file.is_file() and not file.is_symlink() and file.read_bytes() == expected,
             'fixed PHY metadata export')
        exports['HIDDEN-CONTROL/' + label] = file
    return export_inputs(out, exports)


def verify_native(directory, kind, source, cc, policy):
    data = load(path(directory, 'RESULTS.json'))
    expected_status = {'i2c': 'PASS_HOST_I2C_IO_ONLY', 'tunip': 'PASS_HOST_TUNIP_COMMAND_CONTRACT_ONLY'}[kind]
    need(data['status'] == expected_status and data['sanitize'] is True and
         data['LSan'] == 'NOT_VERIFIED' and data['end_input_stability'] is True and not data.get('error'),
         'complete current native status')
    for field, expected in policy['fields'].items():
        need(json.dumps(data[field], sort_keys=True) == json.dumps(expected, sort_keys=True),
             'native fixed obligations: ' + field)
    need(data['inputs'] == {str(source / name): digest for name, digest in policy['inputs'].items()},
         'native complete input binding')
    check(source, policy['inputs'])
    need(len(data['commands']) == len(policy['commands']), 'native command inventory')
    for actual, expected in zip(data['commands'], policy['commands']):
        label = expected['label']
        need(actual['label'] == label and type(actual['returncode']) is int and
             actual['returncode'] == expected['returncode'] and not actual.get('timeout', False),
             'native precise command exit: ' + label)
        need(normalized_argv(actual['command'], source, directory, cc, label) == expected['argv'],
             'native exact command: ' + label)
        stem = ('logs/' if kind == 'i2c' else '') + label
        need(load(path(directory, stem + '.json')) == actual, 'native raw JSON: ' + label)
        for stream in ('stdout', 'stderr'):
            raw = path(directory, stem + '.' + stream).read_bytes()
            if kind == 'i2c':
                need(raw == actual[stream].encode(), 'native embedded stream: ' + label)
            else:
                need(actual[stream + '_file'] == stem + '.' + stream and
                     sha(raw) == actual[stream + '_sha256'], 'native raw stream binding')
            if stream == 'stderr' and expected['sanitizer']:
                marker = (b'ERROR: AddressSanitizer: heap-buffer-overflow' if expected['sanitizer'] == 'asan'
                          else b'runtime error: signed integer overflow:')
                competing = b'runtime error:' if expected['sanitizer'] == 'asan' else b'AddressSanitizer'
                need(marker in raw and competing not in raw and b'DEADLYSIGNAL' not in raw,
                     'native directed sanitizer activation: ' + label)
            elif stream == 'stdout' and (label in ('reverse050', 'forward050', 'roundtrip-reverse', 'roundtrip-forward')):
                exact_patch_stdout(raw, label, expected[stream + '_sha256'])
            else:
                need(sha(raw) == expected[stream + '_sha256'], 'native exact stream: ' + label)
        for name in ('ASAN_OPTIONS', 'UBSAN_OPTIONS'):
            need(actual[name] == expected[name], 'native sanitizer environment')
    generated = inventory(directory)
    generated.pop('RESULTS.json', None)
    need(generated == data['generated'], 'native generated inventory and bytes')
    return {'status': expected_status, 'commands': len(data['commands']),
            'receipt_sha256': sha(path(directory, 'RESULTS.json').read_bytes()),
            'runtime_approved': False}


def run_current(args, kind):
    data = configuration()
    source = args.source_root.resolve()
    need(args.legacy_source_root is not None, 'legacy test-only checkout required')
    legacy = args.legacy_source_root.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'INCOMPLETE', 'scope': 'CURRENT_LAYERS_WITH_EXPLICIT_PREFIX_HOST_TESTS',
              'source_commit': data['source_commit'], 'legacy_test_commit': data['legacy_test_commit'],
              'runtime_approved': False, 'commands': [], 'kind': kind,
              'contract_sha256': sha(CONTRACT.read_bytes())}
    owned = {p: sha(p.read_bytes()) for p in (CONTRACT, POLICY, BASE_MDIO, LEGACY_MDIO, BASE_NSS,
             Path(__file__).resolve(), ROOT / '.github/scripts/verify-mdio-lifecycle-repairs.py',
             ROOT / '.github/scripts/verify-nss-command-inputs.py')}

    def invoke(label, command, cwd=ROOT, raw=None):
        try:
            process = subprocess.run([str(s) for s in command], cwd=cwd, input=raw,
                                     capture_output=True, timeout=2400,
                                     env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            code, stdout, stderr = process.returncode, process.stdout, process.stderr
        except subprocess.TimeoutExpired as error:
            code, stdout, stderr = 'timeout', error.stdout or b'', error.stderr or b''
        record = {'label': label, 'command': [str(s) for s in command], 'returncode': code,
                  'stdout_sha256': sha(stdout), 'stderr_sha256': sha(stderr)}
        (out / (label + '.stdout')).write_bytes(stdout)
        (out / (label + '.stderr')).write_bytes(stderr)
        (out / (label + '.json')).write_text(json.dumps(record, indent=2) + '\n')
        report['commands'].append(record)
        need(type(code) is int and code == 0 and not stderr, 'current command failed: ' + label)
        return stdout

    try:
        need(invoke('current-head', ['git', '-C', source, 'rev-parse', 'HEAD']).decode().strip() == data['source_commit'],
             'actual current source HEAD')
        need(invoke('legacy-head', ['git', '-C', legacy, 'rev-parse', 'HEAD']).decode().strip() == data['legacy_test_commit'],
             'actual historical test checkout HEAD')
        check(source, data['assets'])
        exports = {'SOURCE/' + name: path(source, name) for name in data['assets']}
        exports.update({'LEGACY-SOURCE/' + name: path(legacy, name) for name in legacy_input_hashes(legacy)})
        exports.update({'BUILD/' + p.name: p for p in owned})
        export_inputs(out, exports)
        old = load(BASE_MDIO)
        new_policy = load(POLICY)
        if kind == 'mdio':
            original = args.ssdk.resolve()
            code, metadata = prepared_partition(original, out, 'ssdk', data['ssdk']['current_files'])
            need(code == data['ssdk']['current_files'], 'actual full SSDK38 code')
            package = source / 'package/qca-nss/qca-ssdk'
            patches = dict(old['ssdk']['patches'], **{data['ssdk']['patch']: data['ssdk']['patch_sha256']})
            need(inventory(package / 'patches') == patches and len(patches) == 38, 'current38 patch inventory')
            need(sha(path(package, 'Makefile').read_bytes()) == data['recipes']['ssdk'], 'current SSDK28 recipe')
            dp_code, dp_metadata = prepared_partition(args.dp.resolve(), out, 'dp', old['dp']['prepared_files'])
            need(dp_code == old['dp']['prepared_files'], 'unchanged actual DP19 code')
            companion = (args.dp.resolve(), dp_code, dp_metadata)
            need(inventory(source / 'package/qca-nss/qca-nss-dp/patches') == old['dp']['patches'], 'DP exact patch inventory')
            need(sha(path(source, 'package/qca-nss/qca-nss-dp/Makefile').read_bytes()) == old['dp']['recipe_sha256'], 'DP recipe')
            patch = path(package / 'patches', data['ssdk']['patch'])
            old_files = old['ssdk']['prepared_files']
            native_script, native_kind = 'test-ssdk-i2c-io.py', 'i2c'
        else:
            original = args.clients.resolve()
            code, metadata = prepared_partition(original, out, 'clients')
            need(len(code) == 298 and invhash(code) == data['clients']['candidate_inventory_sha256'], 'actual clients27 code')
            old_nss = load(path(legacy, 'tests/nss-command-inputs/profile.json'))
            package = source / 'package/qca-nss/qca-nss-clients'
            patches = dict(old_nss['clients']['patches'], **{
                '027-tunipip6-command-errors-and-netdev-ownership.patch': data['clients']['patch_sha256']})
            need(inventory(package / 'patches') == patches and len(patches) == 27, 'current27 patch inventory')
            need(sha(path(package, 'Makefile').read_bytes()) == data['recipes']['clients'], 'current clients30 recipe')
            drv_code, drv_metadata = prepared_partition(args.driver.resolve(), out, 'driver')
            need(len(drv_code) == old_nss['driver']['files'] and
                 invhash(drv_code) == old_nss['driver']['candidate_inventory_sha256'], 'unchanged actual DRV25 code')
            companion = (args.driver.resolve(), drv_code, drv_metadata)
            need(inventory(source / 'package/qca-nss/qca-nss-drv/patches') == old_nss['driver']['patches'], 'DRV exact patch inventory')
            need(sha(path(source, 'package/qca-nss/qca-nss-drv/Makefile').read_bytes()) ==
                 load(BASE_NSS)['recipes']['driver'], 'unchanged actual DRV25 recipe')
            patch = path(package / 'patches', '027-tunipip6-command-errors-and-netdev-ownership.patch')
            old_files = None
            native_script, native_kind = 'test-tunip-command-transaction.py', 'tunip'
            driver_code = out / 'verified-driver-code'
            copy_code(args.driver.resolve(), driver_code, drv_code)
        current = out / 'actual-current-code'
        copy_code(original, current, code)
        prefix = out / 'verified-prior-prefix'
        copy_code(original, prefix, code)
        patch_command = ['patch', '--batch', '--fuzz=0', '-p1', '-R']
        stdout = invoke('reverse-current-layer', patch_command, cwd=prefix, raw=patch.read_bytes())
        need(not re.search(rb'offset|fuzz|FAILED|reject|malformed|Reversed', stdout, re.I), 'exact current reverse')
        prefix_files = inventory(prefix)
        if kind == 'mdio':
            need(prefix_files == old_files, 'exact full692 prefix37')
            command = [sys.executable, '-B', ROOT / '.github/scripts/verify-mdio-lifecycle-repairs.py',
                       '--gcc11-legacy-profile', '--source-root', legacy, '--dp', args.dp.resolve(),
                       '--ssdk', prefix, '--cc', args.cc, '--output', out / 'legacy37']
            native = [sys.executable, '-B', source / 'tests' / native_script, '--baseline', prefix,
                      '--prepared', current, '--cc', args.cc, '--sanitize', '--output', out / native_kind]
        else:
            need(len(prefix_files) == 298 and invhash(prefix_files) == data['clients']['baseline_inventory_sha256'],
                 'exact full298 prefix26')
            command = [sys.executable, '-B', ROOT / '.github/scripts/verify-nss-command-inputs.py',
                       '--source-root', legacy, '--driver', driver_code, '--clients', prefix,
                       '--cc', args.cc, '--output', out / 'legacy26']
            native = [sys.executable, '-B', source / 'tests' / native_script, '--clients', current,
                      '--cc', args.cc, '--sanitize', '--output', out / native_kind]
        report['actual_prepared_path'] = str(original)
        report['actual_code_files'] = code
        report['actual_recipe_metadata'] = metadata
        report['prefix_code_files'] = prefix_files
        invoke('historical-prefix-regressions', command)
        report['historical_prefix'] = verify_legacy(out / ('legacy37' if kind == 'mdio' else 'legacy26'), kind)
        if kind == 'mdio':
            add_phy_controls(out, exports)
        invoke('current-layer-native', native)
        report['current_native'] = verify_native(out / native_kind, native_kind, source, args.cc, new_policy[native_kind])
        check(source, data['assets'])
        need(partition(original) == (code, metadata) and inventory(current) == code and
             inventory(prefix) == prefix_files, 'current/prefix end input stability')
        need(partition(companion[0]) == (companion[1], companion[2]), 'companion end input stability')
        if kind == 'nss':
            need(inventory(driver_code) == drv_code, 'driver code snapshot end stability')
        rows = export_inputs(out, exports)
        need(configuration() == data and all(sha(p.read_bytes()) == digest for p, digest in owned.items()),
             'build input end stability')
        report.update(status='PASS_CURRENT_LAYER_AND_EXPLICIT_PREFIX_HOST_ONLY',
                      current_counts=data['expected_counts'][native_kind],
                      whole_target_compile_approved=False, exported_inputs=len(rows))
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        (out / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('status', 'kind', 'current_counts', 'runtime_approved')}))
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print-legacy-ref', action='store_true', required=True)
    parser.parse_args()
    print(configuration()['legacy_test_commit'])
