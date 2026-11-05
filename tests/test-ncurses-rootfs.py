#!/usr/bin/env python3
"""Synthetic package/reader controls only; no target library is executed."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


F = load('ncurses_image_fixtures', ROOT / 'tests/test-vim-rootfs.py')
M = load('ncurses_image_gate', ROOT / '.github/scripts/verify-ncurses-rootfs.py')


class Tests(unittest.TestCase):
    def setUp(self):
        self.packages = {}
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
            self.packages[name] = {'control': actual, 'payload': payload, 'sha256': M.sha(raw)}

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


if __name__ == '__main__':
    unittest.main()
