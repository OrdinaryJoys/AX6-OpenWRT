#!/usr/bin/env python3
"""Acquire original Vim-family build evidence before any acceptance gate.

Never reconstruct an IPK/index, extract an image, or execute target programs.
Collection is not acceptance. Failed collections retain bounded partial evidence.
"""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time

SPEC = importlib.util.spec_from_file_location('ax6_collection_fields',
                                             Path(__file__).with_name('verify-ax6-artifacts.py'))
ART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ART)
MIB = 1024 * 1024
IPK_LIMIT, INDEX_LIMIT, TOTAL_LIMIT = 128 * MIB, 64 * MIB, 512 * MIB
ROOT_LIMIT, STATUS_LIMIT, SMALL_LIMIT = 128 * MIB, 16 * MIB, MIB
SCAN_ENTRIES, SCAN_DIRS, SCAN_DEPTH = 65536, 256, 4
ROOTCAT_SECONDS, ROOTCAT_KILL_SECONDS = 60, 5
PACKAGES = ('vim-fuller', 'vim-runtime')
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def require(ok, message):
    if not ok:
        raise ValueError(message)


def absolute(path):
    path = Path(path)
    require('..' not in path.parts, 'parent traversal is forbidden')
    return path.absolute()


def open_directory(path):
    """No-follow every ancestor using directory descriptors, not resolve()."""
    path = absolute(path)
    fd = os.open('/', DIR_FLAGS)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def open_regular(path, limit):
    path = absolute(path)
    parent = open_directory(path.parent)
    try:
        fd = os.open(path.name, FILE_FLAGS, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode), 'source is not regular: ' + str(path))
        require(0 <= info.st_size <= limit, 'oversized source: ' + str(path))
        return fd, info
    except Exception:
        os.close(fd)
        raise


def unchanged(before, after):
    return (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                    after.st_mtime_ns, after.st_ctime_ns)


def confirm_source(path, before, limit):
    """Detect replacement/unlink as well as changes to the already opened FD."""
    fd, current = open_regular(path, limit)
    try:
        require(unchanged(before, current), 'source changed or replaced: ' + str(path))
    finally:
        os.close(fd)


def rootcat(image_fd, path, executable, limit):
    """Bound both subprocess pipes and wall time; pass an already safe image FD."""
    buffers = {'out': bytearray(), 'err': bytearray()}
    selector = selectors.DefaultSelector()
    proc = None
    try:
        proc = subprocess.Popen([str(executable), '-cat', '/dev/fd/' + str(image_fd), path],
                                pass_fds=(image_fd,), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True,
                                env={**os.environ, 'LC_ALL': 'C'})
        selector.register(proc.stdout, selectors.EVENT_READ, ('out', limit))
        selector.register(proc.stderr, selectors.EVENT_READ, ('err', 64 * 1024))
        deadline = time.monotonic() + ROOTCAT_SECONDS
        while selector.get_map():
            require(time.monotonic() < deadline, 'unsquashfs timed out')
            for key, _ in selector.select(min(0.5, max(0, deadline - time.monotonic()))):
                name, maximum = key.data
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                require(len(buffers[name]) + len(data) <= maximum,
                        'unsquashfs output exceeds bound: ' + path)
                buffers[name].extend(data)
        rc = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        require(rc == 0 and not buffers['err'],
                'unsquashfs failed/diagnosed ' + path + ': ' + bytes(buffers['err']).decode(errors='replace')[:400])
        require(buffers['out'], 'empty image metadata: ' + path)
        return bytes(buffers['out'])
    finally:
        try:
            if proc is not None:
                # A tool may leave descendants holding a pipe after its own exit.
                # Kill only the fresh process session, and bound cleanup as well.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=ROOTCAT_KILL_SECONDS)
                finally:
                    proc.stdout.close()
                    proc.stderr.close()
        finally:
            selector.close()


