#!/usr/bin/env python3
"""Synthetic metadata-only diagnostics tests. No build, flash or kernel commands."""

import contextlib
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/diagnose-ax6-kernel-inputs.py'
SPEC = importlib.util.spec_from_file_location('ax6_input_diagnostics', SCRIPT)
DIAGNOSTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTICS)


def snapshot(root):
    """Include contents, links and mutation metadata, without following links."""
    rows = {}

    def visit(path):
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return
        identity = (metadata.st_mode, metadata.st_size, metadata.st_ino,
                    metadata.st_mtime_ns, metadata.st_ctime_ns)
        if stat.S_ISLNK(metadata.st_mode):
            value = os.readlink(path)
        elif stat.S_ISREG(metadata.st_mode):
            value = path.read_bytes()
        else:
            value = None
        rows[str(path.relative_to(root))] = (identity, value)
        if stat.S_ISDIR(metadata.st_mode):
            for child in sorted(path.iterdir()):
                visit(child)

    visit(root)
    return rows


class KernelInputDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ax6-input-diagnostics-')
        self.addCleanup(self.temporary.cleanup)
        # macOS may spell its temporary directory through a system symlink.
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / 'inputs'
        self.root.mkdir()
        self.outside = self.base / 'outside'
        self.outside.mkdir()
        (self.outside / 'sentinel').write_bytes(b'outside must remain unchanged\n')
        self.output = self.base / 'diagnostics.json'

    def put(self, path, data=b'synthetic input\n'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def kernel(self, name='linux-6.18.38', root=None):
        kernel = (self.root if root is None else root) / name
        for filename in ('include/linux/list.h', 'kernel/module/main.c',
                         'include/linux/module.h'):
            self.put(kernel / filename)
        return kernel

    def run_cli(self, root=None, output=None, cwd=None):
        root = self.root if root is None else root
        output = self.output if output is None else output
        before = snapshot(self.root), snapshot(self.outside)
        result = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), '--root', str(root), '--output', str(output)],
            cwd=self.base if cwd is None else cwd,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
            text=True, capture_output=True, timeout=15, check=False)
        self.assertEqual(before, (snapshot(self.root), snapshot(self.outside)),
                         'diagnostic mutated fixtures or wrote into root')
        return result

    def report(self, root=None, output=None, cwd=None):
        result = self.run_cli(root, output, cwd)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
        report = json.loads((self.output if output is None else output).read_text())
        self.assertEqual(report['status'], 'DIAGNOSTIC_ONLY_NOT_SELECTOR_SUCCESS')
        self.assertIs(report['selector_evaluated'], False)
        self.assertIs(report['workflow_assertions_authoritative'], True)
        self.assertIs(report['scan']['follow_symlinks'], False)
        self.assertEqual(report['scan']['mindepth'], 4)
        self.assertEqual(report['scan']['maxdepth'], 4)
        return report

    def assert_write_failure(self, output, root=None):
        result = self.run_cli(root, output)
        self.assertNotEqual(result.returncode, 0)
        error = json.loads(result.stderr)
        self.assertEqual(error['status'], 'DIAGNOSTIC_REPORT_WRITE_FAILED')
        self.assertIs(error['selector_evaluated'], False)

    def test_missing_root_is_report_not_selector_success(self):
        self.root.rmdir()
        report = self.report()
        self.assertFalse(self.root.exists())
        self.assertEqual(report['root']['state'], 'missing')
        self.assertIs(report['root']['exists'], False)
        self.assertEqual(report['root']['direct_subdirectories'], [])
        self.assertEqual(report['candidate_count'], 0)
        self.assertEqual(report['candidate_cardinality'], 'zero')
        self.assertIs(report['scan']['complete'], False)

    def test_empty_root(self):
        report = self.report()
        self.assertEqual(report['root']['state'], 'directory')
        self.assertIs(report['root']['exists'], True)
        self.assertEqual(report['root']['direct_subdirectories'], [])
        self.assertEqual(report['candidates'], [])
        self.assertEqual(report['candidate_cardinality'], 'zero')
        self.assertTrue(report['scan']['complete'])

    def test_one_complete_candidate_with_spaces_and_newlines(self):
        name = 'linux-6.18 space\nsecond line'
        self.kernel(name)
        report = self.report()
        self.assertEqual(report['candidate_count'], 1)
        self.assertEqual(report['candidate_cardinality'], 'one')
        self.assertEqual(report['root']['direct_subdirectories'], [name])
        row = report['candidates'][0]
        self.assertEqual(row['path'], name + '/include/linux/list.h')
        self.assertEqual(row['kernel_directory'], name)
        for key in ('header', 'module_main_c', 'module_h'):
            self.assertEqual(row[key]['state'], 'nonempty')
            self.assertTrue(row[key]['exists'])
            self.assertTrue(row[key]['regular_file'])
            self.assertTrue(row[key]['nonempty'])
            self.assertEqual(row[key]['size_bytes'], len(b'synthetic input\n'))
        self.assertIn('space\\nsecond', self.output.read_text())
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)

    def test_multiple_candidates_are_all_reported_without_selection(self):
        self.kernel('linux-z')
        self.kernel('linux-a')
        report = self.report()
        self.assertEqual(report['candidate_count'], 2)
        self.assertEqual(report['candidate_cardinality'], 'multiple')
        self.assertEqual([row['kernel_directory'] for row in report['candidates']],
                         ['linux-a', 'linux-z'])
        self.assertNotIn('selected_kernel', report)

    def test_exact_depth_no_tools_patch_quilt_or_toolchain_fallback(self):
        for filename in ('include/linux/list.h',
                         'linux-real/tools/include/linux/list.h',
                         'linux-real/.pc/change/include/linux/list.h',
                         '.patch/linux-copy/include/linux/list.h',
                         'toolchain-a/linux-copy/include/linux/list.h'):
            self.put(self.root / filename)
        report = self.report()
        self.assertEqual(report['candidate_count'], 0)
        self.assertEqual(report['root']['direct_subdirectories'],
                         ['.patch', 'include', 'linux-real', 'toolchain-a'])

    def test_full_find_path_pattern_keeps_suspicious_matches_diagnostic_only(self):
        # find's -path wildcard can span slashes, including a linux-* root.
        root = self.root / 'linux-qualcommax_ipq807x'
        for name in ('.patch', '.pc', 'toolchain-a'):
            self.kernel(name, root)
        report = self.report(root=root)
        self.assertEqual(report['candidate_count'], 3)
        self.assertEqual(report['candidate_cardinality'], 'multiple')
        for row in report['candidates']:
            self.assertTrue(row['provenance_flags'])

    def test_relative_root_matching_does_not_gain_an_absolute_linux_prefix(self):
        cwd = self.root / 'linux-workspace'
        root = cwd / 'plain-root'
        self.kernel('.patch', root)
        self.kernel('linux-real', root)
        report = self.report(root='plain-root', cwd=cwd)
        self.assertEqual(report['scan']['root_argument'], 'plain-root')
        self.assertEqual(report['candidate_count'], 1)
        self.assertEqual(report['candidates'][0]['kernel_directory'], 'linux-real')

    def test_dot_and_dot_prefixed_roots_preserve_find_matching(self):
        root = self.root / 'linux-root'
        self.kernel('plain-copy', root)
        self.kernel('linux-real', root)
        report = self.report(root='./linux-root', cwd=self.root)
        self.assertEqual(report['candidate_count'], 2)
        report = self.report(root='.', cwd=root, output=self.base / 'dot-root.json')
        self.assertEqual(report['candidate_count'], 1)
        self.assertEqual(report['candidates'][0]['kernel_directory'], 'linux-real')

    def test_root_and_output_names_with_spaces_and_newlines_round_trip(self):
        root = self.root / 'root space\nline'
        self.kernel(root=root)
        output = self.base / 'report space\nline.json'
        report = self.report(root=root, output=output)
        self.assertEqual(report['root']['path'], str(root))
        self.assertEqual(report['scan']['root_argument'], str(root))
        self.assertEqual(report['candidate_count'], 1)

    def test_zero_byte_header_remains_a_candidate(self):
        kernel = self.kernel()
        (kernel / 'include/linux/list.h').write_bytes(b'')
        report = self.report()
        self.assertEqual(report['candidate_count'], 1)
        header = report['candidates'][0]['header']
        self.assertEqual(header['state'], 'empty')
        self.assertTrue(header['exists'])
        self.assertIs(header['nonempty'], False)
        self.assertEqual(header['size_bytes'], 0)

    def test_missing_header_is_zero_candidates(self):
        kernel = self.kernel()
        (kernel / 'include/linux/list.h').unlink()
        self.assertEqual(self.report()['candidate_cardinality'], 'zero')

    def test_missing_module_source_and_header_are_separate_observations(self):
        self.put(self.root / 'linux-a/include/linux/list.h')
        report = self.report()
        for key in ('module_main_c', 'module_h'):
            observed = report['candidates'][0][key]
            self.assertEqual(observed['state'], 'missing')
            self.assertIs(observed['exists'], False)
            self.assertIsNone(observed['nonempty'])
        self.assertEqual(report['candidate_cardinality'], 'one')

    def test_empty_module_files_are_not_missing(self):
        kernel = self.kernel()
        for filename in ('kernel/module/main.c', 'include/linux/module.h'):
            (kernel / filename).write_bytes(b'')
        report = self.report()
        for key in ('module_main_c', 'module_h'):
            observed = report['candidates'][0][key]
            self.assertEqual(observed['state'], 'empty')
            self.assertTrue(observed['exists'])
            self.assertIs(observed['nonempty'], False)

    def test_symlink_directories_at_each_scan_level_are_not_followed(self):
        external = self.kernel('linux-external', self.outside)
        (self.root / 'linux-linked').symlink_to(external, target_is_directory=True)
        (self.root / 'linux-middle').mkdir()
        (self.root / 'linux-middle/include').symlink_to(external / 'include',
                                                      target_is_directory=True)
        (self.root / 'linux-leaf/include').mkdir(parents=True)
        (self.root / 'linux-leaf/include/linux').symlink_to(external / 'include/linux',
                                                         target_is_directory=True)
        report = self.report()
        self.assertEqual(report['candidate_count'], 0)
        self.assertEqual(report['root']['direct_subdirectories'], ['linux-leaf', 'linux-middle'])
        self.assertEqual(report['skipped_symlinks'],
                         ['linux-leaf/include/linux', 'linux-linked', 'linux-middle/include'])

    def test_symlink_and_dangling_header_files_are_not_candidates(self):
        for name, target in (('linux-linked', self.outside / 'sentinel'),
                             ('linux-dangling', self.outside / 'missing')):
            header = self.root / name / 'include/linux/list.h'
            header.parent.mkdir(parents=True)
            header.symlink_to(target)
        report = self.report()
        self.assertEqual(report['candidate_count'], 0)
        self.assertEqual(len(report['skipped_symlinks']), 2)

    def test_symlink_module_files_are_not_followed(self):
        kernel = self.kernel()
        for filename in ('kernel/module/main.c', 'include/linux/module.h'):
            path = kernel / filename
            path.unlink()
            path.symlink_to(self.outside / 'sentinel')
        report = self.report()
        for key in ('module_main_c', 'module_h'):
            self.assertEqual(report['candidates'][0][key]['state'], 'symlink')
            self.assertIsNone(report['candidates'][0][key]['nonempty'])

    def test_module_directory_symlink_is_not_traversed(self):
        kernel = self.kernel()
        module = kernel / 'kernel/module'
        (module / 'main.c').unlink()
        module.rmdir()
        self.put(self.outside / 'main.c')
        module.symlink_to(self.outside, target_is_directory=True)
        report = self.report()
        observed = report['candidates'][0]['module_main_c']
        self.assertEqual(observed['state'], 'blocked_symlink')
        self.assertEqual(observed['blocked_at'], 'linux-6.18.38/kernel/module')
        self.assertIsNone(observed['exists'])

    def test_symlink_to_directory_inside_root_is_also_not_followed(self):
        kernel = self.kernel()
        (self.root / 'linux-alias').symlink_to(kernel, target_is_directory=True)
        report = self.report()
        self.assertEqual(report['candidate_count'], 1)
        self.assertIn('linux-alias', report['skipped_symlinks'])

    def test_symlink_root_and_symlink_ancestor_are_not_followed(self):
        self.kernel()
        alias = self.base / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        for index, root in enumerate((alias, alias / 'linux-6.18.38')):
            with self.subTest(root=root):
                report = self.report(root=root, output=self.base / ('alias-{}.json'.format(index)))
                self.assertEqual(report['root']['state'], 'blocked_symlink')
                self.assertEqual(report['root']['blocked_at'], str(alias))
                self.assertEqual(report['candidate_count'], 0)
                self.assertFalse(report['scan']['complete'])

    def test_non_directory_root_is_reported(self):
        self.root.rmdir()
        self.root.write_bytes(b'not a directory')
        report = self.report()
        self.assertEqual(report['root']['state'], 'blocked_not_directory')
        self.assertTrue(report['root']['exists'])
        self.assertEqual(report['candidate_count'], 0)

    def test_non_regular_header_and_module_inputs(self):
        kernel = self.kernel()
        source = kernel / 'kernel/module/main.c'
        source.unlink()
        source.mkdir()
        self.assertEqual(self.report()['candidates'][0]['module_main_c']['state'], 'directory')
        (kernel / 'include/linux/list.h').unlink()
        (kernel / 'include/linux/list.h').mkdir()
        report = self.report(output=self.base / 'directory-header.json')
        self.assertEqual(report['candidate_count'], 0)

    def test_rerun_refuses_existing_output_without_changing_it(self):
        self.kernel()
        self.report()
        before = snapshot(self.output)
        self.assert_write_failure(self.output)
        self.assertEqual(snapshot(self.output), before)

    def test_existing_directory_and_symlink_outputs_are_refused(self):
        outputs = [self.base / 'existing-dir', self.base / 'linked-report',
                   self.base / 'dangling-report']
        outputs[0].mkdir()
        outputs[1].symlink_to(self.outside / 'sentinel')
        outputs[2].symlink_to(self.outside / 'absent')
        for output in outputs:
            with self.subTest(output=output):
                before = snapshot(output)
                self.assert_write_failure(output)
                self.assertEqual(snapshot(output), before)

    def test_output_parent_missing_file_or_symlink_fails_without_creation(self):
        self.put(self.base / 'parent-file')
        (self.base / 'parent-link').symlink_to(self.outside, target_is_directory=True)
        for parent in ('absent-parent', 'parent-file', 'parent-link'):
            with self.subTest(parent=parent):
                self.assert_write_failure(self.base / parent / 'report.json')
        self.assertFalse((self.base / 'absent-parent').exists())
        self.assertFalse((self.outside / 'report.json').exists())

    def test_output_in_root_or_equal_to_root_is_refused(self):
        self.kernel()
        for output in (self.root, self.root / 'report.json',
                       self.root / 'missing-parent/report.json'):
            with self.subTest(output=output):
                self.assert_write_failure(output)

    def test_output_in_missing_root_is_refused_without_creating_root(self):
        self.root.rmdir()
        self.assert_write_failure(self.root / 'report.json')
        self.assertFalse(self.root.exists())

    def test_parent_traversal_paths_are_refused(self):
        self.assert_write_failure(self.base / 'outside/../report.json')
        self.assert_write_failure(self.output, root=self.root / '..')

    def test_write_failure_returns_nonzero_and_removes_partial_output(self):
        self.kernel()
        before = snapshot(self.root), snapshot(self.outside)
        stderr = io.StringIO()
        with mock.patch.object(DIAGNOSTICS.os, 'fsync',
                               side_effect=OSError(errno.ENOSPC, 'synthetic disk full')):
            with contextlib.redirect_stderr(stderr):
                status = DIAGNOSTICS.main(['--root', str(self.root),
                                           '--output', str(self.output)])
        self.assertNotEqual(status, 0)
        self.assertEqual(json.loads(stderr.getvalue())['status'], 'DIAGNOSTIC_REPORT_WRITE_FAILED')
        self.assertFalse(self.output.exists())
        self.assertEqual(before, (snapshot(self.root), snapshot(self.outside)))

    def test_partial_stream_write_failure_returns_nonzero(self):
        self.kernel()
        before = snapshot(self.root), snapshot(self.outside)
        real_fdopen = os.fdopen

        class FailingStream:
            def __init__(self, *args, **kwargs):
                self.stream = real_fdopen(*args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def write(self, payload):
                self.stream.write(payload[:10])
                self.stream.flush()
                raise OSError(errno.ENOSPC, 'synthetic partial write')

        stderr = io.StringIO()
        with mock.patch.object(DIAGNOSTICS.os, 'fdopen', side_effect=FailingStream):
            with contextlib.redirect_stderr(stderr):
                status = DIAGNOSTICS.main(['--root', str(self.root),
                                           '--output', str(self.output)])
        self.assertNotEqual(status, 0)
        self.assertEqual(json.loads(stderr.getvalue())['status'], 'DIAGNOSTIC_REPORT_WRITE_FAILED')
        self.assertFalse(self.output.exists())
        self.assertEqual(before, (snapshot(self.root), snapshot(self.outside)))

    def test_scan_error_is_explicit_and_not_a_complete_zero_result(self):
        before = snapshot(self.root)
        with mock.patch.object(DIAGNOSTICS.os, 'scandir', side_effect=PermissionError('synthetic')):
            status = DIAGNOSTICS.main(['--root', str(self.root), '--output', str(self.output)])
        self.assertEqual(status, 0)
        report = json.loads(self.output.read_text())
        self.assertFalse(report['scan']['complete'])
        self.assertEqual(report['errors'][0]['operation'], 'list_directory')
        self.assertEqual(report['candidate_count'], 0)
        self.assertEqual(snapshot(self.root), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
