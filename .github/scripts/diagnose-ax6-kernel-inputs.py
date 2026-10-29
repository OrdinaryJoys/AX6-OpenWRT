#!/usr/bin/env python3
"""Read-only, depth-bounded AX6 input observations, never a kernel selector.

Only metadata is inspected. No kernel is selected, prepared, generated or built.
The original workflow's uniqueness, nonempty-file and compile gates remain
authoritative. A successful exit means only that this JSON report was written.
Root/output directory ancestors must be real directories, not symlinks. Output
must be outside root, with an existing parent; existing outputs are never reused.
"""

import argparse
import fnmatch
import json
import os
from pathlib import Path
import stat
import sys


PATTERN = '*/linux-*/include/linux/list.h'
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
STATUS = 'DIAGNOSTIC_ONLY_NOT_SELECTOR_SUCCESS'


class UnsafeDirectory(ValueError):
    def __init__(self, path, kind):
        self.path = Path(path)
        self.kind = kind
        super().__init__('refusing {} directory component: {!r}'.format(kind, str(path)))


def absolute_path(path):
    path = Path(path)
    if '..' in path.parts:
        raise ValueError('parent traversal (..) is not supported')
    return Path(os.path.abspath(path))


def open_child_directory(parent_fd, name, path):
    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(metadata.st_mode):
        raise UnsafeDirectory(path, 'symlink')
    if not stat.S_ISDIR(metadata.st_mode):
        raise UnsafeDirectory(path, 'not_directory')
    # Directory descriptors anchor every lookup; O_NOFOLLOW also covers a
    # component replaced by a symlink between the stat and the open.
    return os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)


def open_absolute_directory(path):
    fd = os.open(path.anchor, DIRECTORY_FLAGS)
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current = current / part
            child_fd = open_child_directory(fd, part, current)
            os.close(fd)
            fd = child_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def metadata_state(metadata):
    mode = metadata.st_mode
    regular = stat.S_ISREG(mode)
    if regular:
        state = 'nonempty' if metadata.st_size else 'empty'
    elif stat.S_ISDIR(mode):
        state = 'directory'
    elif stat.S_ISLNK(mode):
        state = 'symlink'
    else:
        state = 'other'
    return {'exists': True, 'state': state, 'regular_file': regular,
            'nonempty': bool(metadata.st_size) if regular else None,
            'size_bytes': metadata.st_size if regular else None}


def unavailable_state(state, exists, **details):
    return dict(exists=exists, state=state, regular_file=False,
                nonempty=None, size_bytes=None, **details)


def error_record(path, operation, error):
    return {'path': str(path), 'operation': operation,
            'errno': getattr(error, 'errno', None), 'error': str(error)}


def inspect_file(root_fd, relative, errors):
    fd = os.dup(root_fd)
    current = Path()
    try:
        for part in relative.parts[:-1]:
            current = current / part
            child_fd = open_child_directory(fd, part, current)
            os.close(fd)
            fd = child_fd
        result = metadata_state(os.stat(relative.name, dir_fd=fd, follow_symlinks=False))
    except FileNotFoundError:
        result = unavailable_state('missing', False)
    except UnsafeDirectory as error:
        result = unavailable_state('blocked_' + error.kind, None,
                                   blocked_at=str(error.path))
    except OSError as error:
        errors.append(error_record(relative, 'inspect_file', error))
        result = unavailable_state('error', None)
    finally:
        os.close(fd)
    return dict(path=str(relative), **result)


def provenance_flags(path):
    flags = []
    if any(part == '.pc' or part.startswith(('.patch', '.quilt')) or part == 'quilt'
           for part in path.parts):
        flags.append('patch_or_quilt_path_not_a_replacement')
    if any(part.startswith('toolchain') for part in path.parts):
        flags.append('toolchain_path_not_a_replacement')
    return flags


