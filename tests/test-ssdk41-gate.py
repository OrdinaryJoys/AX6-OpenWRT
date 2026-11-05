#!/usr/bin/env python3
"""Frozen admission and synthetic receipt rejection controls; no native campaign."""
import argparse
import ast
from contextlib import contextmanager
import copy
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('platform41_gate', ROOT / '.github/scripts/verify-ssdk-platform-resource.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
ARGS = None


class ConfigurationTests(unittest.TestCase):
    def reject(self, edit, message):
        original = M.base.load
        data = copy.deepcopy(original(M.PROFILE))
        edit(data)
        with patch.object(M.base, 'load', side_effect=lambda p: data if Path(p) == M.PROFILE else original(p)):
            with self.assertRaisesRegex(ValueError, message):
                M.configuration()

    def test_frozen_quality35_and_692_single_platform_delta(self):
        data, parent = M.configuration(), M.old.configuration()
        self.assertEqual(data['source_commit'], M.SOURCE)
        self.assertEqual(data['accepted40_commit'], M.PARENT)
        self.assertEqual(len(data['prepared_files']), 692)
        self.assertEqual({n for n, v in data['prepared_files'].items() if parent['prepared_files'][n] != v}, {M.PLAT})
        self.assertEqual(len(M.patch_inventory(data)), 41)
        self.assertEqual({n for n in data['source_assets'] if n not in parent['source_assets']}, set(M.SOURCE_OVERRIDES) - {M.PACKAGE + 'Makefile'})
        self.assertEqual(data['quality_test_blobs'], M.QUALITY_BLOBS)

    def test_source_identity_cannot_follow_input(self):
        for name in ('source_commit', 'accepted40_commit'):
            with self.subTest(name=name):
                self.reject(lambda d: d.__setitem__(name, '0' * 40), 'source identity')
        self.reject(lambda d: d.__setitem__('source_commit', 'f41e5fd9aa974fb679268ba1517e769e2a3e4fa2'), 'source identity')

    def test_immutable40_contract_and_gate(self):
        for name in ('accepted40_contract_sha256', 'accepted40_gate_sha256'):
            with self.subTest(name=name):
                self.reject(lambda d: d.__setitem__(name, '0' * 64), 'immutable SSDK40')

    def test_schema_bool_and_unknown_contract_fields(self):
        self.reject(lambda d: d.__setitem__('schema', True), 'fixed SSDK41 profile')
        self.reject(lambda d: d.__setitem__('source_assets', {}), 'contract keys')
        self.reject(lambda d: d.__setitem__('frozen', 1), 'fixed SSDK41 profile')

    def test_each_git_asset_hash_is_pinned(self):
        for name in M.SOURCE_OVERRIDES:
            with self.subTest(name=name):
                self.reject(lambda d: d['source_overrides'].__setitem__(name, '0' * 64), 'fixed Git quality35')

    def test_source_asset_missing_and_extra(self):
        self.reject(lambda d: d['source_overrides'].pop(M.RUNNER), 'fixed Git quality35')
        self.reject(lambda d: d['source_overrides'].__setitem__('tests/extra.py', '0' * 64), 'fixed Git quality35')

    def test_each_quality_test_blob_is_pinned(self):
        for name in M.QUALITY_BLOBS:
            with self.subTest(name=name):
                self.reject(lambda d: d['quality_test_blobs'].__setitem__(name, '0' * 40), 'Git test blobs')
        self.reject(lambda d: d['quality_test_blobs'].pop(M.RUNNER), 'Git test blobs')

    def test_prepared_override_missing_extra_and_other_delta(self):
        for edit in (lambda d: d['prepared_overrides'].clear(),
                     lambda d: d['prepared_overrides'].__setitem__('src/init/ssdk_init.c', '0' * 64),
                     lambda d: d['prepared_overrides'].__setitem__(M.PLAT, '0' * 64)):
            self.reject(edit, 'only reviewed platform')

    def test_remaining_scope_cannot_be_closed_by_config(self):
        self.reject(lambda d: d.__setitem__('quality_revision', 'COMPLETE'), 'remaining open boundaries')
        self.reject(lambda d: d.__setitem__('open', []), 'remaining open boundaries')

    def test_frozen_obligation_inventory(self):
        self.assertEqual(sum(len(M.positive_cases(d)) for d in M.PROFILES.values()), 1705)
        self.assertEqual(len(M.PROFILES), 9)
        self.assertEqual(len(M.MUTANTS), 35)
        self.assertEqual(len({n for n, *_ in M.MUTANTS}), 35)
        self.assertEqual(len(M.WITNESSES), 4)

    def test_precise_negative_process_codes(self):
        M.exact(86, b'', b'PLATFORM:MAP_LEAK\n', expected_err=b'PLATFORM:MAP_LEAK\n', expected_code=86)
        for code in (True, False, 86.0, '86', 0, 1, -6, -11, 97, 98, None):
            with self.subTest(code=code), self.assertRaises(ValueError):
                M.exact(code, b'', b'PLATFORM:MAP_LEAK\n', expected_err=b'PLATFORM:MAP_LEAK\n', expected_code=86)

    def test_negative_diagnostic_contamination(self):
        for out, err in ((b'PASS', b'PLATFORM:MAP_LEAK\n'), (b'', b'PLATFORM:CLOCK_LEAK\n'),
                         (b'', b'PLATFORM:MAP_LEAK\nnoise'), (b'', b'noise\nPLATFORM:MAP_LEAK\n'),
                         (b'', b'AddressSanitizer: DEADLYSIGNAL\n'), (b'', b'runtime error: overflow\n'),
                         (bytearray(), b'PLATFORM:MAP_LEAK\n'), (b'', bytearray(b'PLATFORM:MAP_LEAK\n'))):
            with self.subTest(out=out, err=err), self.assertRaises(ValueError):
                M.exact(86, out, err, expected_err=b'PLATFORM:MAP_LEAK\n', expected_code=86)

    def test_positive_typed_ledger_and_raw_noise(self):
        value = M.simple_ledger(['HPPE'], 2, 0, 0)
        raw = json.dumps(value).encode()
        self.assertEqual(M.positive(0, raw, b'', value), value)
        for code in (True, False, 0.0, '0', 1, -11, 97, 98, None):
            with self.subTest(code=code), self.assertRaises(ValueError):
                M.positive(code, raw, b'')
        for count in (True, False, '1', 1.0, -1, None):
            row = dict(value, maps=count)
            with self.subTest(count=count), self.assertRaises(ValueError):
                M.positive(0, json.dumps(row).encode(), b'')
        for out, err in ((raw, b'warning'), (raw + b'noise', b''), (b'[]', b''),
                         (raw.replace(b'"maps": 1', b'"maps": 0, "maps": 1'), b'')):
            with self.subTest(out=out, err=err), self.assertRaises(ValueError):
                M.positive(0, out, err)
        with self.assertRaisesRegex(ValueError, 'exact resource counts'):
            M.positive(0, json.dumps(dict(value, enables=0)).encode(), b'', value)

    def test_independent_prefix_clock_and_region_counts(self):
        self.assertEqual(M.simple_ledger(['HPPE', 'DESS', 'IN_UNIPHY'], 7, 3, 1),
                         dict(status='PLATFORM_CASE', maps=2, unmaps=2, claims=1, releases=1,
                              enables=0, disables=0, gcc_starts=0, gcc_stops=0))
        self.assertEqual(M.simple_ledger(['HPPE'], 2, 0, 4)['disables'], 0)
        self.assertEqual(M.simple_ledger(['HPPE'], 2, 0, 3)['disables'], 1)
        self.assertEqual(M.simple_ledger(['HPPE'], 2, 0, 5)['gcc_starts'], 1)

    def test_sdk_view_strict_pairs(self):
        self.assertEqual(M.sdk_view('hidden\n/*qca808x_start*/\nkept\n/*qca808x_end*/\n'), 'kept\n')
        for text in ('no export', '/*qca808x_start*/', '/*qca808x_end*/',
                     '/*qca808x_start*/\n/*qca808x_start*/\n/*qca808x_end*/'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                M.sdk_view(text)


class DebugCompanionTests(unittest.TestCase):
    """Synthetic non-executable Mach-O data; never invokes retained programs."""
    UUID = bytes.fromhex('0123456789abcdef0123456789abcdef')

    @staticmethod
    def macho(kind=2, cpu=0x0100000c, subtype=0, uuid=UUID, commands=None, count=1):
        if commands is None:
            commands = struct.pack('<2I', 0x1b, 24) + uuid
        return struct.pack('<8I', 0xfeedfacf, cpu, subtype, kind, count, len(commands), 0, 0) + commands

    def setUp(self):
        if ARGS is None:
            raise RuntimeError('run directly with --output')
        self.root = ARGS.output / 'synthetic-debug-data-not-programs' / self._testMethodName
        self.root.mkdir(parents=True)
        self.program = 'profiles/plain.host'
        self.bundle = self.root / (self.program + '.dSYM')
        self.plist = self.bundle / 'Contents/Info.plist'
        self.dwarf = self.bundle / 'Contents/Resources/DWARF/plain.host'
        self.yaml = self.bundle / 'Contents/Resources/Relocations/aarch64/plain.host.yml'
        self.info = {'CFBundleDevelopmentRegion': 'English', 'CFBundleIdentifier': 'com.apple.xcode.dsym.plain.host',
                     'CFBundleInfoDictionaryVersion': '6.0', 'CFBundlePackageType': 'dSYM',
                     'CFBundleSignature': '????', 'CFBundleShortVersionString': '1.0', 'CFBundleVersion': '1'}
        self.put(self.root / self.program, self.macho())
        self.put(self.plist, plistlib.dumps(self.info))
        self.put(self.dwarf, self.macho(10))
        self.put(self.yaml, b"---\ntriple: 'arm64-apple-darwin'\nrelocations: []\n...\n")

    @staticmethod
    def put(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def check(self):
        return M.host_debug_companions(self.root, {self.program}, M.base.inventory(self.root))

    def expected(self):
        return {p.relative_to(self.root).as_posix() for p in (self.plist, self.dwarf, self.yaml)}

    def test_valid_arm64_exact_three_file_bundle(self):
        self.assertEqual(M.macho_identity(self.macho(), 2), ((0x0100000c, 0, 32, '<'), self.UUID))
        self.assertEqual(M.macho_identity(self.macho(10), 10), ((0x0100000c, 0, 32, '<'), self.UUID))
        self.assertEqual(self.check(), self.expected())

    def test_no_dsym_does_not_allow_extra_linux_host(self):
        shutil.rmtree(self.bundle)
        self.put(self.root / self.program, b'\x7fELF' + b'\0' * 28)
        self.assertEqual(self.check(), set())
        self.put(self.root / 'unlisted.host', b'\x7fELF' + b'\0' * 28)
        actual = M.base.inventory(self.root)
        allowed = M.host_debug_companions(self.root, {self.program}, actual)
        self.assertNotEqual({n for n in actual if n.endswith('.host')} - allowed, {self.program})

    def test_strict_macho_bytes_only(self):
        for raw in (None, False, '', bytearray(self.macho()), memoryview(self.macho())):
            with self.subTest(kind=type(raw).__name__), self.assertRaises(ValueError):
                M.macho_identity(raw, 2)

    def test_malformed_headers_and_load_commands(self):
        good = self.macho()
        rows = [b'', b'not Mach-O', good[:20], good[:-1], self.macho(commands=b'', count=0),
                self.macho(uuid=b'\0' * 16), self.macho(commands=(struct.pack('<2I', 0x1b, 24) + self.UUID) * 2, count=2)]
        for offset, value in ((16, 2), (20, 32), (36, 7), (36, 25), (36, 8)):
            raw = bytearray(good)
            struct.pack_into('<I', raw, offset, value)
            rows.append(bytes(raw))
        for raw in rows:
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                M.macho_identity(raw, 2)

    def test_foreign_bundle_and_fake_bundle_file(self):
        self.bundle.rename(self.root / 'foreign.host.dSYM')
        with self.assertRaises(ValueError):
            self.check()
        shutil.rmtree(self.root / 'foreign.host.dSYM')
        self.put(self.root / (self.program + '.dSYM'), b'not a directory')
        with self.assertRaises(ValueError):
            self.check()

    def test_debug_executable_disguise_and_wrong_program_type(self):
        for program_type, debug_type in ((2, 2), (10, 10), (6, 10)):
            self.put(self.root / self.program, self.macho(program_type))
            self.put(self.dwarf, self.macho(debug_type))
            with self.subTest(program_type=program_type, debug_type=debug_type), self.assertRaises(ValueError):
                self.check()

    def test_elf_program_cannot_own_macho_dsym(self):
        self.put(self.root / self.program, b'\x7fELF' + b'\0' * 28)
        with self.assertRaises(ValueError):
            self.check()

    def test_architecture_and_subtype_mismatch(self):
        for cpu, subtype in ((0x01000007, 0), (0x0100000c, 1)):
            self.put(self.dwarf, self.macho(10, cpu=cpu, subtype=subtype))
            with self.subTest(cpu=cpu, subtype=subtype), self.assertRaises(ValueError):
                self.check()

    def test_matching_x86_pair_not_current_arm64_layout(self):
        self.put(self.root / self.program, self.macho(cpu=0x01000007, subtype=3))
        self.put(self.dwarf, self.macho(10, cpu=0x01000007, subtype=3))
        with self.assertRaises(ValueError):
            self.check()

    def test_uuid_mismatch_and_zero_uuid(self):
        for uuid in (b'\x42' * 16, b'\0' * 16):
            self.put(self.dwarf, self.macho(10, uuid=uuid))
            with self.subTest(uuid=uuid), self.assertRaises(ValueError):
                self.check()

    def test_plist_identity_type_and_invalid_encoding(self):
        for key, value in (('CFBundleIdentifier', 'com.apple.xcode.dsym.foreign.host'),
                           ('CFBundlePackageType', 'APPL'), ('CFBundleIdentifier', True)):
            self.put(self.plist, plistlib.dumps(dict(self.info, **{key: value})))
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.check()
        self.put(self.plist, b'not a plist')
        with self.assertRaises(ValueError):
            self.check()

    def test_binary_plist_is_structurally_verified(self):
        self.put(self.plist, plistlib.dumps(self.info, fmt=plistlib.FMT_BINARY))
        self.assertEqual(self.check(), self.expected())

    def test_extra_file_and_extra_directory_not_allowed(self):
        extra = self.bundle / 'Contents/Resources/DWARF/foreign.host'
        self.put(extra, self.macho(10))
        with self.assertRaises(ValueError):
            self.check()
        extra.unlink()
        (self.bundle / 'Contents/extra-empty-directory').mkdir()
        with self.assertRaises(ValueError):
            self.check()

    def test_wrong_debug_or_relocation_basename(self):
        self.dwarf.rename(self.dwarf.with_name('foreign.host'))
        with self.assertRaises(ValueError):
            self.check()
        self.dwarf.with_name('foreign.host').rename(self.dwarf)
        self.yaml.rename(self.yaml.with_name('foreign.host.yml'))
        with self.assertRaises(ValueError):
            self.check()

    def test_wrong_relocation_arch_and_missing_companion(self):
        self.yaml.parent.rename(self.yaml.parent.with_name('x86_64'))
        with self.assertRaises(ValueError):
            self.check()
        self.yaml.parent.with_name('x86_64').rename(self.yaml.parent)
        for path in (self.plist, self.dwarf, self.yaml):
            raw = path.read_bytes()
            path.unlink()
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.check()
            self.put(path, raw)

    def test_yaml_utf8_nonempty_and_maximum_bound(self):
        for raw in (b'', b'\xff', b'x' * (16 * 1024 * 1024 + 1)):
            self.put(self.yaml, raw)
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                self.check()

    def test_yaml_is_opaque_bounded_metadata_not_semantic_proof(self):
        for raw in (b'x', b'not interpreted as YAML: [\n', b'x' * (16 * 1024 * 1024)):
            self.put(self.yaml, raw)
            self.assertEqual(self.check(), self.expected())


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ARGS is None:
            raise RuntimeError('run directly with --output, --source-git and --prepared41')
        cls.root = ARGS.output / 'synthetic-reader-controls-not-native'
        cls.root.mkdir()
        cls.source, cls.current, cls.prefix = (cls.root / n for n in ('git-quality35-input-data', 'actual41', 'prefix40'))
        cls.source.mkdir()
        cls.data = M.configuration()
        for name, digest in cls.data['source_assets'].items():
            p = subprocess.run(['git', '-C', str(ARGS.source_git), 'show', M.SOURCE + ':' + name],
                               capture_output=True, timeout=30)
            M.exact(p.returncode, p.stderr, b'')
            M.need(M.sha(p.stdout) == digest, 'fixed Git object hash: ' + name)
            if name in M.QUALITY_BLOBS:
                blob = subprocess.run(['git', '-C', str(ARGS.source_git), 'rev-parse', M.SOURCE + ':' + name],
                                      capture_output=True, timeout=30)
                M.exact(blob.returncode, blob.stdout, blob.stderr, (M.QUALITY_BLOBS[name] + '\n').encode())
            target = cls.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.stdout)
        M.admit_prepared(ARGS.prepared41, cls.data['prepared_files'])
        M.base.copy_code(ARGS.prepared41, cls.current, cls.data['prepared_files'])
        M.base.copy_code(ARGS.prepared41, cls.prefix, cls.data['prepared_files'])
        p = subprocess.run(['patch', '-p1', '-R', '--batch', '--fuzz=0', '-V', 'none'], cwd=cls.prefix,
                           input=(cls.source / M.PATCH).read_bytes(), capture_output=True, timeout=60)
        M.exact(p.returncode, p.stderr, b'')
        M.need(p.stdout in (b'patching file src/init/ssdk_plat.c\n', b"patching file 'src/init/ssdk_plat.c'\n"), 'exact unit fixture reverse053')
        M.admit_prepared(cls.prefix, M.old.configuration()['prepared_files'])
        cls.native = cls.root / 'fabricated-receipts-do-not-qualify-native'
        cls.native.mkdir()
        cls.compiler = str(Path(sys.executable).resolve())
        cls.sources = M.generated_sources(cls.source, cls.current, cls.prefix)
        cls.make_synthetic_receipts()

    @classmethod
    def write(cls, name, raw):
        path = cls.native / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    @classmethod
    def make_synthetic_receipts(cls):
        commands = []

        def command(label, argv, out=b'', err=b'', code=0):
            row = dict(argv=list(map(str, argv)), returncode=code, ASAN_OPTIONS=M.ASAN, UBSAN_OPTIONS=M.UBSAN)
            cls.write(label + '.json', json.dumps(row).encode())
            cls.write(label + '.stdout', out)
            cls.write(label + '.stderr', err)
            commands.append({'label': label, **row})

        for name, raw in cls.sources.items():
            cls.write(name, raw)
            # Deliberately synthetic reader data, not a compiled or executed program.
            cls.write(name[:-2] + '.host', b'\x7fELF' + b'\x00' * 28)
        shutil.copytree(cls.current, cls.native / 'replayed')
        cls.write('patch.stdout', b'patching file src/init/ssdk_plat.c\n')
        cls.write('patch.stderr', b'')
        controls = {'synthetic': True}
        cls.write('detector-controls/RESULTS.json', json.dumps({'sanitizer_controls': controls}).encode())
        command('detector-controls', [sys.executable, '-B', cls.source / 'tests/test-ssdk-retirement-admission.py',
                                     '--canaries-only', '--sanitize', '--cc', cls.compiler, '--output', cls.native / 'detector-controls'],
                b'{"status": "PASS_SANITIZER_CONTROLS_ONLY"}\n')
        for name, definitions in M.PROFILES.items():
            path = cls.native / ('profiles/' + name + '.c')
            binary = path.with_suffix('.host')
            command('profiles/' + name + '-compile', [cls.compiler, *M.FLAGS, '-DCANDIDATE=1',
                                                     *('-D' + d + '=1' for d in definitions), path, '-o', binary])
            for index, case in enumerate(M.positive_cases(definitions)):
                value = M.simple_ledger(definitions, *case[:3])
                command('positive/' + name + '/' + str(index), [binary, *case], json.dumps(value).encode())
        for name, _, _, case, marker in M.MUTANTS:
            path = cls.native / ('negative/' + name + '.c')
            binary = path.with_suffix('.host')
            command('negative/' + name + '-compile', [cls.compiler, *M.FLAGS, '-DCANDIDATE=1', '-DHPPE=1', '-DDESS=1', '-DIN_UNIPHY=1', path, '-o', binary])
            command('negative/' + name + '-run', [binary, *case], err=('PLATFORM:' + marker + '\n').encode(), code=86)
        path = cls.native / 'old/current40.c'
        command('old/current40-compile', [cls.compiler, *M.FLAGS, '-DHPPE=1', '-DDESS=1', '-DIN_UNIPHY=1', path, '-o', path.with_suffix('.host')])
        for index, (case, marker) in enumerate(M.WITNESSES):
            command('old/witness-' + str(index), [path.with_suffix('.host'), *case], err=('PLATFORM:' + marker + '\n').encode(), code=86)
        command('sdk-view-compile', [cls.compiler, *M.FLAGS, '-Wno-unused-parameter', cls.native / 'sdk-view.c', '-o', cls.native / 'sdk-view.host'])
        command('sdk-view-run', [cls.native / 'sdk-view.host'])
        names = {M.RUNNER, M.SUPPORT + 'fixture.c', M.SUPPORT + 'README.md', 'tests/test-ssdk-platform-oracles.py',
                 'tests/test-ssdk-retirement-admission.py', 'tests/edma_patch_context.py',
                 'tests/nss-dp-containment/extract_prepared_c.py', M.PACKAGE + 'Makefile'}
        names.update(n for n in cls.data['source_assets'] if n.startswith(M.PACKAGE + 'patches/'))
        report = dict(status=M.NATIVE_STATUS, runtime_approved=False,
                      profile='SERIAL_COLD_RESOURCE_MODELS_NOT_ROOT_SHARED_READERS_OR_TARGET_ABI',
                      prepared_files=cls.data['prepared_files'], source_patches=M.patch_inventory(cls.data),
                      inputs={str(cls.source / n): cls.data['source_assets'][n] for n in names},
                      compiler=dict(path=cls.compiler, sha256=M.sha(Path(cls.compiler).read_bytes()), flags=M.FLAGS),
                      positive=[dict(profile=n, defines=d, cases=len(M.positive_cases(d))) for n, d in M.PROFILES.items()],
                      negative=[dict(name=n, case=list(c), marker=m) for n, _, _, c, m in M.MUTANTS],
                      old_witnesses=[dict(case=list(c), marker=m) for c, m in M.WITNESSES],
                      positive_count=1705, negative_count=35, old_witness_count=4,
                      sanitizer_controls=controls, sdk_reg_func_fields=['i2c_get', 'i2c_set', 'mdio_get', 'mdio_set'], commands=commands)
        cls.write('RESULTS.json', json.dumps(report).encode())

    @contextmanager
    def changed(self, path, raw):
        before = path.read_bytes() if path.exists() else None
        if raw is None:
            path.unlink()
        else:
            path.write_bytes(raw)
        try:
            yield
        finally:
            if before is None:
                path.unlink()
            else:
                path.write_bytes(before)

    def read(self):
        # Only the controls subtree is mocked. No native programs are run here.
        with patch.object(M.old.old, 'sanitizer_receipts'):
            return M.platform_receipts(self.native, self.compiler, self.source, self.current, self.prefix, self.data)

    def mutate_report(self, edit):
        path = self.native / 'RESULTS.json'
        row = M.base.load(path)
        edit(row)
        return self.changed(path, json.dumps(row).encode())

    def test_synthetic_reader_positive_not_native_qualification(self):
        self.assertEqual(self.read()['raw_commands'], 1792)
        with self.assertRaises((KeyError, ValueError)):
            M.platform_receipts(self.native, self.compiler, self.source, self.current, self.prefix, self.data)

    def test_reviewed_git_source_and_exact_patch_support_sets(self):
        M.admit_source(self.source, self.data)
        for path in (self.source / M.RUNNER, self.source / M.PATCH, self.source / (M.PACKAGE + 'Makefile')):
            with self.subTest(path=path), self.changed(path, path.read_bytes() + b'\n'), self.assertRaisesRegex(ValueError, 'input drift'):
                M.admit_source(self.source, self.data)
        for path in (self.source / (M.PACKAGE + 'patches/series'), self.source / (M.SUPPORT + '.hidden')):
            with self.subTest(path=path), self.changed(path, b'pollution'), self.assertRaisesRegex(ValueError, 'directory'):
                M.admit_source(self.source, self.data)

    def test_missing_source_and_symlink_rejected(self):
        path = self.source / M.RUNNER
        before = path.read_bytes()
        with self.changed(path, None), self.assertRaisesRegex(ValueError, 'missing regular'):
            M.admit_source(self.source, self.data)
        path.unlink()
        try:
            path.symlink_to(self.source / 'tests/test-ssdk-platform-oracles.py')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                M.admit_source(self.source, self.data)
        finally:
            path.unlink()
            path.write_bytes(before)

    def test_frozen_git_exact35_mutations_match_independent_gate_list(self):
        tree = ast.parse((self.source / M.RUNNER).read_text())
        nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and
                 len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'mutants']
        self.assertEqual(len(nodes), 1)
        self.assertEqual(ast.literal_eval(nodes[0].value), M.MUTANTS)
        self.assertEqual(len(self.sources), 46)

    def test_each_historical_f41_test_input_is_rejected(self):
        for name in M.QUALITY_BLOBS:
            process = subprocess.run(['git', '-C', str(ARGS.source_git), 'show',
                                      'f41e5fd9aa974fb679268ba1517e769e2a3e4fa2:' + name], capture_output=True, timeout=30)
            M.exact(process.returncode, process.stderr, b'')
            with self.subTest(name=name), self.changed(self.source / name, process.stdout), self.assertRaisesRegex(ValueError, 'input drift'):
                M.admit_source(self.source, self.data)

    def test_prepared_missing_extra_changed_and_build_pollution(self):
        M.admit_prepared(self.current, self.data['prepared_files'])
        path = self.current / M.PLAT
        for raw in (None, path.read_bytes() + b'\n'):
            with self.changed(path, raw), self.assertRaisesRegex(ValueError, 'complete frozen prepared'):
                M.admit_prepared(self.current, self.data['prepared_files'])
        for name in ('unexpected.c', 'module.o', '.hidden', 'version.date'):
            with self.subTest(name=name), self.changed(self.current / name, b'pollution'), self.assertRaises(ValueError):
                M.admit_prepared(self.current, self.data['prepared_files'])

    def test_prepare_metadata_rules_not_an_extra_code_escape(self):
        with self.changed(self.current / 'version.date', b'123\n'):
            code, metadata = M.admit_prepared(self.current, self.data['prepared_files'])
            self.assertEqual(code, self.data['prepared_files'])
            self.assertEqual(set(metadata), {'version.date'})
        name = '.prepared_' + 'a' * 32 + '_' + 'b' * 32
        with self.changed(self.current / (name + '_check'), b''), self.assertRaisesRegex(ValueError, 'unmatched'):
            M.admit_prepared(self.current, self.data['prepared_files'])

    def test_complete_generated_c_is_not_a_runner_hash(self):
        for name in ('profiles/plain.c', 'negative/foreign-instance-exit.c', 'old/current40.c', 'sdk-view.c',
                     'negative/uniphy-wrong-map-address.c', 'negative/psgmii-read-not-published.c',
                     'negative/foreign-ess-retirement.c', 'negative/switch-wrong-getter.c',
                     'negative/uniphy-wrong-device.c', 'negative/psgmii-wrong-slot.c'):
            path = self.native / name
            with self.subTest(name=name), self.changed(path, path.read_bytes() + b'\n/* altered */\n'), self.assertRaisesRegex(ValueError, 'full generated C'):
                self.read()

    def test_missing_extra_generated_c_rejected(self):
        for path, raw in ((self.native / 'sdk-view.c', None), (self.native / 'unlisted.c', b'int fake;')):
            with self.changed(path, raw), self.assertRaisesRegex(ValueError, 'C file inventory'):
                self.read()

    def test_runner_summary_cannot_substitute_for_raw_negative(self):
        path = self.native / 'negative/uniphy-leak-run.stderr'
        for raw in (None, b'PLATFORM:WRONG\n', b'PLATFORM:MAP_LEAK\nAddressSanitizer: heap-buffer-overflow\n'):
            with self.subTest(raw=raw), self.changed(path, raw), self.assertRaises(ValueError):
                self.read()

    def test_command_argv_instrumentation_compiler_and_timeout(self):
        label = 'profiles/plain-compile'
        path = self.native / (label + '.json')
        baseline = M.base.load(path)
        for edit in (lambda d: d['argv'].__setitem__(0, '/wrong/cc'),
                     lambda d: d['argv'].remove('-fsanitize=address,undefined'),
                     lambda d: d.__setitem__('ASAN_OPTIONS', 'detect_leaks=0'),
                     lambda d: d.__setitem__('timeout', True), lambda d: d.__setitem__('returncode', False)):
            row = copy.deepcopy(baseline)
            edit(row)
            with self.changed(path, json.dumps(row).encode()), self.assertRaises(ValueError):
                M.command_receipt(self.native, label, baseline['argv'])
        for suffix in ('.stdout', '.stderr'):
            with self.changed(self.native / (label + suffix), b'noise'), self.assertRaisesRegex(ValueError, 'precise process'):
                self.read()

    def test_quality35_new_raw_markers_cannot_be_replaced_by_counts(self):
        for name in ('uniphy-wrong-map-address', 'psgmii-read-not-published', 'foreign-gcc-retirement',
                     'switch-wrong-getter', 'uniphy-wrong-device', 'psgmii-wrong-slot'):
            path = self.native / ('negative/' + name + '-run.stderr')
            with self.subTest(name=name), self.changed(path, b'PLATFORM:WRONG\n'), self.assertRaisesRegex(ValueError, 'precise process'):
                self.read()

    def test_actual_compiler_hash_and_fixed_flags(self):
        for edit in (lambda d: d['compiler'].__setitem__('sha256', '0' * 64),
                     lambda d: d['compiler']['flags'].remove('-fno-sanitize-recover=all')):
            with self.mutate_report(edit), self.assertRaisesRegex(ValueError, 'compiler bytes/flags'):
                self.read()

    def test_exact_positive_case_inventory_and_typed_counts(self):
        for edit in (lambda d: d['positive'][0].__setitem__('cases', True),
                     lambda d: d['negative'].pop(), lambda d: d['old_witnesses'].pop(),
                     lambda d: d.__setitem__('positive_count', 1705.0)):
            with self.mutate_report(edit), self.assertRaises(ValueError):
                self.read()

    def test_positive_raw_counts_are_recomputed(self):
        path = self.native / 'positive/plain/0.stdout'
        row = M.base.load(path)
        row['maps'] += 1
        with self.changed(path, json.dumps(row).encode()), self.assertRaisesRegex(ValueError, 'exact resource counts'):
            self.read()

    def test_sdk_runtime_contamination_and_callback_summary(self):
        with self.changed(self.native / 'sdk-view-run.stdout', b'PASS\n'), self.assertRaisesRegex(ValueError, 'precise process'):
            self.read()
        with self.mutate_report(lambda d: d['sdk_reg_func_fields'].append('private_ledger')), self.assertRaisesRegex(ValueError, 'SDK-only callback'):
            self.read()

    def test_aggregate_command_order_not_trusted(self):
        with self.mutate_report(lambda d: d['commands'].reverse()), self.assertRaisesRegex(ValueError, 'raw commands and order'):
            self.read()

    def test_extra_receipt_and_raw_file_rejected(self):
        for name, message in (('unlisted.json', 'command receipts'), ('unlisted.stderr', 'contamination'),
                              ('.unexpected', 'contamination')):
            with self.subTest(name=name), self.changed(self.native / name, b'noise'), self.assertRaisesRegex(ValueError, message):
                self.read()

    def test_host_binary_not_just_declared_in_summary(self):
        with self.changed(self.native / 'sdk-view.host', b'not a program'), self.assertRaisesRegex(ValueError, 'ELF/Mach-O'):
            self.read()

    def test_replay_drift_and_patch_offset_rejected(self):
        path = self.native / ('replayed/' + M.PLAT)
        with self.changed(path, path.read_bytes() + b'\n'), self.assertRaisesRegex(ValueError, 'replay tree'):
            self.read()
        with self.changed(self.native / 'patch.stdout', b'patching file src/init/ssdk_plat.c\nHunk #1 succeeded at 1 (offset 1 line).\n'), self.assertRaisesRegex(ValueError, 'replay diagnostics'):
            self.read()

    def test_reader_does_not_refresh_expectations_from_prepared_inputs(self):
        for root in (self.current, self.prefix):
            path = root / M.PLAT
            with self.subTest(root=root), self.changed(path, path.read_bytes() + b'\n'), self.assertRaisesRegex(ValueError, 'fixed complete41/40'):
                self.read()
        path = self.source / M.RUNNER
        with self.changed(path, path.read_bytes() + b'\n'), self.assertRaisesRegex(ValueError, 'fixed input drift'):
            self.read()

    def test_main_wrong_actual_head_persists_fail_without_parent(self):
        output = self.root / 'simulated-main-wrong-source-head'
        argv = ['gate41', '--admission-only', '--source-root', str(self.source), '--ssdk', str(self.current), '--output', str(output)]
        process = subprocess.CompletedProcess([], 0, (M.PARENT + '\n').encode(), b'')
        with patch.object(sys, 'argv', argv), patch.object(M.subprocess, 'run', return_value=process) as run:
            with self.assertRaisesRegex(ValueError, 'precise process'):
                M.main()
        self.assertEqual(run.call_count, 1)
        report = M.base.load(output / 'RESULTS.json')
        self.assertEqual(report['status'], 'FAIL')
        self.assertFalse(report['integrated'])
        self.assertFalse(report['firmware_approved'])

    def test_main_frozen40_requires_real_separate_head(self):
        output = self.root / 'simulated-main-wrong-frozen40-head'
        frozen = self.root / 'simulated-frozen40-not-a-real-checkout'
        frozen.mkdir()
        argv = ['gate41', '--source-root', str(self.source), '--ssdk', str(self.current), '--output', str(output),
                '--accepted40-source-root', str(frozen), '--accepted39-source-root', str(self.root / 'frozen39'),
                '--baseline-source-root', str(self.root / 'frozen38'), '--legacy-source-root', str(self.root / 'legacy'),
                '--dp', str(self.root / 'dp'), '--cc', self.compiler]
        original_run = subprocess.run
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if command[0] == 'git':
                # A claimed quality35 HEAD is not admissible as frozen40.
                return subprocess.CompletedProcess(command, 0, (M.SOURCE + '\n').encode(), b'')
            return original_run(command, **kwargs)

        with patch.object(sys, 'argv', argv), patch.object(M.subprocess, 'run', side_effect=run):
            with self.assertRaisesRegex(ValueError, 'precise process'):
                M.main()
        self.assertEqual([r[0] for r in calls], ['git', 'patch', 'git'])
        report = M.base.load(output / 'RESULTS.json')
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(M.base.inventory(output / 'prefix40'), M.old.configuration()['prepared_files'])
        self.assertFalse((output / 'accepted40-parent').exists())
        self.assertFalse((output / 'platform-native').exists())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-git', type=Path)
    parser.add_argument('--prepared41', type=Path)
    parser.add_argument('--debug-controls-only', action='store_true')
    ARGS = parser.parse_args()
    if not ARGS.debug_controls_only and not (ARGS.source_git and ARGS.prepared41):
        parser.error('--source-git and --prepared41 required outside --debug-controls-only')
    ARGS.output = ARGS.output.absolute()
    ARGS.output.mkdir(parents=True, exist_ok=False)
    stream = io.StringIO()
    suite = (unittest.defaultTestLoader.loadTestsFromTestCase(DebugCompanionTests) if ARGS.debug_controls_only else
             unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    gate_digest = M.sha(Path(M.__file__).read_bytes())
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    raw = stream.getvalue()
    (ARGS.output / 'unittest.log').write_text(raw)
    (ARGS.output / 'RESULTS.json').write_text(json.dumps(dict(
        status='PASS_READER_CONTROLS_ONLY_NOT_NATIVE' if result.wasSuccessful() else 'FAIL',
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        synthetic_receipts=True, native_campaign_run=False, firmware_approved=False, quality_revision=M.QUALITY,
        debug_controls_only=ARGS.debug_controls_only, gate_sha256=gate_digest), indent=2) + '\n')
    print(raw, end='')
    sys.exit(0 if result.wasSuccessful() else 1)
