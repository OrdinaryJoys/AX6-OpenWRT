#!/usr/bin/env python3
"""Offline source-container and workflow controls; never Linux runtime approval."""
import ast
import importlib.util
import io
from pathlib import Path
import re
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('phy_smoke', ROOT / '.github/scripts/run-ax6-phy-host-smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SourceContainer(unittest.TestCase):
    def archive(self, entries):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name, kind in entries:
                item = tarfile.TarInfo(name)
                if kind == 'file':
                    raw = b'TESTONLY source data; not an executable\n'
                    item.size = len(raw); archive.addfile(item, io.BytesIO(raw))
                else:
                    item.type = {'symlink': tarfile.SYMTYPE, 'hardlink': tarfile.LNKTYPE,
                                 'directory': tarfile.DIRTYPE}[kind]
                    item.linkname = 'outside'; archive.addfile(item)
        return stream.getvalue()

    def unpack(self, entries):
        with tempfile.TemporaryDirectory() as directory:
            return smoke.unpack(self.archive(entries), Path(directory) / 'source')

    def test_regular_source_data(self):
        result = self.unpack([('src', 'directory'), ('src/source.c', 'file')])
        self.assertEqual(set(result), {'src/source.c'})

    def test_parent_escape(self):
        with self.assertRaises(ValueError): self.unpack([('../outside', 'file')])

    def test_absolute_path(self):
        with self.assertRaises(ValueError): self.unpack([('/outside', 'file')])

    def test_symlink(self):
        with self.assertRaises(ValueError): self.unpack([('source.c', 'symlink')])

    def test_hardlink(self):
        with self.assertRaises(ValueError): self.unpack([('source.c', 'hardlink')])

    def test_git_metadata(self):
        with self.assertRaises(ValueError): self.unpack([('.git/config', 'file')])

    def test_duplicate_member(self):
        with self.assertRaises(ValueError): self.unpack([('source.c', 'file'), ('source.c', 'file')])


class FixedAdmission(unittest.TestCase):
    def setUp(self):
        self.data = smoke.load(smoke.CONTRACT)

    def reject(self):
        with mock.patch.object(smoke, 'load', return_value=self.data):
            with self.assertRaises((ValueError, OSError)): smoke.contract()

    def test_current_fixed_contract(self):
        self.assertEqual(smoke.contract()['scope'], 'PHY37_HOST_SUBSET_NO_050_NO_FIRMWARE')

    def test_boolean_schema(self):
        self.data['schema'] = True; self.reject()

    def test_source_not_full_sha(self):
        self.data['source_ref'] = 'moving-branch'; self.reject()

    def test_changed_fixture_digest(self):
        self.data['fixture_sha256'] = '0' * 64; self.reject()

    def test_changed_profile_digest(self):
        self.data['mdio37_profile_sha256'] = '0' * 64; self.reject()

    def test_changed_fixture_metadata(self):
        self.data['fixture_metadata_sha256'] = '0' * 64; self.reject()

    def test_fixture_path_escape(self):
        self.data['fixture'] = '../outside'; self.reject()


class WorkflowBoundary(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/lint.yml').read_text()

    def test_modes_are_explicit_and_exclusive(self):
        self.assertIn("if: ${{ github.event_name == 'workflow_dispatch' && inputs.phy_host_only }}", self.workflow)
        self.assertIn("if: ${{ github.event_name != 'workflow_dispatch' || !inputs.phy_host_only }}", self.workflow)
        for event in ('workflow_dispatch', 'push', 'pull_request'):
            for flag in (True, False):
                host = event == 'workflow_dispatch' and flag
                normal = event != 'workflow_dispatch' or not flag
                self.assertNotEqual(host, normal)

    def test_manual_input_defaults_to_regular_lint(self):
        entry = self.workflow.split('      phy_host_only:\n', 1)[1].split('\n  push:', 1)[0]
        self.assertIn('type: boolean', entry); self.assertIn('default: false', entry)

    def test_host_job_has_no_firmware_or_device_step(self):
        entry = self.workflow.split('  phy-host:\n', 1)[1].split('\n  lint:\n', 1)[0]
        self.assertIn('--source-root source --cc gcc-11 --output phy-host-evidence', entry)
        self.assertIn('runs-on: ubuntu-22.04', entry)
        for text in ('make ', 'sysupgrade', 'ssh ', 'build-AX6-NSS.yml', 'gh workflow run'):
            self.assertNotIn(text, entry)

    def test_host_actions_match_reviewed_official_commits(self):
        entry = self.workflow.split('  phy-host:\n', 1)[1].split('\n  lint:\n', 1)[0]
        actions = re.findall(r'^\s+(?:-\s+)?uses:\s*([^\s#]+)', entry, re.M)
        self.assertEqual(actions, [
            'actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0',
            'actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0',
            'actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a',
        ])

    def test_native_runner_has_closed_record_labels(self):
        code = ast.parse((ROOT / '.github/scripts/run-ax6-phy-host-smoke.py').read_text())
        labels = set(); dynamic = []
        for node in ast.walk(code):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'record':
                if isinstance(node.args[0], ast.Constant): labels.add(node.args[0].value)
                else: dynamic.append(ast.dump(node.args[0]))
        self.assertEqual(labels, {'source-head', 'gcc-version', 'native-canary-controls',
                                  'native-phy-campaign', 'source-clean'})
        self.assertEqual(len(dynamic), 1)
        self.assertIn('patch-%02d', dynamic[0])


if __name__ == '__main__':
    unittest.main()