def diagnose(root):
    find_root = os.fspath(root)
    root = absolute_path(root)
    errors = []
    report = {
        'schema_version': 1,
        'status': STATUS,
        'selector_evaluated': False,
        'workflow_assertions_authoritative': True,
        'limits': [
            'Exit 0 means report written, not selector success or kernel readiness.',
            'No fallback, preparation, generation, compilation or input writes.',
            'Patch/quilt copies and toolchain trees cannot replace workflow inputs.',
            'Metadata only, not content validation or an atomic filesystem snapshot.',
        ],
        'scan': {'root_argument': find_root, 'mindepth': 4, 'maxdepth': 4, 'path_pattern': PATTERN,
                 'type': 'regular_file', 'follow_symlinks': False, 'complete': False},
        'root': {'path': str(root), 'direct_subdirectories': []},
        'candidates': [],
        'skipped_symlinks': [],
        'errors': errors,
    }
    try:
        root_fd = open_absolute_directory(root)
    except FileNotFoundError:
        report['root'].update(unavailable_state('missing', False))
    except UnsafeDirectory as error:
        report['root'].update(unavailable_state(
            'blocked_' + error.kind, True if error.path == root else None,
            blocked_at=str(error.path)))
    except OSError as error:
        report['root'].update(unavailable_state('error', None))
        errors.append(error_record(root, 'open_root', error))
    else:
        def walk(fd, relative, depth):
            try:
                with os.scandir(fd) as entries:
                    names = sorted(entry.name for entry in entries)
            except OSError as error:
                errors.append(error_record(relative, 'list_directory', error))
                return
            for name in names:
                child = relative / name
                try:
                    metadata = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISLNK(metadata.st_mode):
                        report['skipped_symlinks'].append(str(child))
                    elif stat.S_ISDIR(metadata.st_mode):
                        if depth == 0:
                            report['root']['direct_subdirectories'].append(name)
                        if depth + 1 < 4:
                            child_fd = open_child_directory(fd, name, child)
                            try:
                                walk(child_fd, child, depth + 1)
                            finally:
                                os.close(child_fd)
                    elif (depth + 1 == 4 and stat.S_ISREG(metadata.st_mode)
                          and fnmatch.fnmatchcase(os.path.join(find_root, str(child)), PATTERN)):
                        kernel = child.parents[2]
                        report['candidates'].append({
                            'path': str(child),
                            'kernel_directory': str(kernel),
                            'provenance_flags': provenance_flags(root / child),
                            'header': dict(path=str(child), **metadata_state(metadata)),
                            'module_main_c': inspect_file(
                                root_fd, kernel / 'kernel/module/main.c', errors),
                            'module_h': inspect_file(
                                root_fd, kernel / 'include/linux/module.h', errors),
                        })
                except (OSError, UnsafeDirectory) as error:
                    errors.append(error_record(child, 'scan_entry', error))

        try:
            report['root'].update(metadata_state(os.fstat(root_fd)))
            walk(root_fd, Path(), 0)
            report['scan']['complete'] = not errors
        finally:
            os.close(root_fd)
    report['candidates'].sort(key=lambda row: row['path'])
    report['skipped_symlinks'].sort()
    count = len(report['candidates'])
    report['candidate_count'] = count
    report['candidate_cardinality'] = 'zero' if count == 0 else 'one' if count == 1 else 'multiple'
    return report


def write_report(root, output, report):
    root, output = absolute_path(root), absolute_path(output)
    if output == root or root in output.parents:
        raise ValueError('output must be outside root; inputs are read-only')
    payload = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + '\n'
    parent_fd = open_absolute_directory(output.parent)
    try:
        fd = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent_fd)
        identity = os.fstat(fd)
        try:
            try:
                stream = os.fdopen(fd, 'w', encoding='utf-8')
            except BaseException:
                os.close(fd)
                raise
            with stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            # Remove only our own failed output, never a pre-existing artifact.
            current = os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                os.unlink(output.name, dir_fd=parent_fd)
            raise
    finally:
        os.close(parent_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = diagnose(args.root)
        write_report(args.root, args.output, report)
    except (OSError, ValueError) as error:
        print(json.dumps({'status': 'DIAGNOSTIC_REPORT_WRITE_FAILED',
                          'selector_evaluated': False, 'error': str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
