#!/usr/bin/env python3
"""Linux GCC11 PHY source/model validation only; no firmware or device operations."""
import argparse
import hashlib
import importlib.util
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('phy_smoke_receipt_gate', ROOT / '.github/scripts/verify-mdio-lifecycle-repairs.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
CONTRACT = ROOT / '.github/ax6-phy-host-smoke.json'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_text(), object_pairs_hook=gate.unique)


def contract():
    data = load(CONTRACT)
    gate.need(type(data['schema']) is int and data['schema'] == 1 and
              data['scope'] == 'PHY37_HOST_SUBSET_NO_050_NO_FIRMWARE', 'smoke scope')
    gate.need(re.fullmatch('[0-9a-f]{40}', data['source_ref']) is not None, 'source ref')
    gate.need(sha(gate.PROFILE.read_bytes()) == data['mdio37_profile_sha256'], 'frozen37 profile')
    fixture = gate.path(ROOT, data['fixture'])
    gate.need(sha(fixture.read_bytes()) == data['fixture_sha256'], 'frozen vendor fixture')
    gate.need(sha(gate.path(ROOT, '.github/fixtures/phy-host/SOURCE.json').read_bytes()) ==
              data['fixture_metadata_sha256'], 'frozen vendor metadata')
    return data


def inventory(root):
    rows = {}
    for path in sorted(root.rglob('*')):
        gate.need(not path.is_symlink(), 'source symlink')
        if path.is_file():
            rows[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return rows


def unpack(raw, destination):
    gate.need(not destination.exists(), 'fresh source destination')
    destination.mkdir(parents=True)
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            gate.need(name.parts and not name.is_absolute() and '..' not in name.parts and
                      '.git' not in name.parts and (member.isfile() or member.isdir()), 'unsafe source member')
            gate.need(str(name) not in seen, 'duplicate source member')
            seen.add(str(name))
            path = destination / str(name)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile(member).read())
    return inventory(destination)


def prepare(source, out, configuration, record):
    payload = (ROOT / configuration['fixture']).read_bytes()
    gate.need(sha(payload) == configuration['fixture_sha256'], 'fixture changed before extraction')
    raw = lzma.decompress(payload, memlimit=128 * 1024 * 1024)
    gate.need(len(raw) == configuration['raw_tar_bytes'] and sha(raw) == configuration['raw_tar_sha256'],
              'raw vendor archive identity')
    tree = out / 'prepared37'
    original = unpack(raw, tree)
    gate.need(len(original) == 692 and gate.inventory_sha(original) == configuration['upstream_inventory_sha256'],
              'complete pinned upstream692')
    profile = load(gate.PROFILE)['ssdk']
    patch_root = source / 'package/qca-nss/qca-ssdk/patches'
    admitted = dict(profile['patches'], **configuration['excluded_patches'])
    gate.need(set(p.name for p in patch_root.glob('*.patch')) == set(admitted), 'exact current38 patch inventory')
    gate.check(patch_root, admitted)
    context_spec = importlib.util.spec_from_file_location('phy_smoke_patch_context', source / 'tests/edma_patch_context.py')
    context = importlib.util.module_from_spec(context_spec)
    context_spec.loader.exec_module(context)
    names = sorted(profile['patches'])
    gate.need(len(names) == 37 and names[-1] == '049-module-lifetime-shared-phy-ops.patch', 'fixed37 prefix')
    entries = []
    for number, name in enumerate(names, 1):
        patch = (patch_root / name).read_bytes()
        expected, declared = context.inspect_patch(tree, patch)
        row = record('patch-%02d' % number, ['patch', '-p1', '--batch', '--fuzz=0', '-V', 'none'],
                     cwd=tree, data=patch)
        gate.need(row['returncode'] == 0 and not row['stderr'] and not re.search(
            'fuzz|offset|FAILED|reject|malformed|Reversed|previously applied', row['stdout'], re.I), 'exact patch replay ' + name)
        context.verify_applied(tree, expected)
        entries.append({'name': name, 'sha256': sha(patch), 'declared_context': declared})
        if number == 36:
            gate.need(gate.inventory_sha(inventory(tree)) == profile['reverse_steps'][0]['inventory_sha256'],
                      'frozen baseline36')
            shutil.copytree(tree, out / 'baseline36')
    gate.need(inventory(tree) == profile['prepared_files'], 'complete prepared37 equality')
    (out / 'SOURCE-PREPARATION.json').write_text(json.dumps({
        'scope': 'TEXT_PREFIX37_NO_MAKE_NO_TARGET_COMPILE', 'patches': entries,
        'excluded_from_this_smoke': configuration['excluded_patches'], 'upstream_files': original,
        'prepared_files': profile['prepared_files']}, indent=2) + '\n')
    return out / 'baseline36', tree


