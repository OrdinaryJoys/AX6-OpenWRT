#!/usr/bin/env python3
"""Source-inventory and archive reader controls, not ncurses target execution."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ncurses_source', ROOT/'.github/scripts/verify-ncurses-source.py')
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)


def tar_rows(rows):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:') as archive:
        for name, kind, data in rows:
            item = tarfile.TarInfo(name); item.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
            item.type = kind; item.size = len(data) if kind == tarfile.REGTYPE else 0
            item.linkname = 'outside' if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ''
            archive.addfile(item, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return stream.getvalue()


class Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)/'source'; self.package = self.source/'package/libs/ncurses'
        self.package.mkdir(parents=True)
        self.profile = copy.deepcopy(M.configuration())
        # These are parser fixtures, not substitutions for upstream package bytes.
        for name in self.profile['files']:
            data = ('fixture '+name+'\n').encode()
            path = self.package/name; path.write_bytes(data); path.chmod(0o644)
            self.profile['files'][name]['sha256'] = M.sha(data)

    def test_complete_package_and_empty_patch_directory(self):
        self.assertEqual(M.verify_package(self.source, self.profile), self.profile['files'])
        (self.package/'patches').mkdir()
        self.assertEqual(M.verify_package(self.source, self.profile), self.profile['files'])

    def test_each_of_six_residual_patches_is_rejected(self):
        directory = self.package/'patches'; directory.mkdir()
        for name in self.profile['removed_patches']:
            path = directory/name; path.write_bytes(b'old patch\n')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'complete package inventory'):
                M.verify_package(self.source, self.profile)
            path.unlink()

    def test_unlisted_patch_and_series_rejected(self):
        for name in ('foreign.patch', 'series', '.hidden'):
            path = self.package/name; path.write_bytes(b'foreign')
            with self.subTest(name=name), self.assertRaises(ValueError): M.verify_package(self.source, self.profile)
            path.unlink()

    def test_src_override_rejected(self):
        (self.package/'src').mkdir(); (self.package/'src/override.c').write_bytes(b'override')
        with self.assertRaises(ValueError): M.verify_package(self.source, self.profile)

    def test_missing_recipe_rejected(self):
        (self.package/'Makefile').unlink()
        with self.assertRaises(ValueError): M.verify_package(self.source, self.profile)

    def test_recipe_drift_rejected(self):
        (self.package/'Makefile').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'bytes or modes'): M.verify_package(self.source, self.profile)

    def test_executable_recipe_rejected(self):
        (self.package/'Makefile').chmod(0o755)
        with self.assertRaises(ValueError): M.verify_package(self.source, self.profile)

    def test_package_file_link_rejected(self):
        (self.package/'Makefile').unlink(); (self.package/'Makefile').symlink_to('Config.in')
        with self.assertRaisesRegex(ValueError, 'symlink'): M.verify_package(self.source, self.profile)

    def test_directory_link_rejected(self):
        (self.package/'patches').symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'): M.verify_package(self.source, self.profile)

    def test_ancestor_link_rejected(self):
        link = Path(self.temporary.name)/'alias'; link.mkdir()
        (link/'package').symlink_to(self.source/'package', target_is_directory=True)
        with self.assertRaises(ValueError): M.verify_package(link, self.profile)

    def test_duplicate_json_key_rejected(self):
        for raw in ('{"a":1,"a":2}', '{"x":{"a":1,"a":2}}'):
            with self.assertRaises(ValueError): json.loads(raw, object_pairs_hook=M.pairs)

    def test_boolean_contract_counts_rejected(self):
        data = M.configuration(); data['archive']['directories'] = True
        profile = Path(self.temporary.name)/'profile.json'
        profile.write_text(json.dumps(data))
        with patch.object(M, 'PROFILE', profile):
            with self.assertRaises(ValueError): M.configuration()

    def test_changed_archive_identity_rejected(self):
        data = M.configuration()
        data['archive'].update(root='foreign', name='foreign.tar.zst',
                               url='https://sources.openwrt.org/foreign.tar.zst')
        profile = Path(self.temporary.name)/'profile.json'
        profile.write_text(json.dumps(data))
        with patch.object(M, 'PROFILE', profile), self.assertRaises(ValueError): M.configuration()

    def test_failed_archive_stage_never_retains_package_pass(self):
        output = Path(self.temporary.name)/'failed'
        args = ['gate', '--source-root', str(self.source), '--archive', 'unused', '--output', str(output)]
        with patch.object(sys, 'argv', args), patch.object(M, 'configuration', return_value=self.profile), \
                patch.object(M, 'mirror', side_effect=ValueError('archive failure')):
            with self.assertRaisesRegex(ValueError, 'archive failure'): M.main()
        result = json.loads((output/'RESULTS.json').read_text())
        self.assertEqual(result['status'], 'FAIL')
        self.assertFalse(result['runtime_approved'])

    def test_safe_paths(self):
        M.safe('misc/terminfo.src')
        for name in ('../x', '/x', 'a/../x', 'a\\x', 'a:x', 'a\nx', './x', 'a//x', ''):
            with self.subTest(name=name), self.assertRaises(ValueError): M.safe(name)

    def tar_check(self, rows, **updates):
        raw = tar_rows(rows)
        profile = {'root': 'source', 'regular_files': 1, 'directories': 1, 'tar_bytes': len(raw), **updates}
        return M.tar_inventory(raw, profile)

    def test_actual_tar_parser_shape(self):
        files, payload = self.tar_check([('source', tarfile.DIRTYPE, b''), ('source/a.c', tarfile.REGTYPE, b'content')])
        self.assertEqual(files, {'a.c': {'sha256': M.sha(b'content'), 'mode': 0o644}})
        self.assertEqual(payload, {'a.c': b'content'})

    def test_tar_link_and_special_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.tar_check([('source', tarfile.DIRTYPE, b''), ('source/link', kind, b'')])

    def test_tar_foreign_and_traversal_rejected(self):
        for name in ('foreign/a.c', '/absolute', 'source/../outside'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.tar_check([('source', tarfile.DIRTYPE, b''), (name, tarfile.REGTYPE, b'x')])

    def test_tar_duplicate_and_collision_rejected(self):
        for second in ('source/a', 'source/A'):
            with self.subTest(second=second), self.assertRaises(ValueError):
                self.tar_check([('source', tarfile.DIRTYPE, b''), ('source/a', tarfile.REGTYPE, b'a'),
                                (second, tarfile.REGTYPE, b'b')], regular_files=2)

    def test_tar_missing_source_rejected(self):
        with self.assertRaises(ValueError): self.tar_check([('source', tarfile.DIRTYPE, b'')])

    def test_archive_hash_rejected_before_decompression(self):
        archive = Path(self.temporary.name)/'bad.tar.zst'; archive.write_bytes(b'wrong')
        with patch.object(M.subprocess, 'run', side_effect=AssertionError('must not decompress untrusted hash')):
            with self.assertRaisesRegex(ValueError, 'SHA256'): M.mirror(archive, M.configuration()['archive'], 'zstd')

    def test_actual_prepared_manifest_and_stamp(self):
        tree = Path(self.temporary.name)/'prepared'; tree.mkdir()
        (tree/'a.c').write_bytes(b'actual'); (tree/'a.c').chmod(0o644)
        expected = {'a.c': {'sha256': M.sha(b'actual'), 'mode': 0o644}}
        marker = tree/('.prepared'+'a'*32+'_'+'b'*32); marker.touch()
        self.assertEqual(M.verify_prepared(tree, expected)[0], expected)
        (tree/'a.c').write_bytes(b'changed')
        with self.assertRaises(ValueError): M.verify_prepared(tree, expected)

    def test_unprepared_missing_or_extra_stamp(self):
        tree = Path(self.temporary.name)/'prepared'; tree.mkdir()
        with self.assertRaises(ValueError): M.verify_prepared(tree, {})
        marker = tree/('.prepared'+'a'*32+'_'+'b'*32); marker.write_bytes(b'not zero')
        with self.assertRaises(ValueError): M.verify_prepared(tree, {})

    def test_host_prepare_wiring_precedes_toolchain(self):
        text = (ROOT/'.github/workflows/build-AX6-NSS.yml').read_text()
        start = text.index('- name: Prepare and verify complete ncurses host source')
        self.assertLess(start, text.index('- name: Build target toolchain before rpcd components'))
        self.assertIn('make -j1 package/libs/ncurses/host/prepare V=s', text)
        self.assertIn('--prepared "${ncurses_sources[0]}"', text)
        self.assertIn('verify-ncurses-source.py', text[:text.index('- name: Add NSS feed and prepare feeds')])
        self.assertLess(text.index('- name: Prepare locked native host tools'), start)
        self.assertLess(start, text.index('- name: Prepare selected Vim source'))
        self.assertIn('verify-ncurses-rootfs.py', text)
        self.assertIn('2>&1 | tee "$GITHUB_WORKSPACE/core-flow-evidence/ncurses/host-prepare.log"', text)

    def test_lint_checks_real_mirror_not_only_synthetic_ipks(self):
        text = (ROOT/'.github/workflows/lint.yml').read_text()
        self.assertIn('zstd', text[:text.index('- name: Install hash-verified')])
        self.assertIn('verify-ncurses-source.py', text)
        self.assertIn('https://sources.openwrt.org/ncurses-6.6.20260801.tar.zst', text)
        self.assertIn('AX6_NCURSES_SOURCE_PREFLIGHT_', text)


if __name__ == '__main__':
    unittest.main()
