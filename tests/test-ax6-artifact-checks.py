#!/usr/bin/env python3
"""Offline parser/consistency negative controls; no kernel or network commands."""
import copy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('artifact_checks', ROOT / '.github/scripts/verify-ax6-artifacts.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def tar(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def ipk(name, payload=b'fixture\n', version='1', architecture='aarch64_cortex-a53', control_override=None):
    control = f'Package: {name}\nVersion: {version}\nArchitecture: {architecture}\nDescription: fixture\n continuation\n \n continued\n'.encode()
    if control_override is not None:
        control = control_override
    return gzip.compress(tar([
        ('./debian-binary', b'2.0\n'),
        ('./control.tar.gz', gzip.compress(tar([('./control', control)]))),
        ('./data.tar.gz', gzip.compress(tar([('./usr/share/fixture', payload)]))),
    ]))


def make_feed(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    for name in ('kmod-fixture', 'runtime-dependency'):
        blob = ipk(name)
        filename = name + '_1_aarch64.ipk'
        (directory / filename).write_bytes(blob)
        records.append(f'Package: {name}\nVersion: 1\nArchitecture: aarch64_cortex-a53\nFilename: {filename}\nSize: {len(blob)}\nSHA256sum: {checks.sha(blob)}\n')
    index = ('\n'.join(records) + '\n').encode()
    (directory / 'Packages').write_bytes(index)
    (directory / 'Packages.gz').write_bytes(gzip.compress(index))
    (directory / 'Packages.manifest').write_bytes(index)
    return directory


def fdt(tree):
    strings = bytearray()
    names = {}
    def node(name, properties, children):
        result = bytearray(struct.pack('>I', 1) + name.encode() + b'\0')
        result += b'\0' * (-len(result) % 4)
        for key, value in properties.items():
            if key not in names:
                names[key] = len(strings)
                strings.extend(key.encode() + b'\0')
            result += struct.pack('>III', 3, len(value), names[key]) + value
            result += b'\0' * (-len(result) % 4)
        for child_name, child_tree in children.items():
            result += node(child_name, *child_tree)
        result += struct.pack('>I', 2)
        return result
    structure = node('', *tree) + struct.pack('>I', 9)
    start = 56
    total = start + len(structure) + len(strings)
    return struct.pack('>10I', 0xd00dfeed, total, start, start + len(structure), 40, 17, 16, 0,
                       len(strings), len(structure)) + b'\0' * 16 + structure + strings


DTB = fdt(({'compatible': b'redmi,ax6-stock\0'}, {}))


def fit_tree():
    def image(data, kind):
        properties = {'data': data, 'arch': b'arm64\0', 'type': kind + b'\0',
                      'compression': b'gzip\0' if kind == b'kernel' else b'none\0'}
        if kind == b'kernel':
            properties.update(os=b'linux\0', load=struct.pack('>I', 0x41000000), entry=struct.pack('>I', 0x41000000))
        return (properties, {'hash-1': ({'algo': b'sha256\0', 'value': hashlib.sha256(data).digest()}, {})})
    return ({}, {'images': ({}, {'kernel-1': image(gzip.compress(b'kernel fixture'), b'kernel'), 'fdt-1': image(DTB, b'flat_dt')}),
                 'configurations': ({'default': b'config@ac04\0'}, {'config@ac04': ({'kernel': b'kernel-1\0', 'fdt': b'fdt-1\0'}, {})})})


def image(data=None, extra=()):
    if data is None:
        data = fdt(fit_tree())
    return tar([('sysupgrade-redmi_ax6-stock/CONTROL', b'BOARD=redmi_ax6-stock\n'),
                ('sysupgrade-redmi_ax6-stock/kernel', data),
                ('sysupgrade-redmi_ax6-stock/root', b'squashfs fixture')] + list(extra))


def link_archive(name, target, *, hard=False, child=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        link = tarfile.TarInfo(name)
        link.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
        link.linkname = target
        archive.addfile(link)
        if child:
            info = tarfile.TarInfo(child)
            info.size = 1
            archive.addfile(info, io.BytesIO(b'x'))
    return stream.getvalue()


def module_fixture():
    packages, root = {}, {}
    statuses = ['Package: kernel\nVersion: 6.18.38~fixture-r1\nStatus: install ok installed']
    for index, name in enumerate(checks.CORE_PACKAGES + ('kmod-noncore', 'kmod-meta')):
        elf = bytearray(b'\0' * 64)
        elf[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', elf, 18, 183)
        path = f'lib/modules/6.18.38/module{index}.ko'
        payload = checks.tar_members(tar([(path, bytes(elf))])) if name != 'kmod-meta' else {}
        packages[name] = {'control': {'Version': 'v1', 'Architecture': 'aarch64_cortex-a53',
                                     'Depends': 'kernel (=6.18.38~fixture-r1)'}, 'payload': payload}
        if name != 'kmod-meta':
            root[path] = bytes(elf)
        statuses.append(f'Package: {name}\nVersion: v1\nArchitecture: aarch64_cortex-a53\nStatus: install ok installed')
    root['usr/lib/opkg/status'] = ('\n\n'.join(statuses) + '\n').encode()
    return packages, root


def main():
    passed = []
    def good(name, fn):
        fn()
        passed.append(name)
    def bad(name, fn):
        try:
            fn()
        except (checks.Invalid, ValueError, OSError, KeyError, struct.error, tarfile.TarError, EOFError):
            passed.append(name)
        else:
            raise AssertionError('negative control accepted: ' + name)

    with tempfile.TemporaryDirectory(prefix='ax6-artifact-tests-') as tmp:
        base = Path(tmp)
        feed = make_feed(base / 'valid')
        good('valid-gzip-ipk-index', lambda: checks.verify_packages(feed))
        good('valid-description-empty-continuation', lambda: checks.fields('Package: x\nDescription: a\n \n b\n'))
        variants = {
            'wrong-index-sha': lambda text: text.replace('SHA256sum: ', 'SHA256sum: ' + '0' * 64 + '\nUnused: ', 1),
            'wrong-index-size': lambda text: text.replace('Size: ', 'Size: 1\nUnused: ', 1),
            'missing-sha': lambda text: '\n'.join(line for line in text.split('\n') if not line.startswith('SHA256sum:')),
            'duplicate-index-field': lambda text: text.replace('Version: 1', 'Version: 1\nVersion: 1', 1),
            'duplicate-package': lambda text: text + '\n' + text,
            'unsafe-index-path': lambda text: text.replace('Filename: kmod-', 'Filename: ../kmod-', 1),
            'wrong-control-version': lambda text: text.replace('Version: 1', 'Version: 2', 1),
            'wrong-control-architecture': lambda text: text.replace('Architecture: aarch64_cortex-a53', 'Architecture: mips', 1),
            'wrong-index-dependency': lambda text: text.replace('Version: 1', 'Version: 1\nDepends: unavailable-package', 1),
        }
        for name, mutate in variants.items():
            case = make_feed(base / name)
            changed = mutate((case / 'Packages').read_text()).encode()
            (case / 'Packages').write_bytes(changed)
            (case / 'Packages.gz').write_bytes(gzip.compress(changed))
            bad(name, lambda case=case: checks.verify_packages(case))
        missing = make_feed(base / 'missing-ipk')
        (missing / 'kmod-fixture_1_aarch64.ipk').unlink()
        bad('missing-indexed-ipk', lambda: checks.verify_packages(missing))
        compressed = make_feed(base / 'compressed-mismatch')
        (compressed / 'Packages.gz').write_bytes(gzip.compress(b'different'))
        bad('compressed-index-mismatch', lambda: checks.verify_packages(compressed))
        dangling = make_feed(base / 'compressed-dangling')
        (dangling / 'Packages.gz').unlink()
        (dangling / 'Packages.gz').symlink_to('missing-target')
        bad('compressed-index-dangling-symlink', lambda: checks.verify_packages(dangling))
        bad('non-ipk-bytes', lambda: checks.read_ipk(b'not an archive'))
        bad('truncated-gzip', lambda: checks.read_ipk(ipk('kmod-x')[:-8]))
        bad('missing-ipk-data', lambda: checks.read_ipk(gzip.compress(tar([('debian-binary', b'2.0\n')]))))
        bad('duplicate-control-field', lambda: checks.read_ipk(ipk('kmod-x', control_override=b'Package: x\nPackage: y\n')))
        bad('unsafe-archive-member', lambda: checks.tar_members(tar([('../outside', b'x')])) )
        bad('duplicate-archive-member', lambda: checks.tar_members(tar([('x', b'a'), ('x', b'b')])) )
        good('image-absolute-symlink-is-legal', lambda: checks.tar_members(link_archive('bin/sh', '/bin/busybox')))
        good('image-relative-symlink-is-legal', lambda: checks.tar_members(link_archive('lib/libx.so', '../usr/lib/libx.so')))
        bad('image-relative-symlink-escape', lambda: checks.tar_members(link_archive('usr/link', '../../../../outside')))
        bad('image-symlink-ancestor', lambda: checks.tar_members(link_archive('usr', 'lib', child='usr/file')))
        bad('image-hardlink-escape', lambda: checks.tar_members(link_archive('usr/link', '../../../../outside', hard=True)))
        good('image-internal-hardlink', lambda: checks.tar_members(link_archive('link', 'regular', hard=True, child='regular')))
        envelope = checks.ipk_members(ipk('kmod-x'))
        ar = bytearray(b'!<arch>\n')
        for name, data in envelope.items():
            ar.extend(f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(data):<10}`\n'.encode())
            ar.extend(data)
            if len(data) % 2:
                ar.extend(b'\n')
        good('valid-ar-ipk', lambda: checks.read_ipk(bytes(ar)))
        bad('truncated-ar-ipk', lambda: checks.read_ipk(bytes(ar[:-2])))
        good('valid-final-fit', lambda: checks.verify_fit(fdt(fit_tree())))
        for key, value in (('arch', b'mips\0'), ('type', b'ramdisk\0'), ('os', b'freebsd\0'),
                           ('compression', b'none\0'), ('entry', struct.pack('>I', 0x40000000))):
            tree = fit_tree()
            tree[1]['images'][1]['kernel-1'][0][key] = value
            bad('fit-invalid-' + key, lambda tree=tree: checks.verify_fit(fdt(tree)))
        for reserve in (41, 56):
            malformed = bytearray(fdt(fit_tree()))
            struct.pack_into('>I', malformed, 16, reserve)
            bad('fdt-invalid-reserve-' + str(reserve), lambda malformed=malformed: checks.verify_fit(bytes(malformed)))
        tree = fit_tree()
        # Keep gzip valid so this negative reaches the FIT hash comparison.
        tree[1]['images'][1]['kernel-1'][0]['data'] = gzip.compress(b'mutated kernel fixture')
        bad('fit-corrupt-payload', lambda: checks.verify_fit(fdt(tree)))
        tree = fit_tree()
        tree[1]['configurations'][1]['config@ac04'][0]['kernel'] = b'unverified\0'
        bad('fit-wrong-default-reference', lambda: checks.verify_fit(fdt(tree)))
        tree = fit_tree()
        tree[1]['configurations'][1]['extra'] = ({'kernel': b'unverified\0'}, {})
        bad('fit-extra-unverified-config', lambda: checks.verify_fit(fdt(tree)))
        tree = fit_tree()
        tree[1]['configurations'][1]['config@ac04'][0]['loadables'] = b'unverified\0'
        bad('fit-extra-loadables-reference', lambda: checks.verify_fit(fdt(tree)))
        tree = fit_tree()
        tree[1]['configurations'][0]['default'] = b'wrong-config\0'
        tree[1]['configurations'][1]['wrong-config'] = tree[1]['configurations'][1].pop('config@ac04')
        bad('fit-wrong-single-config-identity', lambda: checks.verify_fit(fdt(tree)))
        tree = fit_tree()
        tree[1]['images'][1]['kernel-1'][1].clear()
        bad('fit-missing-hash', lambda: checks.verify_fit(fdt(tree)))
        tree = fit_tree()
        tree[1]['images'][1]['kernel-1'][1]['hash-1'][0].update(
            algo=b'crc32\0', value=struct.pack('>I', checks.zlib.crc32(tree[1]['images'][1]['kernel-1'][0]['data']) & 0xffffffff))
        bad('fit-crc-only-downgrade', lambda: checks.verify_fit(fdt(tree)))
        tree = fit_tree()
        tree[1]['images'][1]['kernel-1'][0]['data-offset'] = struct.pack('>I', 0)
        bad('fit-ambiguous-external-data', lambda: checks.verify_fit(fdt(tree)))
        bad('fit-truncated', lambda: checks.verify_fit(fdt(fit_tree())[:-4]))
        good('valid-stock-sysupgrade', lambda: checks.sysupgrade_payload(image()))
        bad('extra-sysupgrade-root', lambda: checks.sysupgrade_payload(image(extra=[('other/root', b'wrong')])))
        bad('duplicate-sysupgrade-kernel', lambda: checks.sysupgrade_payload(image(extra=[('sysupgrade-redmi_ax6-stock/kernel', b'wrong')])))
        symlink_stream = io.BytesIO(image())
        with tarfile.open(fileobj=symlink_stream, mode='a') as archive:
            link = tarfile.TarInfo('extra-link')
            link.type = tarfile.SYMTYPE
            link.linkname = '/outside'
            archive.addfile(link)
        bad('extra-sysupgrade-symlink', lambda: checks.sysupgrade_payload(symlink_stream.getvalue()))
        recovery = base / 'recovery'
        recovery.mkdir()
        (recovery / 'a-redmi_ax6-stock-squashfs-factory.ubi').write_bytes(b'fixture, not UBI payload validation')
        bad('missing-recovery-itb', lambda: checks.recovery_paths(recovery))
        (recovery / 'a-redmi_ax6-stock-initramfs-uImage.itb').write_bytes(fdt(fit_tree()))
        good('one-itb-one-ubi', lambda: checks.recovery_paths(recovery))
        (recovery / 'b-initramfs-uImage.itb').write_bytes(fdt(fit_tree()))
        bad('duplicate-recovery-itb', lambda: checks.recovery_paths(recovery))
        (recovery / 'b-initramfs-uImage.itb').rename(recovery / 'otherwise-unmatched.itb')
        bad('extra-noncanonical-recovery-itb', lambda: checks.recovery_paths(recovery))
        packages, root = module_fixture()
        good('all-installed-kmods-including-noncore-and-meta', lambda: checks.verify_modules(packages, root.__getitem__))
        wrong_root = dict(root)
        wrong_root['lib/modules/6.18.38/module0.ko'] = b'wrong bytes'
        bad('rootfs-module-byte-mismatch', lambda: checks.verify_modules(packages, wrong_root.__getitem__))
        wrong_packages = copy.deepcopy(packages)
        wrong_packages[checks.CORE_PACKAGES[0]]['control']['Depends'] = 'kernel (=wrong-r1)'
        bad('kernel-abi-mismatch', lambda: checks.verify_modules(wrong_packages, root.__getitem__))
        wrong_packages = copy.deepcopy(packages)
        wrong_packages[checks.CORE_PACKAGES[0]]['control']['Version'] = 'wrong-r1'
        bad('rootfs-package-version-mismatch', lambda: checks.verify_modules(wrong_packages, root.__getitem__))
        wrong_packages = dict(packages)
        del wrong_packages[checks.CORE_PACKAGES[0]]
        bad('missing-core-ipk', lambda: checks.verify_modules(wrong_packages, root.__getitem__))
        wrong_packages = dict(packages)
        del wrong_packages['kmod-noncore']
        bad('missing-noncore-ipk', lambda: checks.verify_modules(wrong_packages, root.__getitem__))
        wrong_root = dict(root)
        wrong_root['lib/modules/6.18.38/module7.ko'] = b'noncore mutation'
        bad('noncore-module-byte-mismatch', lambda: checks.verify_modules(packages, wrong_root.__getitem__))
        wrong_packages = copy.deepcopy(packages)
        wrong_packages['kmod-noncore']['control']['Depends'] = 'kernel (=wrong-r1)'
        bad('noncore-kernel-abi-mismatch', lambda: checks.verify_modules(wrong_packages, root.__getitem__))
        for suffix in (' | kernel (=wrong)', ', kernel', ', kernel (=6.18.38~fixture-r1)'):
            wrong_packages = copy.deepcopy(packages)
            wrong_packages['kmod-noncore']['control']['Depends'] += suffix
            bad('noncore-kernel-ambiguous-' + suffix, lambda wrong_packages=wrong_packages: checks.verify_modules(wrong_packages, root.__getitem__))
        wrong_packages = copy.deepcopy(packages)
        wrong_root = dict(root)
        old_path = 'lib/modules/6.18.38/module7.ko'
        wrong_path = 'lib/modules/0.0.0-wrong/module7.ko'
        wrong_packages['kmod-noncore']['payload'][wrong_path] = wrong_packages['kmod-noncore']['payload'].pop(old_path)
        wrong_root[wrong_path] = wrong_root.pop(old_path)
        bad('noncore-wrong-module-release-directory', lambda: checks.verify_modules(wrong_packages, wrong_root.__getitem__))
        wrong_packages = copy.deepcopy(packages)
        wrong_packages['kmod-noncore']['control']['Architecture'] = 'mips'
        bad('noncore-architecture-mismatch', lambda: checks.verify_modules(wrong_packages, root.__getitem__))
        paths = {path for path in root if path.endswith('.ko')}
        good('complete-rootfs-module-inventory', lambda: checks.verify_modules(packages, root.__getitem__, paths))
        bad('unowned-rootfs-module', lambda: checks.verify_modules(packages, root.__getitem__, paths | {'lib/modules/extra.ko'}))
        bad('missing-rootfs-module', lambda: checks.verify_modules(packages, root.__getitem__, paths - {'lib/modules/6.18.38/module7.ko'}))
        listing = '-rw-r--r-- root/root 64 2026-10-01 00:00 squashfs-root/lib/modules/6.18.38/example.ko'
        good('regular-module-listing', lambda: checks.module_paths_from_listing(listing))
        bad('duplicate-module-listing', lambda: checks.module_paths_from_listing(listing + '\n' + listing))
        bad('symlink-module-listing', lambda: checks.module_paths_from_listing(listing.replace('-rw-r--r--', 'lrwxrwxrwx') + ' -> elsewhere'))
    print(json.dumps({'status': 'PASS', 'checks': len(passed), 'names': passed}, indent=2))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--make-feed':
        make_feed(sys.argv[2])
    else:
        require_args = len(sys.argv) == 1
        if not require_args:
            raise SystemExit('usage: test-ax6-artifact-checks.py [--make-feed DIRECTORY]')
        main()
