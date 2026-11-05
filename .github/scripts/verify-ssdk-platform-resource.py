#!/usr/bin/env python3
"""Freeze quality35 platform evidence and run immutable40/39/38 on real prefixes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / '.github/ax6-ssdk41-contract.json'
OLD_GATE = ROOT / '.github/scripts/verify-ssdk-probe-resource.py'
spec = importlib.util.spec_from_file_location('frozen40_platform_parent', OLD_GATE)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
base = old.base
need, sha = base.need, base.sha
SOURCE = '4245760179a1fbf2a0ce35cc4e6f21fc49b642cc'
PARENT = 'fce57df4d7828fa9e9c7a45975f37f09a77fa101'
PARENT_CONTRACT = 'a4c6901e6175a56d7c8930838a0b75ee90e05cdf5eecccae91750d7585772872'
PARENT_GATE = 'e203373bcc34706315d4bfe051934eb91e2a606cfdede8a3e14d4e042785fc97'
PACKAGE = 'package/qca-nss/qca-ssdk/'
PATCH = PACKAGE + 'patches/053-ssdk-track-platform-resource-acquisition.patch'
PLAT = 'src/init/ssdk_plat.c'
SUPPORT = 'tests/ssdk-platform-resources/'
RUNNER = 'tests/test-ssdk-platform-resources.py'
SOURCE_OVERRIDES = {
    PACKAGE + 'Makefile': 'a4f44c2ea43aaf4a35e93472cef0c81f96b0104fb913a93d17b0b4197ecc9757',
    PATCH: '9863d5e960f8582100cf61fc22373490c6cfc5db8236a4da20cb1d8ecc159938',
    SUPPORT + 'README.md': 'efb08a3d78ecc12d28c27dc25d16660a6b342e0a899bb733ee8327d8c6c6904c',
    SUPPORT + 'fixture.c': '198f5504dd491efffb45740cdfeec80de5c611038be1aa4c1ea9b0ea8268f86e',
    'tests/test-ssdk-platform-oracles.py': 'b8fa54fe36656af3df7b3cb9de598048f646f2b2785e4740e6a2cc706d83ca46',
    RUNNER: 'aac21378daf2f225f24800be2509bb89f3cbdf867e985fded95d58eedf503f4f',
}
QUALITY_BLOBS = {
    SUPPORT + 'README.md': 'c3a06ab3c3bcdb492f1c4d8f4820bf7e192bad90',
    SUPPORT + 'fixture.c': 'fe073f0aa24850939bd3161ce757965fbd0db8ce',
    'tests/test-ssdk-platform-oracles.py': 'c13f388bb88ad016fc5cf8414f0e95e926dd71c4',
    RUNNER: '3ee68375bfaaa1e1de1be80b7b85e821ea125ee7',
}
PREPARED_OVERRIDES = {PLAT: 'aff83ac50ba65685ab44d1c6ad8c96d8c6f040045a532e52b6cc7af2f1d0474f'}
QUALITY = 'QUALITY35_4245760179_MANUALLY_REVIEWED_SOURCE_AND_EXACT_ORACLES'
OPEN = [
    'root/module UK/SD/PHY provider and reader retirement',
    'nested void GCC clock/reset success and clock error propagation',
    'Linux GCC11, target ABI, hardware, firmware and performance',
    'workflow, source lock and source manifest integration',
]
STATUS = 'PASS_SSDK41_QUALITY35_RECEIPTS_AND_IMMUTABLE40_39_38_HOST_ONLY'
NATIVE_STATUS = 'PASS_SSDK41_PLATFORM_HOST_ONLY_NOT_ROOT_SHARED_LIFECYCLE'
ASAN = 'detect_leaks=0:halt_on_error=1:abort_on_error=0:exitcode=97'
UBSAN = 'halt_on_error=1:abort_on_error=0:print_stacktrace=1:exitcode=98'
FLAGS = ['-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
         '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer']
PROFILES = {
    'plain': [], 'uniphy': ['IN_UNIPHY'], 'dess': ['DESS'], 'dess-uniphy': ['DESS', 'IN_UNIPHY'],
    'hppe': ['HPPE'], 'hppe-uniphy': ['HPPE', 'IN_UNIPHY'], 'hppe-dess': ['HPPE', 'DESS'],
    'hppe-dess-uniphy-synthetic': ['HPPE', 'DESS', 'IN_UNIPHY'], 'mp-uniphy': ['MP', 'IN_UNIPHY'],
}

# These anchors and obligations are reviewed Git data, never runner declarations.
MUTANTS = [
    ('uniphy-leak', '\tif (resources->uniphy)\n\t\tiounmap(resources->uniphy);', '(void)resources->uniphy;', (3, 2, 1, 0), 'MAP_LEAK'),
    ('region-leak', '\tif (resources->psgmii_region)\n\t\trelease_mem_region(resources->psgmii_map.base_addr,\n\t\t\tresources->psgmii_map.size);', '(void)resources->psgmii_region;', (7, 3, 0, 0), 'REGION_LEAK'),
    ('clock-leak', '\tif (resources->ess_enabled)\n\t\tclk_disable_unprepare(resources->ess_clk);', '(void)resources->ess_enabled;', (2, 0, 0, 0), 'CLOCK_LEAK'),
    ('failed-clock-retired', '\t\t\tif (clock_rv) {', '\t\t\tif (clock_rv) { pending.ess_clk = ess_clk; pending.ess_enabled = true;', (2, 0, 4, 0), 'UNOWNED_CLOCK'),
    ('gcc-repeated-init', '\t\t\tif (!ssdk_plat_gcc_users)\n\t\t\t\tssdk_gcc_clock_init();', '\t\t\tssdk_gcc_clock_init();', (2, 0, 1, 2), 'GCC_DOUBLE_START'),
    ('gcc-premature-stop', 'resources->gcc && --ssdk_plat_gcc_users == 0', 'resources->gcc && --ssdk_plat_gcc_users < SW_MAX_NR_DEV', (2, 0, 1, 2), 'GCC_PEER_RETIRE'),
    ('gcc-missing-right', '\t\t\t++ssdk_plat_gcc_users;', '\t\t\t(void)ssdk_plat_gcc_users;', (2, 0, 1, 0), 'GCC_LEAK'),
    ('region-missing-right', 'pending.psgmii_region = true;', 'pending.psgmii_region = false;', (7, 3, 0, 0), 'REGION_LEAK'),
    ('ledger-not-retired', '\tmemset(resources, 0, sizeof(*resources));', '\t(void)resources;', (2, 0, 0, 0), 'LEDGER_LEAK'),
    ('early-cfg', '\tpending.owner = priv;', '\tpending.owner = priv; cfg->reg_func.uniphy_reg_set = qca_uniphy_reg_write;', (7, 0, 0, 0), 'EARLY_CFG'),
    ('early-map', '#ifdef DESS\n\treg_mode = ssdk_psgmii_reg_access_mode_get(dev_id);', '\tpriv->hw_addr = pending.switch_base;\n#ifdef DESS\n\treg_mode = ssdk_psgmii_reg_access_mode_get(dev_id);', (7, 0, 0, 0), 'EARLY_PUBLICATION'),
    ('region-wrong-identity', 'release_mem_region(resources->psgmii_map.base_addr,', 'release_mem_region(resources->psgmii_map.base_addr + 4,', (7, 0, 0, 0), 'REGION_PAIR'),
    ('invalid-accepted', '\t\trv = -EINVAL;', '\t\trv = 0;', (0, 0, 0, 5), 'INVALID_RESULT'),
    ('wrong-mdio', '\t\taccess_mode = HSL_MDIO;', '\t\taccess_mode = HSL_HEADER;', (0, 0, 0, 0), 'CFG_MODE'),
    ('empty-owner-admission', 'ssdk_plat_resources[dev_id].owner || ', '', (0, 0, 0, 1), 'ADMISSION_RESULT'),
    ('borrowed-map-admission', ' || priv->hw_addr ||', ' ||', (0, 0, 0, 3), 'ADMISSION_RESULT'),
    ('foreign-instance-exit', '\tif (!qca_phy_priv_global || dev_id >= ssdk_switch_device_num_get() ||\n\t    qca_phy_priv_global[dev_id] != resources->owner)\n\t\tgoto foreign;', '\t(void)qca_phy_priv_global;', (2, 0, 6, 4), 'FOREIGN_RETIRE'),
    ('foreign-mapping-exit', '\tif (priv->hw_addr != resources->switch_base ||\n\t    priv->uniphy_hw_addr != resources->uniphy ||\n\t    priv->psgmii_hw_addr != resources->psgmii)\n\t\tgoto foreign;', '\t(void)priv;', (2, 0, 6, 4), 'FOREIGN_RETIRE'),
    ('missing-cold-lock', '\trv = -1;\n\tmutex_lock(&ssdk_plat_resource_lock);', '\trv = -1;', (2, 0, 0, 0), 'LOCK_MISSING'),
    ('gcc-before-mapping-complete', '#ifdef DESS\n\treg_mode = ssdk_psgmii_reg_access_mode_get(dev_id);', '\tssdk_gcc_clock_init(); ++ssdk_plat_gcc_users; pending.gcc = true;\n#ifdef DESS\n\treg_mode = ssdk_psgmii_reg_access_mode_get(dev_id);', (7, 3, 1, 0), 'CLOCK_BEFORE_MAP_COMPLETE'),
    ('uniphy-wrong-map-address', 'pending.uniphy = ioremap(map.base_addr, map.size);',
     'pending.uniphy = ioremap(map.base_addr + 4, map.size);', (1, 0, 2, 0), 'MAP_IDENTITY'),
    ('switch-wrong-map-address', 'pending.switch_base = ioremap(map.base_addr, map.size);',
     'pending.switch_base = ioremap(map.base_addr + 4, map.size);', (2, 0, 2, 0), 'MAP_IDENTITY'),
    ('psgmii-wrong-map-address', 'pending.psgmii = ioremap(pending.psgmii_map.base_addr,',
     'pending.psgmii = ioremap(pending.psgmii_map.base_addr + 4,', (4, 0, 2, 0), 'MAP_IDENTITY'),
    ('uniphy-read-not-published', '\t\treg_func.uniphy_reg_get = qca_uniphy_reg_read;',
     '\t\t/* mutation: read callback omitted */', (1, 0, 2, 0), 'UNIPHY_READ_PUBLICATION'),
    ('psgmii-read-not-published', '\t\treg_func.psgmii_reg_get = qca_psgmii_reg_read;',
     '\t\t/* mutation: read callback omitted */', (4, 0, 2, 0), 'PSGMII_READ_PUBLICATION'),
    ('foreign-ess-retirement', 'foreign:\n',
     'foreign:\n\tif (resources->ess_enabled) {\n\t\tclk_disable_unprepare(resources->ess_clk);\n'
     '\t\tresources->ess_enabled = false;\n\t}\n', (2, 0, 0, 4), 'FOREIGN_RIGHTS'),
    ('foreign-gcc-retirement', 'foreign:\n',
     'foreign:\n\tif (resources->gcc) {\n\t\tif (--ssdk_plat_gcc_users == 0)\n'
     '\t\t\tssdk_gcc_clock_exit();\n\t\tresources->gcc = false;\n\t}\n', (2, 0, 1, 4), 'FOREIGN_RIGHTS'),
    ('foreign-ledger-erased', 'foreign:\n',
     'foreign:\n\tmemset(resources, 0, sizeof(*resources));\n', (2, 0, 2, 4), 'FOREIGN_RIGHTS'),
    ('uniphy-wrong-getter', 'ssdk_uniphy_reg_map_info_get(dev_id, &map);',
     'ssdk_switch_reg_map_info_get(dev_id, &map);', (7, 1, 2, 0), 'MAP_ROLE'),
    ('switch-wrong-getter', 'ssdk_switch_reg_map_info_get(dev_id, &map);',
     'ssdk_uniphy_reg_map_info_get(dev_id, &map);', (7, 2, 2, 0), 'MAP_ROLE'),
    ('psgmii-wrong-getter', 'ssdk_psgmii_reg_map_info_get(dev_id, &pending.psgmii_map);',
     'ssdk_switch_reg_map_info_get(dev_id, &pending.psgmii_map);', (7, 3, 2, 0), 'MAP_ROLE'),
    ('uniphy-wrong-device', 'ssdk_uniphy_reg_map_info_get(dev_id, &map);',
     'ssdk_uniphy_reg_map_info_get((dev_id + 1) % SW_MAX_NR_DEV, &map);', (1, 0, 2, 0), 'MAP_DEVICE_ROLE'),
    ('uniphy-wrong-slot', 'priv->uniphy_hw_addr = pending.uniphy;',
     'priv->uniphy_hw_addr = pending.switch_base;', (7, 0, 2, 0), 'MAP_SLOT_IDENTITY'),
    ('switch-wrong-slot', 'priv->hw_addr = pending.switch_base;',
     'priv->hw_addr = pending.uniphy;', (7, 0, 2, 0), 'MAP_SLOT_IDENTITY'),
    ('psgmii-wrong-slot', 'priv->psgmii_hw_addr = pending.psgmii;',
     'priv->psgmii_hw_addr = pending.switch_base;', (7, 0, 2, 0), 'MAP_SLOT_IDENTITY'),
]
WITNESSES = [((3, 2, 1, 0), 'ERROR_PUBLICATION'), ((7, 3, 0, 0), 'ERROR_PUBLICATION'),
             ((2, 0, 6, 10), 'EXIT_PUBLICATION'), ((2, 0, 1, 2), 'GCC_DOUBLE_START')]


def configuration():
    data = base.load(PROFILE)
    need(set(data) == {'schema', 'frozen', 'profile', 'source_commit', 'accepted40_commit',
                      'accepted40_contract_sha256', 'accepted40_gate_sha256', 'source_overrides',
                      'prepared_overrides', 'quality_test_blobs', 'quality_revision', 'open'}, 'exact frozen41 contract keys')
    need(type(data['schema']) is int and data['schema'] == 1 and data['frozen'] is True and
         data['profile'] == 'SSDK41_PLATFORM_QUALITY35_REVIEWED_HOST_ONLY', 'fixed SSDK41 profile')
    need(data['source_commit'] == SOURCE and data['accepted40_commit'] == PARENT, 'fixed41/40 source identity')
    need(data['accepted40_contract_sha256'] == PARENT_CONTRACT == sha(old.PROFILE.read_bytes()) and
         data['accepted40_gate_sha256'] == PARENT_GATE == sha(OLD_GATE.read_bytes()), 'immutable SSDK40 contract/gate')
    parent = old.configuration()
    need(parent['source_commit'] == PARENT, 'real frozen40 source identity')
    need(data['source_overrides'] == SOURCE_OVERRIDES, 'fixed Git quality35 source assets')
    need(data['quality_test_blobs'] == QUALITY_BLOBS, 'fixed quality35 Git test blobs')
    need(data['prepared_overrides'] == PREPARED_OVERRIDES and
         parent['prepared_files'][PLAT] == 'd4575ba235184edb072761cf5e5d02bc3b61f0944b315d8bdd73d991a19bb8f1',
         'only reviewed platform delta')
    need(data['quality_revision'] == QUALITY and data['open'] == OPEN,
         'fixed quality35 scope and remaining open boundaries')
    data = dict(data, source_assets=parent['source_assets'] | SOURCE_OVERRIDES,
                prepared_files=parent['prepared_files'] | PREPARED_OVERRIDES)
    need(len(data['prepared_files']) == 692, 'complete frozen692')
    return data


def patch_inventory(data):
    prefix = PACKAGE + 'patches/'
    return {n[len(prefix):]: v for n, v in data['source_assets'].items() if n.startswith(prefix)}


def admit_source(source, data):
    base.check(source, data['source_assets'])
    need(base.inventory(source / (PACKAGE + 'patches')) == patch_inventory(data) and
         len(patch_inventory(data)) == 41, 'exact41 patch directory')
    need(base.inventory(source / SUPPORT) == {n[len(SUPPORT):]: v for n, v in SOURCE_OVERRIDES.items()
                                            if n.startswith(SUPPORT)}, 'exact platform support directory')


def admit_prepared(root, expected):
    code, metadata = base.partition(root)
    need(code == expected, 'complete frozen prepared tree; no missing/extra/drift')
    return code, metadata


def exact(code, out, err, expected_out=b'', expected_err=b'', expected_code=0):
    need(type(code) is int and type(out) is bytes and type(err) is bytes and
         code == expected_code and out == expected_out and err == expected_err, 'precise process result')


def positive(code, out, err, expected=None):
    need(type(code) is int and code == 0 and type(out) is bytes and type(err) is bytes and err == b'', 'clean positive process')
    value = json.loads(out, object_pairs_hook=base.unique)
    counts = {'maps', 'unmaps', 'claims', 'releases', 'enables', 'disables', 'gcc_starts', 'gcc_stops'}
    need(type(value) is dict and set(value) == counts | {'status'} and value['status'] == 'PLATFORM_CASE' and
         all(type(value[k]) is int and value[k] >= 0 for k in counts), 'typed exact positive ledger')
    need(expected is None or value == expected, 'independent exact resource counts')
    return value


def positive_cases(defines):
    cases = []
    for mask in range(8):
        count = int(bool(mask & 2)) + int('IN_UNIPHY' in defines and bool(mask & 1)) + int('DESS' in defines and bool(mask & 4))
        faults = [0, *range(1, count + 1), *([10] if 'DESS' in defines and mask & 4 else [])]
        cases.extend((mask, fault, clock, 0) for clock in range(7) for fault in faults)
    cases.extend((7, 0, clock, scenario) for clock in range(7) for scenario in (1, 2, 4, 6, 7, 9, 10))
    count = 1 + int('IN_UNIPHY' in defines) + int('DESS' in defines)
    cases.extend((7, fault, clock, 8) for clock in range(7) for fault in range(1, count + 1))
    cases.extend([(7, 0, 0, 3), (0, 0, 0, 5)])
    need(len(cases) == len(set(cases)), 'unique frozen positive cases')
    return cases


def simple_ledger(defines, mask, fault, clock):
    kinds = ([0] if 'IN_UNIPHY' in defines and mask & 1 else []) + ([1] if mask & 2 else [])
    kinds += [2] if 'DESS' in defines and mask & 4 else []
    maps, region = 0, 0
    for index, kind in enumerate(kinds, 1):
        if kind == 2:
            if fault == 10:
                break
            region = 1
        if index == fault:
            break
        maps += 1
    clock_reached = maps == len(kinds) and bool(mask & 2)
    gcc = int(clock_reached and clock in (1, 5) and bool({'HPPE', 'MP'} & set(defines)))
    return dict(status='PLATFORM_CASE', maps=maps, unmaps=maps, claims=region, releases=region,
                enables=int(clock_reached and clock in (0, 3, 4, 6)),
                disables=int(clock_reached and clock in (0, 3, 6)), gcc_starts=gcc, gcc_stops=gcc)


def typedef(text, name):
    rows = re.findall(r'\btypedef\s+(?:enum|struct)\s*\{[^{}]*\}\s*' + re.escape(name) + r'\s*;', text)
    need(len(rows) == 1, 'one actual typedef: ' + name)
    return rows[0]


def sdk_view(text):
    active, result = False, []
    for line in text.splitlines(True):
        if '/*qca808x_start*/' in line:
            need(not active, 'nested SDK export marker')
            active = True
        elif '/*qca808x_end*/' in line:
            need(active, 'unpaired SDK export marker')
            active = False
        elif active:
            result.append(line)
    need(not active and result, 'complete SDK export view')
    return ''.join(result)


def generated_sources(source, current, prefix):
    # Reuse only the frozen lexical parser, never import the campaign/runner.
    lexer_path = base.path(source, 'tests/nss-dp-containment/extract_prepared_c.py')
    spec = importlib.util.spec_from_file_location('platform_receipt_lexer', lexer_path)
    lexer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lexer)
    header = base.path(current, 'include/init/ssdk_init.h').read_text()
    errors = typedef(base.path(current, 'include/common/sw_error.h').read_text(), 'sw_error_t')

    def register_types(text):
        first = text.index('    typedef enum {\n        HSL_MDIO')
        last = text.index('} hsl_reg_func;', first) + len('} hsl_reg_func;')
        return text[first:last]

    types = errors + '\n' + register_types(header)
    types += '\n' + '\n'.join(typedef(header, n) for n in ('ssdk_chip_type', 'ssdk_port_cfg', 'ssdk_init_cfg'))
    types += '\n' + typedef(base.path(current, 'include/init/ssdk_dts.h').read_text(), 'ssdk_reg_map_info')
    maximum = re.findall(r'^#define SW_MAX_NR_DEV\s+3\s*$', base.path(current, 'include/common/sw_config.h').read_text(), re.M)
    need(len(maximum) == 1, 'actual frozen three device limit')
    template = base.path(source, SUPPORT + 'fixture.c').read_text()
    need(template.count('@ACTUAL_TYPES@') == template.count('@ACTUAL_MAX_DEV@') == template.count('@ACTUAL_CODE@') == 1,
         'one complete fixture substitution per actual input')
    template = template.replace('@ACTUAL_TYPES@', types).replace('@ACTUAL_MAX_DEV@', maximum[0])
    text = base.path(current, PLAT).read_text()
    start = text.index('/* Cold root init/exit only;')
    end_body = lexer.function(text, 'ssdk_plat_exit').rstrip()
    candidate = text[start:text.index(end_body, start) + len(end_body)]
    previous = base.path(prefix, PLAT).read_text()
    baseline = lexer.function(previous, 'ssdk_plat_init') + lexer.function(previous, 'ssdk_plat_exit')
    bodies = {**{'profiles/' + n: candidate for n in PROFILES}, 'old/current40': baseline}
    for name, before, after, _, _ in MUTANTS:
        need(candidate.count(before) == 1, 'independent unique mutation anchor: ' + name)
        bodies['negative/' + name] = candidate.replace(before, after, 1)
    sources = {name + '.c': template.replace('@ACTUAL_CODE@', body).encode() for name, body in bodies.items()}
    exported = sdk_view(text)
    exported_header = sdk_view(header)
    fields = sorted(re.findall(r'\b\w+\s+(\w+)\s*;', typedef(exported_header, 'hsl_reg_func')))
    need(fields == ['i2c_get', 'i2c_set', 'mdio_get', 'mdio_set'], 'actual SDK-only four callbacks')
    sdk_types = errors + '\n' + register_types(exported_header)
    sdk_types += '\n' + typedef(exported_header, 'ssdk_chip_type') + '\n' + typedef(exported_header, 'ssdk_init_cfg')
    sdk = '#include <stdio.h>\ntypedef unsigned a_uint32_t; typedef unsigned short a_uint16_t;\n'
    sdk += sdk_types + '\n#define SSDK_INFO(...) ((void)0)\n'
    sdk += lexer.function(exported, 'ssdk_plat_init') + lexer.function(exported, 'ssdk_plat_exit')
    sdk += '\nint main(void) { ssdk_plat_exit(0); return ssdk_plat_init(NULL, 0); }\n'
    sources['sdk-view.c'] = sdk.encode()
    need(all(b'@ACTUAL_' not in raw for raw in sources.values()), 'complete generated C')
    return sources


def command_receipt(directory, label, argv):
    row = base.load(base.path(directory, label + '.json'))
    need(set(row) == {'argv', 'returncode', 'ASAN_OPTIONS', 'UBSAN_OPTIONS'} and
         row['argv'] == list(map(str, argv)) and row['ASAN_OPTIONS'] == ASAN and row['UBSAN_OPTIONS'] == UBSAN,
         'actual exact argv/environment: ' + label)
    need(type(row['returncode']) is int, 'integer process exit: ' + label)
    out = base.path(directory, label + '.stdout').read_bytes()
    err = base.path(directory, label + '.stderr').read_bytes()
    return row, out, err


def macho_identity(raw, filetype):
    formats = {b'\xcf\xfa\xed\xfe': ('<', 32), b'\xfe\xed\xfa\xcf': ('>', 32),
               b'\xce\xfa\xed\xfe': ('<', 28), b'\xfe\xed\xfa\xce': ('>', 28)}
    need(type(raw) is bytes and raw[:4] in formats, 'thin Mach-O dSYM/program identity')
    endian, header = formats[raw[:4]]
    need(len(raw) >= header, 'complete Mach-O header')
    cpu, subtype, kind, count, size = struct.unpack_from(endian + '5I', raw, 4)
    need(kind == filetype, 'Mach-O filetype identity')
    end = header + size
    need(end <= len(raw) and count <= size // 8, 'Mach-O load command bounds')
    pos, uuids = header, []
    for _ in range(count):
        need(pos + 8 <= end, 'Mach-O load command header')
        cmd, length = struct.unpack_from(endian + '2I', raw, pos)
        need(length >= 8 and length % 4 == 0 and pos + length <= end, 'Mach-O load command size')
        if cmd == 0x1b:
            need(length == 24, 'Mach-O UUID command size')
            uuids.append(raw[pos + 8:pos + 24])
        pos += length
    need(pos == end and len(uuids) == 1 and any(uuids[0]), 'one actual Mach-O UUID')
    return (cpu, subtype, header, endian), uuids[0]


def host_debug_companions(directory, binaries, inventory):
    """Read only the reviewed three-file arm64 dSYM partner layout."""
    allowed, roots = set(), {name + '.dSYM': name for name in binaries}
    for bundle in directory.rglob('*.dSYM'):
        name = bundle.relative_to(directory).as_posix()
        if name.startswith(('replayed/', 'detector-controls/')):
            continue
        need(name in roots and bundle.is_dir() and not bundle.is_symlink(), 'only expected program dSYM bundles')
        program = roots[name]
        stem = Path(program).name
        plist = name + '/Contents/Info.plist'
        dwarf = name + '/Contents/Resources/DWARF/' + stem
        relocation = name + '/Contents/Resources/Relocations/aarch64/' + stem + '.yml'
        files = {plist, dwarf, relocation}
        need(base.inventory(bundle) == {n[len(name) + 1:]: inventory[n] for n in files if n in inventory} and
             files <= inventory.keys(), 'exact three-file dSYM companion set')
        directories = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_dir()}
        need(directories == {'Contents', 'Contents/Resources', 'Contents/Resources/DWARF',
                             'Contents/Resources/Relocations', 'Contents/Resources/Relocations/aarch64'},
             'exact dSYM directory layout')
        try:
            info = plistlib.loads(base.path(directory, plist).read_bytes())
        except Exception as error:
            raise ValueError('valid dSYM Info.plist') from error
        need(info == {'CFBundleDevelopmentRegion': 'English',
                      'CFBundleIdentifier': 'com.apple.xcode.dsym.' + stem,
                      'CFBundleInfoDictionaryVersion': '6.0', 'CFBundlePackageType': 'dSYM',
                      'CFBundleSignature': '????', 'CFBundleShortVersionString': '1.0', 'CFBundleVersion': '1'},
             'exact dSYM plist identity')
        executable = macho_identity(base.path(directory, program).read_bytes(), 2)
        debug = macho_identity(base.path(directory, dwarf).read_bytes(), 10)
        need(executable[0] == debug[0] and executable[0] == (0x0100000c, 0, 32, '<'), 'dSYM/program arm64 architecture identity')
        need(executable[1] == debug[1], 'dSYM/program UUID identity')
        raw = base.path(directory, relocation).read_bytes()
        need(0 < len(raw) <= 16 * 1024 * 1024, 'bounded dSYM relocation metadata')
        try:
            raw.decode('utf-8')
        except UnicodeError as error:
            raise ValueError('UTF-8 dSYM relocation metadata') from error
        need(all(sha(base.path(directory, n).read_bytes()) == inventory[n] for n in files | {program}),
             'dSYM/program byte stability')
        allowed.update(files)
    return allowed


def platform_receipts(directory, cc, source, current, prefix, data):
    admit_source(source, data)
    need(base.inventory(current) == data['prepared_files'] and
         base.inventory(prefix) == old.configuration()['prepared_files'], 'reader fixed complete41/40 source trees')
    report = base.load(base.path(directory, 'RESULTS.json'))
    need(report['status'] == NATIVE_STATUS and report['runtime_approved'] is False and
         report['profile'] == 'SERIAL_COLD_RESOURCE_MODELS_NOT_ROOT_SHARED_READERS_OR_TARGET_ABI', 'frozen native scope')
    need(report['prepared_files'] == data['prepared_files'] and report['source_patches'] == patch_inventory(data),
         'fixed native source inventories')
    owned_names = {RUNNER, SUPPORT + 'fixture.c', SUPPORT + 'README.md', 'tests/test-ssdk-platform-oracles.py',
                   'tests/test-ssdk-retirement-admission.py', 'tests/edma_patch_context.py',
                   'tests/nss-dp-containment/extract_prepared_c.py', PACKAGE + 'Makefile'}
    owned_names.update(n for n in data['source_assets'] if n.startswith(PACKAGE + 'patches/'))
    inputs = {str(base.path(source, n)): data['source_assets'][n] for n in owned_names}
    need(report['inputs'] == inputs, 'exact frozen native input set')
    compiler = shutil.which(cc)
    need(compiler is not None, 'actual host compiler')
    compiler = str(Path(compiler).resolve(strict=True))
    compiler_hash = sha(Path(compiler).read_bytes())
    need(report['compiler'] == {'path': compiler, 'sha256': compiler_hash, 'flags': FLAGS}, 'actual compiler bytes/flags')
    expected_positive = [{'profile': n, 'defines': d, 'cases': len(positive_cases(d))} for n, d in PROFILES.items()]
    negatives = [{'name': n, 'case': list(c), 'marker': m} for n, _, _, c, m in MUTANTS]
    witnesses = [{'case': list(c), 'marker': m} for c, m in WITNESSES]
    # JSON encodings preserve int versus bool/float in inventories too.
    need(json.dumps(report['positive'], sort_keys=True) == json.dumps(expected_positive, sort_keys=True) and
         json.dumps(report['negative'], sort_keys=True) == json.dumps(negatives, sort_keys=True) and
         json.dumps(report['old_witnesses'], sort_keys=True) == json.dumps(witnesses, sort_keys=True), 'exact fixed case inventory')
    need(all(type(report[k]) is int and report[k] == v for k, v in
             [('positive_count', 1705), ('negative_count', 35), ('old_witness_count', 4)]), 'typed fixed counts')
    sources = generated_sources(source, current, prefix)
    need({n for n in base.inventory(directory) if n.endswith('.c') and not n.startswith(('replayed/', 'detector-controls/'))} == set(sources),
         'exact generated C file inventory')
    for name, raw in sources.items():
        need(base.path(directory, name).read_bytes() == raw, 'independent full generated C: ' + name)
    need(base.inventory(directory / 'replayed') == data['prepared_files'], 'complete independent replay tree')
    patch_out = base.path(directory, 'patch.stdout').read_bytes()
    need(patch_out in (b'patching file src/init/ssdk_plat.c\n', b"patching file 'src/init/ssdk_plat.c'\n") and
         base.path(directory, 'patch.stderr').read_bytes() == b'', 'exact native patch replay diagnostics')
    commands = []

    def command(label, argv, marker=None, ledger=False, expected=None):
        row, out, err = command_receipt(directory, label, argv)
        if ledger:
            positive(row['returncode'], out, err, expected)
        else:
            exact(row['returncode'], out, err, expected_err=b'' if marker is None else ('PLATFORM:' + marker + '\n').encode(),
                  expected_code=0 if marker is None else 86)
        commands.append({'label': label, **row})

    row, out, err = command_receipt(directory, 'detector-controls',
                                  [sys.executable, '-B', source / 'tests/test-ssdk-retirement-admission.py', '--canaries-only',
                                   '--sanitize', '--cc', compiler, '--output', directory / 'detector-controls'])
    exact(row['returncode'], out, err, b'{"status": "PASS_SANITIZER_CONTROLS_ONLY"}\n')
    commands.append({'label': 'detector-controls', **row})
    old.old.sanitizer_receipts(directory / 'detector-controls', old.old.configuration(), compiler, False)
    need(report['sanitizer_controls'] == base.load(directory / 'detector-controls/RESULTS.json')['sanitizer_controls'],
         'raw sanitizer controls bound to native summary')
    for name, definitions in PROFILES.items():
        path = directory / ('profiles/' + name + '.c')
        binary = path.with_suffix('.host')
        command('profiles/' + name + '-compile', [compiler, *FLAGS, '-DCANDIDATE=1',
                                                *('-D' + d + '=1' for d in definitions), path, '-o', binary])
        for index, case in enumerate(positive_cases(definitions)):
            expected = simple_ledger(definitions, *case[:3]) if case[3] == 0 else None
            command('positive/' + name + '/' + str(index), [binary, *case], ledger=True, expected=expected)
    for name, _, _, case, marker in MUTANTS:
        path = directory / ('negative/' + name + '.c')
        binary = path.with_suffix('.host')
        command('negative/' + name + '-compile', [compiler, *FLAGS, '-DCANDIDATE=1', '-DHPPE=1', '-DDESS=1', '-DIN_UNIPHY=1', path, '-o', binary])
        command('negative/' + name + '-run', [binary, *case], marker)
    path = directory / 'old/current40.c'
    command('old/current40-compile', [compiler, *FLAGS, '-DHPPE=1', '-DDESS=1', '-DIN_UNIPHY=1', path, '-o', path.with_suffix('.host')])
    for index, (case, marker) in enumerate(WITNESSES):
        command('old/witness-' + str(index), [path.with_suffix('.host'), *case], marker)
    command('sdk-view-compile', [compiler, *FLAGS, '-Wno-unused-parameter', directory / 'sdk-view.c', '-o', directory / 'sdk-view.host'])
    command('sdk-view-run', [directory / 'sdk-view.host'])
    need(report['sdk_reg_func_fields'] == ['i2c_get', 'i2c_set', 'mdio_get', 'mdio_set'], 'SDK-only callback receipt')
    need(report['commands'] == commands and len(commands) == 1792, 'all actual raw commands and order')
    expected_json = {'RESULTS.json', *(r['label'] + '.json' for r in commands)}
    actual = base.inventory(directory)
    need({n for n in actual if n.endswith('.json') and not n.startswith('detector-controls/')} == expected_json,
         'no missing or extra native command receipts')
    binaries = {n[:-2] + '.host' for n in sources}
    debug = host_debug_companions(directory, binaries, actual)
    need({n for n in actual if n.endswith('.host') and not n.startswith('detector-controls/')} - debug == binaries,
         'exact46 actual host programs')
    expected_files = set(sources) | binaries | debug | {'RESULTS.json', 'patch.stdout', 'patch.stderr'}
    expected_files.update(r['label'] + suffix for r in commands for suffix in ('.json', '.stdout', '.stderr'))
    need({n for n in actual if not n.startswith(('replayed/', 'detector-controls/'))} == expected_files,
         'exact native evidence directory; no contamination')
    for name in binaries:
        raw = base.path(directory, name).read_bytes()
        need(len(raw) >= 32 and raw[:4] in (b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce'),
             'actual ELF/Mach-O host program: ' + name)
    need(sha(Path(compiler).read_bytes()) == compiler_hash, 'end compiler byte stability')
    admit_source(source, data)
    return {'positive': 1705, 'precise_negative': 35, 'old_witness': 4, 'generated_c': 46,
            'raw_commands': 1792, 'quality_revision': QUALITY}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--print-source-ref', action='store_true')
    mode.add_argument('--print-prefix40-ref', action='store_true')
    mode.add_argument('--admission-only', action='store_true')
    for name in ('source-root', 'accepted40-source-root', 'accepted39-source-root', 'baseline-source-root',
                 'legacy-source-root', 'ssdk', 'dp', 'output'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--cc')
    args = parser.parse_args()
    data = configuration()
    if args.print_source_ref or args.print_prefix40_ref:
        print(data['source_commit'] if args.print_source_ref else data['accepted40_commit'])
        return
    need(args.source_root and args.ssdk and args.output, 'source/prepared/output required')
    if args.admission_only:
        need(not any((args.accepted40_source_root, args.accepted39_source_root, args.baseline_source_root,
                      args.legacy_source_root, args.dp, args.cc)), 'admission-only does not qualify parent or native inputs')
    else:
        need(all((args.accepted40_source_root, args.accepted39_source_root, args.baseline_source_root,
                  args.legacy_source_root, args.dp, args.cc)), 'separate frozen40/39/38/legacy inputs required')
    source = args.source_root.absolute()
    original = args.ssdk.absolute()
    output = args.output.absolute()
    readonly = [p.absolute() for p in (args.source_root, args.ssdk, args.accepted40_source_root,
                args.accepted39_source_root, args.baseline_source_root, args.legacy_source_root, args.dp) if p]
    need(not any(output.resolve() == p.resolve() or output.resolve() in p.resolve().parents or
                 p.resolve() in output.resolve().parents for p in readonly), 'output must be separate from all input trees')
    output.mkdir(parents=True, exist_ok=False)
    result = {'status': 'INCOMPLETE', 'source_commit': SOURCE, 'accepted40_commit': PARENT,
              'runtime_approved': False, 'firmware_approved': False, 'integrated': False,
              'quality_revision': QUALITY, 'open': data['open'], 'commands': []}
    owned = {p: sha(p.read_bytes()) for p in (PROFILE, Path(__file__), old.PROFILE, OLD_GATE)}

    def invoke(label, argv, cwd=ROOT, raw=None):
        argv = list(map(str, argv))
        try:
            process = subprocess.run(argv, input=raw, cwd=cwd, capture_output=True, timeout=3600,
                                     env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            code, stdout, stderr, timed_out = process.returncode, process.stdout, process.stderr, False
        except subprocess.TimeoutExpired as error:
            code, stdout, stderr, timed_out = None, error.stdout or b'', error.stderr or b'', True
        (output / (label + '.stdout')).write_bytes(stdout)
        (output / (label + '.stderr')).write_bytes(stderr)
        row = {'argv': argv, 'returncode': code, 'timeout': timed_out, 'cwd': str(cwd)}
        (output / (label + '.json')).write_text(json.dumps(row, indent=2) + '\n')
        result['commands'].append({'label': label, **row})
        need(not timed_out and type(code) is int and code == 0 and stderr == b'', 'clean gate command: ' + label)
        return stdout

    try:
        exact(0, invoke('source-head', ['git', '-C', source, 'rev-parse', 'HEAD']), b'', (SOURCE + '\n').encode())
        admit_source(source, data)
        base.export_inputs(output, {'SOURCE/' + n: base.path(source, n) for n in data['source_assets']} |
                           {'BUILD/profile.json': PROFILE, 'BUILD/gate.py': Path(__file__),
                            'BUILD/parent40-profile.json': old.PROFILE, 'BUILD/parent40-gate.py': OLD_GATE})
        code, metadata = base.prepared_partition(original, output, 'ssdk', data['prepared_files'])
        need(code == data['prepared_files'], 'complete actual41 prepared tree')
        current, prefix = output / 'actual41', output / 'prefix40'
        base.copy_code(original, current, code)
        base.copy_code(original, prefix, code)
        raw = invoke('reverse053', ['patch', '-p1', '-R', '--batch', '--fuzz=0', '-V', 'none'],
                     cwd=prefix, raw=base.path(source, PATCH).read_bytes())
        need(raw in (b'patching file src/init/ssdk_plat.c\n', b"patching file 'src/init/ssdk_plat.c'\n"), 'exact053 reverse diagnostics')
        parent = old.configuration()
        need(base.inventory(prefix) == parent['prepared_files'], 'exact053 reverse to full frozen40')
        if args.admission_only:
            result['status'] = 'PASS_SSDK41_QUALITY35_SOURCE_AND_REVERSE053_ADMISSION_ONLY_NOT_NATIVE_OR_PARENT'
        else:
            frozen = args.accepted40_source_root.absolute()
            need(frozen.resolve() != source.resolve(), 'frozen40 checkout separate from actual41')
            exact(0, invoke('prefix40-head', ['git', '-C', frozen, 'rev-parse', 'HEAD']), b'', (PARENT + '\n').encode())
            base.check(frozen, parent['source_assets'])
            invoke('accepted40-parent', [sys.executable, '-B', OLD_GATE, '--source-root', frozen,
                   '--accepted39-source-root', args.accepted39_source_root.absolute(),
                   '--baseline-source-root', args.baseline_source_root.absolute(),
                   '--legacy-source-root', args.legacy_source_root.absolute(), '--ssdk', prefix,
                   '--dp', args.dp.absolute(), '--cc', args.cc, '--output', output / 'accepted40-parent'])
            receipt = base.load(output / 'accepted40-parent/RESULTS.json')
            need(receipt['status'] == 'PASS_SSDK40_PROBE_AND_IMMUTABLE39_38_HOST_ONLY' and
                 receipt['source_commit'] == PARENT and receipt['runtime_approved'] is False and
                 receipt['actual_code_files'] == parent['prepared_files'] and receipt['actual_recipe_metadata'] == {},
                 'actual immutable40/39/38 parent campaign')
            invoke('platform-native', [sys.executable, '-B', '-O', base.path(source, RUNNER), '--baseline40', prefix,
                   '--prepared', current, '--cc', args.cc, '--sanitize', '--output', output / 'platform-native'])
            result['platform'] = platform_receipts(output / 'platform-native', args.cc, source, current, prefix, data)
            exact(0, invoke('prefix40-head-end', ['git', '-C', frozen, 'rev-parse', 'HEAD']), b'', (PARENT + '\n').encode())
            base.check(frozen, parent['source_assets'])
            result['status'] = STATUS
        admit_source(source, data)
        exact(0, invoke('source-head-end', ['git', '-C', source, 'rev-parse', 'HEAD']), b'', (SOURCE + '\n').encode())
        need(base.partition(original) == (code, metadata) and base.inventory(current) == code and
             base.inventory(prefix) == parent['prepared_files'], 'end full tree stability')
        need(all(sha(p.read_bytes()) == digest for p, digest in owned.items()), 'end immutable gate stability')
    except Exception as error:
        result.update(status='FAIL', error=str(error))
        raise
    finally:
        (output / 'RESULTS.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'quality_revision': QUALITY}))


if __name__ == '__main__':
    main()
