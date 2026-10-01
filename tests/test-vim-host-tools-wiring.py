#!/usr/bin/env python3
"""Execute the exact CI run block with fake host tools; never run real make."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap

root = Path(__file__).resolve().parents[1]
workflow = (root / '.github/workflows/build-AX6-NSS.yml').read_text()
name = 'Prepare locked native host tools before Vim source preparation'
marker = '      - name: ' + name + '\n'
assert workflow.count(marker) == 1
block = workflow.split(marker)[1].split('\n      - name:', 1)[0]
assert 'working-directory: ./openwrt' in block
script = textwrap.dedent(block.split('        run: |\n', 1)[1])
assert workflow.index('      - name: Download package\n') < workflow.index(marker)
assert workflow.index(marker) < workflow.index('      - name: Prepare selected Vim source')
assert workflow.index('      - name: Prepare selected Vim source') < workflow.index('      - name: Preserve Vim prepare evidence even on failure')
assert 'if: always()' in workflow.split('      - name: Preserve Vim prepare evidence even on failure')[1].split('\n      - name:', 1)[0]
assert 'package/feeds/packages/vim/prepare' in workflow
assert 'apply-vim-security-backport.py prepared "$vim_source"' in workflow
assert not re.search(r'(?m)^\s*(?:export\s+)?M4=', script)

make_mock = r'''#!/usr/bin/env python3
import os
from pathlib import Path
import sys
assert sys.argv[1:] == ['-j2', 'tools/install', 'V=s'], sys.argv
Path('make-called').write_text('native-tools-install\n')
print('synthetic native host stage', flush=True)
case = os.environ['AX6_HOST_TOOLS_TEST_CASE']
if case == 'make-failure':
    sys.exit(2)
dest = Path('staging_dir/host/bin')
dest.mkdir(parents=True)
for name, version in [('m4', 'm4 (GNU M4) 1.4.21'), ('autoconf', 'autoconf (GNU Autoconf) 2.72')]:
    if case == 'missing-' + name:
        continue
    if case == 'wrong-' + name:
        version += '-wrong'
    path = dest / name
    path.write_text("#!/bin/sh\nprintf '%s\\n' '" + version + "'\n")
    if case == 'version-failure-' + name:
        path.write_text('#!/bin/sh\nexit 7\n')
    path.chmod(0o644 if case == 'nonexec-' + name else 0o755)
'''

hash_mock = r'''#!/usr/bin/env python3
import hashlib
import os
from pathlib import Path
import sys
if os.environ['AX6_HOST_TOOLS_TEST_CASE'] == 'hash-failure':
    sys.exit(13)
assert sys.argv[1:] == ['staging_dir/host/bin/m4', 'staging_dir/host/bin/autoconf']
for filename in sys.argv[1:]:
    print(hashlib.sha256(Path(filename).read_bytes()).hexdigest() + '  ' + filename)
'''

tee_mock = r'''#!/usr/bin/env python3
import os
from pathlib import Path
import sys
data = sys.stdin.buffer.read()
Path(sys.argv[1]).write_bytes(data)
sys.stdout.buffer.write(data)
if os.environ['AX6_HOST_TOOLS_TEST_CASE'] == 'tee-failure':
    sys.exit(11)
'''

rows = []
cases = ['valid', 'make-failure', 'tee-failure', 'missing-m4', 'missing-autoconf',
         'wrong-m4', 'wrong-autoconf', 'version-failure-m4', 'version-failure-autoconf',
         'nonexec-m4', 'nonexec-autoconf', 'hash-failure', 'invalid-jobs', 'nproc-failure']
for case in cases:
    with tempfile.TemporaryDirectory(prefix='ax6-vim-host-tools-') as temporary:
        base = Path(temporary)
        tree = base / 'openwrt'
        tree.mkdir()
        mocks = base / 'mocks'
        mocks.mkdir()
        nproc = '#!/bin/sh\nprintf "2\\n"\n'
        if case == 'invalid-jobs':
            nproc = '#!/bin/sh\nprintf "0\\n"\n'
        elif case == 'nproc-failure':
            nproc = '#!/bin/sh\nexit 17\n'
        for filename, content in [('make', make_mock), ('nproc', nproc),
                                  ('sha256sum', hash_mock), ('tee', tee_mock)]:
            path = mocks / filename
            path.write_text(content)
            path.chmod(0o755)
        env = os.environ.copy()
        env['PATH'] = str(mocks) + os.pathsep + env['PATH']
        env['AX6_HOST_TOOLS_TEST_CASE'] = case
        result = subprocess.run(['bash', '-c', script + '\nprintf done > ../completed\n'],
                                cwd=tree, env=env, capture_output=True, timeout=20)
        expected = case == 'valid'
        assert (result.returncode == 0) == expected, (case, result.returncode, result.stderr.decode())
        assert (base / 'completed').exists() == expected, case
        if case in ('invalid-jobs', 'nproc-failure'):
            assert not (tree / 'make-called').exists(), case
        if expected:
            evidence = base / 'vim-evidence'
            assert (evidence / 'host-tools.log').read_text() == 'synthetic native host stage\n'
            for tool in ('m4', 'autoconf'):
                path = tree / 'staging_dir/host/bin' / tool
                assert hashlib.sha256(path.read_bytes()).hexdigest() in (evidence / 'HOST-TOOLS-SHA256.txt').read_text()
        rows.append({'name': case, 'rc': result.returncode, 'matched': True})
print(json.dumps({'scope': 'Exact workflow block with fake make/nproc/tee/hash/staged tools; no actual OpenWrt bootstrap or router',
                  'workflow_sha256': hashlib.sha256(workflow.encode()).hexdigest(),
                  'cases': rows}, indent=2))
