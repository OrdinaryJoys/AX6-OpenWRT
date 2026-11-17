#!/usr/bin/env python3
"""Admit one reviewed DRV29 build; replay the exact older source boundaries."""
import argparse
import hashlib
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
PROFILE = ROOT / '.github/ax6-nss-drv29-contract.json'
PROFILE_SHA256 = 'bb3e1ec11dc7340d85ca193f041e3e7d2b27656d8196273b1bf7560407ad4358'
OLD_COMMIT = '5e5ccf0bb7b31a0f5890c98a37ca5b256a2749d8'
OLD_RELEASE = 27
PACKAGE = 'package/qca-nss/qca-nss-drv'
LOCK = '.github/ax6-nss-lock.env'
RECIPE_SHA256 = 'c2cb769849f490501b808e723bcebfee5c1b2b410f4ea16decdcdbd750b87a85'
FROZEN = {
    '.github/scripts/verify-nss-root-host.py': 'd3c41e9478a7593c4e588b6f11ac33fca88f29882f86a4edbac1ae432671eab1',
    '.github/scripts/verify-ax6-current-layers.py': '27f4220ff829ab7ccd73c452ae969f67a42839873bdb1f46e26d098ef3060fe0',
    '.github/scripts/verify-nss-command-inputs.py': 'cc563cc9f13278f9c02fb11a15ff1ec0361a5b649a2c41fdac098460eb638ced',
    '.github/ax6-nss-root-host-contract.json': 'f89e893bcc21b23be67c0d8afd5dae80c5bd4817b74ddb213569586e5890200c',
    '.github/ax6-current-layer-contract.json': 'ea6166ce5649ba370ec214c9f8bb7423583197b0cf2bbc1e4d0c0946a4533d1f',
    '.github/ax6-nss-command-contract.json': '508cb56de0841de94da7cfe747d0ab2622f9d137899546015a145e2cbf5a88e7',
}
# These postimages are from the audited candidate-030, candidate-031 and
# integrated-032 PREPARE.json inventories, not from the new build's unpack.
PRIOR = (
    (30, '030-hal-probe-allocate-local-dummy-first.patch',
     'b20e37b5d9fcbac965b7ddf360136eda33ef339436bd00f0e3c7f6bf2836c2e6',
     'nss_hal/nss_hal.c', 'a2aecd95d9f84ef399ff4ce23ad64b85534592b24960980f5a98c0cf6c38fd9c',
     '7799610a19decc46d207cde67cc0afb5cc2ff0d14011301b2c4eb16101ac9847'),
    (31, '031-coredump-empty-write-noop.patch',
     'b4c9582f5a9ca19110db6643ad89d8918ed36a09a3561fa81e5678397ae5ba3b',
     'nss_init.c', 'dbbddfb1a260a545ecac9c80004645acadf839aa6166e33fe43490f13fb02e65',
     'ff3126f32bc2d0c0df82bef5a598c6d5f6a938e81aebacd2a733edd0ddf737b2'),
    (32, '032-ipq807x-private-pdata-rollback.patch',
     'd3339c2720b97a55160676f9f236acf4d463d7c3afdfcf4f4a64f8e7569e47a9',
     'nss_hal/ipq807x/nss_hal_pvt.c', '262c4a38d3bb2c8fe078f607b995d560b58e25e272eefea524b395989c4563a7',
     '670eafd37122a56970c069f2c278230a223551c9340266d5c7d3edc10a3234d4'),
)
TEST_DIRS = ('nss-probe-allocation', 'nss-coredump-control', 'nss-pdata-ownership',
             'nss-conn-transaction')
PRIOR_TESTS_SHA256 = '87e30861c8a105979974f701eafe78e665526406feb0b182b957fb5d50813d2a'
KERNEL_SHA256 = 'ac9501697708f8921734125d507661487462a6dae3205bf3c2ab92d7df94dc53'
CONNECTION_COUNTS = ('transaction_cases', 'transaction_controls', 'integration_cases', 'integration_controls')
USERSPACE_PATHS = (
    'package/libs/libubox/',
    'package/network/config/netifd/',
    'package/network/services/dnsmasq/',
    'package/network/services/hostapd/',
    'package/network/services/odhcpd/',
)
USERSPACE_FILES = {'README.md', 'tests/test-ax6-upstream-leaves.py', 'tests/test-dns-redirect-scope.sh'}


def load_frozen():
    spec = importlib.util.spec_from_file_location(
        'frozen_root_host', ROOT / '.github/scripts/verify-nss-root-host.py')
    frozen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    return frozen


