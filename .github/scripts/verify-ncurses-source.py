#!/usr/bin/env python3
"""Check the complete package and actual host-prepared source, never execute it."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT/'.github/ax6-ncurses-contract.json'
MAX_ARCHIVE = 16*1024*1024
STAMP = re.compile(r'\.prepared[0-9a-f]{32}_[0-9a-f]{32}')


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(items):
    data = {}
    for key, value in items:
        need(key not in data, 'duplicate JSON key')
        data[key] = value
    return data


def configuration():
    data = json.loads(PROFILE.read_bytes(), object_pairs_hook=pairs)
    need(type(data['schema']) is int and data['schema'] == 1 and
         data['profile'] == 'NCURSES_COMPLETE_UPSTREAM_PACKAGE_NOT_RUNTIME_ABI' and
         data['package'] == 'package/libs/ncurses', 'fixed ncurses profile')
    need(set(data['files']) == {'Makefile', 'Config.in'} and len(data['removed_patches']) == 6,
         'complete upstream two-file package and six deletions')
    for path, item in data['files'].items():
        safe(path)
        need(set(item) == {'sha256', 'mode'} and re.fullmatch(r'[0-9a-f]{64}', item['sha256']) and
             type(item['mode']) is int and item['mode'] == 0o644, 'fixed official package file')
    archive = data['archive']
    need(archive['root'] == 'ncurses-6.6.20260801' and
         archive['name'] == archive['root']+'.tar.zst' and
         archive['url'] == 'https://sources.openwrt.org/'+archive['name'] and
         archive['sha256'] == 'a64061953353818a511e2ec7a284e10e89ac5ec62f3cdccc1ab549eb5f2d9c84' and
         [archive[k] for k in ('regular_files', 'directories', 'tar_bytes')] == [1253, 47, 19691520] and
         all(type(archive[k]) is int for k in ('regular_files', 'directories', 'tar_bytes')), 'fixed ncurses mirror')
    return data


def safe(name):
    path = PurePosixPath(name)
    need(bool(name) and str(path) == name and not path.is_absolute() and '..' not in path.parts and
         not any(ord(c) < 32 or ord(c) == 127 for c in name) and '\\' not in name and ':' not in name,
         'unsafe source path')
    return path


def regular_inventory(root, allow_stamp=False):
    need(root.is_dir() and not root.is_symlink(), 'regular source directory required')
    files, stamps = {}, []
    for path in root.rglob('*'):
        mode = path.lstat().st_mode
        need(not stat.S_ISLNK(mode), 'source symlink rejected')
        if stat.S_ISDIR(mode):
            continue
        need(stat.S_ISREG(mode), 'source special file rejected')
        relative = path.relative_to(root).as_posix()
        safe(relative)
        if allow_stamp and STAMP.fullmatch(relative):
            need(path.stat().st_size == 0, 'nonempty prepared stamp')
            stamps.append(relative)
            continue
        files[relative] = {'sha256': sha(path.read_bytes()), 'mode': stat.S_IMODE(mode)}
    need(not allow_stamp or len(stamps) == 1, 'one actual host-prepared stamp required')
    return files, stamps


def verify_package(source, profile):
    path = source
    for part in safe(profile['package']).parts:
        path = path/part
        need(path.is_dir() and not path.is_symlink(), 'package ancestor must not be a link')
    files, _ = regular_inventory(path)
    need(set(files) == set(profile['files']), 'complete package inventory differs: '+
         ', '.join(sorted(set(files)^set(profile['files']))))
    need(files == profile['files'], 'official package bytes or modes differ')
    return files


def tar_inventory(raw, profile):
    need(len(raw) == profile['tar_bytes'], 'fixed mirror tar size')
    files, payload, names, directories = {}, {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        for member in archive.getmembers():
            path = safe(member.name.rstrip('/'))
            need(path.parts[0] == profile['root'], 'foreign source root')
            key = unicodedata.normalize('NFC', str(path)).casefold()
            need(key not in names, 'duplicate/colliding tar member')
            names.add(key)
            need(len(names) <= 10000 and member.mode in (0o644, 0o755), 'tar inventory/mode bound')
            if member.isdir():
                directories += 1
                continue
            need(member.isfile() and len(path.parts) > 1 and 0 <= member.size <= 16*1024*1024,
                 'source tar link/special/size rejected')
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            stream = archive.extractfile(member)
            need(stream is not None, 'source payload missing')
            data = stream.read()
            need(len(data) == member.size, 'truncated source payload')
            files[relative] = {'sha256': sha(data), 'mode': member.mode}
            payload[relative] = data
    need(len(files) == profile['regular_files'] and directories == profile['directories'], 'complete mirror inventory')
    for name in files:
        need(not any(str(parent) in files for parent in PurePosixPath(name).parents if str(parent) != '.'),
             'source file cannot be an ancestor')
    return files, payload


def mirror(archive, profile, zstd):
    need(archive.is_file() and not archive.is_symlink() and 0 < archive.stat().st_size <= MAX_ARCHIVE,
         'regular bounded source archive required')
    need(sha(archive.read_bytes()) == profile['sha256'], 'fixed source archive SHA256 differs')
    process = subprocess.run([zstd, '-dc', str(archive)], capture_output=True, timeout=60)
    need(process.returncode == 0 and not process.stderr, 'source archive decompression failed')
    return tar_inventory(process.stdout, profile)


def verify_prepared(prepared, expected):
    actual, stamps = regular_inventory(prepared, allow_stamp=True)
    need(actual == expected, 'actual host-prepared source differs from fixed mirror')
    return actual, stamps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--zstd', default='zstd')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    need(not args.prepared or args.archive, 'prepared check needs the fixed source archive')
    args.output.mkdir(parents=True, exist_ok=False)
    profile = configuration()
    result = {'status': 'INCOMPLETE', 'runtime_approved': False,
              'profile_sha256': sha(PROFILE.read_bytes()), 'gate_sha256': sha(Path(__file__).read_bytes())}
    try:
        result['package'] = verify_package(args.source_root, profile)
        inputs = args.output/'INPUTS'; inputs.mkdir()
        for name in profile['files']:
            (inputs/name).write_bytes((args.source_root/profile['package']/name).read_bytes())
        (inputs/'profile.json').write_bytes(PROFILE.read_bytes())
        (inputs/'gate.py').write_bytes(Path(__file__).read_bytes())
        result['status'] = 'PASS_NCURSES_COMPLETE_PACKAGE_ONLY'
        if args.archive:
            expected, _ = mirror(args.archive, profile['archive'], args.zstd)
            (args.output/'MIRROR-SOURCE.json').write_text(json.dumps(expected, indent=2)+'\n')
            result.update(status='PASS_NCURSES_PACKAGE_AND_MIRROR_NOT_HOST_BUILD',
                          archive_sha256=profile['archive']['sha256'], source_files=len(expected))
        if args.prepared:
            actual, stamps = verify_prepared(args.prepared, expected)
            (args.output/'HOST-PREPARED.json').write_text(json.dumps({'files': actual, 'stamps': stamps}, indent=2)+'\n')
            retained = args.output/'prepared'; retained.mkdir()
            for name in actual:
                dest = retained/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((args.prepared/name).read_bytes()); dest.chmod(0o600)
            result['status'] = 'PASS_NCURSES_ACTUAL_HOST_PREPARED_SOURCE_NOT_COMPILE_OR_RUNTIME'
        need(verify_package(args.source_root, profile) == result['package'], 'package changed while checking')
    except Exception as error:
        result['status'] = 'FAIL'
        result['error'] = str(error)
        raise
    finally:
        (args.output/'RESULTS.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
