#!/usr/bin/env python3
"""Stateful UCI substitute. Only reads/writes a test-created JSON file."""
import json
import os
from pathlib import Path
import sys

path = Path(os.environ['UCI_FIXTURE_STATE'])
state = json.loads(path.read_text())
args = sys.argv[1:]
if args[0] == '-q':
    args.pop(0)
cmd, key = args
key = key.replace('firewall.@defaults[0]', 'firewall.cfgdefaults')
state['calls'].append([cmd, key])
failure = state.get('failure', {})
rc = 0
for item in state.get('failures', []):
    if item.get('cmd') == cmd and key.startswith(item.get('key', '')):
        count = sum(c[0] == cmd and c[1].startswith(item.get('key', '')) for c in state['calls'])
        if count == item.get('nth', count):
            failure = item
            break
if failure.get('cmd') == cmd and key.startswith(failure.get('key', '')):
    rc = failure.get('rc', 17)
elif cmd == 'changes':
    print('\n'.join(state['pending'].get(key, [])))
elif cmd == 'get':
    if key not in state['values']:
        rc = 1
    else:
        print(state['values'][key])
elif cmd == 'show':
    found = [(k, v) for k, v in state['values'].items() if k == key or k.startswith(key + '.')]
    if not found:
        rc = 1
    for k, v in found:
        print(k + '=' + (v if k.count('.') == 1 else repr(v)))
elif cmd in ('set', 'delete'):
    name = key.split('=', 1)[0]
    package = name.split('.')[0]
    if cmd == 'set':
        if state.get('ignore_set') != name:
            state['values'][name] = key.split('=', 1)[1]
    elif state.get('ignore_delete') != name:
        state['values'].pop(name, None)
    state['pending'].setdefault(package, []).append(key)
elif cmd == 'commit':
    state['pending'].pop(key, None)
    if state.get('corrupt_commit') == key:
        state['values'][key + ('.globals.packet_steering' if key == 'network' else '.general.disable_offloads')] = '9'
else:
    rc = 99
path.write_text(json.dumps(state))
sys.exit(rc)