# Verify the exact helpers before importing executable code.
for _path, _digest in FROZEN.items():
    _file = ROOT / _path
    if not _file.is_file() or _file.is_symlink() or hashlib.sha256(_file.read_bytes()).hexdigest() != _digest:
        raise ValueError('frozen prerequisite drift: ' + _path)
frozen = load_frozen()
base = frozen.base
need, sha = base.need, base.sha


def lock_value(raw, key):
    rows = [line.split('=', 1)[1] for line in raw.splitlines() if line.startswith(key + '=')]
    need(len(rows) == 1, 'one lock value required: ' + key)
    return rows[0]


def configuration():
    need(sha(PROFILE.read_bytes()) == PROFILE_SHA256,
         'DRV29 contract is not sealed to reviewed identities')
    profile = base.load(PROFILE)
    need(type(profile['schema']) is int and profile['schema'] == 1 and
         profile['profile'] == 'DRV29_CONNECTION_HOST_WITH_EXACT_DRV27_PREFIX' and
         profile['state'] == 'REVIEWED_DIAGNOSTIC_INPUTS', 'DRV29 diagnostic profile')
    for key in ('source_commit', 'source_parent'):
        need(re.fullmatch(r'[0-9a-f]{40}', profile[key]) is not None, 'full identity: ' + key)
    need(profile['source_parent'] == OLD_COMMIT and profile['source_commit'] != OLD_COMMIT,
         'DRV29 must be the direct child of the immutable DRV27 source')
    need(re.fullmatch(r'033-[a-z0-9-]+\.patch', profile['patch_name']) is not None, 'exact 033 patch name')
    for key in ('patch_sha256', 'inventory_sha256', 'source_manifest_sha256'):
        need(re.fullmatch(r'[0-9a-f]{64}', profile[key]) is not None, 'full digest: ' + key)
    for rows in (profile['changed_files'], profile['added_files'], profile['test_files']):
        need(type(rows) is dict and all(re.fullmatch(r'[0-9a-f]{64}', digest) for digest in rows.values()),
             'reviewed file digests')
    if 'firmware_successor' in profile:
        next_source = profile['firmware_successor']
        need(type(next_source) is dict and set(next_source) ==
             {'commit', 'manifest_sha256', 'tree_delta_sha256'}, 'one sealed userspace successor')
        need(re.fullmatch(r'[0-9a-f]{40}', next_source['commit']) and
             next_source['commit'] not in (profile['source_commit'], OLD_COMMIT), 'distinct successor identity')
        for key in ('manifest_sha256', 'tree_delta_sha256'):
            need(re.fullmatch(r'[0-9a-f]{64}', next_source[key]), 'sealed successor digest: ' + key)
    need('tests/nss-conn-transaction/run.py' in profile['test_files'] and
         all(name.startswith('tests/nss-conn-transaction/') for name in profile['test_files']),
         'exact reviewed connection test assets')
    for key in CONNECTION_COUNTS:
        need(type(profile[key]) is int and profile[key] > 0, 'reviewed connection test count: ' + key)
    return profile


def firmware_identity(profile):
    return profile.get('firmware_successor', {
        'commit': profile['source_commit'], 'manifest_sha256': profile['source_manifest_sha256'],
    })


def current_lock(profile):
    firmware = firmware_identity(profile)
    raw = base.path(ROOT, LOCK).read_text()
    need(lock_value(raw, 'SOURCE_COMMIT') == firmware['commit'] and
         lock_value(raw, 'SOURCE_QCA_NSS_DRV_PKG_RELEASE') == '29' and
         lock_value(raw, 'SOURCE_PATCHSET_MANIFEST_SHA256') == firmware['manifest_sha256'],
         'exact DRV29 firmware source, release and manifest lock')
    need(sha(base.path(ROOT, '.github/ax6-source-patchset.sha256').read_bytes()) ==
         firmware['manifest_sha256'], 'exact DRV29 firmware source manifest bytes')
    if 'firmware_successor' in profile:
        need(lock_value(raw, 'SOURCE_DRV29_ANCHOR_COMMIT') == profile['source_commit'],
             'exact source anchor for the userspace successor')


def git(source, *args):
    run = subprocess.run(['git', '-C', str(source), *args], capture_output=True, timeout=30)
    need(run.returncode == 0 and not run.stderr, 'git identity query: ' + ' '.join(args))
    return run.stdout


