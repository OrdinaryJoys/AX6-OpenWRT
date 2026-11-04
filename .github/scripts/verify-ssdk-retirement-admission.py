#!/usr/bin/env python3
"""Gate actual SSDK39, preserving the immutable accepted38 and older prefix gates."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / '.github/ax6-ssdk39-contract.json'
spec = importlib.util.spec_from_file_location('accepted_layers', ROOT / '.github/scripts/verify-ax6-current-layers.py')
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
need, sha = base.need, base.sha


def configuration():
    data = base.load(PROFILE)
    need(data['schema'] == 1 and data['frozen'] is True and data['profile'] == 'SSDK39_ADMISSION_NOT_SHARED_RETIREMENT',
         'fixed retirement profile')
    need(sha(base.CONTRACT.read_bytes()) == data['accepted38_contract_sha256'], 'immutable accepted38 contract')
    need(base.configuration()['source_commit'] == data['baseline_commit'], 'accepted38 identity')
    return data


def positive(code, out, err):
    need(type(code) is int and code == 0 and not err and
         json.loads(out, object_pairs_hook=base.unique) ==
         {'status': 'PASS', 'cases': 266, 'shared_uk_order': 'OPEN'}, 'native positive exact')


def negative(code, out, err, marker):
    need(type(code) is int and code == 86 and not out and
         err == ('RETIRE:' + marker + '\n').encode(), 'native precise runtime negative')


def probe_ok(code, out, err, kind):
    if type(code) is not int or code != {'asan': 97, 'ubsan': 98}[kind] or out != b'' or not isinstance(err, bytes):
        return False
    if kind == 'asan':
        return (b'ERROR: AddressSanitizer: heap-buffer-overflow' in err and b'WRITE of size 1' in err and
                b'runtime error:' not in err and b'DEADLYSIGNAL' not in err)
    return (b'runtime error: signed integer overflow:' in err and b'2147483647 + 1' in err and
            b'AddressSanitizer' not in err)


def sanitizer_receipts(directory, data, cc, hppe):
    report = base.load(directory / 'RESULTS.json')
    controls = report['sanitizer_controls']
    need(controls['activation'] == [{'name': 'asan', 'instrumentation': 'address', 'exit': 97},
                                  {'name': 'ubsan', 'instrumentation': 'undefined', 'exit': 98}] and
         controls['crossed'] == [{'actual': 'asan', 'rejected_as': 'ubsan'},
                                {'actual': 'ubsan', 'rejected_as': 'asan'}] and
         type(controls['oracle_rejections']) is int and controls['oracle_rejections'] == 24,
         'fixed activation/crossed/oracle inventory')
    need(len(controls['disabled']) == 2 and {r['name'] for r in controls['disabled']} == {'asan', 'ubsan'},
         'disabled detector inventory')
    common = ['-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-O1', '-g']
    if hppe:
        common += ['-DHPPE=1']
    for kind, instrumentation, expected in [('asan', 'address', 97), ('ubsan', 'undefined', 98)]:
        source = directory / ('canary-' + kind + '.c')
        need(sha(source.read_bytes()) == data['probe_source_sha256'][kind], 'fixed probe C')
        for disabled in (False, True):
            label = ('disabled-' if disabled else 'canary-') + kind
            binary = directory / (label + '.host')
            flags = common + ([] if disabled else ['-fsanitize=' + instrumentation, '-fno-omit-frame-pointer'])
            compile_row = base.load(directory / (label + '-compile.argv.json'))
            need(compile_row['argv'] == [cc, *flags, str(source), '-o', str(binary)], 'probe exact instrumentation argv')
            code = base.load(directory / (label + '-compile.exit.json'))['returncode']
            need(type(code) is int and code == 0 and not (directory / (label + '-compile.stdout')).read_bytes() and
                 not (directory / (label + '-compile.stderr')).read_bytes(), 'probe clean compilation')
            row = base.load(directory / (label + '-run.argv.json'))
            need(row == {'argv': [str(binary)],
                         'ASAN_OPTIONS': f'detect_leaks=0:halt_on_error=1:abort_on_error=0:exitcode={expected}',
                         'UBSAN_OPTIONS': f'halt_on_error=1:abort_on_error=0:print_stacktrace=1:exitcode={expected}'},
                 'probe actual argv/environment')
            code = base.load(directory / (label + '-run.exit.json'))['returncode']
            out = (directory / (label + '-run.stdout')).read_bytes()
            err = (directory / (label + '-run.stderr')).read_bytes()
            if disabled:
                recorded = next(r['returncode'] for r in controls['disabled'] if r['name'] == kind)
                need(type(code) is int and type(recorded) is int and code == recorded and not probe_ok(code, out, err, kind),
                     'actual disabled detector must not qualify')
            else:
                need(probe_ok(code, out, err, kind), 'actual isolated detector activation')
                other = 'ubsan' if kind == 'asan' else 'asan'
                need(not probe_ok({'asan': 97, 'ubsan': 98}[other], out, err, other), 'actual crossed diagnostic rejection')


def native(directory, data, source, cc, hppe):
    report = base.load(directory / 'RESULTS.json')
    need(report['status'] == 'PASS_LOCAL_ONLY' and report['profile'] == ('HPPE_UK' if hppe else 'NON_HPPE_UK'),
         'native profile status')
    need(report['prepared_inventory'] == data['prepared_files'], 'native whole692')
    need(report['qca808x_fields'] == ['i2c_get', 'i2c_set', 'mdio_get', 'mdio_set'],
         'vendor SDK4 export boundary')
    rows = report['native']
    need(len(rows) == 23 and len({r['name'] for r in rows}) == 23 and
         {r['name']: r['marker'] for r in rows} == data['native_markers'], 'all fixed native obligations')
    for item in rows:
        label, marker = item['name'], item['marker']
        c = directory / (label + '.c'); binary = directory / (label + '.host')
        need(sha(c.read_bytes()) == item['code_sha256'], 'actual complete generated C')
        compile_row = base.load(directory / (label + '-compile.argv.json'))
        flags = ['-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-O1', '-g']
        flags += ['-DHPPE=1'] if hppe else []
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
        need(compile_row['argv'] == [cc, *flags, str(c), '-o', str(binary)], 'real compile argv')
        compiled = base.load(directory / (label + '-compile.exit.json'))['returncode']
        need(type(compiled) is int and compiled == 0 and
             not (directory / (label + '-compile.stdout')).read_bytes() and
             not (directory / (label + '-compile.stderr')).read_bytes(), 'all native variants compile clean')
        run = base.load(directory / (label + '-run.argv.json'))
        need(run['argv'] == [str(binary), *(['conflict'] if label == 'old-sd' else [])], 'real runtime argv')
        need(run['ASAN_OPTIONS'] == 'detect_leaks=0:halt_on_error=1:abort_on_error=0:exitcode=97' and
             run['UBSAN_OPTIONS'] == 'halt_on_error=1:abort_on_error=0:print_stacktrace=1:exitcode=98', 'native sanitizer environment')
        code = base.load(directory / (label + '-run.exit.json'))['returncode']
        out = (directory / (label + '-run.stdout')).read_bytes()
        err = (directory / (label + '-run.stderr')).read_bytes()
        if marker is None:
            positive(code, out, err)
        else:
            negative(code, out, err, marker)
    sanitizer_receipts(directory, data, cc, hppe)
    for name, expected in report['inputs'].items():
        need(sha(Path(name).read_bytes()) == expected, 'native live-input stability')
    return {'positives': 266, 'mutants': 20, 'old_witnesses': 2, 'profile': report['profile']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--print-baseline-ref', action='store_true')
    mode.add_argument('--print-source-ref', action='store_true')
    mode.add_argument('--sanitizer-preflight', action='store_true')
    for name in ('source-root', 'baseline-source-root', 'legacy-source-root', 'ssdk', 'dp', 'output'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--cc')
    args = parser.parse_args(); data = configuration()
    if args.print_baseline_ref:
        print(data['baseline_commit']); return
    if args.print_source_ref:
        print(data['source_commit']); return
    if args.sanitizer_preflight:
        need(args.source_root is not None and args.output is not None and args.cc is not None,
             'complete source-bound sanitizer preflight inputs')
        need(not any((args.baseline_source_root, args.legacy_source_root, args.ssdk, args.dp)),
             'sanitizer preflight is not a prepared SDK campaign')
        source, output = args.source_root.resolve(), args.output.resolve()
        output.mkdir(parents=True, exist_ok=False)
        report = {'status': 'INCOMPLETE', 'source_commit': data['source_commit'], 'firmware_approved': False}
        try:
            actual = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=30)
            need(actual.returncode == 0 and not actual.stderr and actual.stdout.strip() == data['source_commit'],
                 'actual preflight source head')
            base.check(source, data['source_assets'])
            command = [sys.executable, '-B', '-O', str(source / 'tests/test-ssdk-retirement-admission.py'),
                       '--canaries-only', '--sanitize', '--cc', args.cc, '--output', str(output / 'controls')]
            process = subprocess.run(command, capture_output=True, timeout=180)
            (output / 'command.stdout').write_bytes(process.stdout)
            (output / 'command.stderr').write_bytes(process.stderr)
            report.update(argv=command, returncode=process.returncode)
            need(process.returncode == 0 and not process.stderr and
                 json.loads(process.stdout, object_pairs_hook=base.unique) == {'status': 'PASS_SANITIZER_CONTROLS_ONLY'},
                 'actual early sanitizer preflight')
            need(base.load(output / 'controls/RESULTS.json')['status'] == 'PASS_SANITIZER_CONTROLS_ONLY',
                 'preflight scope not a formal SDK campaign')
            sanitizer_receipts(output / 'controls', data, args.cc, False)
            base.check(source, data['source_assets'])
            report['status'] = 'PASS_SOURCE_BOUND_SANITIZERS_ONLY_NOT_SSDK_OR_FIRMWARE'
        except Exception as error:
            report['error'] = str(error); raise
        finally:
            (output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report)); return
    need(all(getattr(args, k.replace('-', '_')) is not None for k in
             ('source-root', 'baseline-source-root', 'legacy-source-root', 'ssdk', 'dp', 'output', 'cc')),
         'complete actual gate inputs')
    source, accepted = args.source_root.resolve(), args.baseline_source_root.resolve()
    original, output = args.ssdk.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'INCOMPLETE', 'scope': 'SOURCE_AND_HOST_ONLY_NOT_TARGET_OR_RUNTIME', 'commands': [],
              'source_commit': data['source_commit'], 'accepted_prefix_commit': data['baseline_commit']}
    owned = {p: sha(p.read_bytes()) for p in [PROFILE, Path(__file__).resolve(), base.CONTRACT]}

    def invoke(label, command, cwd=ROOT, raw=None):
        command = [str(x) for x in command]
        p = subprocess.run(command, input=raw, cwd=cwd, capture_output=True, timeout=3600,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        (output / (label + '.stdout')).write_bytes(p.stdout)
        (output / (label + '.stderr')).write_bytes(p.stderr)
        row = {'argv': command, 'returncode': p.returncode, 'stdout_sha256': sha(p.stdout), 'stderr_sha256': sha(p.stderr)}
        (output / (label + '.json')).write_text(json.dumps(row, indent=2) + '\n')
        report['commands'].append(row)
        need(p.returncode == 0 and not p.stderr, 'retirement command:' + label)
        return p.stdout

    try:
        need(invoke('source-head', ['git', '-C', source, 'rev-parse', 'HEAD']).decode().strip() == data['source_commit'],
             'actual new source identity')
        need(invoke('accepted-head', ['git', '-C', accepted, 'rev-parse', 'HEAD']).decode().strip() == data['baseline_commit'],
             'actual accepted source identity')
        base.check(source, data['source_assets'])
        package_prefix = 'package/qca-nss/qca-ssdk/patches/'
        expected_patches = {name[len(package_prefix):]: digest for name, digest in data['source_assets'].items()
                            if name.startswith(package_prefix)}
        need(len(expected_patches) == 39 and base.inventory(source / package_prefix) == expected_patches,
             'complete current39 patch inventory')
        inherited = {k: v for k, v in base.configuration()['assets'].items()
                     if k != 'package/qca-nss/qca-ssdk/Makefile'}
        base.check(source, inherited)
        exports = {'SOURCE/' + name: base.path(source, name) for name in data['source_assets']}
        exports.update({'BUILD/profile.json': PROFILE, 'BUILD/gate.py': Path(__file__).resolve()})
        base.export_inputs(output, exports)
        code, metadata = base.prepared_partition(original, output, 'ssdk', data['prepared_files'])
        need(code == data['prepared_files'], 'actual full SSDK39 code')
        current = output / 'actual39'; base.copy_code(original, current, code)
        prefix = output / 'accepted38'; base.copy_code(original, prefix, code)
        patch = base.path(source, 'package/qca-nss/qca-ssdk/patches/' + data['patch'])
        stdout = invoke('reverse051', ['patch', '-p1', '-R', '--batch', '--fuzz=0'], cwd=prefix, raw=patch.read_bytes())
        need(not re.search(rb'offset|fuzz|FAILED|reject|Reversed', stdout, re.I), 'exact051 reverse')
        need(base.inventory(prefix) == base.configuration()['ssdk']['current_files'], 'full frozen38 prefix')
        for hppe, label in [(True, 'native-hppe'), (False, 'native-other')]:
            directory = output / label
            argv = [sys.executable, '-B', '-O', source / 'tests/test-ssdk-retirement-admission.py',
                    '--baseline38', prefix, '--prepared', current, '--cc', args.cc,
                    '--sanitize', '--output', directory]
            if hppe: argv += ['--hppe']
            invoke(label, argv)
            report[label] = native(directory, data, source, args.cc, hppe)
        invoke('accepted38-prefix-regressions', [sys.executable, '-B', ROOT / '.github/scripts/verify-mdio-lifecycle-repairs.py',
            '--current-layers', '--source-root', accepted, '--legacy-source-root', args.legacy_source_root.resolve(),
            '--dp', args.dp.resolve(), '--ssdk', prefix, '--cc', args.cc, '--output', output / 'prefix-regressions'])
        parent = base.load(output / 'prefix-regressions/RESULTS.json')
        need(parent['status'] == 'PASS_CURRENT_LAYER_AND_EXPLICIT_PREFIX_HOST_ONLY' and parent['kind'] == 'mdio' and
             parent['source_commit'] == data['baseline_commit'], 'actual accepted38 parent result')
        need(base.partition(original) == (code, metadata) and base.inventory(current) == code and
             base.inventory(prefix) == base.configuration()['ssdk']['current_files'], 'prepared end stability')
        base.check(source, data['source_assets'])
        need(all(sha(p.read_bytes()) == expected for p, expected in owned.items()), 'build gate end stability')
        report.update(status='PASS_SSDK39_AND_ACCEPTED38_PREFIX_HOST_ONLY', runtime_approved=False,
                      actual_code_files=code, actual_recipe_metadata=metadata)
    except Exception as error:
        report['error'] = str(error); raise
    finally:
        (output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'native-hppe': report['native-hppe'], 'native-other': report['native-other']}))


if __name__ == '__main__':
    main()
