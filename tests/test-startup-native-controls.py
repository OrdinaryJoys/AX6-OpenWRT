#!/usr/bin/env python3
"""The native behavior gate must reject the exact former hard-coded globals."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--uci', required=True)
parser.add_argument('--shell', required=True)
args = parser.parse_args()
legacy = ROOT / 'tests/fixtures/startup-before-globals.data'
assert hashlib.sha256(legacy.read_bytes()).hexdigest() == '8133a018b669ac325f3dd316486486a6d30b82e891f91c77b4a30150477efe18'
command = [sys.executable, '-B', str(ROOT / 'tests/test-startup-real-uci.py'),
           '--uci', args.uci, '--shell', args.shell]
negative = subprocess.run([*command, '--service', str(legacy)], capture_output=True, text=True, timeout=60)
assert negative.returncode == 1 and not negative.stdout, (negative.returncode, negative.stdout, negative.stderr)
assert "AssertionError: ('no-globals'," in negative.stderr, negative.stderr
positive = subprocess.run(command, capture_output=True, text=True, timeout=60)
assert positive.returncode == 0 and not positive.stderr, (positive.returncode, positive.stderr)
result = json.loads(positive.stdout)
assert len(result['cases']) == 9
assert result['service_sha256'] == 'e7fe4a88bb9c521dc2cd92c8c2de12fde3d290bd644a4e79f61b1f41b2603b53'
print(json.dumps({'legacy': {'source_build': '0423eeb526efc6e821c8574fe9d59905813a3219',
                             'rejected_case': 'no-globals', 'exit_code': negative.returncode},
                  'candidate': result,
                  'scope': 'Private native UCI behavior positive and exact legacy negative; not boot or kernel acceptance'}))