def check_parent(source, commit, parent):
    headers = git(source, 'cat-file', 'commit', commit).partition(b'\n\n')[0]
    need(re.findall(rb'^parent ([0-9a-f]{40})$', headers, re.M) == [parent.encode()], 'exact source parent')


def check_head(source, commit, parent):
    need(git(source, 'rev-parse', '--show-toplevel').decode().strip() == str(source), 'checkout root required')
    need(git(source, 'rev-parse', 'HEAD').strip() == commit.encode(), 'locked source commit')
    check_parent(source, commit, parent)


def check_firmware(source, profile):
    anchor = profile['source_commit']
    if 'firmware_successor' not in profile:
        check_head(source, anchor, profile['source_parent'])
        return

    successor = firmware_identity(profile)
    check_head(source, successor['commit'], anchor)
    check_parent(source, anchor, profile['source_parent'])
    raw = git(source, 'diff', '--no-ext-diff', '--raw', '--no-abbrev', '--no-renames',
              '-z', anchor, successor['commit'], '--')
    need(sha(raw) == successor['tree_delta_sha256'], 'exact userspace successor tree delta')
    fields = raw.split(b'\0')
    need(len(fields) > 1 and len(fields) % 2 == 1 and fields[-1] == b'', 'nonempty raw tree delta')
    for meta, name in zip(fields[:-1:2], fields[1:-1:2]):
        child = name.decode('ascii')
        need(re.fullmatch(r'[A-Za-z0-9_./+-]+', child) and
             not {'', '.', '..'}.intersection(child.split('/')) and
             (child in USERSPACE_FILES or child.startswith(USERSPACE_PATHS)),
             'only reviewed userspace paths: ' + child)
        mode = re.fullmatch(
            rb':(000000|100644|100755) (100644|100755) [0-9a-f]{40} [0-9a-f]{40} ([AM])', meta)
        need(mode and (mode.groups() == (b'000000', b'100644', b'A') or
             (mode[3] == b'M' and mode[1] == mode[2])),
             'only regular files without mode changes or new executables: ' + child)
        need(base.path(source, child).read_bytes() == git(source, 'show', successor['commit'] + ':' + child),
             'exact userspace working-tree bytes: ' + child)


