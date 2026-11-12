#!/usr/bin/env python3
"""Synthetic package/reader controls only; no target library is executed."""
import contextlib
import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


F = load('ncurses_image_fixtures', ROOT / 'tests/test-vim-rootfs.py')
M = load('ncurses_image_gate', ROOT / '.github/scripts/verify-ncurses-rootfs.py')


def package_fixture():
    packages, blobs = {}, {}
    for name in M.NAMES:
        control = {'Package': name, 'Version': M.VERSION, 'Architecture': 'aarch64_cortex-a53',
                   'Depends': 'libc, terminfo' if name == 'libncurses6' else 'libc'}
        if name == 'libncurses6':
            entries = [(p, '-', 0o755, F.elf()) for p in M.LIBRARIES]
            entries.append(('usr/lib/libncurses.so.6', 'l', 0o777, 'libncursesw.so.6.6'))
        else:
            entries = [('usr/share/terminfo/x/xterm-256color', '-', 0o644, b'terminfo fixture\n')]
        raw = F.ipk(name, control, entries)
        actual, payload = M.V.ART.read_ipk(raw)
        packages[name] = {'control': actual, 'payload': payload, 'sha256': M.sha(raw)}
        blobs[name] = raw
    return packages, blobs


class Tests(unittest.TestCase):
    def setUp(self):
        self.packages, self.blobs = package_fixture()

    def status(self, state='install ok installed'):
        return '\n'.join(F.control_text(p['control']) + 'Status: ' + state + '\n' for p in self.packages.values())

    def check(self, status=None, listing=None, cat=None):
        return M.verify(self.packages, self.status() if status is None else status,
                        F.listing(self.packages) if listing is None else listing,
                        F.rootcat(self.packages) if cat is None else cat)

    def test_actual_shape_and_hold(self):
        for state in ('install ok installed', 'install hold installed', 'install hold,user installed'):
            self.assertEqual(self.check(status=self.status(state))['status'], 'PASS_NCURSES_IPK_INDEX_ROOTFS_BYTES_ONLY')

    def test_old_version_rejected(self):
        self.packages['terminfo']['control']['Version'] = '6.4-r3'
        with self.assertRaises(M.V.Invalid): self.check()

    def test_foreign_architecture(self):
        self.packages['libncurses6']['control']['Architecture'] = 'x86_64'
        with self.assertRaises(M.V.Invalid): self.check()

    def test_wrong_payload_machine(self):
        path = M.LIBRARIES[0]
        member, raw = self.packages['libncurses6']['payload'][path]
        self.packages['libncurses6']['payload'][path] = member, raw[:18] + b'\x3e\x00' + raw[20:]
        with self.assertRaises(M.V.Invalid): self.check()

    def test_changed_bytes(self):
        with self.assertRaises(M.V.Invalid): self.check(cat=lambda path: b'changed')

    def test_changed_mode(self):
        text = F.listing(self.packages).replace('-rwxr-xr-x', '-rw-r--r--')
        with self.assertRaises(M.V.Invalid): self.check(listing=text)

    def test_changed_link(self):
        text = F.listing(self.packages).replace(' -> libncursesw.so.6.6', ' -> libother.so.6')
        with self.assertRaises(M.V.Invalid): self.check(listing=text)

    def test_missing_library(self):
        del self.packages['libncurses6']['payload'][M.LIBRARIES[0]]
        with self.assertRaises(M.V.Invalid): self.check()

    def test_missing_terminfo(self):
        self.packages['terminfo']['payload'] = {}
        with self.assertRaises(M.V.Invalid): self.check()

    def test_duplicate_status_and_abnormal_flags(self):
        with self.assertRaises(M.V.Invalid): self.check(status=self.status() + self.status())
        for state in ('install reinstreq installed', 'deinstall ok installed', 'install user,hold installed'):
            with self.assertRaises(M.V.Invalid): self.check(status=self.status(state))

    def test_dependency_mismatch(self):
        with self.assertRaises(M.V.Invalid): self.check(status=self.status().replace('libc, terminfo', 'libc, wrong-provider'))

    def test_hardlink_payload(self):
        self.packages['libncurses6']['payload'][M.LIBRARIES[0]][0].type = F.tarfile.LNKTYPE
        with self.assertRaises(M.V.Invalid): self.check()


