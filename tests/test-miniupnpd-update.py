#!/usr/bin/env python3
"""Pure updater controls; no target daemon execution or firewall operations."""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mini_update', ROOT / 'AX6-IPQ/scripts/apply-miniupnpd-update.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class Updater(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.feed = self.root / 'feed'
        self.pkg = self.feed / 'net/miniupnpd'; self.pkg.mkdir(parents=True)
        self.assets = self.root / 'assets'; self.assets.mkdir()
        self.before = {'Makefile': b'old\n', 'files/keep': b'UCI\n', 'obsolete.patch': b'old patch\n'}
        self.after = {'Makefile': b'new\n', 'files/keep': b'UCI\n', 'test.sh': b'source test only\n'}
        for name, raw in self.before.items():
            p = self.pkg / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
        self.data = {'version': '2.3.11', 'candidate_commit': 'reviewed', 'source_sha256': 'fixed',
                     'baseline': {n: m.digest(r) for n, r in self.before.items()},
                     'candidate': {n: m.digest(r) for n, r in self.after.items()},
                     'payload': {'Makefile': '0000.data', 'test.sh': '0001.data'},
                     'payload_modes': {'Makefile': '100644', 'test.sh': '100755'}}
        for name, file in self.data['payload'].items(): (self.assets / file).write_bytes(self.after[name])
        self.addCleanup(patch.stopall)
        patch.object(m, 'ASSETS', self.assets).start()
        # Synthetic transactions test the updater, never simulate an SSDK/target result.
        patch.object(m, 'load', return_value=self.data).start()

    def test_apply_and_idempotence(self):
        self.assertEqual(m.apply(self.feed)['status'], 'APPLIED_SELECTED_PACKAGE_ONLY')
        self.assertEqual(m.inventory(self.pkg), self.data['candidate'])
        self.assertEqual((self.pkg/'test.sh').stat().st_mode & 0o777, 0o755)
        self.assertEqual(m.apply(self.feed)['status'], 'ALREADY_REVIEWED')

    def test_candidate_mode_changes_rejected(self):
        m.apply(self.feed)
        (self.pkg/'test.sh').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'candidate payload mode'): m.apply(self.feed)

    def test_foreign_changes_rejected(self):
        for name in ('Makefile', 'unexpected'):
            with self.subTest(name=name):
                p = self.pkg / name; old = p.read_bytes() if p.exists() else None
                p.write_bytes(b'foreign'); snapshot = m.inventory(self.pkg)
                with self.assertRaisesRegex(ValueError, 'unknown or locally modified'): m.apply(self.feed)
                self.assertEqual(snapshot, m.inventory(self.pkg))
                if old is None: p.unlink()
                else: p.write_bytes(old)

    def test_symlink_rejected_without_following(self):
        (self.pkg / 'bad').symlink_to(self.assets)
        with self.assertRaisesRegex(ValueError, 'nonregular'): m.apply(self.feed)

    def test_write_failure_restores_exact_prefix(self):
        (self.pkg/'Makefile').chmod(0o600)
        original = Path.write_bytes; count = 0
        def fail_once(path, raw):
            nonlocal count
            count += 1
            if count == 2: raise OSError('injected write failure')
            return original(path, raw)
        with patch.object(Path, 'write_bytes', fail_once):
            with self.assertRaisesRegex(OSError, 'injected'): m.apply(self.feed)
        self.assertEqual(m.inventory(self.pkg), self.data['baseline'])
        self.assertEqual((self.pkg/'Makefile').stat().st_mode & 0o777, 0o600)

    def test_removed_file_failure_restores_all_changes(self):
        original = Path.unlink; fired = False
        def fail_once(path, *a, **k):
            nonlocal fired
            if path.name == 'obsolete.patch' and not fired:
                fired = True; raise OSError('injected unlink failure')
            return original(path, *a, **k)
        with patch.object(Path, 'unlink', fail_once):
            with self.assertRaisesRegex(OSError, 'injected'): m.apply(self.feed)
        self.assertEqual(m.inventory(self.pkg), self.data['baseline'])


class RealAssets(unittest.TestCase):
    def test_actual_frozen_payload_and_version(self):
        data = m.load()
        self.assertEqual(data['version'], '2.3.11')
        self.assertEqual(len(data['baseline']), 16)
        self.assertEqual(len(data['candidate']), 15)
        self.assertEqual(len(data['payload']), 5)
        self.assertEqual(data['payload_modes']['test.sh'], '100755')
        for n in set(data['baseline']) & set(data['candidate']) - set(data['payload']):
            self.assertEqual(data['baseline'][n], data['candidate'][n])
        self.assertEqual(data['source_sha256'], '91994b127da735b2c97f19992e34420648c0e8c4ace8a4bcb0596e7685c48678')

    def test_workflow_hook_before_configuration(self):
        diy = (ROOT / 'AX6-IPQ/diy.sh').read_text()
        self.assertEqual(diy.count('apply-miniupnpd-update.py'), 1)


if __name__ == '__main__': unittest.main()