def export_inputs(out, files):
    destination = out / 'INPUT-BLOBS'; destination.mkdir(exist_ok=True)
    rows = []
    for number, (name, path) in enumerate(sorted(files.items())):
        gate.need(not path.is_symlink() and path.is_file() and '.git' not in path.parts, 'fixed input export')
        raw = path.read_bytes(); relative = 'INPUT-BLOBS/%05d.data' % number
        (out / relative).write_bytes(raw)
        rows.append({'origin': name, 'file': relative, 'bytes': len(raw), 'sha256': sha(raw)})
    gate.need({p.name for p in destination.iterdir()} ==
              {'%05d.data' % n for n in range(len(rows))}, 'exact nonhidden input export')
    (out / 'INPUT-EXPORT.json').write_text(json.dumps({'scope': 'FIXED_NONHIDDEN_INPUT_MAPPING', 'files': rows}, indent=2) + '\n')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print-source-ref', action='store_true')
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cc', default='gcc-11')
    args = parser.parse_args()
    configuration = contract()
    if args.print_source_ref:
        print(configuration['source_ref']); return
    gate.need(args.source_root is not None and args.output is not None, 'source/output required')
    source, out = args.source_root.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'INCOMPLETE', 'scope': configuration['scope'],
              'firmware_build': False, 'device_access': False, 'contract_sha256': sha(CONTRACT.read_bytes()),
              'github_run_id': os.environ.get('GITHUB_RUN_ID'), 'github_head': os.environ.get('GITHUB_SHA'),
              'github_ref': os.environ.get('GITHUB_REF'),
              'platform': platform.platform(), 'commands': []}

    def record(label, command, cwd=ROOT, data=None, timeout=120):
        try:
            process = subprocess.run([str(p) for p in command], cwd=cwd, input=data,
                                     capture_output=True, timeout=timeout)
            code, stdout, stderr = process.returncode, process.stdout, process.stderr
        except subprocess.TimeoutExpired as error:
            code, stdout, stderr = 'timeout', error.stdout or b'', error.stderr or b''
        row = {'command': [str(p) for p in command], 'returncode': code,
               'stdout': stdout.decode(errors='replace'), 'stderr': stderr.decode(errors='replace')}
        (out / (label + '.stdout')).write_bytes(stdout)
        (out / (label + '.stderr')).write_bytes(stderr)
        (out / (label + '.json')).write_text(json.dumps(row, indent=2) + '\n')
        report['commands'].append({'label': label, **row})
        return row

    try:
        gate.need(sys.platform == 'linux' and platform.machine() == 'x86_64', 'Linux x86_64 required')
        head = record('source-head', ['git', '-C', source, 'rev-parse', 'HEAD'])
        gate.need(head['returncode'] == 0 and not head['stderr'] and
                  head['stdout'].strip() == configuration['source_ref'], 'actual source identity')
        gate.check(source, configuration['source_assets'])
        dump = record('gcc-version', [args.cc, '-dumpfullversion', '-dumpversion'])
        gate.need(dump['returncode'] == 0 and not dump['stderr'] and
                  dump['stdout'].strip() == '11.4.0', 'actual GCC11.4 required')
        exports = {'SOURCE/' + n: gate.path(source, n) for n in configuration['source_assets']}
        exports.update({'BUILD/contract.json': CONTRACT, 'BUILD/mdio37.json': gate.PROFILE,
                        'BUILD/runner.py': Path(__file__).resolve(),
                        'BUILD/receipt-gate.py': ROOT / '.github/scripts/verify-mdio-lifecycle-repairs.py',
                        'BUILD/workflow.yml': ROOT / '.github/workflows/lint.yml',
                        'BUILD/vendor-source.tar.xz': ROOT / configuration['fixture'],
                        'BUILD/vendor-source.json': ROOT / '.github/fixtures/phy-host/SOURCE.json',
                        'BUILD/workflow-tests.py': ROOT / 'tests/test-phy-host-smoke.py'})
        for name in load(gate.PROFILE)['ssdk']['patches']:
            exports['PATCH/' + name] = source / 'package/qca-nss/qca-ssdk/patches' / name
        build_inputs = {name: sha(path.read_bytes()) for name, path in exports.items() if name.startswith('BUILD/')}
        report['build_inputs'] = build_inputs
        export_inputs(out, exports)
        command = [sys.executable, '-B', source / 'tests/test-ssdk-phy-sanitizer-canaries.py',
                   '--cc', args.cc, '--output', out / 'canary-controls']
        row = record('native-canary-controls', command)
        gate.need(row['returncode'] == 0 and not row['stderr'], 'native canary control failure')
        controls = load(out / 'canary-controls/RESULTS.json')
        gate.need(controls['status'] == 'PASS_SANITIZER_CONTROLS_ONLY' and
                  len(controls['disabled_controls']) == len(controls['crossed_identity_controls']) == 2 and
                  controls['oracle_controls']['rejected_pollution'] == 24, 'native activation control inventory')
        baseline, prepared = prepare(source, out, configuration, record)
        command = [sys.executable, '-B', source / 'tests/test-ssdk-phy-ops-lifetime.py',
                   '--baseline', baseline, '--prepared', prepared, '--cc', args.cc,
                   '--patch-tool', '/usr/bin/patch', '--sanitize', '--output', out / 'phy']
        row = record('native-phy-campaign', command, timeout=900)
        gate.need(row['returncode'] == 0 and not row['stderr'], 'native complete PHY campaign failure')
        data = load(out / 'phy/RESULTS.json')
        gate.verify_phy_ops(out / 'phy', data, args.cc)
        for label, tree in [('BASELINE36', baseline), ('PREPARED37', prepared)]:
            exports.update({label + '/' + name: tree / name for name in inventory(tree)})
        for name in ['marker-valid', 'both-valid', 'marker-nonempty']:
            exports['METADATA/' + name] = out / 'phy/metadata-controls' / name / '.prepared_deadbeef'
        report['exported_inputs'] = export_inputs(out, exports)
        gate.check(source, configuration['source_assets'])
        clean = record('source-clean', ['git', '-C', source, 'status', '--porcelain'])
        gate.need(clean['returncode'] == 0 and not clean['stdout'] and not clean['stderr'], 'source changed during smoke')
        gate.need(all(sha(exports[name].read_bytes()) == digest for name, digest in build_inputs.items()),
                  'build inputs changed during smoke')
        expected_labels = ['source-head', 'gcc-version', 'native-canary-controls'] + [
            'patch-%02d' % n for n in range(1, 38)] + ['native-phy-campaign', 'source-clean']
        gate.need([row['label'] for row in report['commands']] == expected_labels, 'complete host orchestration')
        report.update(status='PASS_LINUX_GCC11_PHY37_HOST_ONLY', source_ref=configuration['source_ref'],
                      positive_cases=68, precise_mutants=80, old_counterexamples=8,
                      full_current38_or_firmware_qualification=False)
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        (out / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'source_ref', 'positive_cases', 'precise_mutants', 'old_counterexamples')}))


if __name__ == '__main__':
    main()
