#!/usr/bin/env python3
"""Bind the scope-backported vlmcsd IPK and index to actual rootfs bytes.

Read-only host inspection. Nothing from a package or image is executed.
ELF identity is not complete ABI, exploit-resistance or runtime qualification.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess

SPEC = importlib.util.spec_from_file_location(
    'ax6_vim_payload', Path(__file__).with_name('verify-vim-rootfs.py'))
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)
require, sha = V.require, V.sha
VERSION = '2020.03.30~e5990804-r9'
PACKAGE = 'vlmcsd'
BINARY = 'usr/bin/vlmcsd'


def healthy_status(value):
    # opkg80503d94 pkg.c serializes want, ordered flag list, then status.
    # A final selected image package must not be pending removal/reinstallation
    # or the obsolete member of an upgrade pair. Hold/user are flags, not want.
    state = value.split()
    require(len(state) == 3 and state[0] == 'install' and state[2] == 'installed',
            'vlmcsd is not a healthy final installed package')
    if state[1] == 'ok':
        return
    flags = state[1].split(',')
    order = ('hold', 'noprune', 'prefer', 'user')
    require(flags and len(set(flags)) == len(flags) and set(flags) <= set(order) and
            flags == [f for f in order if f in flags], 'vlmcsd has unknown/abnormal package flags')


def verify(package, status, listing, rootcat):
    control, payload = package['control'], package['payload']
    records = V.ART.fields(status)
    names = [r.get('Package') for r in records]
    require(all(names) and len(set(names)) == len(names), 'missing/duplicate status package')
    chosen = [r for r in records if r.get('Package') == PACKAGE]
    require(len(chosen) == 1, 'vlmcsd status record missing')
    installed = chosen[0]
    healthy_status(installed.get('Status', ''))
    require(control.get('Package') == PACKAGE and
            control.get('Version') == installed.get('Version') == VERSION,
            'vlmcsd scope-backport version differs')
    require(control.get('Architecture') == installed.get('Architecture') == 'aarch64_cortex-a53',
            'vlmcsd architecture differs')
    for field in ('Depends', 'Pre-Depends', 'Provides', 'Conflicts', 'Replaces'):
        require(V.dependency_atoms(control.get(field, '')) ==
                V.dependency_atoms(installed.get(field, '')), 'vlmcsd status/control ' + field)
    require(payload and BINARY in payload, 'vlmcsd binary payload missing')
    binary_info, binary = payload[BINARY]
    require(binary_info.isfile() and binary_info.mode == 0o755, 'vlmcsd binary type/mode differs')
    require(len(binary) >= 64 and binary[:7] == b'\x7fELF\x02\x01\x01' and
            struct.unpack_from('<H', binary, 16)[0] in (2, 3) and
            struct.unpack_from('<H', binary, 18)[0] == 183, 'vlmcsd is not AArch64 ELF64 identity')
    actual = V.listing_entries(listing, set(payload))
    files = []
    for path, (member, data) in payload.items():
        V.safe_listing_path(path)
        require(member.isfile() or member.isdir() or member.issym(), 'unsupported vlmcsd payload type')
        entry = actual[path]
        typ = 'd' if member.isdir() else 'l' if member.issym() else '-'
        require(entry['type'] == typ, 'vlmcsd rootfs type differs: ' + path)
        if not member.isdir():
            require(entry['mode'] == member.mode, 'vlmcsd rootfs mode differs: ' + path)
        if member.issym():
            V.safe_listing_path(member.linkname)
            require(entry['target'] == member.linkname, 'vlmcsd rootfs link differs: ' + path)
        elif member.isfile():
            require(entry['size'] == len(data) and rootcat(path) == data,
                    'vlmcsd rootfs/IPK bytes differ: ' + path)
        files.append({'path': path, 'type': typ, 'mode': oct(member.mode),
                      'sha256': sha(data) if data is not None else None,
                      'link': member.linkname if member.issym() else None})
    return {'status': 'PASS_VLMCSD_IPK_ROOTFS_BINDING_ONLY', 'version': VERSION,
            'ipk_sha256': package.get('sha256'), 'index_sha256': package.get('index_sha256'),
            'binary_sha256': sha(binary), 'payloads': files,
            'limits': ['Source scope proof is separate from binary identity and payload binding',
                       'No target execution, full ABI or runtime/performance acceptance',
                       'Shared parent directory modes are not package-owned']}


def audit(args):
    require(args.rootfs.is_file() and not args.rootfs.is_symlink(), 'rootfs is not a regular file')
    def command(*arguments):
        result = subprocess.run([str(args.unsquashfs), *map(str, arguments)], capture_output=True,
                                timeout=60, env={**os.environ, 'LC_ALL': 'C'})
        require(result.returncode == 0 and not result.stderr, 'unsquashfs failed/diagnosed input')
        return result.stdout
    rootcat = lambda path: command('-cat', args.rootfs, path)
    package = V.selected_ipks(args.packages_root, (PACKAGE,))[PACKAGE]
    if args.retain_packages:
        retain(package, args.retain_packages)
    result = verify(package, rootcat('usr/lib/opkg/status').decode(),
                    command('-ll', args.rootfs).decode(), rootcat)
    result['rootfs_sha256'] = sha(args.rootfs.read_bytes())
    return result


def retain(package, output):
    """Preserve original selected package/index bytes for independent inspection."""
    output.mkdir(parents=True, exist_ok=False)
    paths = [Path(package['path']), Path(package['index_path'])]
    compressed = paths[1].with_name('Packages.gz')
    if compressed.exists():
        paths.append(compressed)
    entries = []
    for source in paths:
        require(source.is_file() and not source.is_symlink(), 'retained input is not regular')
        data = source.read_bytes()
        expected = package['sha256'] if source == paths[0] else package['index_sha256']
        if source != compressed:
            require(sha(data) == expected, 'input changed before evidence copy')
        target = output / source.name
        with target.open('xb') as stream:
            stream.write(data)
        entries.append({'original': str(source), 'name': source.name, 'sha256': sha(data)})
    # Reuse the strict index/IPK reader on the retained copy as well.
    checked = V.selected_ipks(output, (PACKAGE,))[PACKAGE]
    require(checked['sha256'] == package['sha256'], 'retained package differs')
    with (output / 'INDEX.json').open('x') as stream:
        json.dump({'status': 'ORIGINAL_INPUTS_RETAINED_NOT_ROOTFS_ACCEPTANCE', 'files': entries}, stream, indent=2)
        stream.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--packages-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--unsquashfs', default='unsquashfs')
    parser.add_argument('--retain-packages', type=Path)
    args = parser.parse_args(argv)
    try:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        print(json.dumps({'status': 'FAIL', 'error': 'new output required: ' + str(error)}))
        return 1
    with os.fdopen(fd, 'w') as stream:
        try:
            result = audit(args)
        except Exception as error:
            result = {'status': 'FAIL', 'error': str(error)}
        stream.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'payloads'}))
    return 0 if result['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    raise SystemExit(main())
