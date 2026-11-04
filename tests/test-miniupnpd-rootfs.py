#!/usr/bin/env python3
"""Pure payload binding controls; synthetic ELF identity is not a driver result."""
import importlib.util
from pathlib import Path
import struct
import sys
import tarfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mini_rootfs', ROOT / '.github/scripts/verify-miniupnpd-rootfs.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class Rootfs(unittest.TestCase):
    def setUp(self):
        self.binary = bytearray(64); self.binary[:7] = b'\x7fELF\x02\x01\x01'; struct.pack_into('<H', self.binary, 18, 183)
        struct.pack_into('<H', self.binary, 16, 3)
        member = tarfile.TarInfo(m.BINARY); member.mode = 0o755; member.size = 64
        self.package = {'control': {'Package': m.PACKAGE, 'Version': m.VERSION, 'Architecture': 'aarch64_cortex-a53'},
                        'payload': {m.BINARY: (member, bytes(self.binary))}, 'sha256': 'synthetic-reader-control'}
        self.status = f'Package: {m.PACKAGE}\nVersion: {m.VERSION}\nArchitecture: aarch64_cortex-a53\nStatus: install ok installed\n\n'
        self.listing = f'-rwxr-xr-x root/root 64 2026-11-04 00:00 squashfs-root/{m.BINARY}\n'

    def verify(self, status=None, listing=None, read=None):
        return m.verify(self.package, self.status if status is None else status,
                        self.listing if listing is None else listing, read or (lambda _: bytes(self.binary)))

    def test_valid_binding_and_hold(self):
        self.assertEqual(self.verify()['status'], 'PASS_MINIUPNPD_IPK_ROOTFS_ONLY')
        self.assertFalse(self.verify()['runtime_approved'])
        self.verify(status=self.status.replace('install ok', 'install hold'))

    def test_version_state_architecture_and_legacy_rejected(self):
        for old, new in [('2.3.11-r1', '2.3.9-r3'), ('aarch64_cortex-a53', 'x86_64'),
                         ('install ok installed', 'deinstall ok installed'),
                         ('install ok installed', 'install broken installed')]:
            with self.subTest(new=new):
                with self.assertRaises(ValueError): self.verify(status=self.status.replace(old, new))
        with self.assertRaises(ValueError): self.verify(status=self.status + 'Package: miniupnpd-iptables\n\n')
        with self.assertRaises(ValueError): self.verify(status=self.status + self.status)

    def test_different_rootfs_bytes_or_mode_rejected(self):
        with self.assertRaises(ValueError): self.verify(read=lambda _: b'other')
        with self.assertRaises(ValueError): self.verify(listing=self.listing.replace('-rwxr-xr-x', '-rw-r--r--'))

    def test_wrong_binary_machine_rejected(self):
        info, raw = self.package['payload'][m.BINARY]
        wrong = bytearray(raw); struct.pack_into('<H', wrong, 18, 62)
        self.package['payload'][m.BINARY] = info, bytes(wrong)
        with self.assertRaises(ValueError): self.verify()


if __name__ == '__main__': unittest.main()
