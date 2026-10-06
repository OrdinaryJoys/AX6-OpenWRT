#!/usr/bin/env python3
"""Read-only, narrow unsquashfs -ll entrypoint gate; never executes image files."""
import json
from pathlib import Path
import sys

PREFIX = 'squashfs-root/'
EXPECTED = {
    'usr/bin/ucode': ('-rwxr-xr-x', None),
    'usr/bin/flock': ('lrwxrwxrwx', '../../bin/busybox'),
    'bin/busybox': ('-rwxr-xr-x', None),
}


def check_listing(text):
    observed = {PREFIX + path: [] for path in EXPECTED}
    for line_no, line in enumerate(text.splitlines(), 1):
        fields = line.split()
        candidates = set(fields).intersection(observed)
        if not candidates:
            continue
        for wanted in candidates:
            # Unsquashfs -ll: mode owner/group size date time pathname
            # A symlink additionally ends in "-> target"; $NF is its target.
            if len(fields) >= 6 and fields[5] == wanted:
                observed[wanted].append((line_no, fields))
            elif len(fields) == 8 and fields[6] == '->' and fields[7] == wanted:
                # Another link pointing at this name is not this entry.
                continue
            else:
                raise ValueError(f'{wanted}: malformed listing entry at line {line_no}')
    rows = []
    for path, (mode, target) in EXPECTED.items():
        wanted = PREFIX + path
        entries = observed[wanted]
        if len(entries) != 1:
            raise ValueError(f'{path}: expected exactly one entry, found {len(entries)}')
        line_no, fields = entries[0]
        if fields[0] != mode:
            raise ValueError(f'{path}: expected mode/type {mode}, found {fields[0]} (line {line_no})')
        if target is None:
            if len(fields) != 6:
                raise ValueError(f'{path}: expected a regular entry without link/suffix (line {line_no})')
        elif len(fields) != 8 or fields[6] != '->' or fields[7] != target:
            raise ValueError(f'{path}: expected exact link target {target} (line {line_no})')
        if not fields[2].isdecimal():
            raise ValueError(f'{path}: invalid size field (line {line_no})')
        rows.append({'path': path, 'mode': mode, 'target': target, 'line': line_no})
    return {'result': 'PASS', 'entries': rows,
            'boundary': 'Listing identity/type/mode only; no binary execution, applet dispatch, package bytes, or runtime health proof.'}


def main(argv):
    try:
        if len(argv) != 2:
            raise ValueError('usage: verify-openclash-rootfs-entrypoints.py LISTING')
        source = Path(argv[1])
        if source.stat().st_size > 16 * 1024 * 1024:
            raise ValueError(f'{source}: listing exceeds 16 MiB')
        print(json.dumps(check_listing(source.read_text(encoding='utf-8')), indent=2))
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({'result': 'FAIL', 'error': str(error)}, indent=2))
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
