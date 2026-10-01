#!/usr/bin/env python3
"""Test the actual RPS rootfs permission gate, including prefix decoys."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
workflow = (root / '.github/workflows/build-AX6-NSS.yml').read_text()
start = workflow.index('          require_rps_executable() {')
end = workflow.index('          require_rps_executable etc/init.d/set-irq-affinity', start)
function = '\n'.join(line[10:] for line in workflow[start:end].splitlines())
target = 'etc/init.d/set-irq-affinity'
path = 'squashfs-root/' + target


def listing(mode, name):
    return f'{mode} root/root 42 2026-09-30 17:50 {name}\n'


cases = [
    ('exact executable', listing('-rwxr-xr-x', path), True),
    ('non-executable', listing('-rw-r--r--', path), False),
    ('missing', '', False),
    ('backup-only', listing('-rwxr-xr-x', path + '.bak'), False),
    ('non-executable plus backup', listing('-rw-r--r--', path) + listing('-rwxr-xr-x', path + '.bak'), False),
    ('duplicate', listing('-rwxr-xr-x', path) * 2, False),
    ('symlink', listing('lrwxrwxrwx', path).rstrip() + ' -> /other\n', False),
    ('executable plus unrelated', listing('-rwxr-xr-x', path) + listing('-rwxr-xr-x', path + '.bak'), True),
]
with tempfile.TemporaryDirectory(prefix='ax6-rps-mode-') as directory:
    fixture = Path(directory) / 'image-verify/rootfs-files.txt'
    fixture.parent.mkdir()
    for name, contents, expected in cases:
        fixture.write_text(contents)
        result = subprocess.run(['bash', '-eu', '-c', function + '\nrequire_rps_executable ' + target], cwd=directory, capture_output=True, text=True)
        assert (result.returncode == 0) == expected, (name, result.stdout, result.stderr)
        print('PASS', name)
print('SUMMARY 8 rootfs permission gate cases passed')

# The real procd library is INSTALL_DATA. Reject executable/writable, backup,
# duplicate and symlink records instead of applying the 0755 script contract.
data_path = 'squashfs-root/lib/functions/procd.sh'
data_cases = [
    ('exact data library', listing('-rw-r--r--', data_path), True),
    ('executable library', listing('-rwxr-xr-x', data_path), False),
    ('world-writable library', listing('-rw-rw-rw-', data_path), False),
    ('missing library', '', False),
    ('backup-only library', listing('-rw-r--r--', data_path + '.bak'), False),
    ('duplicate library', listing('-rw-r--r--', data_path) * 2, False),
    ('symlink library', listing('lrwxrwxrwx', data_path).rstrip() + ' -> /other\n', False),
]
with tempfile.TemporaryDirectory(prefix='ax6-procd-mode-') as directory:
    fixture = Path(directory) / 'image-verify/rootfs-files.txt'
    fixture.parent.mkdir()
    for library in ('lib/functions/procd.sh', 'lib/functions.sh'):
        for name, contents, expected in data_cases:
            fixture.write_text(contents.replace(data_path, 'squashfs-root/' + library))
            result = subprocess.run(['bash', '-eu', '-c', function + '\nrequire_rps_datafile ' + library], cwd=directory, capture_output=True, text=True)
            assert (result.returncode == 0) == expected, (library, name, result.stdout, result.stderr)
            print('PASS', library, name)
print('SUMMARY 14 rootfs data-library gate cases passed')
