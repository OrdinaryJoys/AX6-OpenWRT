#!/usr/bin/env python3
"""Image/package parser controls only; no image binaries are executed."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
