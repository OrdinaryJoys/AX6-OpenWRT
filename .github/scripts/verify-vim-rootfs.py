#!/usr/bin/env python3
"""Bind the two security-backported Vim IPKs to an existing SquashFS, read-only.

No filesystem extraction, installation or execution of target files. ELF checking
here is identity only, not full ELF/ABI validation or proof of exploit resistance.
"""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import importlib.util
import gzip
import json
import os
from pathlib import Path
import re
import struct
import subprocess

SPEC = importlib.util.spec_from_file_location('ax6_artifact_checks',
                                             Path(__file__).with_name('verify-ax6-artifacts.py'))
ART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ART)
Invalid, require, sha = ART.Invalid, ART.require, ART.sha
VERSION = '9.2.1014-r2'
PACKAGES = ('vim-fuller', 'vim-runtime')
LEGACY = ('vim', 'vim-full')
XXD_VERSION = '2026.06.16-r2'


def safe_listing_path(value):
    require(value and not value.startswith('-') and ' -> ' not in value and
            not any(ord(c) < 32 or ord(c) == 127 for c in value), 'unsafe listing path/target')
    return value


def permission_bits(text):
    require(re.fullmatch(r'[dl-][rwxstST-]{9}', text) is not None, 'unsupported listing type/mode')
    mode = 0
    for i, token in enumerate(text[1:]):
        if i % 3 == 0:
            require(token in 'r-', 'malformed read permission')
            enabled = token == 'r'
        elif i % 3 == 1:
            require(token in 'w-', 'malformed write permission')
            enabled = token == 'w'
        else:
            allowed = 'x-sS' if i < 8 else 'x-tT'
            require(token in allowed, 'malformed execute permission')
            enabled = token in 'xst'
            if token in 'sStT':
                mode |= (0o4000, 0o2000, 0o1000)[i // 3]
        if enabled:
            mode |= 1 << (8 - i)
    return mode


def listing_entries(text, wanted):
    """Parse only exact wanted virtual paths; links are never resolved on host."""
    result = {}
    pattern = re.compile(r'^([dl-][rwxstST-]{9})\s+\S+\s+([0-9]+)\s+'
                         r'[0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}\s+(.+)$')
    for line in text.splitlines():
        match = pattern.fullmatch(line)
        if not match:
            continue
        mode, size, printed = match.groups()
        prefix = 'squashfs-root/'
        if not printed.startswith(prefix):
            continue
        path, arrow, target = printed[len(prefix):].partition(' -> ')
        if path not in wanted:
            continue
        safe_listing_path(path)
        require(path not in result, 'duplicate rootfs listing entry: ' + path)
        require((mode[0] == 'l') == bool(arrow), 'malformed symlink listing: ' + path)
        if arrow:
            safe_listing_path(target)
        result[path] = {'type': mode[0], 'mode': permission_bits(mode),
                        'size': int(size), 'target': target if arrow else None}
    require(set(result) == set(wanted), 'rootfs payload missing/unparseable: ' +
            ', '.join(sorted(set(wanted) - set(result))[:8]))
    return result


def exact_runtime_dependency(value):
    clauses = [x.strip() for x in value.split(',')]
    matches = [x for x in clauses if re.search(r'(?<![A-Za-z0-9_.+-])vim-runtime(?![A-Za-z0-9_.+-])', x)]
    # BuildPackage emits both DEPENDS (+vim-runtime) and EXTRA_DEPENDS (=version).
    # Their comma-separated conjunction retains the exact pin. Permit this one
    # known redundant bare clause, never alternatives or a second constraint.
    constrained = [x for x in matches if x != 'vim-runtime']
    require(len(constrained) == 1 and len(matches) - len(constrained) <= 1 and
            re.fullmatch(r'vim-runtime\s*\(=\s*' + re.escape(VERSION) + r'\)', constrained[0]),
            'vim-fuller must have one exact vim-runtime (= ' + VERSION + ') dependency')


def selected_ipks(directory, names=PACKAGES):
    root = Path(directory)
    require(root.is_dir() and not root.is_symlink(), 'packages-root is not a regular directory')
    result = {}
    for name in names:
        candidates = sorted(root.rglob(name + '_*.ipk'))
        require(len(candidates) == 1, 'expected exactly one actual ' + name + ' IPK')
        path = candidates[0]
        require(path.is_file() and not path.is_symlink(), 'IPK is not a regular file: ' + str(path))
        for relative_parent in path.relative_to(root).parents:
            require(not (root / relative_parent).is_symlink(), 'IPK has symlink parent')
        blob = path.read_bytes()
        control, payload = ART.read_ipk(blob)
        require(control.get('Package') == name, 'IPK filename/control package mismatch')
        index = path.parent / 'Packages'
        require(index.is_file() and not index.is_symlink(), 'original regular Packages index missing')
        raw_index = index.read_bytes()
        compressed = path.parent / 'Packages.gz'
        if compressed.exists() or compressed.is_symlink():
            require(compressed.is_file() and not compressed.is_symlink(), 'Packages.gz is not a regular file')
            require(gzip.decompress(compressed.read_bytes()) == raw_index, 'Packages.gz differs from Packages')
        # Only selected records/IPKs are materialized; do not decode every IPK
        # in a potentially large feed just to audit two or three Vim packages.
        records = ART.fields(raw_index.decode('utf-8'))
        selected = [r for r in records if r.get('Package') == name]
        require(len(selected) == 1, 'missing/duplicate Vim package index record: ' + name)
        record = selected[0]
        require(record.get('Filename') == path.name and
                sum(r.get('Filename') == path.name for r in records) == 1, 'index Filename differs/duplicated')
        require(re.fullmatch(r'[1-9][0-9]*', record.get('Size', '')) and
                int(record['Size']) == len(blob), 'index Size differs')
        require(re.fullmatch(r'[0-9a-f]{64}', record.get('SHA256sum', '')) and
                record['SHA256sum'] == sha(blob), 'index SHA256 differs')
        for field in ('Package', 'Version', 'Architecture'):
            require(record.get(field) and record[field] == control.get(field), 'index/control ' + field + ' differs')
        for field in ('Depends', 'Pre-Depends', 'Provides', 'Conflicts', 'Replaces'):
            require(' '.join(record.get(field, '').split()) == ' '.join(control.get(field, '').split()),
                    'index/control ' + field + ' differs')
        result[name] = {'control': control, 'payload': payload, 'path': str(path), 'sha256': sha(blob),
                        'index_path': str(index), 'index_sha256': sha(raw_index)}
    return result


def installed_records(status):
    installed, all_names = {}, set()
    for record in ART.fields(status):
        name = record.get('Package')
        require(name and name not in all_names, 'missing/duplicate status package')
        all_names.add(name)
        state = record.get('Status', '').split()
        if name in (*PACKAGES, *LEGACY, 'xxd'):
            require(len(state) == 3, 'malformed targeted package status')
            if name == 'xxd':
                require(state[-1] in ('installed', 'not-installed', 'config-files'),
                        'xxd has unknown/partial install state')
        if state and state[-1] == 'installed':
            # Desired state/flags can say hold/user; the final token is the
            # actual installed state. Do not hide a held legacy provider.
            require(len(state) == 3, 'malformed installed package status')
            installed[name] = record
    return installed


def package_contract(packages, status):
    installed = installed_records(status)
    expected = set(PACKAGES) | ({'xxd'} if 'xxd' in installed else set())
    require(set(packages) == expected, 'selected package set differs (including optional xxd)')
    require(not set(LEGACY).intersection(installed), 'legacy vim/vim-full provider remains installed')
    require(set(PACKAGES) <= set(installed), 'required Vim package is not installed')
    arch = set()
    for name in packages:
        control, current = packages[name]['control'], installed[name]
        version = XXD_VERSION if name == 'xxd' else VERSION
        require(control.get('Package') == current['Package'] == name, 'package identity differs')
        require(control.get('Version') == current.get('Version') == version, 'Vim/xxd package version differs')
        require(control.get('Architecture') and control['Architecture'] == current.get('Architecture'),
                'Vim control/status architecture differs')
        arch.add(control['Architecture'])
        require(' '.join(control.get('Depends', '').split()) == ' '.join(current.get('Depends', '').split()),
                'Vim control/status dependency metadata differs')
    require(arch == {'aarch64_cortex-a53'}, 'Vim packages are not the expected AArch64 target architecture')
    exact_runtime_dependency(packages['vim-fuller']['control'].get('Depends', ''))
    exact_runtime_dependency(installed['vim-fuller'].get('Depends', ''))
    return installed


def payload_contract(packages):
    combined, owners = {}, {}
    for name in packages:
        require(packages[name]['payload'], 'empty Vim package payload: ' + name)
        for path, entry in packages[name]['payload'].items():
            safe_listing_path(path)
            member, _ = entry
            require(not member.islnk(), 'hardlink payload unsupported: ' + path)
            require(member.isfile() or member.isdir() or member.issym(), 'unsupported Vim payload type: ' + path)
            if member.issym():
                safe_listing_path(member.linkname)
            if path in combined:
                require(member.isdir() and combined[path][0].isdir(), 'payload is claimed by both Vim packages: ' + path)
            else:
                combined[path] = entry
            owners.setdefault(path, []).append(name)
    require('usr/bin/vim' in combined and combined['usr/bin/vim'][0].isfile() and
            combined['usr/bin/vim'][0].mode == 0o755 and owners['usr/bin/vim'] == ['vim-fuller'],
            'usr/bin/vim must be a regular 0755 vim-fuller payload')
    for name, path in [('vim-fuller', 'usr/bin/vim')] + ([('xxd', 'usr/bin/xxd')] if 'xxd' in packages else []):
        require(path in combined and combined[path][0].isfile() and combined[path][0].mode == 0o755 and
                owners[path] == [name], 'executable must be regular 0755 owned payload: ' + path)
        binary = combined[path][1]
        require(len(binary) >= 64 and binary[:7] == b'\x7fELF\x02\x01\x01' and
                struct.unpack_from('<H', binary, 16)[0] in (2, 3) and
                struct.unpack_from('<H', binary, 18)[0] == 183,
                'Vim/xxd is not an AArch64 little-endian ELF64 executable/PIE identity')
    return combined, owners


def verify_payload(packages, status, listing, rootcat):
    package_contract(packages, status)
    entries, owners = payload_contract(packages)
    actual = listing_entries(listing, set(entries))
    regular, reports = [], []
    for path, (member, data) in entries.items():
        found = actual[path]
        typ = 'd' if member.isdir() else 'l' if member.issym() else '-'
        require(found['type'] == typ, 'rootfs payload type differs: ' + path)
        # Shared parent directories can be installed by many packages; only
        # their directory type is bound. All files/links bind exact modes.
        if not member.isdir():
            require(found['mode'] == member.mode, 'rootfs payload mode differs: ' + path)
        if member.issym():
            require(found['target'] == member.linkname, 'rootfs symlink target differs: ' + path)
        elif member.isfile():
            require(found['size'] == len(data), 'rootfs payload size differs: ' + path)
            regular.append((path, data))
        reports.append({'path': path, 'owners': owners[path], 'type': typ,
                        'mode': oct(found['mode']), 'mode_bound': not member.isdir(),
                        'bytes': len(data) if data is not None else None,
                        'sha256': sha(data) if data is not None else None,
                        'symlink_target': member.linkname if member.issym() else None})
    def compare(item):
        path, expected = item
        require(rootcat(path) == expected, 'rootfs/IPK payload bytes differ: ' + path)
    # At most four cat processes and four outstanding jobs, even on failure.
    iterator = iter(regular)
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(compare, item) for _, item in zip(range(4), iterator)}
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            try:
                for task in done:
                    task.result()
                    item = next(iterator, None)
                    if item is not None:
                        pending.add(pool.submit(compare, item))
            except Exception:
                for task in pending:
                    task.cancel()
                raise
    return {'status': 'PASS_VIM_IPK_ROOTFS_BINDING_ONLY', 'version': VERSION,
            'packages': [{'name': name, 'ipk_path': packages[name].get('path'),
                          'ipk_sha256': packages[name].get('sha256'),
                          'index_path': packages[name].get('index_path'),
                          'index_sha256': packages[name].get('index_sha256'),
                          'version': packages[name]['control']['Version'],
                          'architecture': packages[name]['control']['Architecture']} for name in packages],
            'xxd_status': 'PASS_INDEX_IPK_ROOTFS_BOUND' if 'xxd' in packages else 'NOT_APPLICABLE_NOT_INSTALLED',
            'regular_files_checked': len(regular), 'regular_bytes_checked': sum(len(x[1]) for x in regular),
            'symlinks_checked': sum(x['type'] == 'l' for x in reports),
            'directories_type_checked': sum(x['type'] == 'd' for x in reports), 'payloads': reports,
            'limits': ['ELF identity only, not complete ELF/ABI or target execution',
                       'Payload binding does not independently prove security patches or exploit resistance',
                       'Shared directory type checked; shared directory modes are not package-owned']}


