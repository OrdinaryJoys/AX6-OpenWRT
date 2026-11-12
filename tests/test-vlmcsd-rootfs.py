#!/usr/bin/env python3
"""Image/package parser controls only; no image binaries are executed."""
import contextlib
import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


F = load('vim_image_fixtures', ROOT / 'tests/test-vim-rootfs.py')
M = load('vlmcsd_rootfs', ROOT / '.github/scripts/verify-vlmcsd-rootfs.py')


def fixture():
    control = {'Package': M.PACKAGE, 'Version': M.VERSION, 'Architecture': 'aarch64_cortex-a53',
               'Depends': 'libc'}
    entries = [('usr', 'd', 0o755, None), ('usr/bin', 'd', 0o755, None),
               (M.BINARY, '-', 0o755, F.elf()), ('etc/config/vlmcsd', '-', 0o755, b'fixture\n')]
    blob = F.ipk(M.PACKAGE, control, entries)
    actual, payload = M.V.ART.read_ipk(blob)
    return {'control': actual, 'payload': payload, 'sha256': M.sha(blob)}, blob


class Tests(unittest.TestCase):
    def setUp(self):
        self.p, self.blob = fixture()

    def check(self, package=None, state='install ok installed', text=None, listing=None, cat=None):
        p = package or self.p
        packages = {M.PACKAGE: p}
        status = F.control_text(p['control']) + 'Status: ' + state + '\n'
        return M.verify(p, text if text is not None else status,
                        listing if listing is not None else F.listing(packages),
                        cat if cat is not None else F.rootcat(packages))

    def test_installed_and_held(self):
        flags = ('hold', 'noprune', 'prefer', 'user')
        states = ['install ok installed'] + ['install ' + ','.join(
            f for i, f in enumerate(flags) if mask & (1 << i)) + ' installed' for mask in range(1, 16)]
        for state in states:
            self.assertTrue(self.check(state=state)['status'].startswith('PASS_'))

    def test_unknown_or_abnormal_status_flags(self):
        for state in ('hold ok installed', 'install reinstreq installed', 'deinstall broken installed',
                      'deinstall ok installed', 'purge ok installed', 'unknown ok installed',
                      'install obsolete installed', 'install replace installed', 'install broken installed',
                      'install user,hold installed', 'install hold,hold installed',
                      'install hold,broken installed', 'install ok,user installed'):
            with self.subTest(state=state), self.assertRaises(M.V.Invalid): self.check(state=state)

    def test_old_release_rejected(self):
        self.p['control']['Version'] = '2020.03.30~e5990804-r8'
        with self.assertRaises(M.V.Invalid): self.check()

    def test_foreign_architecture(self):
        self.p['control']['Architecture'] = 'all'
        with self.assertRaises(M.V.Invalid): self.check()

    def test_partial_state(self):
        for state in ('install ok unpacked', 'installed', 'deinstall ok not-installed'):
            with self.assertRaises(M.V.Invalid): self.check(state=state)

    def test_duplicate_status(self):
        text = F.control_text(self.p['control']) + 'Status: install ok installed\n\n'
        with self.assertRaises(M.V.Invalid): self.check(text=text + text)

    def test_missing_payload(self):
        del self.p['payload'][M.BINARY]
        with self.assertRaises(M.V.Invalid): self.check()

    def test_elf_identity(self):
        member, binary = self.p['payload'][M.BINARY]
        self.p['payload'][M.BINARY] = member, binary[:18] + b'\x3e\x00' + binary[20:]
        with self.assertRaises(M.V.Invalid): self.check()

    def test_changed_rootfs_bytes(self):
        with self.assertRaises(M.V.Invalid): self.check(cat=lambda path: b'not original')

    def test_changed_rootfs_modes(self):
        listing = F.listing({M.PACKAGE: self.p}).replace('-rwxr-xr-x', '-rw-r--r--')
        with self.assertRaises(M.V.Invalid): self.check(listing=listing)

    def test_missing_listing(self):
        with self.assertRaises(M.V.Invalid): self.check(listing='')

    def test_dependency_drift(self):
        text = F.control_text(self.p['control']).replace('Depends: libc', 'Depends: libother')
        with self.assertRaisesRegex(M.V.Invalid, 'vlmcsd status/control Depends'):
            self.check(text=text + 'Status: install hold installed\n')

    def test_hardlink_rejected(self):
        self.p['payload'][M.BINARY][0].type = F.tarfile.LNKTYPE
        with self.assertRaises(M.V.Invalid): self.check()

    def test_original_package_retention(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            feed = root / 'feed'
            feed.mkdir()
            filename = 'vlmcsd_fixture.ipk'
            (feed / filename).write_bytes(self.blob)
            record = dict(self.p['control'], Filename=filename, Size=str(len(self.blob)),
                          SHA256sum=M.sha(self.blob))
            (feed / 'Packages').write_text(F.control_text(record))
            package = M.V.selected_ipks(feed, (M.PACKAGE,))[M.PACKAGE]
            M.retain(package, root / 'retained')
            self.assertEqual((root / 'retained' / filename).read_bytes(), self.blob)
            with self.assertRaises(FileExistsError): M.retain(package, root / 'retained')
            (feed / filename).write_bytes(self.blob + b'changed')
            with self.assertRaises(M.V.Invalid): M.retain(package, root / 'changed')


class RetentionTests(unittest.TestCase):
    """Real source files, indices, copies and strict rereads; no reader mocks."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='package-retention-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.feed = self.root / 'feed with spaces'
        self.feed.mkdir()
        self.p, self.blob = fixture()
        self.filename = 'vlmcsd_fixture.ipk'
        (self.feed / self.filename).write_bytes(self.blob)
        self.record = dict(self.p['control'], Filename=self.filename, Size=str(len(self.blob)), SHA256sum=M.sha(self.blob))
        self.write_index([self.record])
        self.package = M.V.selected_ipks(self.feed, (M.PACKAGE,))[M.PACKAGE]
        self.output = self.root / 'retained'

    def write_index(self, records):
        raw = '\n'.join(F.control_text(record) for record in records).encode()
        (self.feed / 'Packages').write_bytes(raw)
        (self.feed / 'Packages.gz').write_bytes(gzip.compress(raw, mtime=0))

    def assert_no_receipt(self):
        self.assertFalse((self.output / 'INDEX.json').exists())

    def test_default_vlmcsd_entry_preserves_original_gzip_and_index(self):
        M.retain(self.package, self.output)
        saved = M.V.selected_ipks(self.output, (M.PACKAGE,))[M.PACKAGE]
        self.assertEqual(saved['control'], self.package['control'])
        for filename in (self.filename, 'Packages', 'Packages.gz'):
            self.assertEqual((self.output / filename).read_bytes(), (self.feed / filename).read_bytes())
        receipt = json.loads((self.output / 'INDEX.json').read_text())
        self.assertEqual(receipt['status'], 'ORIGINAL_INPUTS_RETAINED_NOT_ROOTFS_ACCEPTANCE')
        self.assertEqual(len(receipt['files']), 3)
        for entry in receipt['files']:
            self.assertEqual(entry['sha256'], M.sha((self.output / entry['name']).read_bytes()))

    def test_default_vlmcsd_entry_without_optional_gzip(self):
        (self.feed / 'Packages.gz').unlink()
        M.retain(self.package, self.output)
        self.assertFalse((self.output / 'Packages.gz').exists())
        self.assertEqual(len(json.loads((self.output / 'INDEX.json').read_text())['files']), 2)

    def test_explicit_non_vlmcsd_name_reuses_full_index_without_other_ipks(self):
        for name in ('libncurses6', 'terminfo'):
            with self.subTest(package_name=name):
                control = {'Package': name, 'Version': '6.6.20260801-r2', 'Architecture': 'aarch64_cortex-a53',
                           'Depends': 'libc'}
                blob = F.ipk(name, control, [('usr/share/' + name + '/fixture', '-', 0o644, b'package fixture\n')])
                filename = name + '_fixture.ipk'
                (self.feed / filename).write_bytes(blob)
                record = dict(control, Filename=filename, Size=str(len(blob)), SHA256sum=M.sha(blob))
                self.write_index([self.record, record])
                package = M.V.selected_ipks(self.feed, (name,))[name]
                destination = self.root / ('retained-' + name)
                M.retain(package, destination, package_name=name)
                self.assertEqual((destination / filename).read_bytes(), blob)
                self.assertEqual((destination / 'Packages.gz').read_bytes(), (self.feed / 'Packages.gz').read_bytes())
                self.assertFalse((destination / self.filename).exists())
                self.assertEqual(M.V.selected_ipks(destination, (name,))[name]['control']['Package'], name)

    def test_explicit_package_name_control_mismatch_rejected_before_mkdir(self):
        with self.assertRaisesRegex(M.V.Invalid, 'retained package identity differs'):
            M.retain(self.package, self.output, package_name='terminfo')
        self.assertFalse(self.output.exists())

    def test_invalid_explicit_package_names_rejected_before_mkdir(self):
        for name in ('../vlmcsd', '', None, 'vlmcsd/other', 'vlmcsd\nother'):
            with self.subTest(package_name=name), self.assertRaisesRegex(M.V.Invalid, 'invalid retained package identity'):
                M.retain(self.package, self.output, package_name=name)
            self.assertFalse(self.output.exists())

    def test_changed_source_ipk_after_real_selection_rejected(self):
        (self.feed / self.filename).write_bytes(self.blob + b'changed after selection')
        with self.assertRaisesRegex(M.V.Invalid, 'input changed before evidence copy'):
            M.retain(self.package, self.output)
        self.assert_no_receipt()

    def test_changed_source_index_after_real_selection_rejected(self):
        (self.feed / 'Packages').write_bytes((self.feed / 'Packages').read_bytes() + b'\n')
        with self.assertRaisesRegex(M.V.Invalid, 'input changed before evidence copy'):
            M.retain(self.package, self.output)
        self.assert_no_receipt()

    def test_changed_source_gzip_after_real_selection_rejected_by_rereader(self):
        (self.feed / 'Packages.gz').write_bytes(gzip.compress(b'changed after selection', mtime=0))
        with self.assertRaisesRegex(M.V.Invalid, 'Packages.gz differs from Packages'):
            M.retain(self.package, self.output)
        self.assert_no_receipt()

    def test_missing_source_ipk_after_selection_rejected(self):
        (self.feed / self.filename).unlink()
        with self.assertRaisesRegex(M.V.Invalid, 'retained input is not regular'):
            M.retain(self.package, self.output)
        self.assert_no_receipt()

    def test_missing_source_index_after_selection_rejected(self):
        (self.feed / 'Packages').unlink()
        with self.assertRaisesRegex(M.V.Invalid, 'retained input is not regular'):
            M.retain(self.package, self.output)
        self.assert_no_receipt()

    def test_symlink_source_after_selection_rejected(self):
        source = self.feed / self.filename
        target = self.feed / 'actual.bin'
        source.rename(target)
        source.symlink_to(target.name)
        with self.assertRaisesRegex(M.V.Invalid, 'retained input is not regular'):
            M.retain(self.package, self.output)
        self.assert_no_receipt()

    def test_existing_destination_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / 'INDEX.json'
        sentinel.write_bytes(b'prior retained evidence')
        with self.assertRaises(FileExistsError):
            M.retain(self.package, self.output)
        self.assertEqual(sentinel.read_bytes(), b'prior retained evidence')
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_forged_package_hash_rejected(self):
        package = copy.deepcopy(self.package)
        package['sha256'] = '0' * 64
        with self.assertRaisesRegex(M.V.Invalid, 'input changed before evidence copy'):
            M.retain(package, self.output)
        self.assert_no_receipt()

    def test_forged_index_hash_rejected(self):
        package = copy.deepcopy(self.package)
        package['index_sha256'] = '0' * 64
        with self.assertRaisesRegex(M.V.Invalid, 'input changed before evidence copy'):
            M.retain(package, self.output)
        self.assert_no_receipt()

    def test_mixed_package_object_cannot_bypass_retained_control_check(self):
        control = {'Package': 'terminfo', 'Version': '6.6.20260801-r2', 'Architecture': 'aarch64_cortex-a53'}
        mixed = F.ipk('terminfo', control, [('usr/share/terminfo/fixture', '-', 0o644, b'mixed package')])
        (self.feed / self.filename).write_bytes(mixed)
        package = copy.deepcopy(self.package)
        package['sha256'] = M.sha(mixed)
        with self.assertRaisesRegex(M.V.Invalid, 'IPK filename/control package mismatch'):
            M.retain(package, self.output)
        self.assert_no_receipt()


class MainPathTests(unittest.TestCase):
    setUp = RetentionTests.setUp
    write_index = RetentionTests.write_index

    def invoke(self):
        image = self.root / 'root'
        image.write_bytes(b'synthetic rootfs handle; no image execution\n')
        report = self.root / 'vlmcsd-rootfs.json'
        reads = []
        packages = {M.PACKAGE: self.p}
        def unsquashfs(argv, **kwargs):
            self.assertEqual(argv[0], 'synthetic-unsquashfs')
            self.assertEqual(Path(argv[2]), image)
            self.assertEqual(kwargs['env']['LC_ALL'], 'C')
            reads.append(tuple(map(str, argv[1:])))
            if argv[1] == '-ll':
                data = F.listing(packages).encode()
            else:
                self.assertEqual(argv[1], '-cat')
                data = F.status(packages).encode() if argv[-1] == 'usr/lib/opkg/status' else F.rootcat(packages)(argv[-1])
            return subprocess.CompletedProcess(argv, 0, data, b'')
        stdout = io.StringIO()
        with mock.patch.object(M.subprocess, 'run', side_effect=unsquashfs), contextlib.redirect_stdout(stdout):
            rc = M.main(['--rootfs', str(image), '--packages-root', str(self.feed),
                         '--retain-packages', str(self.output), '--output', str(report),
                         '--unsquashfs', 'synthetic-unsquashfs'])
        return rc, json.loads(report.read_text()), reads

    def test_main_default_vlmcsd_retention_and_real_rereader(self):
        rc, result, reads = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(result['status'], 'PASS_VLMCSD_IPK_ROOTFS_BINDING_ONLY')
        self.assertTrue(reads)
        self.assertEqual((self.output / self.filename).read_bytes(), self.blob)
        self.assertEqual((self.output / 'Packages.gz').read_bytes(), (self.feed / 'Packages.gz').read_bytes())
        self.assertEqual(M.V.selected_ipks(self.output, (M.PACKAGE,))[M.PACKAGE]['sha256'], M.sha(self.blob))

    def test_main_existing_report_fails_without_reading_or_overwriting(self):
        report = self.root / 'vlmcsd-rootfs.json'
        report.write_bytes(b'prior report')
        # main returns before the normal report parser because the old file is intentionally not JSON.
        stdout = io.StringIO()
        with mock.patch.object(M.subprocess, 'run', side_effect=AssertionError('no rootfs read allowed')), contextlib.redirect_stdout(stdout):
            rc = M.main(['--rootfs', str(self.root / 'unused-root'), '--packages-root', str(self.feed),
                         '--retain-packages', str(self.output), '--output', str(report)])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(stdout.getvalue())['status'], 'FAIL')
        self.assertEqual(report.read_bytes(), b'prior report')
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
