#!/usr/bin/env python3
"""Bind actual DRV27 source, preserving an exact historical command-test prefix."""
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
PROFILE = ROOT / '.github/ax6-nss-root-host-contract.json'
PROFILE_SHA256 = 'f89e893bcc21b23be67c0d8afd5dae80c5bd4817b74ddb213569586e5890200c'
spec = importlib.util.spec_from_file_location('root_host_frozen_helpers', ROOT / '.github/scripts/verify-ax6-current-layers.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
need, sha = base.need, base.sha
PACKAGE = 'package/qca-nss/qca-nss-drv'
PATCHES = ('029-root-producer-diagnostic-host-transaction.patch', '028-meminfo-cold-init-transaction.patch')
AUXILIARY = {'nss_init.c.orig': 'f4c1b47f418282d49ff8ac7b1dd89dfdaef041f16442dbe3e5b4e9ec068ee020'}


def configuration():
    need(sha(PROFILE.read_bytes()) == PROFILE_SHA256, 'frozen root-host contract bytes')
    data = base.load(PROFILE)
    need(type(data['schema']) is int and data['schema'] == 1 and data['frozen'] is True and
         data['profile'] == 'DRV27_BOUNDED_ROOT_HOST_WITH_EXACT_DRV25_PREFIX', 'fixed root-host profile')
    need(data['reviewed_inventory_sha256'] == '669d166be5cfbfc06cb0c5c5cd64fed7881df642d7e4eaabbd3976ae8c35e26e', 'reviewed root inventory identity')
    need(data['reviewed_source_ancestor'] == '4245760179a1fbf2a0ce35cc4e6f21fc49b642cc' and
         data['vendor_pin'] == '6aa14c78e097b29c493ff2fef87e4d35906b2b5a', 'reviewed source ancestry and pin')
    need(data['recipe_sha256'] == 'e8f72b752333919b7caa708b943620cc2ddabda345b2fc46b544e598366eae4f' and
         type(data['driver_release']) is int and data['driver_release'] == 27, 'root recipe identity')
    need(len(data['current_code_files']) == 484 and len(data['prefix25_code_files']) == 480 and
         len(data['patches']) == 27, 'exact reviewed source sets')
    need(data['exact_noncompiled_auxiliary'] == AUXILIARY and data['reverse_order'] == list(PATCHES), 'exact backup and reverse policy')
    need(data['patches'][PATCHES[0]] == '57dac5d6bed3f25cdb5dd310a7187bb4673e65de270d2fd4f547c66b169dda2c' and
         data['patches'][PATCHES[1]] == 'cf2f5cb1bd5854accada3beff0f074c59f7a345158d6b68963f5ce2fd30c9f3f', 'accepted patch identities')
    prior = data['prefix25_code_files'] | AUXILIARY
    need(base.invhash(prior) == data['legacy_driver_inventory_sha256'] ==
         '8725c8ee568d698941659db9ac546c165b7817cb4787d8fe73ea163ecc19f4ce', 'immutable historical prefix')
    return data


def lock_identity():
    raw = (ROOT / '.github/ax6-nss-lock.env').read_text()
    def one(name):
        rows = re.findall(r'^' + re.escape(name) + r'=(\S+)$', raw, re.M)
        need(len(rows) == 1, 'one lock key: ' + name)
        return rows[0]
    commit = one('SOURCE_COMMIT')
    need(re.fullmatch('[0-9a-f]{40}', commit) is not None, 'fixed source lock')
    need(one('SOURCE_QCA_NSS_DRV_PKG_RELEASE') == '27', 'actual driver release lock')
    return commit


def prepare_prefix(source, driver, output, data):
    """Copy verified data, then reverse only owned patches; never modify input."""
    output.mkdir(parents=True, exist_ok=False)
    result = {'status': 'INCOMPLETE', 'scope': 'ACTUAL_SOURCE_AND_EXACT_HISTORICAL_PREFIX_ONLY',
              'native_or_target_or_runtime_approved': False, 'commands': []}
    owned = {p: sha(p.read_bytes()) for p in (PROFILE, Path(__file__), base.CONTRACT, base.BASE_NSS)}
    try:
        package = source / PACKAGE
        need(sha(base.path(package, 'Makefile').read_bytes()) == data['recipe_sha256'], 'actual root recipe')
        need(base.inventory(package / 'patches') == data['patches'], 'actual 27 patch inputs')
        expected = data['current_code_files'] | AUXILIARY
        code, metadata = base.prepared_partition(driver, output, 'driver', expected)
        need(code == expected, 'actual reviewed484 plus one fixed backup; no wildcard metadata')
        current = output / 'current-driver27'
        prefix = output / 'driver25-prefix'
        base.copy_code(driver, current, code)
        base.copy_code(driver, prefix, code)
        for name in PATCHES:
            patch = base.path(package / 'patches', name)
            argv = ['patch', '-p1', '-R', '--batch', '--fuzz=0', '--remove-empty-files', '-V', 'none', '-i', str(patch)]
            process = subprocess.run(argv, cwd=prefix, capture_output=True, timeout=60,
                                     env=dict(os.environ, LC_ALL='C'))
            (output / (name + '.stdout')).write_bytes(process.stdout)
            (output / (name + '.stderr')).write_bytes(process.stderr)
            result['commands'].append({'argv': argv, 'returncode': process.returncode,
                                       'stdout_sha256': sha(process.stdout), 'stderr_sha256': sha(process.stderr)})
            need(process.returncode == 0 and not process.stderr and
                 not re.search(rb'offset|fuzz|FAILED|reject|malformed|Reversed', process.stdout, re.I), 'exact reviewed patch reverse: ' + name)
        expected_prefix = data['prefix25_code_files'] | AUXILIARY
        need(base.inventory(prefix) == expected_prefix and base.invhash(expected_prefix) == data['legacy_driver_inventory_sha256'], 'full immutable DRV25 prefix')
        need(base.inventory(current) == code and base.partition(driver) == (code, metadata), 'actual prepared input unchanged')
        need(base.inventory(package / 'patches') == data['patches'], 'source patch end stability')
        need(all(sha(p.read_bytes()) == digest for p, digest in owned.items()), 'fixed gate end stability')
        result.update(status='PASS_DRV27_SOURCE_AND_EXACT_DRV25_PREFIX_NOT_NATIVE_OR_RUNTIME',
                      actual_code_files=484, exact_noncompiled_backup_files=AUXILIARY,
                      actual_recipe_metadata=metadata, prefix_files=481, prefix_inventory_sha256=base.invhash(expected_prefix),
                      reviewed_inventory_sha256=data['reviewed_inventory_sha256'],
                      current_tree=str(current), historical_prefix_tree=str(prefix))
    except Exception as error:
        result['status'] = 'FAIL'
        result['error'] = str(error)
        raise
    finally:
        (output / 'RESULTS.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, driver, output = args.source_root.resolve(), args.driver.resolve(), args.output.resolve()
    need(not args.source_root.is_symlink() and not args.driver.is_symlink() and not args.output.is_symlink(), 'regular input roots')
    need(not output.exists() and all(p != output and p not in output.parents for p in (source, driver)), 'fresh output outside source inputs')
    data = configuration()
    expected = lock_identity()
    head = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=30)
    need(head.returncode == 0 and not head.stderr and head.stdout.strip() == expected, 'actual source matches new build lock')
    ancestry = subprocess.run(['git', '-C', str(source), 'cat-file', '-p', expected], capture_output=True, text=True, timeout=30)
    parents = re.findall(r'^parent ([0-9a-f]{40})$', ancestry.stdout.split('\n\n', 1)[0], re.M)
    need(ancestry.returncode == 0 and not ancestry.stderr and parents == [data['reviewed_source_ancestor']], 'reviewed source direct parent (works with shallow checkout)')
    result = prepare_prefix(source, driver, output, data)
    try:
        end = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=30)
        need(end.returncode == 0 and not end.stderr and end.stdout.strip() == expected and lock_identity() == expected, 'source and lock end stability')
        result['actual_locked_source_commit'] = expected
        result['actual_build_lock_sha256'] = sha((ROOT / '.github/ax6-nss-lock.env').read_bytes())
    except Exception as error:
        result.update(status='FAIL', error=str(error))
        raise
    finally:
        (output / 'RESULTS.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'actual_code_files', 'prefix_files')}))


if __name__ == '__main__':
    main()