def audit(args):
    require(args.rootfs.is_file() and not args.rootfs.is_symlink(), 'rootfs is not a regular file')
    def command(*arguments):
        r = subprocess.run([str(args.unsquashfs), *map(str, arguments)], capture_output=True,
                           timeout=60, env={**os.environ, 'LC_ALL': 'C'})
        require(r.returncode == 0 and not r.stderr,
                'unsquashfs failed or diagnosed input: ' + r.stderr.decode(errors='replace')[:400])
        return r.stdout
    rootcat = lambda path: command('-cat', args.rootfs, path)
    status_text = rootcat('usr/lib/opkg/status').decode('utf-8')
    installed = installed_records(status_text)
    names = (*PACKAGES, 'xxd') if 'xxd' in installed else PACKAGES
    packages = selected_ipks(args.packages_root, names)
    result = verify_payload(packages, status_text,
                            command('-ll', args.rootfs).decode('utf-8'), rootcat)
    result['rootfs_sha256'] = sha(args.rootfs.read_bytes())
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rootfs', type=Path, required=True)
    p.add_argument('--packages-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--unsquashfs', default='unsquashfs')
    args = p.parse_args(argv)
    # Reserve before inspection. Existing files or dangling symlinks must never
    # be overwritten, including when the audit fails.
    try:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        print(json.dumps({'status': 'FAIL', 'error': 'output must be new: ' + str(error)}))
        return 1
    with os.fdopen(fd, 'w') as output:
        try:
            result = audit(args)
        except Exception as error:
            result = {'status': 'FAIL', 'error': str(error)}
        output.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'payloads'}, indent=2))
    return 0 if result['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    raise SystemExit(main())
