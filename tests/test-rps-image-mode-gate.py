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
