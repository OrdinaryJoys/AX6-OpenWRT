#!/usr/bin/env python3
"""Build both rpcd modes; bind only the OFF packages to the final stock rootfs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess

SPEC = importlib.util.spec_from_file_location('artifact_checks', Path(__file__).with_name('verify-ax6-artifacts.py'))
ART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ART)
VIM_SPEC = importlib.util.spec_from_file_location('vim_rootfs_checks', Path(__file__).with_name('verify-vim-rootfs.py'))
VIM = importlib.util.module_from_spec(VIM_SPEC)
VIM_SPEC.loader.exec_module(VIM)
SYMBOL = 'CONFIG_RPCD_CHECKED_UCI_SUPPORT'
MODULES = ('file', 'iwinfo', 'rpcsys', 'ucode')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def checked_mode(config):
    rows = [line for line in config.splitlines() if line.startswith(SYMBOL + '=') or line == '# ' + SYMBOL + ' is not set']
    require(len(rows) <= 1, 'duplicate experimental config')
    require(not rows or rows[0] in (SYMBOL + '=y', SYMBOL + '=n', '# ' + SYMBOL + ' is not set'), 'invalid experimental config')
    return rows == [SYMBOL + '=y']


def configure(config, enabled):
    checked_mode(config)
    rows = [line for line in config.splitlines() if not (line.startswith(SYMBOL + '=') or line == '# ' + SYMBOL + ' is not set')]
    return '\n'.join(rows + [SYMBOL + '=y' if enabled else '# ' + SYMBOL + ' is not set']) + '\n'


def elf(data):
    require(len(data) >= 64 and data[:6] == b'\x7fELF\x02\x01', 'not ELF64 little endian')
    require(struct.unpack_from('<H', data, 18)[0] == 183, 'not AArch64')
    require(struct.unpack_from('<H', data, 16)[0] in (2, 3), 'unexpected ELF type')
    return sha(data)


def prepared(source, provenance):
    for name, digest in provenance['prepared_files'].items():
        path = source / name
        require(path.is_file() and not path.is_symlink() and sha(path.read_bytes()) == digest,
                'prepared rpcd source differs: ' + name)
    return dict(provenance['prepared_files'])


def package_set(config):
    require('CONFIG_PACKAGE_rpcd=y' in config.splitlines(), 'rpcd must be built-in')
    result = {'rpcd': 'sbin/rpcd'}
    for module in MODULES:
        name = 'rpcd-mod-' + module
        enabled = 'CONFIG_PACKAGE_' + name + '=y' in config.splitlines()
        require(enabled or module == 'rpcsys', 'missing built-in rpcd module: ' + name)
        if enabled:
            result[name] = 'usr/lib/rpcd/' + module + '.so'
    return result


def record_packages(root, out, wanted):
    result = {}
    for name, payload_path in wanted.items():
        paths = sorted((root / 'bin').rglob(name + '_*.ipk'))
        require(len(paths) == 1, 'expected unique target IPK for ' + name)
        control, payload = ART.read_ipk(paths[0].read_bytes())
        require(control.get('Package') == name and control.get('Architecture') == 'aarch64_cortex-a53', 'package identity/architecture mismatch')
        require(control.get('Version', '').endswith('-r2'), 'rpcd release must be r2')
        require(payload_path in payload and payload[payload_path][0].isfile(), 'missing regular ELF payload')
        info, data = payload[payload_path]
        require(info.mode & 0o777 == 0o755, 'unexpected ELF mode')
        digest = elf(data)
        shutil.copy2(paths[0], out / paths[0].name)
        result[name] = {'control': control, 'payload_path': payload_path, 'payload_sha256': digest,
                        'payload_mode': info.mode, 'ipk_sha256': sha(paths[0].read_bytes()), 'ipk': paths[0].name}
    return result


def build(root, out):
    root, out = root.resolve(), out.resolve()
    require(not out.exists(), 'use a fresh evidence directory')
    out.mkdir(parents=True)
    config = (root / '.config').read_text()
    require(not checked_mode(config), 'firmware config must start OFF')
    wanted = package_set(config)
    provenance = json.loads((root / 'package/system/rpcd/provenance.json').read_text())
    require(provenance['default_checked_support'] is False, 'provenance default must be OFF')
    shutil.copy2(root / 'package/system/rpcd/provenance.json', out / 'SOURCE-PROVENANCE.json')
    commands = []

    def run(argv, label):
        with (out / (label + '.log')).open('wb') as log:
            result = subprocess.run(argv, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        commands.append({'argv': argv, 'returncode': result.returncode, 'log': label + '.log'})
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        if result.returncode:
            print((out / (label + '.log')).read_text(errors='replace')[-20000:])
        require(result.returncode == 0, 'target build failed: ' + label)

    modes = {}
    try:
        for mode, enabled in [('ON', True), ('OFF', False)]:
            destination = out / mode
            destination.mkdir()
            (root / '.config').write_text(configure(config, enabled))
            run(['make', 'defconfig'], mode + '-defconfig')
            final_config = (root / '.config').read_text()
            require(checked_mode(final_config) == enabled, 'defconfig discarded requested mode')
            require(package_set(final_config) == wanted, 'rpcd module selection changed')
            (destination / 'config').write_text(final_config)
            # PKG_CONFIG_DEPENDS plus explicit clean prevents the ON objects leaking into stock.
            run(['make', 'package/system/rpcd/clean', 'V=s'], mode + '-clean')
            run(['make', '-j2', 'package/system/rpcd/compile', 'V=s'], mode + '-compile')
            caches = sorted((root / 'build_dir').glob('target-*/rpcd-*/CMakeCache.txt'))
            require(len(caches) == 1, 'expected exactly one target rpcd CMake cache')
            cache = caches[0]
            require('CHECKED_UCI_SUPPORT:BOOL=' + mode in cache.read_text().splitlines(), 'CMake mode mismatch')
            shutil.copy2(cache, destination / cache.name)
            prepared(cache.parent, provenance)
            plugins = {}
            for module in MODULES:
                plugin = cache.parent / (module + '.so')
                plugins[module] = elf(plugin.read_bytes())
                shutil.copy2(plugin, destination / plugin.name)
            binary = cache.parent / 'rpcd'
            shutil.copy2(binary, destination / 'rpcd.unstripped')
            records = record_packages(root, destination, wanted)
            modes[mode] = {'binary_sha256': elf(binary.read_bytes()), 'plugins': plugins, 'packages': records,
                           'source_files': provenance['prepared_files'], 'config_sha256': sha(final_config.encode())}
            (out / 'components.json').write_text(json.dumps({'schema': 1, 'modes': modes}, indent=2) + '\n')
        require(modes['ON']['binary_sha256'] != modes['OFF']['binary_sha256'], 'ON and OFF binaries unexpectedly identical')
    finally:
        (root / '.config').write_text(configure(config, False))
        run(['make', 'defconfig'], 'final-OFF-defconfig')
        require(not checked_mode((root / '.config').read_text()), 'final config is not OFF')
    print('RPCD target ON/OFF, four modules, prepared sources and IPK evidence verified')


def rootfs(image, out, config_path):
    require(not checked_mode(config_path.read_text()), 'final firmware experimental API is ON')
    data = json.loads((out / 'components.json').read_text())
    require(set(data['modes']) == {'ON', 'OFF'}, 'both target component modes required')
    report = {}
    wanted = [r['payload_path'] for r in data['modes']['OFF']['packages'].values()]
    entries = VIM.listing_entries(subprocess.check_output(['unsquashfs', '-ll', str(image)]).decode(), wanted)
    status = ART.fields(subprocess.check_output(['unsquashfs', '-cat', str(image), 'usr/lib/opkg/status']).decode())
    for name, record in data['modes']['OFF']['packages'].items():
        installed = [r for r in status if r.get('Package') == name]
        require(len(installed) == 1 and installed[0].get('Status', '').split()[-1:] == ['installed'], 'rootfs package absent/duplicate: ' + name)
        for field in ('Package', 'Version', 'Architecture'):
            require(installed[0].get(field) == record['control'].get(field), 'rootfs control mismatch: ' + name + ':' + field)
        for field in ('Depends', 'Pre-Depends'):
            require(VIM.dependency_atoms(installed[0].get(field, '')) ==
                    VIM.dependency_atoms(record['control'].get(field, '')), 'rootfs dependency mismatch: ' + name)
        entry = entries[record['payload_path']]
        require(entry['type'] == '-' and entry['mode'] == 0o755, 'rootfs ELF is not regular/executable: ' + name)
        content = subprocess.check_output(['unsquashfs', '-cat', str(image), record['payload_path']])
        require(elf(content) == record['payload_sha256'], 'rootfs ELF does not match target OFF IPK: ' + name)
        # Re-read archived packages: a receipt alone is not package evidence.
        package = out / 'OFF' / record['ipk']
        require(sha(package.read_bytes()) == record['ipk_sha256'], 'archived OFF IPK drift')
        control, payload = ART.read_ipk(package.read_bytes())
        info, original = payload[record['payload_path']]
        require(info.isfile() and content == original and control == record['control'], 'rootfs/IPK payload differs')
        report[name] = {'version': installed[0]['Version'], 'sha256': sha(content), 'checked_support': 'OFF'}
    (out / 'ROOTFS-CONSISTENCY.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    compile_parser = sub.add_parser('build')
    compile_parser.add_argument('source', type=Path)
    compile_parser.add_argument('evidence', type=Path)
    verify_parser = sub.add_parser('rootfs')
    verify_parser.add_argument('image', type=Path)
    verify_parser.add_argument('evidence', type=Path)
    verify_parser.add_argument('config', type=Path)
    args = parser.parse_args()
    if args.command == 'build':
        build(args.source, args.evidence)
    else:
        rootfs(args.image, args.evidence, args.config)


if __name__ == '__main__':
    main()
