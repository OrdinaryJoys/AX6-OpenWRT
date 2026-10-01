#!/usr/bin/env python3
"""Read-only AX6 artifact checks. Never extract a rootfs or execute its files.

FIT support is deliberately limited to this build's inline-data FDT v17 format.
Checksums establish integrity/consistency, not signatures, ownership or bootability.
Factory UBI is counted and size-bounded, not decoded by this checker.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import tarfile
import zlib


class Invalid(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Invalid(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fields(text):
    """RFC822-like package records; continuation lines do not create fields."""
    result = []
    for block in re.split(r'\n\n+', text.strip('\n')):
        if not block:
            continue
        record = {}
        last = None
        for line in block.splitlines():
            if line[:1].isspace():
                require(last is not None, 'orphan package continuation')
                record[last] += '\n' + line
                continue
            key, separator, value = line.partition(':')
            require(separator and key and key not in record, 'malformed/duplicate package field')
            record[key] = value.strip()
            last = key
        result.append(record)
    return result


def member_name(name):
    while name.startswith('./'):
        name = name[2:]
    if name in ('', '.'):
        return ''
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and '\\' not in name,
            'unsafe archive member: ' + name)
    return str(path)


def tar_members(data):
    result = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        for member in archive.getmembers():
            name = member_name(member.name)
            if not name:
                require(member.isdir(), 'archive root is not a directory')
                continue
            require(name not in result, 'duplicate archive member: ' + name)
            require(0 <= member.size <= 256 * 1024 * 1024, 'archive member too large')
            require(member.isfile() or member.isdir() or member.issym() or member.islnk(),
                    'unsupported archive member type: ' + name)
            payload = archive.extractfile(member).read() if member.isfile() else None
            result[name] = (member, payload)
    # Absolute symlinks such as /bin/busybox are legitimate *inside* the image.
    # Reject relative paths escaping that virtual root and links with descendants;
    # we never extract any link to the host filesystem.
    for name, (member, _) in result.items():
        if not (member.issym() or member.islnk()):
            continue
        target = member.linkname
        require(target and '\\' not in target, 'invalid archive link target')
        require(not member.islnk() or not target.startswith('/'), 'absolute archive hardlink target')
        parts = [] if target.startswith('/') or member.islnk() else list(PurePosixPath(name).parent.parts)
        for part in PurePosixPath(target).parts:
            if part in ('/', '.'):
                continue
            if part == '..':
                require(parts, 'archive link escapes image root: ' + name)
                parts.pop()
            else:
                parts.append(part)
        resolved = '/'.join(parts)
        require(not any(other.startswith(name + '/') for other in result), 'archive link is ancestor of payload: ' + name)
        if member.islnk():
            require(resolved in result and result[resolved][0].isfile(), 'hardlink target is not a regular archive member')
    return result


def ipk_members(data):
    if data.startswith(b'!<arch>\n'):
        result = {}
        position = 8
        while position < len(data):
            require(position + 60 <= len(data), 'truncated ar header')
            header = data[position:position + 60]
            require(header[58:60] == b'`\n', 'invalid ar header')
            name = header[:16].decode('ascii').strip().removesuffix('/')
            require(name in ('debian-binary', 'control.tar.gz', 'data.tar.gz') and name not in result,
                    'unexpected/duplicate ar member')
            size_text = header[48:58].decode('ascii').strip()
            require(size_text.isdigit(), 'invalid ar size')
            size = int(size_text)
            position += 60
            require(position + size <= len(data), 'truncated ar payload')
            result[name] = data[position:position + size]
            position += size
            if size % 2:
                require(data[position:position + 1] == b'\n', 'invalid ar padding')
                position += 1
        return result
    require(data.startswith(b'\x1f\x8b'), 'IPK is neither gzip-tar nor supported ar')
    # Explicit decompression checks gzip CRC/truncation, even after the tar EOF.
    members = tar_members(gzip.decompress(data))
    require(all(item[0].isfile() for item in members.values()), 'IPK envelope members must be regular')
    return {name: item[1] for name, item in members.items()}


def read_ipk(data):
    outer = ipk_members(data)
    require(set(outer) == {'debian-binary', 'control.tar.gz', 'data.tar.gz'}, 'IPK envelope members differ')
    require(outer['debian-binary'] == b'2.0\n', 'invalid debian-binary marker')
    control = tar_members(gzip.decompress(outer['control.tar.gz']))
    require('control' in control and control['control'][0].isfile(), 'IPK regular control missing')
    records = fields(control['control'][1].decode('utf-8'))
    require(len(records) == 1, 'IPK must have one control record')
    payload = tar_members(gzip.decompress(outer['data.tar.gz']))
    return records[0], payload


def verify_packages(directory):
    directory = Path(directory)
    index_path = directory / 'Packages'
    require(index_path.is_file() and not index_path.is_symlink(), 'regular Packages index missing')
    index = index_path.read_bytes()
    compressed = directory / 'Packages.gz'
    if compressed.exists() or compressed.is_symlink():
        require(compressed.is_file() and not compressed.is_symlink(), 'Packages.gz must be a regular file')
        require(gzip.decompress(compressed.read_bytes()) == index,
                'Packages.gz differs from Packages')
    records = fields(index.decode('utf-8'))
    require(records, 'empty package index')
    packages = {}
    filenames = set()
    for record in records:
        for field in ('Package', 'Version', 'Architecture', 'Filename', 'Size', 'SHA256sum'):
            require(bool(record.get(field)), 'missing package field: ' + field)
        name, filename = record['Package'], record['Filename']
        require(name not in packages, 'duplicate package identity: ' + name)
        require(filename not in filenames, 'duplicate package filename: ' + filename)
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.~%-]*\.ipk', filename) is not None,
                'unsafe/non-IPK filename: ' + filename)
        require(re.fullmatch(r'[0-9a-f]{64}', record['SHA256sum']) is not None, 'invalid indexed SHA256')
        require(re.fullmatch(r'[1-9][0-9]*', record['Size']) is not None, 'invalid indexed Size')
        path = directory / filename
        require(path.is_file() and not path.is_symlink(), 'indexed regular IPK missing: ' + filename)
        data = path.read_bytes()
        require(len(data) == int(record['Size']), 'indexed Size mismatch: ' + filename)
        require(sha(data) == record['SHA256sum'], 'indexed SHA256 mismatch: ' + filename)
        control, payload = read_ipk(data)
        for field in ('Package', 'Version', 'Architecture'):
            require(control.get(field) == record[field], 'IPK/index ' + field + ' mismatch: ' + filename)
        for field in ('Depends', 'Pre-Depends', 'Provides', 'Conflicts', 'Replaces'):
            normalize = lambda value: ' '.join(value.split())
            require(normalize(control.get(field, '')) == normalize(record.get(field, '')),
                    'IPK/index dependency metadata differs: ' + field + ': ' + filename)
        packages[name] = {'index': record, 'control': control, 'payload': payload}
        filenames.add(filename)
    require(any(name.startswith('kmod-') for name in packages), 'index has no kmod package')
    return packages


def parse_fdt(blob):
    require(len(blob) >= 40, 'truncated FDT header')
    magic, total, offset, strings_offset, reserve, version, compatible, _, strings_size, tree_size = struct.unpack_from('>10I', blob)
    require(magic == 0xd00dfeed and version == 17 and compatible <= 17, 'unsupported FDT header')
    require(40 <= total <= len(blob), 'invalid FDT total size')
    require(40 <= reserve < total and 40 <= offset and offset + tree_size <= total and
            40 <= strings_offset and strings_offset + strings_size <= total, 'FDT region out of bounds')
    require(offset + tree_size <= strings_offset or strings_offset + strings_size <= offset,
            'overlapping FDT structure/string regions')
    require(reserve % 8 == 0 and offset % 4 == 0, 'unaligned FDT memory reserve/structure region')
    reserve_end = reserve
    while True:
        require(reserve_end + 16 <= total, 'unterminated FDT memory reserve map')
        address, length = struct.unpack_from('>QQ', blob, reserve_end)
        reserve_end += 16
        if address == 0 and length == 0:
            break
    require((reserve_end <= offset or offset + tree_size <= reserve) and
            (reserve_end <= strings_offset or strings_offset + strings_size <= reserve),
            'FDT memory reserve map overlaps another region')
    strings = blob[strings_offset:strings_offset + strings_size]
    nodes, stack = {}, []
    end = offset + tree_size
    ended = False
    while offset < end:
        require(offset + 4 <= end, 'truncated FDT token')
        token, = struct.unpack_from('>I', blob, offset)
        offset += 4
        if token == 1:
            zero = blob.find(b'\0', offset, end)
            require(zero >= 0, 'unterminated node name')
            name = blob[offset:zero].decode('ascii')
            require('/' not in name and (stack or name == ''), 'invalid FDT node name')
            stack.append(name)
            path = '/' + '/'.join(stack[1:])
            require(path not in nodes, 'duplicate FDT node: ' + path)
            nodes[path] = {}
            offset = (zero + 4) & ~3
        elif token == 2:
            require(stack, 'unbalanced FDT END_NODE')
            stack.pop()
        elif token == 3:
            require(stack and offset + 8 <= end, 'FDT property outside node/truncated')
            length, name_offset = struct.unpack_from('>II', blob, offset)
            offset += 8
            require(offset + length <= end and name_offset < strings_size, 'FDT property out of bounds')
            zero = strings.find(b'\0', name_offset)
            require(zero >= 0, 'unterminated property name')
            name = strings[name_offset:zero].decode('ascii')
            properties = nodes['/' + '/'.join(stack[1:])]
            require(name and name not in properties, 'duplicate/empty FDT property')
            properties[name] = blob[offset:offset + length]
            offset = (offset + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            require(not stack and '/' in nodes, 'unbalanced FDT END')
            ended = True
            break
        else:
            raise Invalid('unknown FDT token: ' + str(token))
    require(ended, 'missing FDT END')
    return nodes


def fdt_string(properties, name):
    value = properties.get(name, b'')
    require(value.endswith(b'\0') and b'\0' not in value[:-1] and len(value) > 1,
            'invalid FDT string: ' + name)
    return value[:-1].decode('ascii')


def verify_fit(blob):
    nodes = parse_fdt(blob)
    images = {path for path in nodes if path.startswith('/images/') and path.count('/') == 2}
    require(images == {'/images/kernel-1', '/images/fdt-1'}, 'unexpected FIT image set')
    hashes = []
    for path in sorted(images):
        properties = nodes[path]
        expected = {'arch': 'arm64', 'type': 'flat_dt', 'compression': 'none'} if path.endswith('fdt-1') else {
            'arch': 'arm64', 'type': 'kernel', 'os': 'linux', 'compression': 'gzip'}
        for key, value in expected.items():
            require(fdt_string(properties, key) == value, 'unexpected AX6 FIT ' + key + ': ' + path)
        if path.endswith('kernel-1'):
            require(properties.get('load') == struct.pack('>I', 0x41000000) and
                    properties.get('entry') == struct.pack('>I', 0x41000000), 'unexpected AX6 kernel load/entry address')
        require('data' in properties and not any(k in properties for k in ('data-offset', 'data-position', 'data-size')),
                'external/ambiguous FIT payload is unsupported')
        data = properties['data']
        require(data, 'empty FIT image')
        if path.endswith('kernel-1'):
            require(bool(gzip.decompress(data)), 'empty gzip kernel payload')
        children = [p for p in nodes if p.startswith(path + '/') and p.count('/') == 3]
        require(children, 'FIT image hash missing')
        algorithms = set()
        for child in children:
            algorithm = fdt_string(nodes[child], 'algo')
            require(algorithm in ('crc32', 'sha1', 'sha256'), 'unsupported FIT hash algorithm')
            digest = struct.pack('>I', zlib.crc32(data) & 0xffffffff) if algorithm == 'crc32' else hashlib.new(algorithm, data).digest()
            require(nodes[child].get('value') == digest, 'FIT hash mismatch: ' + child)
            algorithms.add(algorithm)
            hashes.append({'node': child, 'algorithm': algorithm, 'digest': digest.hex()})
        require(bool(algorithms & {'sha1', 'sha256'}), 'FIT image must not be protected by CRC32 alone')
    require('/configurations' in nodes, 'FIT configurations missing')
    default = fdt_string(nodes['/configurations'], 'default')
    require(default == 'config@ac04', 'unexpected AX6 STOCK FIT configuration name')
    configs = {p for p in nodes if p.startswith('/configurations/')}
    require(configs == {'/configurations/' + default}, 'FIT has additional/unverified configurations')
    config = nodes.get('/configurations/' + default, {})
    require(set(config) <= {'description', 'kernel', 'fdt'}, 'unsupported FIT configuration references/properties')
    require(fdt_string(config, 'kernel') == 'kernel-1' and fdt_string(config, 'fdt') == 'fdt-1',
            'default FIT configuration references unverified image')
    parse_fdt(nodes['/images/fdt-1']['data'])
    return nodes['/images/fdt-1']['data'], {'hashes': hashes, 'default': default,
            'kernel_sha256': sha(nodes['/images/kernel-1']['data']),
            'dtb_sha256': sha(nodes['/images/fdt-1']['data'])}


def sysupgrade_payload(blob):
    members = tar_members(blob)
    prefix = 'sysupgrade-redmi_ax6-stock/'
    required = {prefix + name for name in ('CONTROL', 'kernel', 'root')}
    regular = {name for name, item in members.items() if item[0].isfile()}
    require(regular == required, 'STOCK sysupgrade must contain exactly CONTROL/kernel/root')
    require(set(members) <= required | {prefix.rstrip('/')}, 'unexpected sysupgrade member')
    if prefix.rstrip('/') in members:
        require(members[prefix.rstrip('/')][0].isdir(), 'sysupgrade top-level entry is not a directory')
    require(all(members[name][0].isfile() for name in required), 'sysupgrade payload is not regular')
    require(members[prefix + 'CONTROL'][1].decode('ascii').splitlines() == ['BOARD=redmi_ax6-stock'],
            'sysupgrade board identity differs')
    return members[prefix + 'kernel'][1], members[prefix + 'root'][1]


def recovery_paths(directory):
    directory = Path(directory)
    itbs = sorted(directory.glob('*.itb'))
    ubis = sorted(directory.glob('*.ubi'))
    require(len(itbs) == 1 and len(ubis) == 1, 'recovery requires exactly one ITB and one factory UBI')
    require(itbs[0].name.endswith('-redmi_ax6-stock-initramfs-uImage.itb') and
            ubis[0].name.endswith('-redmi_ax6-stock-squashfs-factory.ubi'), 'recovery filename is not AX6 STOCK')
    require(all(p.is_file() and not p.is_symlink() for p in itbs + ubis), 'recovery paths must be regular files')
    require(0 < ubis[0].stat().st_size <= 0x06340000, 'STOCK factory UBI exceeds size budget or is empty')
    return itbs[0], ubis[0]


CORE_PACKAGES = ('kmod-qca-nss-ecm', 'kmod-qca-nss-drv', 'kmod-qca-nss-dp',
                 'kmod-qca-ssdk', 'kmod-ath11k', 'kmod-ath11k-ahb', 'kmod-mac80211')


def verify_modules(packages, rootcat, root_module_paths=None):
    installed = {}
    for record in fields(rootcat('usr/lib/opkg/status').decode('utf-8')):
        if re.fullmatch(r'install [^ ]+ installed', record.get('Status', '')):
            name = record.get('Package')
            require(name and name not in installed, 'duplicate/missing installed package name')
            installed[name] = record
    require(all(name in installed for name in CORE_PACKAGES), 'required core package missing from rootfs')
    modules, module_paths = [], set()
    installed_kmods = sorted(name for name in installed if name.startswith('kmod-'))
    kernel_version = installed.get('kernel', {}).get('Version', '')
    kernel_release = kernel_version.split('~', 1)[0].replace('_rc', '-rc')
    require(re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-rc[0-9]+)?', kernel_release) is not None,
            'unsupported installed kernel release')
    module_packages = 0
    for name in installed_kmods:
        require(name in packages, 'installed kmod has no indexed IPK: ' + name)
        package = packages[name]
        for field in ('Version', 'Architecture'):
            require(package['control'].get(field) and package['control'].get(field) == installed[name].get(field),
                    'kmod package/rootfs ' + field + ' differs: ' + name)
        dependencies = package['control'].get('Depends', '')
        kernel_clauses = [clause.strip() for clause in dependencies.split(',')
                          if re.search(r'(?<![A-Za-z0-9_.+\-])kernel(?![A-Za-z0-9_.+\-])', clause)]
        require(len(kernel_clauses) == 1, 'kmod must declare exactly one kernel dependency: ' + name)
        kernel_dependency = re.fullmatch(r'kernel\s*\(=\s*([^)\s]+)\)', kernel_clauses[0])
        require(kernel_dependency is not None and kernel_dependency.group(1) == kernel_version,
                'kmod kernel ABI dependency differs: ' + name)
        found = [(path, item[1]) for path, item in package['payload'].items() if item[0].isfile() and path.endswith('.ko')]
        if name in CORE_PACKAGES:
            require(found, 'core IPK has no regular module payload: ' + name)
        if found:
            module_packages += 1
        for path, data in found:
            require(path.startswith('lib/modules/' + kernel_release + '/') and len(data) >= 20 and data[:6] == b'\x7fELF\x02\x01' and
                    struct.unpack_from('<H', data, 18)[0] == 183, 'module is not AArch64 ELF64: ' + path)
            require(path not in module_paths, 'module payload claimed by multiple packages: ' + path)
            require(rootcat(path) == data, 'module IPK/rootfs bytes differ: ' + path)
            module_paths.add(path)
            modules.append({'package': name, 'path': path, 'sha256': sha(data), 'bytes': len(data)})
    if root_module_paths is not None:
        require(module_paths == set(root_module_paths), 'rootfs module path inventory differs from installed IPK payloads')
    return {'installed_kmod_packages': len(installed_kmods), 'module_packages': module_packages,
            'module_count': len(modules), 'modules': modules}


def module_paths_from_listing(listing):
    """Only parse module paths, whose kernel build names cannot contain spaces."""
    paths = set()
    for line in listing.splitlines():
        if 'squashfs-root/lib/modules/' not in line or '.ko' not in line:
            continue
        match = re.search(r' (squashfs-root/lib/modules/[^\s]+\.ko)$', line)
        require(match is not None and line.startswith('-'), 'non-regular or malformed rootfs module entry')
        path = match.group(1).removeprefix('squashfs-root/')
        require(path not in paths, 'duplicate rootfs module listing entry')
        paths.add(path)
    require(paths, 'rootfs module inventory is empty')
    return paths


def verify_images(args):
    # New output directory avoids overwriting prior evidence. No archive paths are extracted.
    output = Path(args.output_dir)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    kernel, rootfs = sysupgrade_payload(Path(args.sysupgrade).read_bytes())
    dtb, stock_fit = verify_fit(kernel)
    require(dtb == Path(args.compiled_dtb).read_bytes(), 'final sysupgrade DTB differs from verified build DTB')
    itb, ubi = recovery_paths(args.recovery_dir)
    recovery_dtb, recovery_fit = verify_fit(itb.read_bytes())
    require(recovery_dtb == dtb, 'recovery DTB differs from sysupgrade DTB')
    root_path = output / 'root.squashfs'
    root_path.write_bytes(rootfs)
    dtb_path = output / 'final-stock.dtb'
    dtb_path.write_bytes(dtb)
    subprocess.run(['sh', args.dtb_check_script, str(dtb_path)], check=True, timeout=30)
    packages = verify_packages(args.packages_dir)

    def rootcat(path):
        return subprocess.check_output([args.unsquashfs, '-cat', str(root_path), path], timeout=60)

    listing = subprocess.check_output([args.unsquashfs, '-ll', str(root_path)], timeout=60).decode('utf-8')
    modules = verify_modules(packages, rootcat, module_paths_from_listing(listing))
    report = {'status': 'PASS_OFFLINE_ARTIFACT_CONSISTENCY_ONLY', 'stock_fit': stock_fit,
              'recovery_fit': recovery_fit, 'packages_checked': len(packages), **modules,
              'sysupgrade_sha256': sha(Path(args.sysupgrade).read_bytes()), 'rootfs_sha256': sha(rootfs),
              'recovery_itb_sha256': sha(itb.read_bytes()), 'factory_ubi_sha256': sha(ubi.read_bytes()),
              'factory_ubi_bytes': ubi.stat().st_size,
              'coverage_limits': ['factory UBI volume payload not decoded', 'no firmware signature authentication',
                                  'no sysupgrade -T, boot, flash, hardware, or performance test',
                                  'initramfs kernel is intentionally not required to equal sysupgrade kernel']}
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    packages = commands.add_parser('packages')
    packages.add_argument('packages_dir')
    images = commands.add_parser('images')
    for option in ('sysupgrade', 'recovery-dir', 'packages-dir', 'compiled-dtb', 'dtb-check-script', 'output-dir'):
        images.add_argument('--' + option, required=True)
    images.add_argument('--unsquashfs', default='unsquashfs')
    args = parser.parse_args()
    try:
        if args.command == 'packages':
            result = {'status': 'PASS_PACKAGE_INDEX_AND_IPK', 'packages_checked': len(verify_packages(args.packages_dir))}
        else:
            result = verify_images(args)
        print(json.dumps(result, indent=2))
    except (Invalid, OSError, ValueError, KeyError, struct.error, tarfile.TarError, zlib.error, EOFError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'FAIL', 'error': str(error)}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
