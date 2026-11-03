#!/usr/bin/env python3
"""Admit frozen, already-prepared NSS inputs; host evidence is not runtime approval."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / '.github/ax6-nss-command-contract.json'
PACKAGES = {'driver': ('qca-nss-drv', 25), 'clients': ('qca-nss-clients', 29)}
CASES = ('sequence-bounds', 'sequence-first-last', 'firmware-terminal', 'firmware-version',
         'ppe-valid', 'ppe-invalid', 'ppe-read', 'ppe-errors', 'ppe-refbalance', 'ppe-bounds',
         'mirror-dispatch', 'mirror-config', 'mirror-invalid', 'mirror-errors', 'mirror-bounds',
         'tunip-frag', 'tunip-map', 'tunip-del-flush', 'tunip-errors', 'tunip-bounds')
NEGATIVES = (
    ('sequence-short', 'sequence-bounds', 'SEQ_RANGE'),
    ('sequence-first', 'sequence-first-last', 'SEQ_FIRST'),
    ('sequence-last', 'sequence-first-last', 'SEQ_LAST'),
    ('sequence-match', 'sequence-first-last', 'SEQ_FIRST'),
    ('firmware-offset', 'firmware-version', 'FW_VERSION'),
    ('ppe-copy', 'ppe-valid', 'PPE_VALID'), ('ppe-proc', 'ppe-errors', 'PPE_ERROR'),
    ('ppe-type', 'ppe-valid', 'PPE_TYPE'), ('ppe-read', 'ppe-read', 'PPE_READ'),
    ('ppe-put', 'ppe-refbalance', 'PPE_PUT'), ('ppe-shared-request', 'ppe-valid', 'PPE_VALID'),
    ('ppe-position', 'ppe-bounds', 'PPE_POSITION'),
    ('mirror-copy', 'mirror-dispatch', 'MIRROR_DISPATCH'),
    ('mirror-limit', 'mirror-bounds', 'MIRROR_LIMIT'), ('mirror-proc', 'mirror-errors', 'MIRROR_PROC'),
    ('mirror-empty-name', 'mirror-invalid', 'MIRROR_EMPTY_NAME'),
    ('mirror-display-empty', 'mirror-invalid', 'MIRROR_EMPTY_NAME'),
    ('mirror-next-empty', 'mirror-invalid', 'MIRROR_EMPTY_INDEX'),
    ('tunip-copy', 'tunip-frag', 'TUNIP_FRAG'), ('tunip-limit', 'tunip-bounds', 'TUNIP_LIMIT'),
    ('tunip-size', 'tunip-bounds', 'TUNIP_ALLOC'),
    ('tunip-suffix-length', 'tunip-map', 'TUNIP_SUFFIX_LENGTH'))
FLAGS = ['-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
         '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-sanitize-recover=all']
EMPTY_SHA256 = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
EMPTY_CONTROL = 'metadata-controls/.prepared_' + 'a' * 32 + '_' + 'b' * 32
CONTROL_PATH = 'suite/' + EMPTY_CONTROL
UPLOAD_DIRECTORY = 'upload-controls'
UPLOAD_DATA = UPLOAD_DIRECTORY + '/prepared-control-empty.dat'
UPLOAD_INDEX = UPLOAD_DIRECTORY + '/INDEX.json'


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def path(root, name):
    relative = PurePosixPath(name)
    need(name == relative.as_posix() and not relative.is_absolute() and
         '..' not in relative.parts and relative.parts, 'unsafe path: ' + name)
    target = root
    need(target.is_dir() and not target.is_symlink(), 'unsafe root: ' + str(root))
    for part in relative.parts:
        target = target / part
        need(not target.is_symlink(), 'symlink: ' + str(target))
    need(target.is_file(), 'missing regular input: ' + str(target))
    return target


def inventory(root):
    need(root.is_dir() and not root.is_symlink(), 'unsafe inventory root')
    rows = {}
    for item in sorted(root.rglob('*')):
        need(not item.is_symlink(), 'symlink inventory: ' + str(item))
        if item.is_file():
            rows[item.relative_to(root).as_posix()] = sha(item.read_bytes())
        else:
            need(item.is_dir(), 'special inventory entry: ' + str(item))
    return rows


def check(root, rows):
    need(isinstance(rows, dict) and bool(rows), 'empty hash inventory')
    for name, digest in rows.items():
        need(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'bad digest')
        need(sha(path(root, name).read_bytes()) == digest, 'input hash drift: ' + name)


def inventory_hash(rows):
    return sha(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode())


def hidden_paths(root):
    inventory(root)  # Reject links and special files, including hidden ones.
    return {p.relative_to(root).as_posix() for p in root.rglob('*')
            if any(part.startswith('.') for part in p.relative_to(root).parts)}


def upload_index(receipt_sha256):
    return {'schema': 1, 'kind': 'INERT_EMPTY_TEST_CONTROL_ONLY',
            'source_receipt_sha256': receipt_sha256,
            'files': [{'original_path': CONTROL_PATH, 'export_path': UPLOAD_DATA,
                       'size': 0, 'sha256': EMPTY_SHA256}]}


def check_upload_control(root, receipt_sha256):
    """Validate the one data-only export; this does not qualify native results."""
    need(re.fullmatch('[0-9a-f]{64}', receipt_sha256), 'upload source receipt digest')
    receipt_raw = path(root, 'suite/RESULTS.json').read_bytes()
    need(sha(receipt_raw) == receipt_sha256, 'upload source receipt binding')
    source = json.loads(receipt_raw, object_pairs_hook=unique)
    hidden = {name for name in source['generated']
              if any(part.startswith('.') for part in PurePosixPath(name).parts)}
    need(hidden == {EMPTY_CONTROL} and source['generated'][EMPTY_CONTROL] == EMPTY_SHA256,
         'upload fixed hidden generated inventory')
    need(hidden_paths(root) <= {CONTROL_PATH}, 'unexpected hidden upload entry')
    raw = path(root, UPLOAD_INDEX).read_bytes()
    index = json.loads(raw, object_pairs_hook=unique)
    need(index == upload_index(receipt_sha256) and type(index['schema']) is int and
         type(index['files'][0]['size']) is int, 'upload fixed INDEX contract')
    data = path(root, UPLOAD_DATA).read_bytes()
    need(data == b'' and sha(data) == EMPTY_SHA256, 'upload empty data content')
    need(inventory(root / UPLOAD_DIRECTORY) == {
         'INDEX.json': sha(raw), 'prepared-control-empty.dat': EMPTY_SHA256}, 'upload exact export inventory')
    original = root / CONTROL_PATH
    if original.exists():
        need(path(root, CONTROL_PATH).read_bytes() == b'', 'upload original control content')
    return {'index_path': UPLOAD_INDEX, 'index_sha256': sha(raw),
            'data_path': UPLOAD_DATA, 'data_sha256': EMPTY_SHA256,
            'original_path': CONTROL_PATH, 'source_receipt_sha256': receipt_sha256}


def export_upload_control(root, receipt_sha256):
    """Never remove or rewrite SOURCE output; only export the fixed empty datum."""
    need(hidden_paths(root) == {CONTROL_PATH}, 'unexpected hidden export entry')
    need(path(root, CONTROL_PATH).read_bytes() == b'', 'export original control content')
    directory = root / UPLOAD_DIRECTORY
    directory.mkdir(exist_ok=False)
    with (root / UPLOAD_DATA).open('xb') as output:
        output.write(b'')
    with (root / UPLOAD_INDEX).open('x', encoding='ascii') as output:
        output.write(json.dumps(upload_index(receipt_sha256), indent=2) + '\n')
    return check_upload_control(root, receipt_sha256)


def restore_upload_control(root):
    """Opt-in reconstruction of inert fixture data, never a script or binary."""
    report = read_json(path(root, 'RESULTS.json'))
    need(report['status'] == 'PASS_FROZEN_HOST_COMMAND_INPUTS_NOT_RUNTIME' and
         report['runtime_approved'] is False, 'upload wrapper receipt status')
    evidence = check_upload_control(root, report['source_receipt_sha256'])
    need(report['upload_control_export'] == evidence, 'upload wrapper export binding')
    # The surviving non-hidden control proves this exact parent is a real directory.
    path(root, 'suite/metadata-controls/input.c')
    original = root / CONTROL_PATH
    restored = not original.exists()
    if restored:
        with original.open('xb') as output:
            output.write(path(root, UPLOAD_DATA).read_bytes())
    need(path(root, CONTROL_PATH).read_bytes() == b'' and
         check_upload_control(root, report['source_receipt_sha256']) == evidence,
         'restored empty control identity')
    return {'status': 'INERT_EMPTY_TEST_CONTROL_READBACK_ONLY', 'restored': restored, **evidence}


def partition(root):
    """Independent OpenWrt root-only metadata classification, not source-helper code."""
    code, metadata = {}, {}
    for name, digest in inventory(root).items():
        if name == 'version.date':
            need(re.fullmatch(rb'[0-9]{1,19}\n', path(root, name).read_bytes()), 'version.date content')
            metadata[name] = digest
        elif re.fullmatch(r'\.prepared_[0-9a-f]{32}_[0-9a-f]{32}', name):
            need(path(root, name).stat().st_size == 0 and
                 not any(k.startswith('.prepared_') for k in metadata), 'prepared stamp content/duplicate')
            metadata[name] = digest
        else:
            code[name] = digest
    return code, metadata


def admit(source, driver, clients, contract):
    need(type(contract['schema']) is int and contract['schema'] == 1 and
         contract['profile'] == 'NSS_COMMAND_INPUTS_DRV25_CLIENTS29' and
         contract['frozen'] is True, 'unfrozen or unknown command contract')
    check(source, contract['assets'])
    reference = contract['source_profile']
    check(source, {reference['path']: reference['sha256']})
    prepared = read_json(path(source, reference['path']))
    need(type(prepared['schema']) is int and prepared['schema'] == 1, 'source profile schema')
    support = source / 'tests/nss-command-inputs'
    expected_support = {name.removeprefix('tests/nss-command-inputs/'): digest
                        for name, digest in contract['assets'].items()
                        if name.startswith('tests/nss-command-inputs/')}
    if reference['path'].startswith('tests/nss-command-inputs/'):
        expected_support[reference['path'].removeprefix('tests/nss-command-inputs/')] = reference['sha256']
    need(inventory(support) == expected_support, 'support inventory drift')
    need(contract['runner'] in contract['assets'], 'unbound source runner')
    state = {'profile': prepared, 'trees': {}, 'metadata': {}, 'inputs': {}}
    for name, digest in contract['assets'].items():
        state['inputs'][str(source / name)] = digest
    state['inputs'][str(source / reference['path'])] = reference['sha256']
    for label, tree in [('driver', driver), ('clients', clients)]:
        item = prepared[label]
        package_name, release = PACKAGES[label]
        need(item['package'] == package_name, 'package identity: ' + label)
        code, metadata = partition(tree)
        need(type(item['files']) is int and len(code) == item['files'] and code and
             inventory_hash(code) == item['candidate_inventory_sha256'], 'whole prepared tree drift: ' + label)
        state['trees'][str(tree)] = {**code, **metadata}
        state['metadata'][str(tree)] = metadata
        package = source / 'package/qca-nss' / package_name
        patches = inventory(package / 'patches')
        need(patches == item['patches'] and patches and
             all('/' not in name and name.endswith('.patch') for name in patches),
             'complete patch inventory drift: ' + label)
        for name, digest in patches.items():
            state['inputs'][str(package / 'patches' / name)] = digest
        recipe_path = path(source, 'package/qca-nss/' + package_name + '/Makefile')
        recipe = recipe_path.read_bytes()
        need(sha(recipe) == contract['recipes'][label], 'recipe hash drift: ' + label)
        state['inputs'][str(recipe_path)] = contract['recipes'][label]
        need(re.findall(rb'^PKG_RELEASE:=(\d+)$', recipe, re.M) == [str(release).encode()],
             'recipe release: ' + label)
        pins = re.findall(rb'^PKG_SOURCE_VERSION:=(\S+)$', recipe, re.M)
        need(re.fullmatch('[0-9a-f]{40}', item['pin']) and len(pins) == 1 and
             re.fullmatch(rb'[0-9a-f]{7,40}', pins[0]) and item['pin'].startswith(pins[0].decode()),
             'recipe pin: ' + label)
    check(source, prepared['metadata_rule_inputs'])
    need(set(prepared['metadata_rule_inputs']) <= set(contract['assets']), 'unbound metadata rule inputs')
    return state


def exact_process(directory, stem, row, rc, stdout, stderr):
    need(type(row['returncode']) is int and row['returncode'] == rc and
         row.get('timeout', False) is False, 'process exit/timeout: ' + stem)
    for stream, expected in [('stdout', stdout), ('stderr', stderr)]:
        raw = path(directory, stem + '.' + stream).read_bytes()
        if expected is not None:
            need(raw == expected, 'exact raw ' + stream + ': ' + stem)
        need(row['label'] == stem and row[stream + '_file'] == stem + '.' + stream,
             'raw stream path: ' + stem)
        if stream in row:
            need(row[stream] == raw.decode(), 'embedded stream: ' + stem)
        need(row[stream + '_sha256'] == sha(raw), 'stream digest: ' + stem)
    saved = read_json(path(directory, stem + '.json'))
    need(saved == row, 'saved process receipt: ' + stem)


def exact_inventory(rows, expected, fields, reason):
    need(isinstance(rows, list) and len(rows) == len(expected), reason)
    observed = [tuple(row[field] for field in fields) for row in rows]
    need(len(set(observed)) == len(observed) and set(observed) == set(expected), reason)


def sanitizer_env(row, code=None):
    def options(name):
        result = {}
        for field in row[name].split(':'):
            key, value = field.split('=', 1)
            need(key not in result, 'duplicate sanitizer option')
            result[key] = value
        return result
    asan, ubsan = options('ASAN_OPTIONS'), options('UBSAN_OPTIONS')
    need(asan.get('detect_leaks') == '0' and asan.get('abort_on_error') == '0' and
         ubsan.get('halt_on_error') == '1', 'sanitizer environment')
    if code is not None:
        need(asan.get('exitcode') == ubsan.get('exitcode') == str(code), 'canary common exitcode')


def verify_receipt(directory, data, state, contract, cc):
    need(data['status'] == 'PASS_HOST_COMMAND_INPUTS_ONLY' and
         data['qualification'] == 'HOST_MODELS_NOT_TARGET_ABI_FW_OR_LIFETIME' and
         data['sanitize'] is True and data['LSan'] == 'NOT_VERIFIED' and
         data['end_input_stability'] is True and not data.get('error'), 'host-only qualification')
    need(type(data['positive_count']) is int and data['positive_count'] == 20 and
         data['positives'] == list(CASES), 'complete positive inventory')
    need(type(data['negative_count']) is int and data['negative_count'] == 22 and
         data['negatives'] == [list(row) for row in NEGATIVES], 'complete negative inventory')
    need(data['inventory_controls'] == {'valid': 1, 'rejected': 6,
         'classification': 'PYTHON_INVENTORY_CONTROLS_NOT_SOURCE_MUTANTS'} and
         data['metadata_controls'] == {'valid': 1, 'rejected': 7,
         'classification': 'METADATA_MODEL_CONTROLS_NOT_SOURCE_MUTANTS'}, 'control classification')
    need(data['numeric_model_controls'] == {'valid': 1, 'rejected': 1,
         'classification': 'NATIVE_NUMERIC_MODEL_CONTROL_NOT_PRODUCTION_SOURCE_MUTANT',
         'mutation': 'Remove only libc EOF-to-kernel zero-assignment normalization',
         'marker': 'KERNEL_SCAN_EMPTY'}, 'independent numeric model classification')
    need(data['source_profile_sha256'] == contract['source_profile']['sha256'], 'source profile receipt')
    need(data['inputs'] == state['inputs'] == read_json(path(directory, 'INPUTS.json')), 'receipt input binding')
    need(state['trees'] == read_json(path(directory, 'TREES.json')) and
         data['prepared_metadata'] == state['metadata'], 'prepared/metadata receipt binding')
    need(read_json(path(directory, 'OBLIGATIONS.json')) == [list(row) for row in NEGATIVES],
         'saved semantic obligations')
    source_profile = state['profile']
    need(data['fixed_source_contract'] == {label: {k: v for k, v in source_profile[label].items()
         if k != 'patches'} for label in PACKAGES}, 'fixed source receipt')
    required = {'INPUTS.json', 'TREES.json', 'OBLIGATIONS.json', 'metadata-controls/input.c',
                'metadata-controls/version.date', 'metadata-controls/.prepared_' + 'a' * 32 + '_' + 'b' * 32}
    need(path(directory, 'metadata-controls/input.c').read_bytes() ==
         b'TESTONLY metadata admission data, never compiled\n' and
         path(directory, 'metadata-controls/version.date').read_bytes() == b'1770000000\n' and
         not path(directory, 'metadata-controls/.prepared_' + 'a' * 32 + '_' + 'b' * 32).read_bytes(),
         'metadata control artifacts')
    commands = []
    for label in PACKAGES:
        for direction in ('reverse', 'forward'):
            commands.append((label + '-' + direction, 'patch', 0, None, b'', None))
        item = source_profile[label]
        for prefix, digest in [('baseline-', item['baseline_inventory_sha256']),
                               ('roundtrip-', item['candidate_inventory_sha256'])]:
            rows = inventory(directory / (prefix + label))
            need(len(rows) == item['files'] and inventory_hash(rows) == digest, 'archived whole tree: ' + prefix + label)
            required.update(prefix + label + '/' + name for name in rows)
    programs = ['positive', 'numeric-model/libc-eof',
                *('negative/' + row[0] for row in NEGATIVES), 'canary/asan', 'canary/ubsan']
    commands.append(('positive/compile', 'compile', 0, b'', b'', None))
    commands.extend([
        ('numeric-model/positive', 'model', 0, b'PASS kernel-numeric-model\n', b'', 'kernel-numeric-model'),
        ('numeric-model/libc-eof/compile', 'compile', 0, b'', b'', None),
        ('numeric-model/negative', 'model', 86, b'', b'NSS_INPUT:KERNEL_SCAN_EMPTY\n', 'kernel-numeric-model')])
    for name, raw in [('positive.expected', b'PASS kernel-numeric-model\n'),
                      ('negative.expected', b'NSS_INPUT:KERNEL_SCAN_EMPTY\n')]:
        relative = 'numeric-model/' + name
        need(path(directory, relative).read_bytes() == raw, 'numeric model expected bytes')
        required.add(relative)
    model = path(directory, 'positive/model.h').read_bytes()
    anchor = b'return result==EOF?0:result;'
    need(model.count(anchor) == 1 and path(directory, 'numeric-model/libc-eof/model.h').read_bytes() ==
         model.replace(anchor, b'return result;', 1), 'restricted numeric model-only delta')
    for name in ('fixture.c', 'types.h', 'actual-scan.c', 'actual-ppe.c', 'actual-mirror.c', 'actual-tunip.c'):
        need(path(directory, 'positive/' + name).read_bytes() ==
             path(directory, 'numeric-model/libc-eof/' + name).read_bytes(), 'numeric control must not mutate production C')
    for case in CASES:
        stdout = ('PASS ' + case + '\n').encode()
        commands.append(('positive/' + case, 'run', 0, stdout, b'', case))
        name = 'positive/' + case + '.expected'
        need(path(directory, name).read_bytes() == stdout, 'positive expected bytes')
        required.add(name)
    for name, case, marker in NEGATIVES:
        label = 'negative/' + name
        commands.append((label + '/compile', 'compile', 0, b'', b'', None))
        stderr = ('NSS_INPUT:' + marker + '\n').encode()
        commands.append((label + '/run', 'run', 86, b'', stderr, case))
        name = label + '/stderr.expected'
        need(path(directory, name).read_bytes() == stderr, 'negative expected bytes')
        required.add(name)
    for name, code in [('asan', 97), ('ubsan', 98)]:
        commands.append(('canary/' + name + '/compile', 'compile', 0, b'', b'', None))
        commands.append(('canary/' + name + '/run', 'canary', code, b'', None, None))
    need(len(data['commands']) == len(commands) == 76 and
         [r['label'] for r in data['commands']] == [row[0] for row in commands], 'complete command inventory')
    for row, (stem, kind, rc, stdout, stderr, case) in zip(data['commands'], commands):
        exact_process(directory, stem, row, rc, stdout, stderr)
        sanitizer_env(row, rc if kind == 'canary' else None)
        required.update(stem + '.' + suffix for suffix in ('json', 'stdout', 'stderr'))
        if kind == 'patch':
            need(row['command'][1:] == ['--batch', '--fuzz=0', '-p1'] +
                 (['-R'] if stem.endswith('-reverse') else []) and
                 Path(row['command'][0]).name in ('patch', 'gpatch'), 'patch command identity')
            need(not re.search(rb'offset|fuzz|FAILED|reject|malformed',
                 path(directory, stem + '.stdout').read_bytes(), re.I), 'patch replay diagnostics')
            continue
        if stem == 'numeric-model/positive':
            label = 'positive'
        elif stem == 'numeric-model/negative':
            label = 'numeric-model/libc-eof'
        else:
            label = 'positive' if kind == 'run' and stem.startswith('positive/') else stem.rsplit('/', 1)[0]
        if kind == 'compile':
            expected = [cc, *FLAGS, str(directory / label / 'fixture.c'), '-o', str(directory / label / 'program.host')]
        else:
            expected = [str(directory / label / 'program.host')] + ([case] if case else [])
        need(row['command'] == expected, 'native command identity: ' + stem)
        if kind == 'canary':
            diagnostic = path(directory, stem + '.stderr').read_bytes()
            marker = 'ERROR: AddressSanitizer: heap-buffer-overflow' if rc == 97 else 'runtime error: signed integer overflow:'
            need(marker.encode() in diagnostic and (b'WRITE of size 4' if rc == 97 else b'2147483647 + 1') in diagnostic,
                 'canary diagnostic')
            control = {'name': 'asan' if rc == 97 else 'ubsan', 'exitcode': rc, 'diagnostic': marker,
                       'ASAN_OPTIONS': row['ASAN_OPTIONS'], 'UBSAN_OPTIONS': row['UBSAN_OPTIONS']}
            need(data['sanitizer_controls'][0 if rc == 97 else 1] == control and
                 len(data['sanitizer_controls']) == 2, 'canary control receipt')
    for label in programs:
        required.update(label + '/' + name for name in ('fixture.c', 'program.host'))
        if not label.startswith('canary/'):
            required.update(label + '/actual-' + group + '.c' for group in ('scan', 'ppe', 'mirror', 'tunip'))
            required.update(label + '/' + name for name in ('types.h', 'model.h'))
        dsym = directory / label / 'program.host.dSYM'
        if dsym.exists():
            names = set(inventory(dsym))
            info = 'Contents/Info.plist'
            dwarf = 'Contents/Resources/DWARF/program.host'
            reloc = 'Contents/Resources/Relocations/aarch64/program.host.yml'
            need(names in ({info, dwarf}, {info, reloc}, {info, dwarf, reloc}), 'dSYM exact shape')
            required.update(label + '/program.host.dSYM/' + name for name in names)
    actual = inventory(directory)
    actual.pop('RESULTS.json', None)
    need(set(actual) == required and actual == data['generated'], 'whole C/binary/log/generated inventory or hash drift')
    return {'positive_count': 20, 'source_negatives': 22, 'commands': 76,
            'source_and_regular_commands': 73, 'numeric_model_commands': 3,
            'numeric_model_valid': 1, 'numeric_model_negative': 1,
            'generated_files': len(actual), 'metadata': state['metadata']}


def main():
    if '--restore-upload-control' in sys.argv[1:]:
        parser = argparse.ArgumentParser(description='Restore only the receipt-bound empty test datum; execute nothing.')
        parser.add_argument('--restore-upload-control', required=True, type=Path)
        args = parser.parse_args()
        try:
            print(json.dumps(restore_upload_control(args.restore_upload_control.absolute())))
            return 0
        except (OSError, ValueError, KeyError, TypeError) as error:
            print('empty control readback rejected: ' + str(error), file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('source-root', 'driver', 'clients', 'output'):
        parser.add_argument('--' + option, required=True, type=Path)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--current-layers', action='store_true')
    parser.add_argument('--legacy-source-root', type=Path)
    args = parser.parse_args()
    for name in ('source_root', 'driver', 'clients', 'output'):
        setattr(args, name, getattr(args, name).absolute())
    if args.current_layers:
        spec = importlib.util.spec_from_file_location('current_nss_layers', ROOT / '.github/scripts/verify-ax6-current-layers.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.run_current(args, 'nss')
    need(args.legacy_source_root is None, 'legacy checkout requires current-layer mode')
    profile_bytes = PROFILE.read_bytes()
    profile = json.loads(profile_bytes, object_pairs_hook=unique)
    state = admit(args.source_root, args.driver, args.clients, profile)
    owned = {str(p): sha(p.read_bytes()) for p in (Path(__file__).resolve(), PROFILE)}
    args.output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, '-B', '-O', str(path(args.source_root, profile['runner'])),
               '--driver', str(args.driver), '--clients', str(args.clients),
               '--cc', args.cc, '--sanitize', '--output', str(args.output / 'suite')]
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    try:
        try:
            process = subprocess.run(command, capture_output=True, timeout=1800, env=environment)
        except subprocess.TimeoutExpired as error:
            for stream in ('stdout', 'stderr'):
                (args.output / ('runner.' + stream)).write_bytes(getattr(error, stream) or b'')
            (args.output / 'runner.json').write_text(json.dumps({
                'command': command, 'returncode': None, 'timeout': True}, indent=2) + '\n')
            raise
        outer = {'command': command, 'returncode': process.returncode, 'timeout': False}
        for stream in ('stdout', 'stderr'):
            raw = getattr(process, stream)
            (args.output / ('runner.' + stream)).write_bytes(raw)
            outer[stream + '_sha256'] = sha(raw)
        (args.output / 'runner.json').write_text(json.dumps(outer, indent=2) + '\n')
        need(process.returncode == 0 and not process.stderr, 'source runner failed')
        need(json.loads(process.stdout, object_pairs_hook=unique) == {
             'status': 'PASS_HOST_COMMAND_INPUTS_ONLY', 'positive_count': 20, 'negative_count': 22},
             'source runner summary')
        receipt_bytes = (args.output / 'suite/RESULTS.json').read_bytes()
        result = json.loads(receipt_bytes, object_pairs_hook=unique)
        detail = verify_receipt(args.output / 'suite', result, state, profile, args.cc)
        need(admit(args.source_root, args.driver, args.clients, profile) == state, 'end input/tree/metadata drift')
        generated = inventory(args.output / 'suite')
        generated.pop('RESULTS.json', None)
        need(generated == result['generated'] and
             (args.output / 'suite/RESULTS.json').read_bytes() == receipt_bytes, 'end output/receipt drift')
        upload = export_upload_control(args.output, sha(receipt_bytes))
        need(all(sha(Path(p).read_bytes()) == digest for p, digest in owned.items()),
             'BUILD gate/profile changed during run')
        report = {'status': 'PASS_FROZEN_HOST_COMMAND_INPUTS_NOT_RUNTIME',
                  'runtime_approved': False, 'profile_sha256': sha(profile_bytes),
                  'source_receipt_sha256': sha(receipt_bytes),
                  'upload_control_export': upload, 'verified': detail, 'command': command}
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        report = {'status': 'FAILED', 'runtime_approved': False, 'error': str(error),
                  'profile_sha256': sha(profile_bytes), 'command': command}
    (args.output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    sys.exit(main())
