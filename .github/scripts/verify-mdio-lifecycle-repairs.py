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
         profile['profile'] == 'DP19_SSDK35_ARGUMENTS_AND_OF_LEASES', 'unknown profile')
    check(source, profile['assets'])
    for label, tree, count in [('dp', dp, 19), ('ssdk', ssdk, 35)]:
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
    admit(args.source_root, args.dp, args.ssdk, profile)
    report = {'status': 'PASS_HOST_REGRESSIONS_NOT_SHARED_RETIREMENT_OR_RUNTIME',
              'profile_sha256': sha(PROFILE.read_bytes()), 'results': results,
              'shared_UK_SD_PHY_retirement': 'OPEN', 'device_or_performance_qualification': False}
    (args.output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
