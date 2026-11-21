#!/usr/bin/env python3
"""Require requested and generated tracing config; never claim runtime usability."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


REQUESTED = ('DEBUG_FS', 'KALLSYMS', 'PERF_EVENTS', 'FTRACE', 'FUNCTION_TRACER',
             'DYNAMIC_FTRACE', 'FUNCTION_GRAPH_TRACER', 'KPROBES', 'KPROBE_EVENTS')
GENERATED = REQUESTED + ('STACKTRACE',)


def values(text, symbols):
    wanted = set(symbols)
    found = {}
    for line in text.splitlines():
        match = re.fullmatch(r'CONFIG_(\w+)=(.*)', line)
        disabled = re.fullmatch(r'# CONFIG_(\w+) is not set', line)
        if not match and not disabled:
            continue
        name = (match or disabled)[1]
        if name not in wanted:
            continue
        if name in found:
            raise ValueError('duplicate configuration symbol: ' + name)
        found[name] = match[2] if match else 'n'
    return found


def enabled(found, symbols, domain):
    for name in symbols:
        if found.get(name) != 'y':
            raise ValueError(f'{domain}: {name} must be y, got {found.get(name, "MISSING")}')


def validate(top, kernel=None, options=None):
    # Bare Linux symbols are not accepted as OpenWrt request symbols.
    if values(top, GENERATED):
        raise ValueError('bare diagnostic CONFIG_* in OpenWrt top-level configuration')
    enabled(values(top, ('KERNEL_' + name for name in REQUESTED)),
            tuple('KERNEL_' + name for name in REQUESTED), 'OpenWrt request')
    if options is not None:
        declared = set(re.findall(r'^config\s+(\w+)\s*$', options, re.M))
        missing = sorted({'KERNEL_' + name for name in REQUESTED} - declared)
        if missing:
            raise ValueError('unknown OpenWrt kernel option(s): ' + ','.join(missing))
    if kernel is not None:
        enabled(values(kernel, GENERATED), GENERATED, 'generated Linux config')
    return {'status': 'PASS_CONFIG_ONLY' if kernel is not None else 'PASS_REQUESTED_CONFIG_ONLY',
            'generated_config_checked': kernel is not None,
            'runtime_probe_usable': 'NOT_VERIFIED',
            'limits': ['Config symbols do not prove probe symbols, tracefs mount, positive control or runtime correctness',
                       'Diagnostic configuration is not a performance acceptance baseline']}


def read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('configuration input must be a regular non-symlink file: ' + str(path))
    data = path.read_bytes()
    return data.decode('utf-8'), {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--top-config', type=Path, required=True)
    parser.add_argument('--kernel-config', type=Path)
    parser.add_argument('--kernel-options', type=Path)
    parser.add_argument('--require-generated', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.require_generated and args.kernel_config is None:
        parser.error('--require-generated requires --kernel-config')
    report = {'status': 'FAIL', 'runtime_probe_usable': 'NOT_VERIFIED', 'inputs': []}
    code = 1
    try:
        texts = {}
        for name, path in (('top', args.top_config), ('kernel', args.kernel_config), ('options', args.kernel_options)):
            if path is not None:
                texts[name], record = read(path)
                report['inputs'].append(record)
        report.update(validate(texts['top'], texts.get('kernel'), texts.get('options')))
        code = 0
    except (OSError, UnicodeError, ValueError) as error:
        report['error'] = str(error)
    if args.output:
        if args.output.exists() or args.output.is_symlink():
            print('refusing existing diagnostic evidence output', file=sys.stderr)
            return 1
        with args.output.open('x') as handle:
            handle.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
