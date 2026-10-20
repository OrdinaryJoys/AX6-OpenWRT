#!/usr/bin/env python3
"""Test the actual workflow header selector against ambiguous tools headers."""
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / '.github/workflows/build-AX6-NSS.yml').read_text()
start = workflow.index('          mapfile -d \'\' linux_list_headers')
end = workflow.index('          echo "=== NSS conditional mesh', start)
SELECTOR = '\n'.join(line[10:] for line in workflow[start:end].splitlines())
assert 'test "${#linux_list_headers[@]}" -eq 1' in SELECTOR
assert 'test -s "${linux_list_headers[0]}"' in SELECTOR
FIND = shlex.split(re.search(r'find\s+.*?-print0', SELECTOR, re.S).group().replace('\\\n', ' '))
BASE = Path('build_dir/target-aarch64_cortex-a53_musl/linux-qualcommax_ipq807x')


class Selector(unittest.TestCase):
    def run_case(self, paths, expected, symlink=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / BASE).mkdir(parents=True)
            for path, content in paths:
                target = root / BASE / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            if symlink:
                link = root / BASE / 'linux-6.18.38/include/linux/list.h'
                link.parent.mkdir(parents=True)
                link.symlink_to(root / BASE / 'external-list.h')
            # Execute the actual find argv. macOS ships Bash 3.2 without mapfile;
            # this tests selector/cardinality, not the Ubuntu Bash interpreter.
            p = subprocess.run(FIND, cwd=root, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            found = [root / name.decode() for name in p.stdout.split(b'\0') if name]
            accepted = len(found) == 1 and found[0].stat().st_size > 0
            self.assertEqual(accepted, expected, (p.stdout, p.stderr))

    def test_kernel_header_not_tools_header(self):
        self.run_case([('linux-6.18.38/include/linux/list.h', 'kernel'),
            ('linux-6.18.38/tools/include/linux/list.h', 'tools')], True)

    def test_tools_header_alone_rejected(self):
        self.run_case([('linux-6.18.38/tools/include/linux/list.h', 'tools')], False)

    def test_multiple_kernel_headers_rejected(self):
        self.run_case([('linux-6.18.38/include/linux/list.h', 'a'),
            ('linux-6.18.39/include/linux/list.h', 'b')], False)

    def test_empty_header_rejected(self):
        self.run_case([('linux-6.18.38/include/linux/list.h', '')], False)

    def test_symlink_header_rejected(self):
        self.run_case([('external-list.h', 'external')], False, symlink=True)


if __name__ == '__main__':
    unittest.main()
