#!/usr/bin/env python3
"""Run both exact CI installer blocks with mocks; no package/network installation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parents[1]
NAME = '      - name: Install hash-verified host-only ELF parser\n'
scripts = {}
for filename in ('lint.yml', 'build-AX6-NSS.yml'):
    text = (ROOT / '.github/workflows' / filename).read_text()
    assert text.count(NAME) == 1
    block = text.split(NAME, 1)[1].split('\n      - name:', 1)[0]
    assert 'timeout-minutes: 3' in block
    script = textwrap.dedent(block.split('        run: |\n', 1)[1])
    for token in ('--require-hashes', '--only-binary=:all:', '--no-deps',
                  '--index-url https://pypi.org/simple', 'AX6_ARTIFACT_PYTHON=',
                  '.github/ax6-artifact-requirements.txt'):
        assert token in script, (filename, token)
    assert 'GITHUB_PATH' not in script and 'sudo' not in script
    assert '"$AX6_ARTIFACT_PYTHON" tests/test-ax6-artifact-checks.py' in text
    assert '"$AX6_ARTIFACT_PYTHON" tests/test-ax6-module-elf.py' in text
    if filename.startswith('build'):
        assert '"$AX6_ARTIFACT_PYTHON" .github/scripts/verify-ax6-artifacts.py images' in text
    scripts[filename] = script
assert len(set(scripts.values())) == 1
assert (ROOT / '.github/ax6-artifact-requirements.txt').read_text().count('--hash=sha256:') == 1

PYTHON_MOCK = r'''#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import sys
case = os.environ['PARSER_CASE']
if sys.argv[1:3] == ['-m', 'venv']:
    if case == 'venv-failed':
        sys.exit(9)
    target = Path(sys.argv[3]) / 'bin/python3'
    target.parent.mkdir(parents=True)
    if case != 'missing-venv-python':
        shutil.copy2(sys.argv[0], target)
    sys.exit(0)
assert sys.argv[1:5] == ['-m', 'pip', '--isolated', '--disable-pip-version-check']
assert '--require-hashes' in sys.argv and '--no-deps' in sys.argv
if case == 'pip-failed':
    sys.exit(11)
Path(os.environ['RUNNER_TEMP'], 'pip-called').write_text('mock-only')
'''
TIMEOUT_MOCK = r'''#!/usr/bin/env python3
import os
import sys
assert sys.argv[1:3] == ['--kill-after=10s', '120s']
if os.environ['PARSER_CASE'] == 'timed-out':
    sys.exit(124)
os.execv(sys.argv[3], sys.argv[3:])
'''
rows = []
for filename, script in scripts.items():
    for case in ('valid', 'venv-failed', 'missing-venv-python', 'pip-failed', 'timed-out', 'env-write-failed'):
        with tempfile.TemporaryDirectory(prefix='ax6-parser-install-') as temporary:
            directory = Path(temporary)
            mocks = directory / 'mocks'
            mocks.mkdir()
            for name, body in (('python3', PYTHON_MOCK), ('timeout', TIMEOUT_MOCK)):
                path = mocks / name
                # Mock shebang bypasses PATH's mocked python3.
                path.write_text(body.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1))
                path.chmod(0o755)
            envfile = directory / 'env'
            if case == 'env-write-failed':
                envfile.mkdir()
            env = dict(os.environ, PATH=str(mocks) + os.pathsep + os.environ['PATH'],
                       RUNNER_TEMP=str(directory), GITHUB_ENV=str(envfile), PARSER_CASE=case)
            result = subprocess.run(['bash', '-c', script + '\nprintf finished'],
                                    env=env, capture_output=True, text=True, timeout=10)
            expected = case == 'valid'
            assert (result.returncode == 0) == expected, (filename, case, result.stderr)
            if expected:
                assert result.stdout == 'finished'
                assert envfile.read_text().startswith('AX6_ARTIFACT_PYTHON=' + str(directory))
            else:
                assert 'finished' not in result.stdout
                assert not envfile.is_file() or not envfile.read_text()
            rows.append({'workflow': filename, 'case': case, 'rc': result.returncode})
print(json.dumps({'status': 'PASS_MOCK_WIRING_ONLY', 'cases': rows,
                  'limits': ['no actual Linux installer or GitHub Actions execution']}, indent=2))
