#!/usr/bin/env python3
"""Inspect the exact workflow block and exercise its ERR trap in isolation."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
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

# Re-execute the exact local selectors and manifest gate in a fresh step shell.
# The collector's shell array must not be assumed to survive an Actions boundary.
image_marker = '# Each Actions run step has its own shell; do not reuse collector arrays.\n'
assert script.count(image_marker) == 1
assert script.count("mapfile -d '' images") == 1
assert script.index("mapfile -d '' images") < script.index('target_dir=$(dirname "${images[0]}")')
assert 'find openwrt/bin/targets -type f' in script
assert 'mapfile -d \'\' images < image-verify/sysupgrade-images.nul' in script
assert 'if [ "${#images[@]}" -ne 1 ]; then' in script
assert 'if [ "${#roots[@]}" -ne 1 ]; then' in script
assert 'target_dir=$(dirname "${roots[0]}")' not in script
assert 'target_dir=$(dirname "$rootfs")' not in script
root_selector = "mapfile -d '' roots" + script.split("mapfile -d '' roots", 1)[1].split('unsquashfs -ll', 1)[0]
manifest_gate = image_marker + script.split(image_marker, 1)[1].split('openclash_version=', 1)[0]
old_manifest_gate = 'target_dir=$(dirname "${images[0]}")' + manifest_gate.split('target_dir=$(dirname "${images[0]}")', 1)[1]
collection_script = textwrap.dedent(collection.split('        run: |\n', 1)[1])
collector_selector = collection_script.split('mkdir -p image-verify', 1)[0]
bash = shlex.split(os.environ.get('AX6_TEST_BASH', 'bash'))
capability = subprocess.run(bash + ['-c', "mapfile -d '' values < /dev/null"],
                            capture_output=True, text=True, timeout=10)
assert capability.returncode == 0, 'These exact workflow selectors require Bash with mapfile -d (Actions Bash or AX6_TEST_BASH).'

rows = []
cases = [
    ('valid', 'true', 0),
    ('silent-test', 'test 1 = 2', 1),
    ('silent-awk', "awk 'BEGIN { exit 7 }'", 7),
    ('pipeline-failure', 'false | true', 1),
    ('child-failure', "bash -c 'exit 13'", 13),
]
for name, command, expected in cases:
    result = subprocess.run(bash + ['-c', prefix + command + '\nprintf completed'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == expected, (name, result.returncode, result.stderr)
    if expected:
        assert '::error::Rootfs validation failed rc=' in result.stderr, (name, result.stderr)
        assert 'line=' in result.stderr and 'command=' in result.stderr
        assert 'completed' not in result.stdout
    else:
        assert result.stdout == 'completed' and result.stderr == ''
    rows.append({'case': name, 'rc': result.returncode, 'matched': True})

scope_rows = []
scope_cases = [
    ('fresh-step-valid', 0, ''),
    ('nul-path-with-space-and-newline', 0, ''),
    ('valid-plus-directory-and-symlink', 0, ''),
    ('removed-local-selector-regression', 1, 'images[0]: unbound variable'),
    ('zero-images', 1, 'Expected exactly one sysupgrade image, found 0'),
    ('two-images', 1, 'Expected exactly one sysupgrade image, found 2'),
    ('directory-image-only', 1, 'Expected exactly one sysupgrade image, found 0'),
    ('symlink-image-only', 1, 'Expected exactly one sysupgrade image, found 0'),
    ('partial-image-scan-fails', 7, 'Rootfs validation failed rc=7'),
    ('zero-retained-roots', 1, 'Expected exactly one retained root filesystem, found 0'),
    ('two-retained-roots', 1, 'Expected exactly one retained root filesystem, found 2'),
    ('zero-manifests', 1, 'Expected exactly one device package manifest, found 0'),
    ('two-manifests', 1, 'Expected exactly one device package manifest, found 2'),
    ('mismatched-manifest', 1, 'device manifest does not match'),
    ('manifest-only-in-rootfs-directory', 1, 'Expected exactly one device package manifest, found 0'),
]
for name, expected, diagnostic in scope_cases:
    with tempfile.TemporaryDirectory(prefix='ax6-rootfs-step-scope-') as tmp:
        fixture = Path(tmp)
        target = fixture / 'openwrt/bin/targets/qualcommax/ipq807x'
        if name == 'nul-path-with-space-and-newline':
            target = target / 'with space\nand newline'
        target.mkdir(parents=True)
        image = target / 'ax6-squashfs-sysupgrade.bin'
        image.write_bytes(b'controlled image-path fixture, not firmware')
        retained = fixture / 'image-verify/extracted'
        retained.mkdir(parents=True)
        retained_root = retained / 'root'
        retained_root.write_bytes(b'controlled retained-path fixture, not SquashFS')
        manifest = target / 'ax6.manifest'
        manifest.write_text('vim-fuller - 9.2.1014-r2\n')
        (fixture / 'image-verify/opkg-status').write_text(
            'Package: vim-fuller\nVersion: 9.2.1014-r2\nStatus: install ok installed\n\n')
        (fixture / '.github').mkdir()
        (fixture / '.github/scripts').symlink_to(root / '.github/scripts', target_is_directory=True)
        environment = os.environ.copy()
        environment.pop('images', None)
        # A completed first shell really defines images, then exits. Only files persist.
        prior = subprocess.run(bash + ['-c', collector_selector + '\ndeclare -p images'],
                               cwd=fixture, env=environment, capture_output=True, text=True, timeout=10)
        assert prior.returncode == 0 and 'declare -a images=' in prior.stdout, (name, prior.stderr)
        extra = ''
        gate = manifest_gate
        if name == 'removed-local-selector-regression':
            gate = old_manifest_gate
        elif name in ('zero-images', 'directory-image-only', 'symlink-image-only'):
            image.unlink()
            if name == 'directory-image-only':
                image.mkdir()
            elif name == 'symlink-image-only':
                image.symlink_to(retained_root)
        elif name == 'two-images':
            (target / 'other-squashfs-sysupgrade.bin').write_bytes(b'second candidate')
        elif name == 'valid-plus-directory-and-symlink':
            (target / 'dir-squashfs-sysupgrade.bin').mkdir()
            (target / 'link-squashfs-sysupgrade.bin').symlink_to(image)
        elif name == 'partial-image-scan-fails':
            extra = ('find() { if [ "$1" = openwrt/bin/targets ]; then '
                     "printf '%s\\0' openwrt/bin/targets/qualcommax/ipq807x/ax6-squashfs-sysupgrade.bin; "
                     'return 7; fi; command find "$@"; }\n')
        elif name == 'zero-retained-roots':
            retained_root.unlink()
        elif name == 'two-retained-roots':
            (retained / 'other').mkdir()
            (retained / 'other/root').write_bytes(b'second retained root')
        elif name in ('zero-manifests', 'manifest-only-in-rootfs-directory'):
            manifest.unlink()
            if name == 'manifest-only-in-rootfs-directory':
                (retained / 'ax6.manifest').write_text('vim-fuller - 9.2.1014-r2\n')
        elif name == 'two-manifests':
            (target / 'other.manifest').write_text('vim-fuller - 9.2.1014-r2\n')
        elif name == 'mismatched-manifest':
            manifest.write_text('vim-fuller - 9.2.1014-r3\n')
        result = subprocess.run(bash + ['-c', prefix + extra + root_selector + gate + '\nprintf completed'],
                                cwd=fixture, env=environment, capture_output=True, text=True, timeout=10)
        assert result.returncode == expected, (name, result.returncode, result.stdout, result.stderr)
        if expected:
            assert diagnostic in result.stdout + result.stderr, (name, result.stdout, result.stderr)
            assert 'completed' not in result.stdout and 'inventory: PASS' not in result.stdout, (name, result.stdout)
        else:
            assert 'Device manifest/rootfs package inventory: PASS' in result.stdout, (name, result.stdout)
            assert result.stdout.endswith('completed') and result.stderr == '', (name, result.stderr)
        scope_rows.append({'case': name, 'prior_step_rc': prior.returncode,
                           'rc': result.returncode, 'matched': True,
                           'expected_diagnostic': diagnostic,
                           'stdout': result.stdout, 'stderr': result.stderr})
print(json.dumps({'scope': 'Exact workflow diagnostic prefix, retained-root selector, fresh-step image selector and real device-manifest gate with controlled host files; no rootfs acceptance, target execution or Actions upload',
                  'trap_cases': rows, 'step_scope_cases': scope_rows}, indent=2))