class Collector:
    def __init__(self, args):
        self.args = args
        self.output = absolute(args.output)
        package_root = absolute(args.packages_root)
        require(not self.output.is_relative_to(package_root), 'output must be outside packages-root')
        parent = open_directory(self.output.parent)
        try:
            os.mkdir(self.output.name, 0o700, dir_fd=parent)
            self.fd = os.open(self.output.name, DIR_FLAGS, dir_fd=parent)
        finally:
            os.close(parent)
        self.files, self.errors, self.inventory = [], [], {}
        self.partial_matches = {}
        self.total = 0
        self.copied = {}
        self.root_identity = None

    def write(self, destination, data, source, category):
        maximum = TOTAL_LIMIT if category == 'collection-manifest' else TOTAL_LIMIT - SMALL_LIMIT
        require(self.total + len(data) <= maximum, 'total evidence byte bound exceeded')
        self.total += len(data)
        parts = Path(destination).parts
        require(parts and all(part not in ('', '.', '..') for part in parts) and
                not Path(destination).is_absolute(), 'unsafe output path')
        parent = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                next_fd = os.open(part, DIR_FLAGS, dir_fd=parent)
                os.close(parent)
                parent = next_fd
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
        finally:
            os.close(parent)
        self.files.append({'file': destination, 'source': str(source), 'category': category,
                           'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})

    def capture(self, path, destination, limit, category):
        path = absolute(path)
        key = str(path)
        if key in self.copied:
            data, before = self.copied[key]
            require(len(data) <= limit, 'cached source exceeds byte bound')
            confirm_source(path, before, limit)
            if not any(row['file'] == destination for row in self.files):
                self.write(destination, data, path, category)
            return data
        fd, before = open_regular(path, limit)
        try:
            data = bytearray()
            while True:
                chunk = os.read(fd, min(MIB, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                require(len(data) <= limit, 'source exceeds bound while read')
            require(len(data) == before.st_size and unchanged(before, os.fstat(fd)),
                    'source changed while read: ' + key)
        finally:
            os.close(fd)
        confirm_source(path, before, limit)
        data = bytes(data)
        self.write(destination, data, path, category)
        self.copied[key] = data, before
        return data

    def attempt(self, label, operation):
        try:
            return operation()
        except Exception as error:
            self.errors.append({'stage': label, 'error': str(error)})
            return None

    def scan(self, names):
        root = absolute(self.args.packages_root)
        matches = {name: [] for name in names}
        self.partial_matches = matches
        entries = directories = 0

        def walk(fd, relative, depth):
            nonlocal entries, directories
            directories += 1
            require(directories <= SCAN_DIRS and depth <= SCAN_DEPTH, 'package directory scan bound exceeded')
            with os.scandir(fd) as iterator:
                for entry in iterator:
                    entries += 1
                    require(entries <= SCAN_ENTRIES, 'package entry scan bound exceeded')
                    require(not entry.is_symlink(), 'symlink in packages-root: ' + str(relative / entry.name))
                    if entry.is_dir(follow_symlinks=False):
                        child = os.open(entry.name, DIR_FLAGS, dir_fd=fd)
                        try:
                            walk(child, relative / entry.name, depth + 1)
                        finally:
                            os.close(child)
                    else:
                        require(entry.is_file(follow_symlinks=False), 'nonregular package directory entry')
                        for name in names:
                            if entry.name.startswith(name + '_') and entry.name.endswith('.ipk'):
                                require(len(matches[name]) < 8, 'too many selected IPK candidates')
                                matches[name].append(relative / entry.name)

        fd = open_directory(root)
        try:
            walk(fd, Path(), 0)
        finally:
            os.close(fd)
            self.inventory = {name: [str(p) for p in sorted(paths)] for name, paths in matches.items()}
        return matches

    def image_metadata(self):
        path = absolute(self.args.rootfs)
        fd, before = open_regular(path, ROOT_LIMIT)
        try:
            require(before.st_size > 0, 'empty rootfs')
            digest = hashlib.sha256()
            consumed = 0
            while chunk := os.read(fd, MIB):
                consumed += len(chunk)
                require(consumed <= ROOT_LIMIT and consumed <= before.st_size, 'rootfs grew beyond bound')
                digest.update(chunk)
            require(consumed == before.st_size and unchanged(before, os.fstat(fd)), 'rootfs changed while hashed')
            confirm_source(path, before, ROOT_LIMIT)
            self.root_identity = {'source': str(path), 'bytes': before.st_size, 'sha256': digest.hexdigest()}
            names, seen, status_error = set(PACKAGES), set(), None
            try:
                raw = rootcat(fd, 'usr/lib/opkg/status', self.args.unsquashfs, STATUS_LIMIT)
                self.write('rootfs-metadata/opkg-status', raw, str(path) + '!/usr/lib/opkg/status', 'image-metadata')
                records = ART.fields(raw.decode('utf-8'))
                for record in records:
                    name = record.get('Package')
                    require(name and name not in seen, 'missing/duplicate image status package')
                    seen.add(name)
                    if name in (*PACKAGES, 'xxd'):
                        state = record.get('Status', '').split()
                        require(len(state) == 3, 'malformed targeted image package state')
                        if name in PACKAGES:
                            require(state[-1] == 'installed', 'required Vim package is not installed')
                        else:
                            require(state[-1] in ('installed', 'not-installed', 'config-files'), 'xxd partial/unknown state')
                            if state[-1] == 'installed':
                                names.add('xxd')
                require(set(PACKAGES) <= seen, 'required Vim status records missing')
            except Exception as error:
                status_error = error
            # Required controls are independently useful diagnostics even when
            # status syntax or state prevents determining xxd applicability.
            for name in sorted(names):
                virtual = 'usr/lib/opkg/info/' + name + '.control'
                def capture_control(name=name, virtual=virtual):
                    data = rootcat(fd, virtual, self.args.unsquashfs, SMALL_LIMIT)
                    self.write('rootfs-metadata/' + name + '.control', data, str(path) + '!/' + virtual, 'image-metadata')
                    parsed = ART.fields(data.decode('utf-8'))
                    require(len(parsed) == 1 and parsed[0].get('Package') == name, 'invalid installed control record')
                self.attempt('image control: ' + name, capture_control)
            require(unchanged(before, os.fstat(fd)), 'rootfs changed during metadata read')
            confirm_source(path, before, ROOT_LIMIT)
            if status_error is not None:
                raise status_error
            return tuple(sorted(names))
        finally:
            os.close(fd)

    def package(self, name, matches):
        # Retain every bounded candidate before uniqueness is checked. Failed
        # collection must preserve the original duplicate evidence as well.
        for relative in sorted(matches):
            self.attempt('original candidate: ' + str(relative), lambda relative=relative: self.candidate(name, relative))
        require(len(matches) == 1, 'expected exactly one original ' + name + ' IPK')

    def candidate(self, name, relative):
        root = absolute(self.args.packages_root)
        def capture_ipk():
            require(self.capture(root / relative, 'offline-packages/' + str(relative), IPK_LIMIT, 'original-ipk'),
                    'empty original IPK')
        self.attempt('IPK acquisition: ' + name, capture_ipk)
        index_relative = relative.parent / 'Packages'
        raw = self.attempt('index acquisition: ' + name, lambda: self.capture(
            root / index_relative, 'offline-packages/' + str(index_relative), INDEX_LIMIT, 'original-full-index'))
        # Preserve originals before interpreting syntax. Never rebuild an index.
        compressed = root / relative.parent / 'Packages.gz'
        parent = open_directory(compressed.parent)
        try:
            try:
                compressed_exists = os.stat(compressed.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                compressed_exists = None
        finally:
            os.close(parent)
        if compressed_exists is not None:
            def capture_compressed():
                packed = self.capture(compressed, 'offline-packages/' + str(relative.parent / 'Packages.gz'), INDEX_LIMIT, 'original-full-index')
                with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
                    unpacked = stream.read(INDEX_LIMIT + 1)
                require(len(unpacked) <= INDEX_LIMIT and raw is not None and unpacked == raw,
                        'Packages.gz differs/exceeds bound or raw index missing')
            self.attempt('compressed index: ' + name, capture_compressed)
        require(raw is not None, 'required original index unavailable')
        records = ART.fields(raw.decode('utf-8'))
        require(records and all(r.get('Package') for r in records), 'malformed original Packages records')
        require(sum(r.get('Package') == name for r in records) == 1, 'selected Packages record missing/duplicated')

    def run(self):
        for label, source in [('PREPARED-SOURCE.json', self.args.prepared_source), ('PROVENANCE.json', self.args.provenance)]:
            def capture_json(source=source, label=label):
                data = self.capture(source, label, SMALL_LIMIT, 'original-preparation-metadata')
                require(isinstance(json.loads(data), dict), 'preparation metadata must be a JSON object')
            self.attempt(label, capture_json)
        names = self.attempt('image metadata', self.image_metadata)
        # If status cannot be trusted, always collect both required packages;
        # optional xxd applicability remains unknown, and collection stays failed.
        names = names or PACKAGES
        matches = self.attempt('bounded package inventory', lambda: self.scan(names))
        matches = matches if matches is not None else self.partial_matches
        for name in names:
            self.attempt('original package: ' + name, lambda name=name: self.package(name, matches.get(name, [])))
        report = {
            'schema_version': 1,
            'status': 'COLLECTION_FAILED_NOT_ACCEPTANCE' if self.errors else 'COLLECTED_DIAGNOSTICS_NOT_ACCEPTANCE',
            'is_acceptance': False, 'gate_status': 'NOT_RUN_BY_COLLECTOR',
            'rootfs': self.root_identity, 'selected_packages': list(names),
            'optional_xxd_applicability': ('UNKNOWN_IMAGE_METADATA_FAILURE' if any(e['stage'] == 'image metadata' for e in self.errors)
                                           else 'INSTALLED_REQUIRED_FOR_COLLECTION' if 'xxd' in names else 'NOT_INSTALLED'),
            'candidate_inventory': self.inventory,
            'candidate_inventory_complete': not any(e['stage'] == 'bounded package inventory' for e in self.errors),
            'files': list(self.files), 'copied_bytes': self.total,
            'limits_bytes': {'ipk': IPK_LIMIT, 'index': INDEX_LIMIT, 'total': TOTAL_LIMIT,
                             'rootfs_read': ROOT_LIMIT, 'status': STATUS_LIMIT, 'small_metadata': SMALL_LIMIT},
            'errors': self.errors,
            'limits': ['Original files only; no IPK/index reconstruction and no target execution',
                       'Collection does not verify dependency equality, payload equality, security patches, ABI or bootability',
                       'Offline indexes intentionally include packages whose IPKs are not included',
                       'All packages-root symlinks/nonregular entries and unsupported layouts fail closed'],
        }
        self.write('MANIFEST.json', (json.dumps(report, indent=2) + '\n').encode(), 'collector report', 'collection-manifest')
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('rootfs', 'packages-root', 'prepared-source', 'provenance', 'output'):
        parser.add_argument('--' + argument, type=Path, required=True)
    parser.add_argument('--unsquashfs', default='unsquashfs')
    args = parser.parse_args(argv)
    collector = None
    try:
        collector = Collector(args)
        report = collector.run()
        print(json.dumps({k: report[k] for k in ('status', 'is_acceptance', 'copied_bytes', 'errors')}, indent=2))
        return 1 if report['errors'] else 0
    except Exception as error:
        print(json.dumps({'status': 'COLLECTION_FAILED_NOT_ACCEPTANCE', 'is_acceptance': False, 'error': str(error)}))
        return 1
    finally:
        if collector is not None:
            os.close(collector.fd)


if __name__ == '__main__':
    raise SystemExit(main())
