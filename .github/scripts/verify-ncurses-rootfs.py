#!/usr/bin/env python3
"""Bind the selected ncurses/terminfo update to actual IPK/index/rootfs data."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess

spec = importlib.util.spec_from_file_location('ncurses_package_helpers', Path(__file__).with_name('verify-vlmcsd-rootfs.py'))
helpers = importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)
V = helpers.V
need, sha = V.require, V.sha
VERSION = '6.6.20260801-r2'
NAMES = ('libncurses6', 'terminfo')
LIBRARIES = tuple('usr/lib/lib' + name + 'w.so.6.6' for name in ('ncurses', 'panel', 'menu', 'form'))


def verify(packages, status, listing, rootcat):
    need(set(packages) == set(NAMES), 'exact ncurses and terminfo package set')
    records = V.ART.fields(status)
    names = [r.get('Package') for r in records]
    need(all(names) and len(names) == len(set(names)), 'missing/duplicate status package')
    installed = {r['Package']: r for r in records}
    results = {}
    for name in NAMES:
        package = packages[name]
        control, payload = package['control'], package['payload']
        need(name in installed, 'selected ncurses package missing')
        actual = installed[name]
        helpers.healthy_status(actual.get('Status', ''))
        need(control.get('Package') == name and control.get('Version') == actual.get('Version') == VERSION,
             'ncurses update version differs')
        need(control.get('Architecture') == actual.get('Architecture') == 'aarch64_cortex-a53', 'ncurses architecture differs')
        for field in ('Depends', 'Pre-Depends', 'Provides', 'Conflicts', 'Replaces'):
            need(V.dependency_atoms(control.get(field, '')) == V.dependency_atoms(actual.get(field, '')), 'ncurses status/control ' + field)
        need(payload, 'empty ncurses payload')
        entries = V.listing_entries(listing, set(payload))
        files = []
        for path, (member, data) in payload.items():
            V.safe_listing_path(path)
            need(member.isfile() or member.isdir() or member.issym(), 'unsupported ncurses payload type')
            entry = entries[path]
            typ = 'd' if member.isdir() else 'l' if member.issym() else '-'
            need(entry['type'] == typ, 'ncurses rootfs type differs: ' + path)
            if not member.isdir():
                need(entry['mode'] == member.mode, 'ncurses rootfs mode differs: ' + path)
            if member.issym():
                V.safe_listing_path(member.linkname)
                need(entry['target'] == member.linkname, 'ncurses link target differs: ' + path)
            elif member.isfile():
                need(entry['size'] == len(data) and rootcat(path) == data, 'ncurses actual rootfs/IPK bytes differ: ' + path)
            files.append({'path': path, 'type': typ, 'mode': oct(member.mode),
                          'sha256': sha(data) if data is not None else None,
                          'link': member.linkname if member.issym() else None})
        if name == 'libncurses6':
            for path in LIBRARIES:
                need(path in payload and payload[path][0].isfile(), 'expected ncurses ABI6 library missing')
                binary = payload[path][1]
                need(len(binary) >= 64 and binary[:7] == b'\x7fELF\x02\x01\x01' and
                     struct.unpack_from('<H', binary, 16)[0] == 3 and struct.unpack_from('<H', binary, 18)[0] == 183,
                     'ncurses library is not AArch64 ELF64 ET_DYN')
        else:
            need('usr/share/terminfo/x/xterm-256color' in payload, 'default terminfo database missing')
        results[name] = {'version': VERSION, 'ipk_sha256': package.get('sha256'),
                         'index_sha256': package.get('index_sha256'), 'payloads': files}
    return {'status': 'PASS_NCURSES_IPK_INDEX_ROOTFS_BYTES_ONLY', 'packages': results,
            'limits': ['ELF header identity is not full dynamic symbol ABI or target execution',
                       'No terminal interaction/performance qualification', 'Shared parent directory modes are not package-owned']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--packages-root', type=Path, required=True)
    parser.add_argument('--retain-packages', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--unsquashfs', default='unsquashfs')
    args = parser.parse_args()
    result = {'status': 'INCOMPLETE', 'runtime_approved': False}
    try:
        need(args.rootfs.is_file() and not args.rootfs.is_symlink(), 'regular actual rootfs required')
        packages = V.selected_ipks(args.packages_root, NAMES)
        for name in NAMES:
            helpers.retain(packages[name], args.retain_packages / name)

        def command(*arguments):
            process = subprocess.run([args.unsquashfs, *map(str, arguments)], capture_output=True, timeout=90,
                                     env={**os.environ, 'LC_ALL': 'C'})
            need(process.returncode == 0 and not process.stderr, 'unsquashfs read failed')
            return process.stdout

        rootcat = lambda path: command('-cat', args.rootfs, path)
        result.update(verify(packages, rootcat('usr/lib/opkg/status').decode(), command('-ll', args.rootfs).decode(), rootcat))
        result['rootfs_sha256'] = sha(args.rootfs.read_bytes())
    except Exception as error:
        result['error'] = str(error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], **({'error': result['error']} if 'error' in result else {})}))
    return 0 if result['status'] == 'PASS_NCURSES_IPK_INDEX_ROOTFS_BYTES_ONLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
