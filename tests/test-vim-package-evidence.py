#!/usr/bin/env python3
"""Offline acquisition controls; fixtures are not real image acceptance."""
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


C = load(ROOT / '.github/scripts/collect-vim-package-evidence.py', 'vim_package_collector_tests')
V = load(ROOT / '.github/scripts/verify-vim-rootfs.py', 'vim_package_gate_tests')
T = load(ROOT / 'tests/test-vim-rootfs.py', 'vim_package_fixture_tests')


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.feed = self.root / 'packages' / 'aarch64_cortex-a53' / 'packages'
        self.feed.mkdir(parents=True)
        self.image = self.root / 'root.squashfs'
        self.image.write_bytes(b'fixture image identity, no target execution')
        self.prepared = self.root / 'prepared.json'
        self.provenance = self.root / 'provenance.json'
        self.prepared.write_bytes(b'{"fixture": "prepared"}\n')
        self.provenance.write_bytes(b'{"fixture": "provenance"}\n')
        self.output = self.root / 'evidence'
        self.packages = {}
        self.install(('vim-fuller', 'vim-runtime'))
        self.status = T.status(self.packages)

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, names):
        records = []
        for name in names:
            control = T.controls()[name]
            if name == 'vim-fuller':
                control['Depends'] = control['Depends'].replace('(= ', '(=')
            blob = T.ipk(name, control=control)
            filename = name + '_fixture.ipk'
            (self.feed / filename).write_bytes(blob)
            parsed, payload = C.ART.read_ipk(blob)
            self.packages[name] = {'control': parsed, 'payload': payload, 'sha256': V.sha(blob)}
            records.append(T.control_text(dict(control, Filename=filename, Size=str(len(blob)), SHA256sum=V.sha(blob))))
        (self.feed / 'Packages').write_text('\n'.join(records))
        (self.feed / 'Packages.gz').write_bytes(gzip.compress((self.feed / 'Packages').read_bytes()))

    def metadata(self, _fd, path, _executable, _limit):
        if path == 'usr/lib/opkg/status':
            return self.status.encode()
        name = Path(path).name.removesuffix('.control')
        if name in self.packages:
            return T.control_text(self.packages[name]['control']).encode()
        raise ValueError('no fixture image control')

    def invoke(self, **changes):
        values = dict(rootfs=self.image, packages_root=self.root / 'packages', prepared_source=self.prepared,
                      provenance=self.provenance, output=self.output, unsquashfs='unused-in-fixture')
        values.update(changes)
        arguments = []
        for name, value in values.items():
            arguments.extend(['--' + name.replace('_', '-'), str(value)])
        with mock.patch.object(C, 'rootcat', side_effect=self.metadata), contextlib.redirect_stdout(io.StringIO()):
            rc = C.main(arguments)
        manifest = json.loads((self.output / 'MANIFEST.json').read_text()) if (self.output / 'MANIFEST.json').is_file() else None
        return rc, manifest

    def fail(self, **changes):
        rc, manifest = self.invoke(**changes)
        self.assertEqual(rc, 1)
        if manifest:
            self.assertEqual(manifest['status'], 'COLLECTION_FAILED_NOT_ACCEPTANCE')
            self.assertFalse(manifest['is_acceptance'])
            self.assertTrue(manifest['errors'])
        return manifest

    def test_originals_retained_before_later_gate_failure(self):
        # Legal opkg serialization differs from untouched IPK/index metadata.
        self.status = self.status.replace('(=9.2.', '(= 9.2.')
        rc, manifest = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(manifest['status'], 'COLLECTED_DIAGNOSTICS_NOT_ACCEPTANCE')
        self.assertFalse(manifest['is_acceptance'])
        original = self.feed / 'vim-fuller_fixture.ipk'
        retained = self.output / 'offline-packages/aarch64_cortex-a53/packages/vim-fuller_fixture.ipk'
        self.assertEqual(retained.read_bytes(), original.read_bytes())
        self.assertEqual((self.output / 'offline-packages/aarch64_cortex-a53/packages/Packages').read_bytes(),
                         (self.feed / 'Packages').read_bytes())
        self.assertEqual((self.output / 'rootfs-metadata/opkg-status').read_text(), self.status)
        # The original new checker may be concurrently corrected. Deliberately
        # change dependency semantics for a guaranteed later strict rejection.
        poisoned = self.status.replace('libc, vim-runtime', 'vim-runtime', 1)
        with self.assertRaises(V.Invalid):
            V.verify_payload(self.packages, poisoned, T.listing(self.packages), T.rootcat(self.packages))
        self.assertEqual(retained.read_bytes(), original.read_bytes())
        for row in manifest['files']:
            data = (self.output / row['file']).read_bytes()
            self.assertEqual(row['bytes'], len(data))
            self.assertEqual(row['sha256'], hashlib.sha256(data).hexdigest())

    def test_complete_is_not_metadata_acceptance(self):
        self.status = self.status.replace('libc, vim-runtime', 'vim-runtime', 1)
        rc, report = self.invoke()
        self.assertEqual(rc, 0)
        self.assertFalse(report['is_acceptance'])
        self.assertEqual(report['gate_status'], 'NOT_RUN_BY_COLLECTOR')

    def test_missing_ipk_keeps_other_original_and_manifest(self):
        (self.feed / 'vim-fuller_fixture.ipk').unlink()
        report = self.fail()
        self.assertTrue(any(r['file'].endswith('vim-runtime_fixture.ipk') for r in report['files']))
        self.assertTrue((self.output / 'rootfs-metadata/opkg-status').is_file())

    def test_missing_index_keeps_ipks(self):
        (self.feed / 'Packages').unlink()
        report = self.fail()
        self.assertEqual(sum(r['category'] == 'original-ipk' for r in report['files']), 2)
        self.assertTrue((self.output / 'offline-packages/aarch64_cortex-a53/packages/Packages.gz').is_file())

    def test_malformed_index_preserved_not_complete(self):
        invalid = b'Package: vim-fuller\nPackage: duplicate\n'
        (self.feed / 'Packages').write_bytes(invalid)
        (self.feed / 'Packages.gz').write_bytes(gzip.compress(invalid))
        self.fail()
        self.assertEqual((self.output / 'offline-packages/aarch64_cortex-a53/packages/Packages').read_bytes(), invalid)

    def test_empty_index_preserved_not_complete(self):
        (self.feed / 'Packages').write_bytes(b'')
        (self.feed / 'Packages.gz').write_bytes(gzip.compress(b''))
        self.fail()
        self.assertEqual((self.output / 'offline-packages/aarch64_cortex-a53/packages/Packages').read_bytes(), b'')

    def test_gzip_mismatch_preserves_both_originals(self):
        wrong = gzip.compress(b'wrong but original compressed index')
        (self.feed / 'Packages.gz').write_bytes(wrong)
        self.fail()
        self.assertEqual((self.output / 'offline-packages/aarch64_cortex-a53/packages/Packages.gz').read_bytes(), wrong)

    def test_index_semantic_mismatch_collected_for_later_rejection(self):
        text = (self.feed / 'Packages').read_text().replace('libc, vim-runtime', 'libc', 1)
        (self.feed / 'Packages').write_text(text)
        (self.feed / 'Packages.gz').write_bytes(gzip.compress(text.encode()))
        rc, report = self.invoke()
        self.assertEqual(rc, 0)
        self.assertFalse(report['is_acceptance'])
        with self.assertRaises(V.Invalid):
            V.selected_ipks(self.output / 'offline-packages')

    def test_output_existing_preserved(self):
        self.output.mkdir()
        marker = self.output / 'KEEP'
        marker.write_bytes(b'keep')
        self.fail()
        self.assertEqual(marker.read_bytes(), b'keep')
        self.assertFalse((self.output / 'MANIFEST.json').exists())

    def test_output_dangling_symlink_not_followed(self):
        target = self.root / 'must-not-create'
        self.output.symlink_to(target, target_is_directory=True)
        self.fail()
        self.assertFalse(target.exists())

    def test_output_linked_ancestor(self):
        (self.root / 'linked').symlink_to(self.root, target_is_directory=True)
        self.fail(output=self.root / 'linked' / 'evidence')
        self.assertFalse(self.output.exists())

    def test_output_within_packages_rejected(self):
        self.fail(output=self.root / 'packages' / 'evidence')
        self.assertFalse((self.root / 'packages/evidence').exists())

    def test_packages_root_symlink_rejected(self):
        linked = self.root / 'linked-packages'
        linked.symlink_to(self.root / 'packages', target_is_directory=True)
        self.fail(packages_root=linked)

    def test_package_directory_symlink_rejected(self):
        (self.root / 'packages' / 'extra').symlink_to(self.feed, target_is_directory=True)
        self.fail()

    def test_ipk_symlink_rejected(self):
        original = self.feed / 'vim-fuller_fixture.ipk'
        moved = self.root / 'real.ipk'
        original.rename(moved)
        original.symlink_to(moved)
        self.fail()

    def test_dangling_index_symlink_rejected(self):
        (self.feed / 'Packages').unlink()
        (self.feed / 'Packages').symlink_to(self.root / 'missing')
        self.fail()

    def test_duplicate_candidates_rejected(self):
        original = (self.feed / 'vim-fuller_fixture.ipk').read_bytes()
        (self.feed / 'vim-fuller_duplicate.ipk').write_bytes(original)
        report = self.fail()
        self.assertEqual(len(report['candidate_inventory']['vim-fuller']), 2)
        self.assertTrue(report['candidate_inventory_complete'])
        self.assertEqual(sum(r['category'] == 'original-ipk' for r in report['files']), 3)
        self.assertEqual((self.output / 'offline-packages/aarch64_cortex-a53/packages/vim-fuller_duplicate.ipk').read_bytes(), original)
        self.assertEqual(sum(r['file'].endswith('/Packages') for r in report['files']), 1)

    def test_duplicate_candidates_across_feeds_preserve_both_full_indexes(self):
        other = self.root / 'packages' / 'aarch64_cortex-a53' / 'other-feed'
        other.mkdir()
        for filename in ('vim-fuller_fixture.ipk', 'Packages', 'Packages.gz'):
            (other / filename).write_bytes((self.feed / filename).read_bytes())
        report = self.fail()
        self.assertEqual(sum(r['category'] == 'original-ipk' for r in report['files']), 3)
        for filename in ('vim-fuller_fixture.ipk', 'Packages', 'Packages.gz'):
            retained = self.output / 'offline-packages/aarch64_cortex-a53/other-feed' / filename
            self.assertEqual(retained.read_bytes(), (other / filename).read_bytes())

    def test_overlarge_candidate_inventory(self):
        for index in range(9):
            (self.feed / ('vim-fuller_extra' + str(index) + '.ipk')).write_bytes(b'candidate')
        report = self.fail()
        self.assertFalse(report['candidate_inventory_complete'])
        self.assertEqual(len(report['candidate_inventory']['vim-fuller']), 8)
        self.assertEqual(sum('vim-fuller_' in r['file'] for r in report['files']), 8)

    def test_ipk_byte_bound_without_reading_sparse_payload(self):
        path = self.feed / 'vim-fuller_fixture.ipk'
        with path.open('wb') as stream:
            stream.truncate(C.IPK_LIMIT + 1)
        report = self.fail()
        self.assertFalse(any(r['file'].endswith('vim-fuller_fixture.ipk') for r in report['files']))

    def test_index_byte_bound(self):
        with mock.patch.object(C, 'INDEX_LIMIT', 32):
            self.fail()

    def test_total_bound_still_has_failure_manifest(self):
        with mock.patch.object(C, 'TOTAL_LIMIT', C.SMALL_LIMIT + 64):
            report = self.fail()
        self.assertLessEqual(report['copied_bytes'], 64)

    def test_optional_xxd_installed_collects_exact_third_package(self):
        self.install(('vim-fuller', 'vim-runtime', 'xxd'))
        self.status = T.status(self.packages)
        rc, report = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(report['selected_packages'], ['vim-fuller', 'vim-runtime', 'xxd'])
        self.assertEqual(report['optional_xxd_applicability'], 'INSTALLED_REQUIRED_FOR_COLLECTION')
        self.assertTrue((self.output / 'rootfs-metadata/xxd.control').is_file())

    def test_optional_xxd_not_installed_not_included(self):
        self.status += '\nPackage: xxd\nStatus: deinstall ok config-files\n'
        rc, report = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(report['optional_xxd_applicability'], 'NOT_INSTALLED')
        self.assertNotIn('xxd', report['selected_packages'])

    def test_optional_xxd_partial_state_fails_and_collects_required(self):
        self.status += '\nPackage: xxd\nStatus: install ok half-installed\n'
        report = self.fail()
        self.assertEqual(report['optional_xxd_applicability'], 'UNKNOWN_IMAGE_METADATA_FAILURE')
        self.assertEqual(sum(r['category'] == 'original-ipk' for r in report['files']), 2)

    def test_duplicate_image_status_fails_but_keeps_raw_status(self):
        self.status += '\nPackage: vim-runtime\nStatus: install ok installed\n'
        self.fail()
        self.assertEqual((self.output / 'rootfs-metadata/opkg-status').read_text(), self.status)
        for name in ('vim-fuller', 'vim-runtime'):
            self.assertEqual((self.output / ('rootfs-metadata/' + name + '.control')).read_text(),
                             T.control_text(self.packages[name]['control']))

    def test_missing_status_keeps_required_installed_controls(self):
        original = self.metadata
        def missing_status(fd, path, executable, limit):
            if path == 'usr/lib/opkg/status':
                raise ValueError('image status is missing')
            return original(fd, path, executable, limit)
        with mock.patch.object(self, 'metadata', side_effect=missing_status):
            report = self.fail()
        self.assertEqual(sum(r['category'] == 'image-metadata' for r in report['files']), 2)
        self.assertEqual(report['optional_xxd_applicability'], 'UNKNOWN_IMAGE_METADATA_FAILURE')

    def test_malformed_control_keeps_raw_control_and_other_evidence(self):
        original = self.metadata
        invalid = b'Package: vim-fuller\nPackage: duplicate\n'
        def malformed_control(fd, path, executable, limit):
            if path.endswith('vim-fuller.control'):
                return invalid
            return original(fd, path, executable, limit)
        with mock.patch.object(self, 'metadata', side_effect=malformed_control):
            report = self.fail()
        self.assertEqual((self.output / 'rootfs-metadata/vim-fuller.control').read_bytes(), invalid)
        self.assertEqual(sum(r['category'] == 'original-ipk' for r in report['files']), 2)

    def test_prepared_invalid_json_retained(self):
        self.prepared.write_bytes(b'original invalid json')
        self.fail()
        self.assertEqual((self.output / 'PREPARED-SOURCE.json').read_bytes(), b'original invalid json')

    def test_provenance_missing_keeps_partial(self):
        self.provenance.unlink()
        self.fail()
        self.assertTrue((self.output / 'PREPARED-SOURCE.json').is_file())

    def test_same_metadata_source_keeps_both_required_original_paths(self):
        rc, report = self.invoke(provenance=self.prepared)
        self.assertEqual(rc, 0)
        for filename in ('PREPARED-SOURCE.json', 'PROVENANCE.json'):
            self.assertEqual((self.output / filename).read_bytes(), self.prepared.read_bytes())
        self.assertEqual(sum(r['category'] == 'original-preparation-metadata' for r in report['files']), 2)

    def test_metadata_symlink_ancestor_rejected(self):
        linked = self.root / 'linked'
        linked.symlink_to(self.root, target_is_directory=True)
        self.fail(prepared_source=linked / 'prepared.json')

    def test_parent_traversal_rejected(self):
        self.fail(prepared_source=self.root / 'packages' / '..' / 'prepared.json')

    def test_fifo_rejected_without_blocking(self):
        os.mkfifo(self.feed / 'not-regular')
        self.fail()

    def test_metadata_fifo_rejected_without_blocking_keeps_other_evidence(self):
        self.prepared.unlink()
        os.mkfifo(self.prepared)
        started = time.monotonic()
        report = self.fail()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(sum(r['category'] == 'original-ipk' for r in report['files']), 2)

    def test_rootfs_fifo_rejected_without_blocking_keeps_ipks(self):
        self.image.unlink()
        os.mkfifo(self.image)
        started = time.monotonic()
        report = self.fail()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(sum(r['category'] == 'original-ipk' for r in report['files']), 2)

    def test_collection_output_modes_private(self):
        rc, report = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        for row in report['files']:
            self.assertEqual(stat.S_IMODE((self.output / row['file']).stat().st_mode), 0o600)

    def test_source_inputs_unchanged(self):
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.feed.iterdir()}
        rc, _ = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.feed.iterdir()})

    def test_shared_full_indexes_captured_once(self):
        rc, report = self.invoke()
        self.assertEqual(rc, 0)
        self.assertEqual(sum(r['file'].endswith('/Packages') for r in report['files']), 1)
        self.assertEqual(sum(r['file'].endswith('/Packages.gz') for r in report['files']), 1)

    def test_cached_index_change_fails_and_keeps_initial_original(self):
        original = C.Collector.write
        raw = (self.feed / 'Packages').read_bytes()
        def mutate_after_capture(collector, destination, data, source, category):
            original(collector, destination, data, source, category)
            if destination.endswith('/Packages'):
                (self.feed / 'Packages').write_bytes(b'changed shared source index')
        with mock.patch.object(C.Collector, 'write', side_effect=mutate_after_capture, autospec=True):
            report = self.fail()
        self.assertTrue(any('source changed or replaced' in e['error'] for e in report['errors']))
        self.assertEqual((self.output / 'offline-packages/aarch64_cortex-a53/packages/Packages').read_bytes(), raw)

    def test_image_symlink_rejected(self):
        alias = self.root / 'alias-root'
        alias.symlink_to(self.image)
        report = self.fail(rootfs=alias)
        self.assertIsNone(report['rootfs'])

    def test_empty_ipk_retained_but_collection_failed(self):
        (self.feed / 'vim-fuller_fixture.ipk').write_bytes(b'')
        report = self.fail()
        rows = [r for r in report['files'] if r['file'].endswith('vim-fuller_fixture.ipk')]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['bytes'], 0)

    def test_missing_installed_control_keeps_status_and_ipks(self):
        original = self.metadata
        def absent_control(fd, path, executable, limit):
            if path.endswith('vim-fuller.control'):
                raise ValueError('missing actual installed control')
            return original(fd, path, executable, limit)
        with mock.patch.object(self, 'metadata', side_effect=absent_control):
            report = self.fail()
        self.assertEqual(sum(r['category'] == 'original-ipk' for r in report['files']), 2)

    def test_directory_depth_bound(self):
        (self.root / 'packages' / 'deep' / 'a' / 'b' / 'c' / 'd').mkdir(parents=True)
        self.fail()

    def test_scan_entry_bound(self):
        with mock.patch.object(C, 'SCAN_ENTRIES', 1):
            self.fail()

    def test_scan_failure_retains_already_discovered_bounded_original(self):
        original = C.os.scandir
        @contextlib.contextmanager
        def ordered_scan(fd):
            with original(fd) as iterator:
                yield iter(sorted(iterator, key=lambda entry: entry.name))
        with mock.patch.object(C.os, 'scandir', side_effect=ordered_scan), mock.patch.object(C, 'SCAN_ENTRIES', 5):
            report = self.fail()
        self.assertFalse(report['candidate_inventory_complete'])
        self.assertEqual(report['candidate_inventory']['vim-fuller'],
                         ['aarch64_cortex-a53/packages/vim-fuller_fixture.ipk'])
        self.assertEqual((self.output / 'offline-packages/aarch64_cortex-a53/packages/vim-fuller_fixture.ipk').read_bytes(),
                         (self.feed / 'vim-fuller_fixture.ipk').read_bytes())

    def test_scan_directory_bound(self):
        with mock.patch.object(C, 'SCAN_DIRS', 1):
            self.fail()

    def test_source_changed_during_acquisition_not_trusted(self):
        target = self.feed / 'vim-fuller_fixture.ipk'
        target_inode = target.stat().st_ino
        original = C.os.read
        changed = False
        def change_source(fd, count):
            nonlocal changed
            data = original(fd, count)
            if data and not changed and C.os.fstat(fd).st_ino == target_inode:
                changed = True
                target.write_bytes(b'changed actual source')
            return data
        with mock.patch.object(C.os, 'read', side_effect=change_source):
            report = self.fail()
        self.assertTrue(changed)
        self.assertTrue(any('source changed' in e['error'] for e in report['errors']))
        self.assertFalse(any(r['file'].endswith('vim-fuller_fixture.ipk') for r in report['files']))

    def test_rootfs_changed_during_metadata_read_fails_keeps_original_metadata(self):
        original = self.metadata
        changed = False
        def mutate_image(fd, path, executable, limit):
            nonlocal changed
            if not changed:
                self.image.write_bytes(b'changed rootfs source')
                changed = True
            return original(fd, path, executable, limit)
        with mock.patch.object(self, 'metadata', side_effect=mutate_image):
            report = self.fail()
        self.assertTrue(any('rootfs changed during' in e['error'] for e in report['errors']))
        self.assertEqual((self.output / 'rootfs-metadata/opkg-status').read_text(), self.status)

    def test_source_replaced_during_acquisition_not_trusted(self):
        target = self.feed / 'vim-fuller_fixture.ipk'
        target_inode = target.stat().st_ino
        replacement = self.root / 'replacement.ipk'
        replacement.write_bytes(b'atomic replacement source')
        original = C.os.read
        changed = False
        def replace_source(fd, count):
            nonlocal changed
            data = original(fd, count)
            if data and not changed and C.os.fstat(fd).st_ino == target_inode:
                changed = True
                os.replace(replacement, target)
            return data
        with mock.patch.object(C.os, 'read', side_effect=replace_source):
            report = self.fail()
        self.assertTrue(changed)
        self.assertTrue(any('source changed' in e['error'] for e in report['errors']))
        self.assertFalse(any(r['file'].endswith('vim-fuller_fixture.ipk') for r in report['files']))


class PipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.image = self.root / 'dummy-image'
        self.image.write_bytes(b'image')
        self.fd, _ = C.open_regular(self.image, 64)
        self.helper = self.root / 'host-tool-fixture'

    def tearDown(self):
        os.close(self.fd)
        self.tmp.cleanup()

    def helper_code(self, body):
        self.helper.write_text('#!/usr/bin/env python3\nimport os,sys\n' + body + '\n')
        self.helper.chmod(0o755)

    def test_passed_image_descriptor_readable_and_output_bound(self):
        self.helper_code('with open(sys.argv[2], "rb") as stream: sys.stdout.buffer.write(stream.read())')
        self.assertEqual(C.rootcat(self.fd, 'public/path', self.helper, 32), b'image')

    def test_stdout_overflow_kills_subprocess(self):
        self.helper_code('sys.stdout.buffer.write(b"x" * 4096)')
        with self.assertRaisesRegex(ValueError, 'output exceeds bound'):
            C.rootcat(self.fd, 'public/path', self.helper, 32)

    def test_stderr_diagnostic_refused(self):
        self.helper_code('sys.stdout.write("data"); sys.stderr.write("diagnostic")')
        with self.assertRaisesRegex(ValueError, 'failed/diagnosed'):
            C.rootcat(self.fd, 'public/path', self.helper, 32)

    def test_nonzero_exit_refused(self):
        self.helper_code('sys.exit(2)')
        with self.assertRaisesRegex(ValueError, 'failed/diagnosed'):
            C.rootcat(self.fd, 'public/path', self.helper, 32)

    def test_empty_output_refused(self):
        self.helper_code('sys.exit(0)')
        with self.assertRaisesRegex(ValueError, 'empty image metadata'):
            C.rootcat(self.fd, 'public/path', self.helper, 32)

    def test_stderr_overflow_refused(self):
        self.helper_code('sys.stderr.buffer.write(b"x" * (64 * 1024 + 1))')
        with self.assertRaisesRegex(ValueError, 'output exceeds bound'):
            C.rootcat(self.fd, 'public/path', self.helper, 32)

    def test_timeout_kills_host_tool(self):
        self.helper_code('sys.stdout.write("fixture")')
        with mock.patch.object(C.time, 'monotonic', side_effect=[0, 61]):
            with self.assertRaisesRegex(ValueError, 'timed out'):
                C.rootcat(self.fd, 'public/path', self.helper, 32)

    def test_descendant_pipe_timeout_is_bounded(self):
        self.helper_code('import subprocess\nsubprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])\nsys.stdout.write("fixture")')
        started = time.monotonic()
        with mock.patch.object(C, 'ROOTCAT_SECONDS', 0.1):
            with self.assertRaisesRegex(ValueError, 'timed out'):
                C.rootcat(self.fd, 'public/path', self.helper, 32)
        self.assertLess(time.monotonic() - started, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
