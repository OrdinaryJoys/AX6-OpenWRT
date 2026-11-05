#!/usr/bin/env python3
"""Gate SSDK40 actual code and unchanged SSDK39/38 prefixes independently."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / '.github/ax6-ssdk40-contract.json'
OLD_GATE = ROOT / '.github/scripts/verify-ssdk-retirement-admission.py'
spec = importlib.util.spec_from_file_location('accepted39_gate', OLD_GATE)
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
base = old.base
need, sha = base.need, base.sha
PATCH = 'package/qca-nss/qca-ssdk/patches/052-ssdk-probe-balanced-node-and-oom.patch'
MARKERS = {'missing-put': (1, 'NODE_REF'), 'double-put': (1, 'NODE_REF'),
           'missing-oom-check': (5, 'NULL_PRIVATE'), 'lost-populate-error': (9, 'RETURN_VALUE'),
           'missing-publication': (1, 'PUBLISHED_POINTER'), 'lost-device-id': (1, 'PROPERTY_PATH'),
           'wrong-oom-result': (5, 'RETURN_VALUE')}


def configuration():
    data = base.load(PROFILE)
    need(data['schema'] == 1 and data['frozen'] is True and data['profile'] == 'SSDK40_PROBE_NOT_SHARED_ROOT', 'fixed SSDK40 profile')
    need(sha(old.PROFILE.read_bytes()) == data['accepted39_contract_sha256'] and
         sha(OLD_GATE.read_bytes()) == data['accepted39_gate_sha256'], 'immutable SSDK39 gates')
    parent = old.configuration()
    need(parent['source_commit'] == data['accepted39_commit'], 'actual accepted39 identity')
    additions = {PATCH, 'tests/test-ssdk-probe-resource.py', 'tests/ssdk-probe-resource/README.md',
                 'tests/ssdk-probe-resource/fixture.c', 'tests/ssdk-probe-resource/prefix39-probe.c',
                 'tests/ssdk-probe-resource/current40-probe.c', 'package/libs/ncurses/Makefile', 'package/libs/ncurses/Config.in'}
    need(set(data['source_assets']) == set(parent['source_assets']) | additions and
         all(data['source_assets'][n] == value for n, value in parent['source_assets'].items()
             if n != 'package/qca-nss/qca-ssdk/Makefile'), 'complete unchanged39 assets plus reviewed40 inputs')
    expected = dict(parent['prepared_files'])
    need(expected['src/init/ssdk_init.c'] == '09f8a1d036ed63bce56ba1d69653870710865c9fcc68957bf92d82ca0d9ded4d', 'fixed39 source')
    expected['src/init/ssdk_init.c'] = '9590d2c01638765d4600984abe48f652f11cefb9d8fd43fc781acab7e7fb53b8'
    need(data['prepared_files'] == expected and len(expected) == 692, 'only reviewed probe changes actual SDK')
    need(data['source_assets'][PATCH] == '004ab0a1472f331cc4c60887281cbfc1a9d428ae6c3513e01d2ee7114e93686e', 'fixed052 patch')
    return data


def exact(code, out, err, expected_out, expected_err, expected_code):
    need(type(code) is int and code == expected_code and out == expected_out and err == expected_err, 'precise process result')


def probe_receipts(directory, cc, source, current=None, prefix=None, preflight=False):
    report = base.load(directory / 'RESULTS.json')
    support = source / 'tests/ssdk-probe-resource'
    current_input = support / 'current40-probe.c' if preflight else current / 'src/init/ssdk_init.c'
    prefix_input = support / 'prefix39-probe.c' if preflight else prefix / 'src/init/ssdk_init.c'
    expected_inputs = [source / 'tests/test-ssdk-probe-resource.py', support / 'fixture.c', support / 'README.md',
                       current_input, prefix_input]
    need(report['inputs'] == {str(p.resolve()): sha(p.read_bytes()) for p in expected_inputs}, 'exact five live probe inputs')

    def body(path):
        rows = re.findall(r'^static int ssdk_probe\(struct platform_device \*pdev\)\n\{.*?^\}', path.read_text(), re.M | re.S)
        need(len(rows) == 1, 'complete current/prefix probe')
        return rows[0]

    current_body, prefix_body = body(current_input), body(prefix_input)
    need(sha(current_body.encode()) == '520b877bb83bf62f7a033416e0800f445da7185931d662a95e657bab2a675084' and
         sha(prefix_body.encode()) == 'cf4f54e388d0230e0a50c294290e0310929d8b1d88942195582c39658e0d1c82', 'actual frozen function bodies')
    edits = {
        'missing-put': ('\tof_node_put(np);', '\t/* source mutant: no put */'),
        'double-put': ('\tof_node_put(np);', '\tof_node_put(np);\n\tof_node_put(np);'),
        'missing-oom-check': ('\tif (!priv) {\n\t\trv = -ENOMEM;\n\t\tgoto out;\n\t}', ''),
        'lost-populate-error': ('rv = of_platform_populate(np, NULL, NULL, &pdev->dev);', 'rv = of_platform_populate(np, NULL, NULL, &pdev->dev);\n\t\trv = 0;'),
        'missing-publication': ('\tplatform_set_drvdata(pdev, priv);', '\t/* source mutant: no publication */'),
        'lost-device-id': ('\tof_property_read_u32(np, "device_id", &(priv->dev_id));', '\t/* source mutant: no property */'),
        'wrong-oom-result': ('\t\trv = -ENOMEM;', '\t\trv = 0;'),
    }
    expected_c = {'current40': current_body, 'prefix39': prefix_body}
    for name, (before, after) in edits.items():
        need(current_body.count(before) == 1, 'independent exact source mutation anchor')
        expected_c['negative/' + name] = current_body.replace(before, after, 1)
    status = 'PASS_PROBE_FUNCTION_PREFLIGHT_NOT_PREPARED_SSDK' if preflight else 'PASS_SSDK40_PROBE_HOST_ONLY'
    need(report['status'] == status and report['runtime_approved'] is False and
         report['positive'] == list(range(12)) and report['negative'] ==
         [{'name': name, 'case': case, 'marker': marker} for name, (case, marker) in MARKERS.items()] and
         report['old_witnesses'] == [{'case': case, 'marker': marker} for case, marker in
                                      [(1, 'NODE_REF'), (5, 'NULL_PRIVATE'), (9, 'NODE_REF')]], 'complete actual probe inventory')
    need([report[k] for k in ('positive_count', 'negative_count', 'old_witness_count')] == [12, 7, 3] and
         all(type(report[k]) is int for k in ('positive_count', 'negative_count', 'old_witness_count')) and
         all(type(i) is int for i in report['positive']) and
         all(type(r['case']) is int for r in report['negative'] + report['old_witnesses']) and
         len(report['commands']) == 31, 'fixed probe obligations')
    compiler = str(Path(shutil.which(cc)).resolve())
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
             '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer']
    need(report['compiler'] == {'path': compiler, 'sha256': sha(Path(compiler).read_bytes()), 'flags': flags}, 'actual dual-instrumented compiler')
    labels = ['current40', *('negative/' + n for n in MARKERS), 'prefix39']
    for label in labels:
        path = directory / label
        need((path / 'actual.c').read_bytes() == (expected_c[label] + '\n').encode() and
             (path / 'fixture.c').read_bytes() == (support / 'fixture.c').read_bytes(), 'actual whole generated C and fixture')
        row = base.load(path / 'compile.json')
        need(row['argv'] == [compiler, *flags, str(path / 'fixture.c'), '-o', str(path / 'fixture')] and
             row['timeout'] is False, 'fixed compile argv')
        exact(row['returncode'], (path / 'compile.stdout').read_bytes(), (path / 'compile.stderr').read_bytes(), b'', b'', 0)
    runs = [('current40/case-' + str(i), 'current40', i, None) for i in range(12)]
    runs += [('negative/' + n + '/run', 'negative/' + n, c, m) for n, (c, m) in MARKERS.items()]
    runs += [('prefix39/case-' + str(c), 'prefix39', c, m) for c, m in [(1, 'NODE_REF'), (5, 'NULL_PRIVATE'), (9, 'NODE_REF')]]
    for stem, label, case, marker in runs:
        row = base.load(directory / (stem + '.json'))
        need(row['argv'] == [str(directory / label / 'fixture'), str(case)] and row['timeout'] is False and
             row['ASAN_OPTIONS'] == 'detect_leaks=0:halt_on_error=1:abort_on_error=0:exitcode=97' and
             row['UBSAN_OPTIONS'] == 'halt_on_error=1:abort_on_error=0:exitcode=98', 'exact probe run')
        exact(row['returncode'], (directory / (stem + '.stdout')).read_bytes(), (directory / (stem + '.stderr')).read_bytes(),
              b'PROBE:PASS\n' if marker is None else b'', b'' if marker is None else ('PROBE:' + marker + '\n').encode(), 0 if marker is None else 86)
    need(all(sha(Path(p).read_bytes()) == digest for p, digest in report['inputs'].items()), 'probe inputs unchanged')
    return {'positives': 12, 'precise_negatives': 7, 'old_witnesses': 3, 'scope': status}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print-source-ref', action='store_true')
    parser.add_argument('--print-prefix39-ref', action='store_true')
    parser.add_argument('--sanitizer-preflight', action='store_true')
    for name in ('source-root', 'accepted39-source-root', 'baseline-source-root', 'legacy-source-root', 'ssdk', 'dp', 'output'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--cc')
    args = parser.parse_args(); data = configuration()
    if args.print_source_ref:
        print(data['source_commit']); return
    if args.print_prefix39_ref:
        print(data['accepted39_commit']); return
    need(args.source_root and args.output and args.cc, 'source/output/compiler required')
    source, out = args.source_root.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    result = {'status': 'INCOMPLETE', 'source_commit': data['source_commit'], 'runtime_approved': False, 'commands': []}
    owned = {p: sha(p.read_bytes()) for p in (PROFILE, Path(__file__), old.PROFILE, OLD_GATE)}

    def invoke(name, argv, cwd=ROOT, raw=None):
        argv = list(map(str, argv))
        process = subprocess.run(argv, input=raw, cwd=cwd, capture_output=True, timeout=3600,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        (out / (name + '.stdout')).write_bytes(process.stdout); (out / (name + '.stderr')).write_bytes(process.stderr)
        row = {'argv': argv, 'returncode': process.returncode}
        (out / (name + '.json')).write_text(json.dumps(row, indent=2) + '\n'); result['commands'].append(row)
        need(process.returncode == 0 and not process.stderr, 'SSDK40 command: ' + name)
        return process.stdout

    try:
        need(invoke('source-head', ['git', '-C', source, 'rev-parse', 'HEAD']).decode().strip() == data['source_commit'], 'actual current source')
        base.check(source, data['source_assets'])
        base.export_inputs(out, {'SOURCE/' + n: base.path(source, n) for n in data['source_assets']} |
                           {'BUILD/profile.json': PROFILE, 'BUILD/gate.py': Path(__file__)})
        unit = source / 'tests/test-ssdk-probe-resource.py'
        if args.sanitizer_preflight:
            invoke('sanitizers', [sys.executable, '-B', '-O', source / 'tests/test-ssdk-retirement-admission.py',
                   '--canaries-only', '--sanitize', '--cc', args.cc, '--output', out / 'controls'])
            old.sanitizer_receipts(out / 'controls', old.configuration(), args.cc, False)
            invoke('probe-functions', [sys.executable, '-B', '-O', unit, '--functions-only', '--cc', args.cc, '--output', out / 'probe-functions'])
            result['probe'] = probe_receipts(out / 'probe-functions', args.cc, source, preflight=True)
            result['status'] = 'PASS_SSDK40_SOURCE_BOUND_PREFLIGHT_NOT_PREPARED_SDK'
        else:
            need(args.accepted39_source_root and args.baseline_source_root and args.legacy_source_root and args.ssdk and args.dp, 'complete prepared inputs')
            prefix_source = args.accepted39_source_root.resolve()
            need(invoke('prefix39-head', ['git', '-C', prefix_source, 'rev-parse', 'HEAD']).decode().strip() == data['accepted39_commit'], 'actual immutable39 checkout')
            base.check(prefix_source, old.configuration()['source_assets'])
            patches = {n.removeprefix('package/qca-nss/qca-ssdk/patches/'): v for n, v in data['source_assets'].items() if n.startswith('package/qca-nss/qca-ssdk/patches/')}
            need(len(patches) == 40 and base.inventory(source / 'package/qca-nss/qca-ssdk/patches') == patches, 'exact40 patch chain')
            original = args.ssdk.resolve()
            code, metadata = base.prepared_partition(original, out, 'ssdk', data['prepared_files'])
            need(code == data['prepared_files'], 'full actual SSDK40 source')
            current, prefix = out / 'actual40', out / 'prefix39'
            base.copy_code(original, current, code); base.copy_code(original, prefix, code)
            raw = invoke('reverse052', ['patch', '-p1', '-R', '--batch', '--fuzz=0'], cwd=prefix, raw=(source / PATCH).read_bytes())
            need(raw in (b'patching file src/init/ssdk_init.c\n', b"patching file 'src/init/ssdk_init.c'\n") and
                 base.inventory(prefix) == old.configuration()['prepared_files'], 'exact052 reverse to frozen39')
            invoke('accepted39-parent', [sys.executable, '-B', OLD_GATE, '--source-root', prefix_source,
                   '--baseline-source-root', args.baseline_source_root.resolve(), '--legacy-source-root', args.legacy_source_root.resolve(),
                   '--ssdk', prefix, '--dp', args.dp.resolve(), '--cc', args.cc, '--output', out / 'accepted39-parent'])
            need(base.load(out / 'accepted39-parent/RESULTS.json')['status'] == 'PASS_SSDK39_AND_ACCEPTED38_PREFIX_HOST_ONLY', 'actual unchanged39/38 parent')
            invoke('probe-native', [sys.executable, '-B', '-O', unit, '--prepared', current, '--baseline39', prefix,
                   '--cc', args.cc, '--output', out / 'probe-native'])
            result['probe'] = probe_receipts(out / 'probe-native', args.cc, source, current, prefix)
            need(base.partition(original) == (code, metadata) and base.inventory(current) == code and
                 base.inventory(prefix) == old.configuration()['prepared_files'], 'end prepared stability')
            result.update(status='PASS_SSDK40_PROBE_AND_IMMUTABLE39_38_HOST_ONLY', actual_code_files=code, actual_recipe_metadata=metadata)
        base.check(source, data['source_assets'])
        need(all(sha(p.read_bytes()) == digest for p, digest in owned.items()), 'gate inputs unchanged')
    except Exception as error:
        result['error'] = str(error); raise
    finally:
        (out / 'RESULTS.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'probe': result['probe']}))


if __name__ == '__main__':
    main()
