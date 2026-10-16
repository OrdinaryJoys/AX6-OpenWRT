#!/usr/bin/env python3
"""Focused gate tests; these do not simulate a successful target compiler."""
import importlib.util
import gzip
import io
import json
from pathlib import Path
import struct
import tempfile
import tarfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rpcd_gate', ROOT / '.github/scripts/validate-rpcd-components.py')
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class Gates(unittest.TestCase):
    def test_stock_selections(self):
        for variant in ('stock', 'expand'):
            config = (ROOT / ('AX6-IPQ/.config-' + variant)).read_text()
            self.assertFalse(GATE.checked_mode(config))
            self.assertEqual(set(GATE.package_set(config)), {'rpcd', 'rpcd-mod-file', 'rpcd-mod-iwinfo', 'rpcd-mod-ucode'})

    def test_mode_switch_preserves_unrelated_config(self):
        config = 'CONFIG_PACKAGE_rpcd=y\nCONFIG_OTHER=y\n'
        for enabled in (True, False):
            switched = GATE.configure(config, enabled)
            self.assertEqual(GATE.checked_mode(switched), enabled)
            self.assertTrue(switched.startswith(config))
            self.assertEqual(switched, GATE.configure(switched, enabled))

    def test_duplicate_and_invalid_modes_rejected(self):
        for value in ('=y\nCONFIG_RPCD_CHECKED_UCI_SUPPORT=n', '=m', '="ON"'):
            with self.assertRaises(ValueError):
                GATE.checked_mode('CONFIG_RPCD_CHECKED_UCI_SUPPORT' + value)

    def test_missing_required_plugin_rejected(self):
        config = (ROOT / 'AX6-IPQ/.config-stock').read_text()
        with self.assertRaises(ValueError):
            GATE.package_set(config.replace('CONFIG_PACKAGE_rpcd-mod-file=y', '# removed'))

    def test_elf_architecture_type_and_class(self):
        valid = bytearray(64)
        valid[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<HH', valid, 16, 3, 183)
        self.assertEqual(GATE.elf(valid), GATE.sha(valid))
        for offset, value in ((4, 1), (5, 2), (16, 1), (18, 62)):
            changed = valid.copy()
            changed[offset] = value
            with self.assertRaises(ValueError):
                GATE.elf(changed)

    def test_prepared_source_mutation_missing_and_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'uci.c'
            file.write_bytes(b'reviewed')
            provenance = {'prepared_files': {'uci.c': GATE.sha(b'reviewed')}}
            self.assertEqual(GATE.prepared(root, provenance), provenance['prepared_files'])
            file.write_bytes(b'mutated')
            with self.assertRaises(ValueError):
                GATE.prepared(root, provenance)
            file.unlink()
            with self.assertRaises(ValueError):
                GATE.prepared(root, provenance)
            file.symlink_to(root / 'missing')
            with self.assertRaises(ValueError):
                GATE.prepared(root, provenance)

    def test_failed_ON_build_restores_OFF_without_retrying_compile(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            package = source / 'package/system/rpcd'
            package.mkdir(parents=True)
            (source / '.config').write_text((ROOT / 'AX6-IPQ/.config-stock').read_text())
            (package / 'provenance.json').write_text(json.dumps({'default_checked_support': False}))
            destination = Path(directory) / 'evidence'
            with patch.object(GATE.subprocess, 'run', side_effect=[SimpleNamespace(returncode=23), SimpleNamespace(returncode=0)]) as run:
                with self.assertRaisesRegex(ValueError, 'ON-defconfig'):
                    GATE.build(source, destination)
            self.assertFalse(GATE.checked_mode((source / '.config').read_text()))
            self.assertEqual(run.call_count, 2)
            self.assertEqual(len(json.loads((destination / 'commands.json').read_text())), 2)

    def test_rootfs_rejects_enabled_config_before_reading_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config'
            config.write_text('CONFIG_RPCD_CHECKED_UCI_SUPPORT=y\n')
            with self.assertRaisesRegex(ValueError, 'experimental API is ON'):
                GATE.rootfs(Path(directory) / 'missing-image', Path(directory), config)

    def test_rootfs_actual_ipk_binding_and_negative_controls(self):
        def archive(files):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode='w') as tar:
                for name, mode, content in files:
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode = len(content), mode
                    tar.addfile(entry, io.BytesIO(content))
            return gzip.compress(output.getvalue(), mtime=0)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'OFF').mkdir()
            config = root / 'config'
            config.write_text((ROOT / 'AX6-IPQ/.config-stock').read_text())
            records, contents, listing, statuses = {}, {}, [], []
            binary = bytearray(64)
            binary[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<HH', binary, 16, 3, 183)
            for name, path in GATE.package_set(config.read_text()).items():
                data = bytes(binary) + name.encode()
                control = {'Package': name, 'Version': '2026.06.04~28faf640-r2', 'Architecture': 'aarch64_cortex-a53'}
                text = ''.join(key + ': ' + value + '\n' for key, value in control.items())
                package = archive([('debian-binary', 0o644, b'2.0\n'),
                                   ('control.tar.gz', 0o644, archive([('control', 0o644, text.encode())])),
                                   ('data.tar.gz', 0o644, archive([(path, 0o755, data)]))])
                filename = name + '_fixture.ipk'
                (root / 'OFF' / filename).write_bytes(package)
                records[name] = {'control': control, 'payload_path': path, 'payload_sha256': GATE.sha(data),
                                 'payload_mode': 0o755, 'ipk_sha256': GATE.sha(package), 'ipk': filename}
                contents[path] = data
                listing.append(f'-rwxr-xr-x root/root {len(data)} 2026-10-16 00:00 squashfs-root/{path}')
                statuses.append(text + 'Status: hold ok installed\n')
            status = '\n'.join(statuses).encode()
            listing_text = ('\n'.join(listing) + '\n').encode()
            (root / 'components.json').write_text(json.dumps({'modes': {'ON': {}, 'OFF': {'packages': records}}}))

            def output(argv):
                if argv[1] == '-ll':
                    return listing_text
                return status if argv[-1] == 'usr/lib/opkg/status' else contents[argv[-1]]

            with patch.object(GATE.subprocess, 'check_output', side_effect=output):
                GATE.rootfs(root / 'image', root, config)
                self.assertTrue((root / 'ROOTFS-CONSISTENCY.json').is_file())
                contents['sbin/rpcd'] += b'wrong payload'
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    GATE.rootfs(root / 'image', root, config)
                contents['sbin/rpcd'] = contents['sbin/rpcd'][:-13]
                listing_text = listing_text.replace(b'-rwxr-xr-x', b'lrwxrwxrwx', 1)
                with self.assertRaises(ValueError):
                    GATE.rootfs(root / 'image', root, config)


if __name__ == '__main__':
    unittest.main()
