#!/usr/bin/env python3
"""ELF structure/metadata negative controls; no module execution or installation."""
import base64
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys

from elftools.elf.elffile import ELFFile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checks = load('artifact_checks', ROOT / '.github/scripts/verify-ax6-artifacts.py')
fixtures = load('artifact_fixtures', ROOT / 'tests/test-ax6-artifact-checks.py')
REFERENCE = base64.b64decode((ROOT / 'tests/fixtures/module-elf/fixture.b64').read_bytes())
assert checks.sha(REFERENCE) == 'b09ab82afeb97f1368eef789aca0a62970a8783ae6cb744e446e82751cab7a6b'
ELF = ELFFile(io.BytesIO(REFERENCE))
PATH = 'lib/modules/6.18.38/module0.ko'
rows = []


def mutate(blob, offset, value, fmt):
    changed = bytearray(blob)
    struct.pack_into(fmt, changed, offset, value)
    return bytes(changed)


def section_offset(name):
    index = next(i for i, section in enumerate(ELF.iter_sections()) if section.name == name)
    return ELF.header['e_shoff'] + index * ELF.header['e_shentsize']


def bad(name, blob):
    # Rebind the same bad bytes into both IPK and rootfs. Byte matching alone
    # must not accept malformed modules, including a non-core package.
    packages, root = fixtures.module_fixture()
    package = checks.CORE_PACKAGES[0]
    packages[package]['payload'] = checks.tar_members(fixtures.tar([(PATH, blob)]))
    root[PATH] = blob
    try:
        checks.verify_modules(packages, root.__getitem__)
    except checks.Invalid as error:
        rows.append({'name': name, 'rejected': True, 'reason': str(error)})
    else:
        raise AssertionError('negative control accepted: ' + name)


positive = checks.verify_module_elf(REFERENCE, PATH, '6.18.38')
assert positive['name'] == 'module0' and positive['vermagic'] == '6.18.38 SMP mod_unload aarch64'
packages, root = fixtures.module_fixture()
assert checks.verify_modules(packages, root.__getitem__)['module_count'] == 8

fake = bytearray(64)
fake[:6] = b'\x7fELF\x02\x01'
struct.pack_into('<H', fake, 18, 183)
bad('fake-64-byte-header', bytes(fake))
bad('short-header', REFERENCE[:20])
bad('truncated-section-table', REFERENCE[:-64])
for name, offset, value, fmt in (
    ('wrong-elf-type', 16, 3, '<H'), ('wrong-ident-version', 6, 0, 'B'),
    ('wrong-elf-version', 20, 0, '<I'), ('section-table-offset-past-eof', 40, len(REFERENCE) + 4096, '<Q'),
    ('wrong-section-entry-size', 58, 1, '<H'), ('wrong-architecture', 18, 62, '<H'),
    ('wrong-endianness', 5, 2, 'B'), ('wrong-class', 4, 1, 'B'),
    ('wrong-header-size', 52, 20, '<H'), ('unexpected-program-headers', 56, 1, '<H'),
    ('missing-section-table', 60, 0, '<H'), ('bad-section-count', 60, 65535, '<H'),
    ('bad-section-name-index', 62, 65534, '<H')):
    bad(name, mutate(REFERENCE, offset, value, fmt))
