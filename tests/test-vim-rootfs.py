#!/usr/bin/env python3
"""Offline fixtures for Vim image binding, no target execution or external tools."""
import contextlib
import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import stat
import struct
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('vim_rootfs', ROOT / '.github/scripts/verify-vim-rootfs.py')
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)


def tar(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as t:
        for path, kind, mode, content in entries:
            info = tarfile.TarInfo(path)
            info.mode = mode
            if kind == 'd':
                info.type = tarfile.DIRTYPE
            elif kind in ('l', 'h'):
                info.type = tarfile.SYMTYPE if kind == 'l' else tarfile.LNKTYPE
                info.linkname = content
            else:
                info.size = len(content)
            t.addfile(info, io.BytesIO(content) if kind == '-' else None)
    return stream.getvalue()


def elf():
    result = bytearray(64)
    result[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HH', result, 16, 3, 183)
    return bytes(result)


def controls():
    result = {name: {'Package': name, 'Version': V.VERSION, 'Architecture': 'aarch64_cortex-a53',
                   'Depends': 'vim-runtime (= ' + V.VERSION + '), libc, vim-runtime' if name == 'vim-fuller' else 'libc'}
            for name in V.PACKAGES}
    result['xxd'] = {'Package': 'xxd', 'Version': V.XXD_VERSION,
                     'Architecture': 'aarch64_cortex-a53', 'Depends': 'libc'}
    return result


def control_text(control):
    return ''.join(k + ': ' + v + '\n' for k, v in control.items())


def payload_entries():
    return {'vim-fuller': [('usr', 'd', 0o755, None), ('usr/bin', 'd', 0o755, None),
                            ('usr/bin/vim', '-', 0o755, elf()), ('usr/bin/vimdiff', 'l', 0o777, 'vim')],
            'vim-runtime': [('usr', 'd', 0o755, None), ('usr/share', 'd', 0o755, None),
                            ('usr/share/vim', 'd', 0o755, None),
                            ('usr/share/vim/defaults.vim', '-', 0o644, b'fixture runtime\n')],
            'xxd': [('usr', 'd', 0o755, None), ('usr/bin', 'd', 0o755, None),
                    ('usr/bin/xxd', '-', 0o755, elf())]}


def ipk(name, control=None, entries=None):
    if control is None:
        control = controls()[name]
    if entries is None:
        entries = payload_entries()[name]
    return gzip.compress(tar([
        ('debian-binary', '-', 0o644, b'2.0\n'),
        ('control.tar.gz', '-', 0o644, gzip.compress(tar([('control', '-', 0o644, control_text(control).encode())]))),
        ('data.tar.gz', '-', 0o644, gzip.compress(tar(entries))),
    ]))


def fixture(names=V.PACKAGES):
    packages = {}
    for name in names:
        blob = ipk(name)
        control, payload = V.ART.read_ipk(blob)
        packages[name] = {'control': control, 'payload': payload, 'sha256': V.sha(blob)}
    return packages


def status(packages, extra=''):
    return '\n'.join(control_text(packages[name]['control']) + 'Status: install ok installed\n'
                     for name in packages) + '\n' + extra


def feed(root, names=V.PACKAGES):
    records = []
    for name in names:
        blob = ipk(name)
        filename = name + '_fixture.ipk'
        (root / filename).write_bytes(blob)
        record = dict(controls()[name], Filename=filename, Size=str(len(blob)), SHA256sum=V.sha(blob))
        records.append(control_text(record))
    (root / 'Packages').write_text('\n'.join(records))
    return records


def listing(packages):
    entries = {}
    for pkg in packages.values():
        entries.update(pkg['payload'])
    lines = []
    for path, (member, data) in entries.items():
        kind = stat.S_IFDIR if member.isdir() else stat.S_IFLNK if member.issym() else stat.S_IFREG
        printed = path + (' -> ' + member.linkname if member.issym() else '')
        lines.append(f'{stat.filemode(kind | member.mode)} root/root {len(data or b"")} 2026-10-01 00:00 squashfs-root/{printed}')
    return '\n'.join(lines)


def rootcat(packages):
    payload = {path: data for pkg in packages.values() for path, (info, data) in pkg['payload'].items() if info.isfile()}
    return payload.__getitem__


class Tests(unittest.TestCase):
    def setUp(self):
        self.p = fixture()

    def check(self, packages=None, status_text=None, listing_text=None, cat=None):
        p = self.p if packages is None else packages
        return V.verify_payload(p, status(p) if status_text is None else status_text,
                                listing(p) if listing_text is None else listing_text,
                                rootcat(p) if cat is None else cat)

    def reject(self, reason, **kw):
        with self.assertRaisesRegex(V.Invalid, reason):
            self.check(**kw)

    def test_positive_counts_and_scope(self):
        r = self.check()
        self.assertEqual(r['regular_files_checked'], 2)
        self.assertEqual(r['symlinks_checked'], 1)
        self.assertEqual(r['directories_type_checked'], 4)
        self.assertEqual(r['status'], 'PASS_VIM_IPK_ROOTFS_BINDING_ONLY')

    def test_old_version(self):
        self.p['vim-fuller']['control']['Version'] = '9.2.0-r1'
        self.reject('version differs')

    def test_status_version_differs(self):
        self.reject('version differs', status_text=status(self.p).replace(V.VERSION, '9.2.1014-r1', 1))

    def test_runtime_version_differs(self):
        self.p['vim-runtime']['control']['Version'] = '9.2.1014-r1'
        self.reject('version differs')

    def test_architecture_mismatch(self):
        self.reject('architecture differs', status_text=status(self.p).replace('aarch64_cortex-a53', 'mips', 1))

    def test_wrong_architecture_consistent(self):
        for p in self.p.values():
            p['control']['Architecture'] = 'mips'
        self.reject('expected AArch64')

    def test_dependency_status_differs(self):
        self.reject('dependency metadata differs', status_text=status(self.p).replace('libc, ', '', 1))

    def test_exact_dependency_negatives(self):
        for dep in ['libc', 'vim-runtime', 'vim-runtime (>= ' + V.VERSION + ')',
                    'vim-runtime (= 9.2.0-r1)', 'vim-runtime (= ' + V.VERSION + ') | libc',
                    'vim-runtime (= ' + V.VERSION + '), vim-runtime (= ' + V.VERSION + ')',
                    'vim-runtime (= ' + V.VERSION + '), vim-runtime, vim-runtime']:
            with self.subTest(dep=dep):
                p = fixture()
                p['vim-fuller']['control']['Depends'] = dep
                self.reject('one exact vim-runtime', packages=p)

    def test_exact_dependency_without_redundant_bare_clause(self):
        self.p['vim-fuller']['control']['Depends'] = 'libc, vim-runtime (= ' + V.VERSION + ')'
        self.assertTrue(self.check()['status'].startswith('PASS_'))

    def test_legacy_installed(self):
        for name in V.LEGACY:
            with self.subTest(name=name):
                self.reject('legacy', status_text=status(self.p, f'Package: {name}\nStatus: install ok installed\n'))

    def test_held_legacy_installed(self):
        self.reject('legacy', status_text=status(self.p, 'Package: vim\nStatus: hold ok installed\n'))

    def test_duplicate_status(self):
        self.reject('duplicate status', status_text=status(self.p, 'Package: vim-runtime\nStatus: deinstall ok config-files\n'))

    def test_not_installed(self):
        self.reject('not installed', status_text=status(self.p).replace('install ok installed', 'deinstall ok config-files', 1))

    def test_user_installed_flags(self):
        self.assertTrue(self.check(status_text=status(self.p).replace('install ok installed', 'install user installed'))['status'].startswith('PASS_'))

    def test_wrong_elf(self):
        member, _ = self.p['vim-fuller']['payload']['usr/bin/vim']
        self.p['vim-fuller']['payload']['usr/bin/vim'] = (member, b'not ELF')
        self.reject('ELF64')

    def test_wrong_elf_machine(self):
        member, content = self.p['vim-fuller']['payload']['usr/bin/vim']
        content = bytearray(content)
        struct.pack_into('<H', content, 18, 62)
        self.p['vim-fuller']['payload']['usr/bin/vim'] = (member, bytes(content))
        self.reject('ELF64')

    def test_changed_runtime_bytes(self):
        cat = rootcat(self.p)
        self.reject('bytes differ', cat=lambda path: b'X' + cat(path)[1:] if path.endswith('defaults.vim') else cat(path))

    def test_changed_binary_bytes(self):
        cat = rootcat(self.p)
        self.reject('bytes differ', cat=lambda path: b'X' + cat(path)[1:] if path == 'usr/bin/vim' else cat(path))

    def test_wrong_binary_mode_in_ipk(self):
        self.p['vim-fuller']['payload']['usr/bin/vim'][0].mode = 0o777
        self.reject('regular 0755')

    def test_wrong_rootfs_mode(self):
        self.reject('mode differs', listing_text=listing(self.p).replace('-rwxr-xr-x', '-rwxrwxrwx'))

    def test_wrong_runtime_mode(self):
        self.reject('mode differs', listing_text=listing(self.p).replace('-rw-r--r--', '-rwxr-xr-x'))

    def test_binary_replaced_by_symlink(self):
        text = listing(self.p).replace('-rwxr-xr-x root/root 64', 'lrwxr-xr-x root/root 64')
        text = text.replace('squashfs-root/usr/bin/vim\n', 'squashfs-root/usr/bin/vim -> other\n')
        self.reject('type differs', listing_text=text)

    def test_missing_payload(self):
        self.reject('missing/unparseable', listing_text='\n'.join(x for x in listing(self.p).splitlines() if 'defaults.vim' not in x))

    def test_symlink_target_changed(self):
        self.reject('symlink target differs', listing_text=listing(self.p).replace(' -> vim', ' -> other'))

    def test_duplicate_listing(self):
        self.reject('duplicate rootfs', listing_text=listing(self.p) + '\n' + listing(self.p))

    def test_unsafe_archive_path(self):
        with self.assertRaisesRegex(V.Invalid, 'unsafe archive'):
            V.ART.read_ipk(ipk('vim-runtime', entries=[('../outside', '-', 0o644, b'x')]))

    def test_unsafe_archive_link(self):
        with self.assertRaisesRegex(V.Invalid, 'escapes image root'):
            V.ART.read_ipk(ipk('vim-runtime', entries=[('usr/bad', 'l', 0o777, '../../outside')]))

    def test_hardlink_rejected(self):
        control, payload = V.ART.read_ipk(ipk('vim-runtime', entries=[('usr/a', '-', 0o644, b'x'), ('usr/b', 'h', 0o644, 'usr/a')]))
        self.p['vim-runtime'].update(control=control, payload=payload)
        self.reject('hardlink payload unsupported')

    def test_newline_path_rejected(self):
        control, payload = V.ART.read_ipk(ipk('vim-runtime', entries=[('usr/bad\nname', '-', 0o644, b'x')]))
        self.p['vim-runtime'].update(control=control, payload=payload)
        self.reject('unsafe listing')

    def test_feed_unique_and_real_ipk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed(root)
            self.assertEqual(set(V.selected_ipks(root)), set(V.PACKAGES))
            (root / 'vim-fuller_duplicate.ipk').write_bytes(ipk('vim-fuller'))
            with self.assertRaisesRegex(V.Invalid, 'exactly one'):
                V.selected_ipks(root)

    def test_index_gzip_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed(root)
            (root / 'Packages.gz').write_bytes(gzip.compress((root / 'Packages').read_bytes()))
            self.assertEqual(set(V.selected_ipks(root)), set(V.PACKAGES))

    def test_index_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in V.PACKAGES:
                (root / (name + '_fixture.ipk')).write_bytes(ipk(name))
            with self.assertRaisesRegex(V.Invalid, 'Packages index missing'):
                V.selected_ipks(root)

    def test_index_metadata_negatives(self):
        mutations = {'Size': '1', 'SHA256sum': '0' * 64, 'Filename': 'other.ipk',
                     'Version': '9.2.0-r1', 'Architecture': 'mips',
                     'Depends': 'libc', 'Provides': 'invented-provider'}
        for field, value in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                feed(root)
                records = V.ART.fields((root / 'Packages').read_text())
                records[0][field] = value
                (root / 'Packages').write_text('\n'.join(control_text(r) for r in records))
                with self.assertRaises(V.Invalid):
                    V.selected_ipks(root)

    def test_index_duplicate_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = feed(root)
            with (root / 'Packages').open('a') as f:
                f.write('\n' + records[0])
            with self.assertRaisesRegex(V.Invalid, 'duplicate Vim package index'):
                V.selected_ipks(root)

    def test_index_gzip_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed(root)
            (root / 'Packages.gz').write_bytes(gzip.compress(b'wrong'))
            with self.assertRaisesRegex(V.Invalid, 'Packages.gz differs'):
                V.selected_ipks(root)

    def test_index_gzip_dangling_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed(root)
            (root / 'Packages.gz').symlink_to(root / 'missing')
            with self.assertRaisesRegex(V.Invalid, 'not a regular file'):
                V.selected_ipks(root)

    def test_xxd_not_applicable(self):
        self.assertEqual(self.check()['xxd_status'], 'NOT_APPLICABLE_NOT_INSTALLED')

    def test_optional_xxd_positive(self):
        p = fixture((*V.PACKAGES, 'xxd'))
        self.assertEqual(self.check(packages=p)['xxd_status'], 'PASS_INDEX_IPK_ROOTFS_BOUND')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed(root, (*V.PACKAGES, 'xxd'))
            self.assertEqual(set(V.selected_ipks(root, (*V.PACKAGES, 'xxd'))), set(p))

    def test_optional_xxd_old_version(self):
        p = fixture((*V.PACKAGES, 'xxd'))
        p['xxd']['control']['Version'] = '2025.11.26-r1'
        self.reject('version differs', packages=p)

    def test_optional_xxd_missing_ipk(self):
        p = fixture((*V.PACKAGES, 'xxd'))
        self.reject('selected package set differs', status_text=status(p))

    def test_optional_xxd_partial_status(self):
        for value in ('unpacked', 'half-installed', 'unknown'):
            with self.subTest(value=value):
                self.reject('unknown/partial', status_text=status(self.p, 'Package: xxd\nStatus: install ok ' + value + '\n'))

    def test_optional_xxd_changed_bytes(self):
        p = fixture((*V.PACKAGES, 'xxd'))
        cat = rootcat(p)
        self.reject('bytes differ', packages=p, cat=lambda path: b'x' * 64 if path.endswith('/xxd') else cat(path))

    def test_missing_ipk(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(V.Invalid, 'exactly one'):
                V.selected_ipks(Path(tmp))

    def test_invalid_ipk_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'vim-fuller_bad.ipk').write_bytes(b'not an ipk')
            with self.assertRaises(V.Invalid):
                V.selected_ipks(root)

    def test_symlink_ipk_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'real.bin'
            target.write_bytes(ipk('vim-fuller'))
            (root / 'vim-fuller_bad.ipk').symlink_to(target)
            with self.assertRaisesRegex(V.Invalid, 'not a regular file'):
                V.selected_ipks(root)

    def test_bounded_four_thread_reads(self):
        for i in range(20):
            member = tarfile.TarInfo('usr/share/vim/extra' + str(i))
            member.mode = 0o644
            self.p['vim-runtime']['payload'][member.name] = (member, b'x')
        original = rootcat(self.p)
        lock, counters = threading.Lock(), {'active': 0, 'peak': 0}
        def cat(path):
            with lock:
                counters['active'] += 1
                counters['peak'] = max(counters['peak'], counters['active'])
            time.sleep(0.005)
            result = original(path)
            with lock:
                counters['active'] -= 1
            return result
        self.assertEqual(self.check(cat=cat)['regular_files_checked'], 22)
        self.assertGreater(counters['peak'], 1)
        self.assertLessEqual(counters['peak'], 4)

    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            output.write_text('keep')
            with mock.patch.object(V, 'audit', side_effect=AssertionError('must not inspect')), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(V.main(['--rootfs', 'unused', '--packages-root', 'unused', '--output', str(output)]), 1)
            self.assertEqual(output.read_text(), 'keep')

    def test_dangling_output_symlink_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            target = Path(tmp) / 'must-not-create'
            output.symlink_to(target)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(V.main(['--rootfs', 'unused', '--packages-root', 'unused', '--output', str(output)]), 1)
            self.assertFalse(target.exists())

    def test_failed_audit_records_new_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            with mock.patch.object(V, 'audit', side_effect=V.Invalid('fixture refusal')), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(V.main(['--rootfs', 'unused', '--packages-root', 'unused', '--output', str(output)]), 1)
            self.assertEqual(json.loads(output.read_text())['error'], 'fixture refusal')
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)


if __name__ == '__main__':
    unittest.main(verbosity=2)