def check_old_source(source, old):
    check_head(source, OLD_COMMIT, old['reviewed_source_ancestor'])
    need(not git(source, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--ignored=matching'),
         'immutable DRV27 source must be a clean dedicated checkout without ignored files')


def expectations(profile, old):
    prepared = {OLD_RELEASE: old['current_code_files'] | frozen.AUXILIARY}
    packages = old['patches'].copy()
    prior = prepared[OLD_RELEASE].copy()
    for step, name, patch_digest, path, postimage, inventory_digest in PRIOR:
        need(path in prior and name not in packages, 'fixed historical delta shape')
        prior = prior | {path: postimage}
        need(base.invhash(prior) == inventory_digest, 'audited historical inventory: %03d' % step)
        prepared[step] = prior
        packages[name] = patch_digest
    changed, added = profile['changed_files'], profile['added_files']
    need(changed and changed.keys() <= prior.keys() and not changed.keys() & frozen.AUXILIARY.keys() and
         all(prior[name] != digest for name, digest in changed.items()) and
         not added.keys() & prior.keys(), 'reviewed 033 delta shape')
    prepared[29] = prior | changed | added
    need(base.invhash(prepared[29]) == profile['inventory_sha256'], 'independent final inventory digest')
    packages[profile['patch_name']] = profile['patch_sha256']
    return prepared, packages


def test_inputs(source, profile):
    prior = {}
    for name in TEST_DIRS:
        parent = 'tests/' + name
        observed = base.inventory(source / parent)
        rows = {parent + '/' + child: digest for child, digest in observed.items()}
        if name == 'nss-conn-transaction':
            need(rows == profile['test_files'], 'exact reviewed connection test assets')
        else:
            prior.update(rows)
    need(base.invhash(prior) == PRIOR_TESTS_SHA256, 'immutable audited 030–032 test assets')


def command(output, result, label, argv, cwd=None, timeout=180):
    argv = [str(arg) for arg in argv]
    row = {'label': label, 'argv': argv}
    result['commands'].append(row)
    stdout, stderr = output / (label + '.stdout'), output / (label + '.stderr')
    with stdout.open('xb') as out, stderr.open('xb') as err:
        try:
            ran = subprocess.run(argv, cwd=cwd, stdout=out, stderr=err, timeout=timeout,
                                 env=dict(os.environ, LC_ALL='C', PYTHONDONTWRITEBYTECODE='1'))
            row['returncode'] = ran.returncode
        finally:
            row['stdout_sha256'] = sha(stdout.read_bytes())
            row['stderr_sha256'] = sha(stderr.read_bytes())
    need(ran.returncode == 0, label + ' failed; see ' + str(stderr))
    return stdout.read_bytes(), stderr.read_bytes()


def reverse(output, result, name, patch, source, target, before, expected, patch_tool):
    base.copy_code(source, target, before)
    # Apple patch does not report a successful offset in non-verbose mode.
    argv = [patch_tool, '-p1', '-R', '--batch', '--fuzz=0', '--verbose',
            '--remove-empty-files', '-V', 'none', '-i', patch]
    stdout, stderr = command(output, result, 'reverse-' + name[:3], argv, cwd=target, timeout=60)
    diagnostics = b'\n'.join(line for line in stdout.splitlines() if not line.startswith(b'|'))
    hunks = re.findall(rb'Hunk #[0-9]+ succeeded at [0-9]+[^\n]*', diagnostics)
    need(not stderr and not re.search(rb'offset|fuzz|failed|reject|malformed|skipping|ignoring', diagnostics, re.I) and
         len(hunks) == len(re.findall(rb'^@@ -', patch.read_bytes(), re.M)) and
         all(re.fullmatch(rb'Hunk #[0-9]+ succeeded at [0-9]+\.', hunk) for hunk in hunks),
         'exact patch reverse (no fuzz or offsets): ' + name)
    need(base.inventory(target) == expected, 'exact prepared reverse inventory: ' + name)


def historical_root(output, result, source, driver):
    # Run the original CLI with unchanged code/contracts, but an explicit,
    # isolated two-field lock. It still checks its original ancestry and release.
    workspace = output / 'frozen-root-executable'
    for name in FROZEN:
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base.path(ROOT, name), target)
    base.check(workspace, FROZEN)
    (workspace / LOCK).write_text(
        f'SOURCE_COMMIT={OLD_COMMIT}\nSOURCE_QCA_NSS_DRV_PKG_RELEASE={OLD_RELEASE}\n')
    argv = [sys.executable, '-B', workspace / '.github/scripts/verify-nss-root-host.py',
            '--source-root', source, '--driver', driver, '--output', output / 'root-host']
    command(output, result, 'frozen-drv27', argv)
    receipt = base.load(output / 'root-host/RESULTS.json')
    need(receipt['status'] == 'PASS_DRV27_SOURCE_AND_EXACT_DRV25_PREFIX_NOT_NATIVE_OR_RUNTIME' and
         receipt['actual_locked_source_commit'] == OLD_COMMIT and
         receipt['actual_build_lock_sha256'] == sha((workspace / LOCK).read_bytes()), 'frozen DRV27 receipt')


def run_tests(output, result, source, driver, trees, kernel, cc, profile):
    python = [sys.executable, '-B']
    tests = output / 'host-test-inputs' / 'tests'
    tests.mkdir(parents=True)
    for name in TEST_DIRS:
        original = source / 'tests' / name
        base.copy_code(original, tests / name, base.inventory(original))
    test_inputs(tests.parent, profile)
    need(sha(base.path(kernel, 'kernel/sysctl.c').read_bytes()) == KERNEL_SHA256,
         'coredump parser requires exact Linux 6.18.38 sysctl.c')
    stdout, stderr = command(output, result, 'connection-033',
                             python + [tests / 'nss-conn-transaction/run.py', '--source', driver,
                                       '--cc', cc, '--sanitize'])
    summary = 'PASS ' + ' '.join(f'{key}={profile[key]}' for key in CONNECTION_COUNTS)
    need(not stderr and stdout.decode().splitlines()[-1:] == [summary], 'complete connection host test matrix')
    command(output, result, 'probe-030', python + [
        tests / 'nss-probe-allocation/run.py', '--baseline', trees[27], '--candidate', driver,
        '--output', output / 'probe-030', '--cc', cc])
    command(output, result, 'coredump-031', python + [
        tests / 'nss-coredump-control/run.py', '--baseline', trees[27], '--candidate', driver,
        '--kernel', kernel, '--output', output / 'coredump-031', '--cc', cc])
    command(output, result, 'pdata-032', python + [
        tests / 'nss-pdata-ownership/run.py', '--source', driver, '--baseline', trees[31],
        '--output', output / 'pdata-032', '--cc', cc, '--sanitize'])
    for receipt in ('probe-030/results.json', 'coredump-031/results.json', 'pdata-032/RESULTS.json'):
        need(base.load(output / receipt)['status'] == 'PASS', 'actual historical host receipt: ' + receipt)
    test_inputs(tests.parent, profile)


