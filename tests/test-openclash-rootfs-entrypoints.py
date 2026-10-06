#!/usr/bin/env python3
"""Exercise the listing gate and CLI; no target files or router operations."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / '.github/scripts/verify-openclash-rootfs-entrypoints.py'
spec = importlib.util.spec_from_file_location('entrypoints', CHECKER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BASE = '\n'.join([
    '-rwxr-xr-x root/root 100 2026-09-30 15:40 squashfs-root/usr/bin/ucode',
    'lrwxrwxrwx root/root 17 2026-09-30 15:40 squashfs-root/usr/bin/flock -> ../../bin/busybox',
    '-rwxr-xr-x root/root 1000 2026-09-30 15:40 squashfs-root/bin/busybox',
]) + '\n'
rows = []


def case(name, text, should_pass, error_path=None):
    try:
        report = module.check_listing(text)
        assert should_pass and report['result'] == 'PASS', (name, report)
        rows.append({'name': name, 'observed': 'PASS'})
    except ValueError as error:
        assert not should_pass and error_path in str(error), (name, error)
        rows.append({'name': name, 'observed': 'FAIL', 'error': str(error)})


case('valid', BASE, True)
case('unrelated-link-target-is-not-duplicate', BASE +
     'lrwxrwxrwx root/root 30 2026-09-30 15:40 squashfs-root/usr/bin/other -> squashfs-root/bin/busybox\n', True)
for path in module.EXPECTED:
    original = next(line for line in BASE.splitlines() if line.split()[5] == module.PREFIX + path)
    case('missing-' + path, BASE.replace(original + '\n', ''), False, path)
    case('duplicate-' + path, BASE + original + '\n', False, path)
    for name, mode in [('non-executable', '-rw-r--r--'), ('directory', 'drwxr-xr-x')]:
        case(name + '-' + path, BASE.replace(original, original.replace(original.split()[0], mode, 1)), False, path)
    case('extra-token-' + path, BASE.replace(original, original + ' extra'), False, path)
    case('non-numeric-size-' + path, BASE.replace(original, original.replace('root/root ' + original.split()[2], 'root/root invalid', 1)), False, path)
for target in ('/bin/busybox', '../../../bin/busybox', '../../bin/missing', '../bin/busybox', '../../bin/busybox/child'):
    case('wrong-link-' + target, BASE.replace('../../bin/busybox', target), False, 'usr/bin/flock')
for path in ('usr/bin/ucode', 'bin/busybox'):
    original = next(line for line in BASE.splitlines() if line.split()[5] == module.PREFIX + path)
    link = original.replace('-rwxr-xr-x', 'lrwxrwxrwx') + ' -> ../../bin/busybox'
    case('regular-replaced-with-link-' + path, BASE.replace(original, link), False, path)
case('flock-regular', BASE.replace('lrwxrwxrwx', '-rwxr-xr-x').replace(' -> ../../bin/busybox', ''), False, 'usr/bin/flock')
case('malformed-duplicate', BASE + 'garbage squashfs-root/usr/bin/flock\n', False, 'usr/bin/flock')
with tempfile.TemporaryDirectory(prefix='ax6-entrypoint-test-') as temporary:
    directory = Path(temporary)
    for name, text, rc in [('good', BASE, 0), ('bad', BASE.replace('../../bin/busybox', 'wrong'), 1)]:
        fixture = directory / name
        fixture.write_text(text)
        result = subprocess.run([sys.executable, str(CHECKER), str(fixture)], capture_output=True, timeout=10)
        assert result.returncode == rc
        assert json.loads(result.stdout)['result'] == ('PASS' if rc == 0 else 'FAIL')
        rows.append({'name': 'cli-' + name, 'rc': rc})
    for name, args in [('missing', [str(directory / 'missing')]), ('no-argument', []), ('directory', [str(directory)])]:
        result = subprocess.run([sys.executable, str(CHECKER)] + args, capture_output=True, timeout=10)
        assert result.returncode == 1 and json.loads(result.stdout)['result'] == 'FAIL'
        rows.append({'name': 'cli-' + name, 'rc': 1})
print(json.dumps({'scope': 'Synthetic unsquashfs listing mutations and CLI errors; not actual target binaries or image approval',
                  'case_count': len(rows), 'cases': rows}, indent=2))