class MainPathTests(unittest.TestCase):
    """Real on-disk IPKs and readers; only host unsquashfs is substituted."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ncurses-main-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.packages, self.blobs = package_fixture()
        self.feed_root = self.root / 'packages with spaces'
        self.feed = self.feed_root / 'aarch64_cortex-a53' / 'base'
        self.feed.mkdir(parents=True)
        self.records = []
        for name in M.NAMES:
            filename = name + '_fixture.ipk'
            blob = self.blobs[name]
            (self.feed / filename).write_bytes(blob)
            self.records.append(dict(self.packages[name]['control'], Filename=filename,
                                     Size=str(len(blob)), SHA256sum=M.sha(blob)))
        self.write_index()
        self.image = self.root / 'root'
        self.image.write_bytes(b'synthetic rootfs handle; reads supplied by host-only mock\n')
        self.retained = self.root / 'retained packages'
        self.output = self.root / 'ncurses-rootfs.json'
        self.reads = []

    def write_index(self):
        raw = '\n'.join(F.control_text(record) for record in self.records).encode()
        (self.feed / 'Packages').write_bytes(raw)
        (self.feed / 'Packages.gz').write_bytes(gzip.compress(raw, mtime=0))

    def unsquashfs(self, argv, **kwargs):
        self.assertEqual(argv[0], 'synthetic-unsquashfs')
        self.assertEqual(Path(argv[2]), self.image)
        self.assertEqual(kwargs['env']['LC_ALL'], 'C')
        self.reads.append(tuple(map(str, argv[1:])))
        if argv[1] == '-ll':
            self.assertEqual(len(argv), 3)
            data = F.listing(self.packages).encode()
        else:
            self.assertEqual(argv[1], '-cat')
            self.assertEqual(len(argv), 4)
            data = (F.status(self.packages).encode() if argv[3] == 'usr/lib/opkg/status'
                    else F.rootcat(self.packages)(argv[3]))
        return subprocess.CompletedProcess(argv, 0, data, b'')

    def invoke(self, module=M, relative=False):
        def argument(path):
            return str(path.relative_to(self.root)) if relative else str(path)
        argv = [str(ROOT / '.github/scripts/verify-ncurses-rootfs.py'),
                '--rootfs', argument(self.image), '--packages-root', argument(self.feed_root),
                '--retain-packages', argument(self.retained), '--output', argument(self.output),
                '--unsquashfs', 'synthetic-unsquashfs']
        saved_argv, saved_cwd = sys.argv, Path.cwd()
        stdout = io.StringIO()
        try:
            sys.argv = argv
            if relative:
                # The CLI paths are relative to its entry cwd; the helper must not change it.
                import os
                os.chdir(self.root)
            entry_cwd = Path.cwd()
            with mock.patch.object(module.subprocess, 'run', side_effect=self.unsquashfs), contextlib.redirect_stdout(stdout):
                rc = module.main()
            self.assertEqual(Path.cwd(), entry_cwd)
        finally:
            sys.argv = saved_argv
            if Path.cwd() != saved_cwd:
                import os
                os.chdir(saved_cwd)
        return rc, json.loads(self.output.read_text()), stdout.getvalue()

    def assert_rejected(self, diagnostic):
        rc, result, _ = self.invoke()
        self.assertEqual(rc, 1)
        self.assertEqual(result['status'], 'INCOMPLETE')
        self.assertFalse(result['runtime_approved'])
        self.assertRegex(result['error'], diagnostic)
        self.assertNotIn('rootfs_sha256', result)
        self.assertEqual(self.reads, [])
        return result

    def assert_retained(self):
        index = (self.feed / 'Packages').read_bytes()
        compressed = (self.feed / 'Packages.gz').read_bytes()
        for name in M.NAMES:
            directory = self.retained / name
            self.assertEqual((directory / (name + '_fixture.ipk')).read_bytes(), self.blobs[name])
            self.assertEqual((directory / 'Packages').read_bytes(), index)
            self.assertEqual((directory / 'Packages.gz').read_bytes(), compressed)
            saved = M.V.selected_ipks(directory, (name,))[name]
            self.assertEqual(saved['control'], self.packages[name]['control'])
            self.assertEqual(saved['sha256'], M.sha(self.blobs[name]))
            receipt = json.loads((directory / 'INDEX.json').read_text())
            self.assertEqual(receipt['status'], 'ORIGINAL_INPUTS_RETAINED_NOT_ROOTFS_ACCEPTANCE')
            self.assertEqual({item['name'] for item in receipt['files']},
                             {name + '_fixture.ipk', 'Packages', 'Packages.gz'})
            for item in receipt['files']:
                self.assertEqual(item['sha256'], M.sha((directory / item['name']).read_bytes()))

    def test_main_two_actual_packages_retained_without_vlmcsd(self):
        self.assertEqual(list(self.feed_root.rglob('vlmcsd_*.ipk')), [])
        rc, result, _ = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(result['status'], 'PASS_NCURSES_IPK_INDEX_ROOTFS_BYTES_ONLY')
        self.assertEqual(set(result['packages']), set(M.NAMES))
        self.assertEqual(result['rootfs_sha256'], M.sha(self.image.read_bytes()))
        self.assertTrue(self.reads)
        self.assert_retained()

    def test_main_relative_paths_and_unselected_corrupt_ipk(self):
        self.records.append({'Package': 'vlmcsd', 'Version': 'unselected', 'Architecture': 'aarch64_cortex-a53',
                             'Filename': 'vlmcsd_unselected.ipk', 'Size': '1', 'SHA256sum': '0' * 64})
        self.write_index()
        (self.feed / 'vlmcsd_unselected.ipk').write_bytes(b'not an IPK; must never be decoded')
        original = self.unsquashfs
        def relative_reader(argv, **kwargs):
            argv = list(argv)
            argv[2] = str((self.root / argv[2]).absolute())
            return original(argv, **kwargs)
        self.unsquashfs = relative_reader
        rc, result, _ = self.invoke(relative=True)
        self.assertEqual(rc, 0)
        self.assertNotIn('vlmcsd', result['packages'])
        self.assert_retained()
        self.assertEqual(list(self.retained.rglob('vlmcsd_*.ipk')), [])

    def test_main_missing_selected_ipk(self):
        (self.feed / 'terminfo_fixture.ipk').unlink()
        self.assert_rejected('expected exactly one actual terminfo IPK')

    def test_main_duplicate_selected_ipk(self):
        (self.feed / 'libncurses6_duplicate.ipk').write_bytes(self.blobs['libncurses6'])
        self.assert_rejected('expected exactly one actual libncurses6 IPK')

    def test_main_mixed_control_package(self):
        (self.feed / 'libncurses6_fixture.ipk').write_bytes(self.blobs['terminfo'])
        self.assert_rejected('IPK filename/control package mismatch')

    def test_main_missing_index(self):
        (self.feed / 'Packages').unlink()
        self.assert_rejected('Packages index missing')

    def test_main_missing_selected_index_record(self):
        self.records = [record for record in self.records if record['Package'] != 'terminfo']
        self.write_index()
        self.assert_rejected('missing/duplicate .* package index record: terminfo')

    def test_main_duplicate_selected_index_record(self):
        self.records.append(copy.deepcopy(self.records[0]))
        self.write_index()
        self.assert_rejected('missing/duplicate .* package index record: libncurses6')

    def test_main_wrong_ipk_hash_in_index(self):
        self.records[0]['SHA256sum'] = '0' * 64
        self.write_index()
        self.assert_rejected('index SHA256 differs')

    def test_main_missing_ipk_hash_in_index(self):
        del self.records[0]['SHA256sum']
        self.write_index()
        self.assert_rejected('index SHA256 differs')

    def test_main_duplicate_hash_field_in_index(self):
        raw = (self.feed / 'Packages').read_bytes()
        raw = raw.replace(b'SHA256sum: ', b'SHA256sum: ' + b'0' * 64 + b'\nSHA256sum: ', 1)
        (self.feed / 'Packages').write_bytes(raw)
        (self.feed / 'Packages.gz').write_bytes(gzip.compress(raw, mtime=0))
        self.assert_rejected('malformed/duplicate package field')

    def test_main_wrong_size_in_index(self):
        self.records[0]['Size'] = '1'
        self.write_index()
        self.assert_rejected('index Size differs')

    def test_main_gzip_index_mismatch(self):
        (self.feed / 'Packages.gz').write_bytes(gzip.compress(b'not the original index', mtime=0))
        self.assert_rejected('Packages.gz differs from Packages')

    def test_main_corrupt_gzip_index(self):
        (self.feed / 'Packages.gz').write_bytes(b'not gzip')
        self.assert_rejected('Not a gzipped file')

    def test_main_existing_retention_output_is_not_reused(self):
        directory = self.retained / M.NAMES[0]
        directory.mkdir(parents=True)
        sentinel = directory / 'INDEX.json'
        sentinel.write_bytes(b'old evidence must not change')
        self.assert_rejected('File exists')
        self.assertEqual(sentinel.read_bytes(), b'old evidence must not change')
        self.assertFalse((self.retained / 'terminfo').exists())

    def test_main_checks_rootfs_after_real_retention(self):
        original = self.unsquashfs
        def changed_reader(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[1] == '-cat' and argv[-1] == M.LIBRARIES[0]:
                return subprocess.CompletedProcess(argv, 0, b'changed rootfs bytes', b'')
            return result
        self.unsquashfs = changed_reader
        rc, result, _ = self.invoke()
        self.assertEqual(rc, 1)
        self.assertEqual(result['status'], 'INCOMPLETE')
        self.assertIn('actual rootfs/IPK bytes differ', result['error'])
        self.assert_retained()

    def test_old_hardcode_source_mutation_reaches_exact_vlmcsd_error(self):
        path = ROOT / '.github/scripts/verify-vlmcsd-rootfs.py'
        source = path.read_text()
        fixed = 'V.selected_ipks(output, (package_name,))[package_name]'
        old = 'V.selected_ipks(output, (PACKAGE,))[PACKAGE]'
        self.assertEqual(source.count(fixed), 1)
        mutant = types.ModuleType('ncurses_old_retention_hardcode_mutant')
        mutant.__file__ = str(path)
        exec(compile(source.replace(fixed, old, 1), str(path) + ':old-hardcode-mutant', 'exec'), mutant.__dict__)
        original = M.helpers
        try:
            M.helpers = mutant
            result = self.assert_rejected('^expected exactly one actual vlmcsd IPK$')
        finally:
            M.helpers = original
        first = self.retained / 'libncurses6'
        self.assertEqual((first / 'libncurses6_fixture.ipk').read_bytes(), self.blobs['libncurses6'])
        self.assertTrue((first / 'Packages.gz').is_file())
        self.assertFalse((first / 'INDEX.json').exists())
        self.assertFalse((self.retained / 'terminfo').exists())
        print(json.dumps({'negative_control': 'one exact old hardcode statement; signature unchanged',
                          'replacement': old, 'main_returncode': 1,
                          'main_status': result['status'], 'main_error': result['error'],
                          'unsquashfs_calls': len(self.reads), 'not_a_type_error': True}, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