def validate(args, profile):
    for root in (args.source_root, args.driver, args.drv27_source_root, args.kernel):
        need(root.is_dir() and not root.is_symlink(), 'regular input directory: ' + str(root))
    source, driver, old_source, kernel = (p.resolve() for p in
                                           (args.source_root, args.driver, args.drv27_source_root, args.kernel))
    output = args.output.resolve()
    need(not args.output.is_symlink() and not output.exists() and all(
        p != output and p not in output.parents and output not in p.parents
        for p in (source, driver, old_source, kernel)), 'fresh output outside all source inputs')
    output.mkdir(parents=True, exist_ok=False)
    result = {'status': 'FAIL', 'scope': 'SOURCE_AND_HOST_ONLY_NO_TARGET_RUNTIME_OR_FW_RETIREMENT',
              'source_commit': firmware_identity(profile)['commit'], 'driver_anchor': profile['source_commit'],
              'old_source_commit': OLD_COMMIT,
              'old_driver_release': OLD_RELEASE, 'profile_sha256': PROFILE_SHA256, 'commands': []}
    try:
        old = frozen.configuration()
        check_firmware(source, profile)
        check_old_source(old_source, old)
        prepared, patches = expectations(profile, old)
        package = source / PACKAGE
        need(sha(base.path(package, 'Makefile').read_bytes()) == RECIPE_SHA256, 'exact DRV29 recipe')
        need(base.inventory(package / 'patches') == patches, 'exact DRV29 package patch inputs')
        test_inputs(source, profile)
        code, metadata = base.prepared_partition(driver, output, 'driver', prepared[29])
        need(code == prepared[29], 'actual DRV29 differs from reviewed independent inventory')
        trees = {29: driver}
        previous = 29
        order = [profile['patch_name'], *(row[1] for row in reversed(PRIOR))]
        for name, step in zip(order, (32, 31, 30, OLD_RELEASE)):
            trees[step] = output / ('driver27-prefix' if step == OLD_RELEASE else 'after-%03d' % step)
            patch = base.path(package, 'patches/' + name)
            need(sha(patch.read_bytes()) == patches[name], 'stable patch input: ' + name)
            reverse(output, result, name, patch, trees[previous], trees[step],
                    prepared[previous], prepared[step], args.patch)
            previous = step
        run_tests(output, result, source, driver, trees, kernel, args.cc, profile)
        historical_root(output, result, old_source, trees[OLD_RELEASE])
        test_inputs(source, profile)
        for stage, tree in trees.items():
            actual = base.partition(driver) if stage == 29 else (base.inventory(tree), {})
            need(actual == (prepared[stage], metadata if stage == 29 else {}), 'prepared source end stability')
        need(sha(base.path(package, 'Makefile').read_bytes()) == RECIPE_SHA256 and
             base.inventory(package / 'patches') == patches, 'package input end stability')
        check_firmware(source, profile)
        check_old_source(old_source, old)
        current_lock(profile)
        base.check(ROOT, FROZEN)
        result.update(status='PASS_DRV29_HOST_AND_FROZEN_DRV27_PREFIX_NOT_TARGET_OR_RUNTIME',
                      inventory_sha256=profile['inventory_sha256'],
                      drv27_receipt_sha256=sha((output / 'root-host/RESULTS.json').read_bytes()))
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        (output / 'RESULTS.json').write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-lock', action='store_true')
    mode.add_argument('--check-source', action='store_true')
    mode.add_argument('--print-anchor', action='store_true')
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--driver', type=Path)
    parser.add_argument('--drv27-source-root', type=Path)
    parser.add_argument('--kernel', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--patch', default='patch')
    args = parser.parse_args()
    profile = configuration()
    current_lock(profile)
    if args.print_anchor:
        print(profile['source_commit'])
    elif args.check_source:
        if args.source_root is None:
            parser.error('source root is required')
        check_firmware(args.source_root.resolve(), profile)
        print('PASS: exact firmware source and DRV29 anchor')
    elif not args.check_lock:
        if not all((args.source_root, args.driver, args.drv27_source_root, args.kernel, args.output)):
            parser.error('source root, driver, DRV27 source root, kernel and output are required')
        validate(args, profile)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        sys.exit('DRV29 gate: ' + str(error))
