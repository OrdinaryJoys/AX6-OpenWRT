#!/usr/bin/env python3
"""Fake make/tee only: no compilation, downloads, privilege or kernel actions."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/scripts/compile-ax6-with-evidence.sh'
FAKE_MAKE = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
trace=Path(os.environ['AX6_TEST_MAKE_TRACE'])
calls=json.loads(trace.read_text()) if trace.exists() else []
calls.append(sys.argv[1:]); trace.write_text(json.dumps(calls))
print('compile fixture: ' + str(len(calls)), flush=True)
raise SystemExit(json.loads(os.environ['AX6_TEST_MAKE_RCS'])[len(calls)-1])
'''
results = []

def scenario(name, rcs, expected, jobs='4', tee_failure=False, existing=False, symlink=False):
    with tempfile.TemporaryDirectory(prefix='ax6-compile-evidence-') as temporary:
        base = Path(temporary)
        tools = base / 'tools'
        tools.mkdir()
        make = tools / 'make'
        make.write_text(FAKE_MAKE)
        make.chmod(0o755)
        if tee_failure:
            tee = tools / 'tee'
            tee.write_text('#!/bin/sh\nexit 8\n')
            tee.chmod(0o755)
        output = base / 'evidence'
        if existing:
            output.mkdir()
            (output / 'preserve.txt').write_text('preserve\n')
        if symlink:
            output.symlink_to(base / 'missing', target_is_directory=True)
        env = os.environ.copy()
        env['PATH'] = str(tools) + os.pathsep + env['PATH']
        env['AX6_TEST_MAKE_TRACE'] = str(base / 'calls.json')
        env['AX6_TEST_MAKE_RCS'] = json.dumps(rcs)
        completed = subprocess.run(['bash', str(SCRIPT), jobs, str(output)], cwd=base,
                                   env=env, capture_output=True, text=True, timeout=15)
        assert completed.returncode == expected, (name, completed.returncode, completed.stderr)
        calls = json.loads((base / 'calls.json').read_text()) if (base / 'calls.json').exists() else []
        events = [json.loads(line) for line in (output / 'attempts.jsonl').read_text().splitlines()] if (output / 'attempts.jsonl').is_file() else []
        if expected == 2:
            assert not calls
            if existing:
                assert (output / 'preserve.txt').read_text() == 'preserve\n'
        elif tee_failure:
            assert len(calls) <= 1
            assert events[-1]['tee_rc'] == 8
            assert not any(event.get('attempt') == 'serial' for event in events)
        else:
            summary = events[-1]
            assert summary['event'] == 'summary' and summary['parallel_rc'] == rcs[0]
            assert summary['overall_rc'] == expected
            assert calls[0] == ['-j4', 'V=s']
            assert (output / 'compile-parallel.log').read_text().startswith('compile fixture: 1')
            if rcs[0]:
                assert calls == [['-j4', 'V=s'], ['-j1', 'V=s']]
                assert summary['serial_rc'] == rcs[1]
                assert (output / 'compile-serial.log').read_text().startswith('compile fixture: 2')
            else:
                assert len(calls) == 1 and summary['serial_rc'] is None
        results.append({'name': name, 'exit': completed.returncode, 'calls': calls})

scenario('parallel-success-no-retry', [0], 0)
scenario('parallel-failure-serial-success-retains-first-rc', [9, 0], 0)
scenario('both-fail-preserve-serial-rc', [9, 23], 23)
scenario('tee-failure-no-blind-retry', [0], 8, tee_failure=True)
scenario('invalid-zero-jobs', [0], 2, jobs='0')
scenario('invalid-shell-jobs', [0], 2, jobs='4;false')
scenario('existing-evidence-preserved', [0], 2, existing=True)
scenario('dangling-evidence-link-refused', [0], 2, symlink=True)
print(json.dumps({'scope': 'fake local make/tee only', 'passed': len(results), 'results': results}, indent=2))