bad('wrong-internal-vermagic', REFERENCE.replace(b'vermagic=6.18.38 ', b'vermagic=0.00.00 ', 1))
bad('missing-modinfo-section', REFERENCE.replace(b'.modinfo\0', b'.badinfo\0', 1))
bad('missing-this-module-section', REFERENCE.replace(b'.gnu.linkonce.this_module\0', b'.gnu.linkonce.fake_module\0', 1))
bad('wrong-internal-name', REFERENCE.replace(b'name=module0\0', b'name=moduleX\0', 1))
bad('missing-vermagic-key', REFERENCE.replace(b'vermagic=', b'badmagic=', 1))
bad('missing-name-key', REFERENCE.replace(b'name=module0\0', b'junk=module0\0', 1))
bad('empty-name', REFERENCE.replace(b'name=module0\0', b'name=\0\0\0\0\0\0\0\0', 1))
bad('non-ascii-metadata-key', REFERENCE.replace(b'name=module0\0', b'nam\xff=module0\0', 1))
bad('section-payload-outside-file', mutate(REFERENCE, section_offset('.modinfo') + 24, len(REFERENCE) + 1, '<Q'))
bad('invalid-metadata-section-type', mutate(REFERENCE, section_offset('.modinfo') + 4, 8, '<I'))
bad('invalid-symbol-entry-size', mutate(REFERENCE, section_offset('.symtab') + 56, 1, '<Q'))
bad('invalid-symbol-string-link', mutate(REFERENCE, section_offset('.symtab') + 40, 65534, '<I'))
relocation = next(section.name for section in ELF.iter_sections() if section['sh_type'] == 'SHT_RELA')
bad('invalid-relocation-target', mutate(REFERENCE, section_offset(relocation) + 44, 65534, '<I'))
bad('invalid-relocation-entry-size', mutate(REFERENCE, section_offset(relocation) + 56, 1, '<Q'))
offset = ELF.get_section_by_name(relocation)['sh_offset']
bad('relocation-offset-outside-target', mutate(REFERENCE, offset, 2**32, '<Q'))
bad('relocation-symbol-outside-table', mutate(REFERENCE, offset + 8, (65534 << 32) | 257, '<Q'))
info = ELF.get_section_by_name('.modinfo')
bad('unterminated-metadata', mutate(REFERENCE, info['sh_offset'] + info['sh_size'] - 1, ord('X'), 'B'))
bad('compressed-metadata', mutate(REFERENCE, section_offset('.modinfo') + 8, info['sh_flags'] | 0x800, '<Q'))
bad('duplicate-vermagic', REFERENCE.replace(b'depends=\0', b'vermagic=', 1))
bad('duplicate-internal-name', REFERENCE.replace(b'depends=\0', b'name=X\0\0\0', 1))
bad('missing-symbol-table', REFERENCE.replace(b'.symtab\0', b'.badtab\0', 1))
bad('invalid-module-descriptor-type', mutate(REFERENCE, section_offset('.gnu.linkonce.this_module') + 4, 8, '<I'))
descriptor = ELF.get_section_by_name('.gnu.linkonce.this_module')
bad('module-descriptor-not-allocated', mutate(REFERENCE, section_offset(descriptor.name) + 8,
                                           descriptor['sh_flags'] & ~2, '<Q'))
for name in ('.text', '.symtab', '.gnu.linkonce.this_module', relocation):
    section = ELF.get_section_by_name(name)
    bad('compressed-required-' + name, mutate(REFERENCE, section_offset(name) + 8,
                                             section['sh_flags'] | 0x800, '<Q'))
for name, delta, value, fmt in (('null-section-type', 4, 1, '<I'),
                              ('null-section-size', 32, 1, '<Q'),
                              ('null-section-address', 16, 1, '<Q')):
    bad(name, mutate(REFERENCE, ELF.header['e_shoff'] + delta, value, fmt))
bad('multiple-symbol-tables', mutate(REFERENCE, section_offset('.text') + 4, 2, '<I'))
bad('section-name-outside-string-table', mutate(REFERENCE, section_offset('.text'), 2**32 - 1, '<I'))
symbols = ELF.get_section_by_name('.symtab')
bad('symbol-name-outside-string-table', mutate(REFERENCE, symbols['sh_offset'] + 24, 2**32 - 1, '<I'))
strings = ELF.get_section(ELF.get_shstrndx())
bad('unterminated-section-name-table', mutate(REFERENCE, strings['sh_offset'] + strings['sh_size'] - 1, ord('X'), 'B'))

# A matching release is not enough: all installed modules must agree on flags.
packages, root = fixtures.module_fixture()
noncore = 'lib/modules/6.18.38/module7.ko'
changed = root[noncore].replace(b'SMP', b'BAD', 1)
packages['kmod-noncore']['payload'] = checks.tar_members(fixtures.tar([(noncore, changed)]))
root[noncore] = changed
try:
    checks.verify_modules(packages, root.__getitem__)
except checks.Invalid as error:
    rows.append({'name': 'noncore-inconsistent-vermagic-flags', 'rejected': True, 'reason': str(error)})
else:
    raise AssertionError('non-core inconsistent vermagic accepted')

print(json.dumps({'status': 'PASS_OFFLINE_MODULE_PARSER_TESTS_ONLY', 'positive_fixture': positive,
                  'negative_count': len(rows), 'negative_controls': rows,
                  'limits': ['synthetic ELF fixture, not a loadable AX6 module',
                             'no complete kernel ABI/signature/hardware/performance verification']}, indent=2))
