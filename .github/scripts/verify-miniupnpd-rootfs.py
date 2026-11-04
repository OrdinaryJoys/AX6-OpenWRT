#!/usr/bin/env python3
"""Bind the selected UPnP daemon/index/IPK to final image bytes without execution."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess

SPEC = importlib.util.spec_from_file_location('mini_payload', Path(__file__).with_name('verify-vim-rootfs.py'))
V = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(V)
require, sha = V.require, V.sha
PACKAGE, VERSION, BINARY = 'miniupnpd-nftables', '2.3.11-r1', 'usr/sbin/miniupnpd'


def verify(package, status, listing, rootcat):
    records = V.ART.fields(status)
    names = [r.get('Package') for r in records]
    require(all(names) and len(names) == len(set(names)), 'UPnP duplicate package status')
    chosen = [r for r in records if r.get('Package') == PACKAGE]
    require(len(chosen) == 1 and not any(r.get('Package') == 'miniupnpd-iptables' for r in records),
            'UPnP nftables package selection')
    installed, control = chosen[0], package['control']
    state = installed.get('Status', '').split()
    require(len(state) == 3 and state[0] == 'install' and state[2] == 'installed' and
            state[1] in ('ok', 'hold'), 'UPnP installed state')
    require(control.get('Package') == PACKAGE and control.get('Version') == installed.get('Version') == VERSION,
            'UPnP selected stable version')
    require(control.get('Architecture') == installed.get('Architecture') == 'aarch64_cortex-a53', 'UPnP architecture')
    for field in ('Depends', 'Pre-Depends', 'Provides', 'Conflicts', 'Replaces'):
        require(V.dependency_atoms(control.get(field, '')) == V.dependency_atoms(installed.get(field, '')),
                'UPnP dependency metadata ' + field)
    payload = package['payload']; require(BINARY in payload, 'UPnP executable payload')
    header, binary = payload[BINARY]
    require(header.isfile() and header.mode == 0o755 and len(binary) >= 64 and
            binary[:7] == b'\x7fELF\x02\x01\x01' and struct.unpack_from('<H', binary, 18)[0] == 183,
            'UPnP AArch64 ELF identity')
    require(struct.unpack_from('<H', binary, 16)[0] in (2, 3), 'UPnP executable ELF type')
    actual = V.listing_entries(listing, set(payload)); rows = []
    for path, (member, raw) in payload.items():
        V.safe_listing_path(path)
        require(member.isfile() or member.isdir() or member.issym(), 'UPnP payload type')
        entry = actual[path]
        kind = 'd' if member.isdir() else 'l' if member.issym() else '-'
        require(entry['type'] == kind, 'UPnP rootfs member type')
        if not member.isdir(): require(entry['mode'] == member.mode, 'UPnP rootfs member mode')
        if member.isfile():
            require(entry['size'] == len(raw) and rootcat(path) == raw, 'UPnP IPK/rootfs member bytes:' + path)
        if member.issym():
            V.safe_listing_path(member.linkname)
            require(entry['target'] == member.linkname, 'UPnP rootfs link')
        rows.append({'path': path, 'type': kind, 'sha256': sha(raw) if raw is not None else None})
    return {'status': 'PASS_MINIUPNPD_IPK_ROOTFS_ONLY', 'version': VERSION, 'payload': rows,
            'ipk_sha256': package['sha256'], 'binary_sha256': sha(binary),
            'runtime_approved': False, 'limits': 'No target execution, firewall, full ABI or performance proof'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--packages-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--retain', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists() and not args.retain.exists(), 'fresh UPnP evidence')
    args.retain.mkdir(parents=True)
    report = {'status': 'INCOMPLETE'}
    try:
        require(args.rootfs.is_file() and not args.rootfs.is_symlink(), 'regular UPnP rootfs input')
        def command(*argv):
            p = subprocess.run(['unsquashfs', *map(str, argv)], capture_output=True, timeout=90,
                               env=dict(os.environ, LC_ALL='C'))
            require(p.returncode == 0 and not p.stderr, 'UPnP unsquashfs read')
            return p.stdout
        package = V.selected_ipks(args.packages_root, (PACKAGE,))[PACKAGE]
        original_index = Path(package['index_path'])
        for source in [Path(package['path']), original_index, original_index.with_name('Packages.gz')]:
            if source.exists():
                require(source.is_file() and not source.is_symlink(), 'UPnP retained file')
                raw = source.read_bytes()
                if source == Path(package['path']): require(sha(raw) == package['sha256'], 'UPnP IPK input stability')
                if source == original_index: require(sha(raw) == package['index_sha256'], 'UPnP index input stability')
                (args.retain / source.name).write_bytes(raw)
        saved = V.selected_ipks(args.retain, (PACKAGE,))[PACKAGE]
        require(saved['sha256'] == package['sha256'], 'UPnP retained original IPK')
        rootcat = lambda name: command('-cat', args.rootfs, name)
        report = verify(package, rootcat('usr/lib/opkg/status').decode(),
                        command('-ll', args.rootfs).decode(), rootcat)
        report['rootfs_sha256'] = sha(args.rootfs.read_bytes())
    except Exception as error:
        report['error'] = str(error); raise
    finally:
        args.output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': main()
