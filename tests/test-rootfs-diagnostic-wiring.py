#!/usr/bin/env python3
"""Inspect the exact workflow block and exercise its ERR trap in isolation."""
import json
from pathlib import Path
import subprocess
import textwrap

root = Path(__file__).resolve().parents[1]
workflow = (root / '.github/workflows/build-AX6-NSS.yml').read_text()
marker = '      - name: Validate final rootfs contents\n'
assert workflow.count(marker) == 1
block = workflow.split(marker, 1)[1].split('\n      - name:', 1)[0]
script = textwrap.dedent(block.split('        run: |\n', 1)[1])
prefix = script.split("mapfile -d '' roots", 1)[0]
assert 'set -Eeuo pipefail' in prefix
assert 'trap ' in prefix and ' ERR\n' in prefix
assert 'set -x' not in prefix
assert 'verify-openclash-rootfs-entrypoints.py' in script
assert 'image-verify/rootfs-files.txt > image-verify/openclash-entrypoints.json' in script
assert 'for path in usr/bin/ucode usr/bin/flock' not in script
assert "Package: ucode-mod-fs" in script
marker = '      - name: Preserve rootfs diagnostic evidence even after validation failure\n'
assert workflow.count(marker) == 1
upload = workflow.split(marker, 1)[1].split('\n      - name:', 1)[0]
assert workflow.index(marker) > workflow.index('      - name: Validate final rootfs contents\n')
assert workflow.index(marker) < workflow.index('      - name: Bind final STOCK FIT')
assert 'if: always()' in upload and 'path: image-verify/' in upload
assert 'ROOTFS_EVIDENCE_${{ github.sha }}' in upload
collect = 'python3 .github/scripts/collect-vim-package-evidence.py'
verify = 'python3 .github/scripts/verify-vim-rootfs.py'
collection_marker = '      - name: Preserve original Vim inputs before DTB and rootfs gates\n'
assert workflow.count(collection_marker) == 1
collection = workflow.split(collection_marker, 1)[1].split('\n      - name:', 1)[0]
assert collection.count(collect) == 1 and script.count(verify) == 1
assert collect not in script
assert "if: ${{ !cancelled() && steps.compile_firmware.outcome == 'success' }}" in collection
assert 'id: compile_firmware' in workflow
assert workflow.index(collection_marker) < workflow.index('      - name: Validate compiled AX6 stock device trees\n')
assert workflow.index(collection_marker) < workflow.index('      - name: Validate final rootfs contents\n')
assert 'unsquashfs -ll' not in collection
assert '--output vim-package-evidence' in collection
assert 'test "${#roots[@]}" -eq 1' in collection
assert '--packages-root vim-package-evidence/offline-packages' in script
assert 'cp image-verify/vim-rootfs.json vim-package-evidence/ROOTFS-CONSISTENCY.json' in script
vim_upload_marker = '      - name: Preserve actual Vim package payloads for independent revalidation\n'
vim_upload = workflow.split(vim_upload_marker, 1)[1].split('\n      - name:', 1)[0]
assert 'if: always()' in vim_upload and 'path: vim-package-evidence/' in vim_upload
kernel_marker = '      - name: Preserve generated kernel and compiled stock DTB before rootfs gates\n'
assert workflow.count(kernel_marker) == 1
kernel = workflow.split(kernel_marker, 1)[1].split('\n      - name:', 1)[0]
assert "if: success() && env.VARIANT_TAG == 'STOCK'" in kernel
assert '--output-dir build-evidence/kernel-evidence' in kernel
assert 'build-evidence/COMPILED-AX6-STOCK.dtb' in kernel
assert workflow.index('      - name: Compile firmware\n') < workflow.index(kernel_marker)
assert workflow.index(kernel_marker) < workflow.index('      - name: Preserve compile attempts even after failure\n')
assert workflow.index(kernel_marker) < workflow.index('      - name: Validate final rootfs contents\n')

rows = []
cases = [
    ('valid', 'true', 0),
    ('silent-test', 'test 1 = 2', 1),
    ('silent-awk', "awk 'BEGIN { exit 7 }'", 7),
    ('pipeline-failure', 'false | true', 1),
    ('child-failure', "bash -c 'exit 13'", 13),
]
for name, command, expected in cases:
    result = subprocess.run(['bash', '-c', prefix + command + '\nprintf completed'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == expected, (name, result.returncode, result.stderr)
    if expected:
        assert '::error::Rootfs validation failed rc=' in result.stderr, (name, result.stderr)
        assert 'line=' in result.stderr and 'command=' in result.stderr
        assert 'completed' not in result.stdout
    else:
        assert result.stdout == 'completed' and result.stderr == ''
    rows.append({'case': name, 'rc': result.returncode, 'matched': True})
print(json.dumps({'scope': 'Exact workflow diagnostic prefix with controlled host commands; no rootfs, target execution or Actions upload',
                  'cases': rows}, indent=2))
