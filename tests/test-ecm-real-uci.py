#!/usr/bin/env python3
"""Actual steering function and UCI CLI; live policy is an observed private file."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, required=True)
parser.add_argument('--uci', type=Path, required=True)
parser.add_argument('--shell', required=True)
parser.add_argument('--init', type=Path)
args = parser.parse_args()
init = args.init or args.source_root / 'package/qca-nss/qca-nss-ecm/files/qca-nss-ecm.init'
definitions = re.findall(r'^disable_packet_steering\(\) \{\n.*?^\}', init.read_text(), re.M | re.S)
assert len(definitions) == 1, 'complete function anchor'
function = definitions[0]
assert function.count('/usr/libexec/platform/packet-steering.sh') == 2
assert 'if [ -e "/usr/libexec/platform/packet-steering.sh" ]; then' in function
assert '\t\t/usr/libexec/platform/packet-steering.sh 0\n' in function
if Path('/tmp/.uci').exists():
    raise SystemExit('Refusing external default UCI delta directory /tmp/.uci')
rows = []
for mode in ['absent', 'named', 'anonymous', 'first-before-named', 'wrong-type-named',
             'malformed', 'pending', 'live-failure', 'pending-live-failure']:
    with tempfile.TemporaryDirectory(prefix='ax6-ecm-real-uci-') as temp:
        base = Path(temp)
        config, config2, delta = [base / name for name in ['config', 'config2', 'delta']]
        for path in [config, config2, delta]:
            path.mkdir()
        network = "config interface 'lan'\n option ipaddr '192.0.2.1'\n"
        if mode == 'malformed':
            network = "config globals 'unclosed\n"
        elif mode not in ['absent', 'wrong-type-named']:
            name = '' if mode in ['anonymous', 'first-before-named'] else " 'globals'"
            network += "config globals" + name + "\n option packet_steering '1'\n option steering_flows '64'\n"
            if mode == 'first-before-named':
                network += "config globals 'globals'\n option packet_steering '1'\n"
        else:
            if mode == 'wrong-type-named':
                network += "config interface 'globals'\n option packet_steering '1'\n"
        net = config / 'network'
        net.write_text(network)

        def uci(*command, check=True):
            return subprocess.run([str(args.uci.resolve()), '-q', '-c', str(config), '-C', str(config2),
                                   '-t', str(delta), *command], capture_output=True, text=True,
                                  check=check, timeout=10)

        if mode in ['pending', 'pending-live-failure']:
            uci('set', 'network.lan.ipaddr=192.0.2.2')
        pending_before = uci('changes', 'network', check=False).stdout
        before = net.read_bytes()
        live = base / 'live-policy'
        live.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CASE_ROOT/live.log"\nexit "$LIVE_RC"\n')
        live.chmod(0o700)
        script = function.replace('/usr/libexec/platform/packet-steering.sh', str(live))
        body = '''uci() { "$NATIVE_UCI" -q -c "$CASE_ROOT/config" -C "$CASE_ROOT/config2" -t "$CASE_ROOT/delta" "$@"; }
logger() { printf '%s\\n' "$*" >> "$CASE_ROOT/logger.log"; }
''' + script + '\ndisable_packet_steering\n'
        live_rc = 17 if mode in ['live-failure', 'pending-live-failure'] else 0
        expected = 1 if mode in ['malformed', 'pending', 'pending-live-failure'] else live_rc
        result = subprocess.run([*shlex.split(args.shell), '-c', body],
                                env=dict(os.environ, CASE_ROOT=temp, NATIVE_UCI=str(args.uci.resolve()),
                                         LIVE_RC=str(live_rc)), capture_output=True, text=True, timeout=15)
        assert result.returncode == expected, (mode, result.returncode, result.stderr)
        assert (base / 'live.log').read_text() == '0\n', (mode, 'live queue policy must still run exactly once')
        if mode in ['absent', 'wrong-type-named', 'malformed', 'pending', 'pending-live-failure']:
            assert net.read_bytes() == before, (mode, 'persistent config changed')
            assert uci('changes', 'network', check=False).stdout == pending_before, (mode, 'foreign delta changed')
        else:
            assert uci('get', 'network.@globals[0].packet_steering').stdout.strip() == '0'
            assert uci('get', 'network.@globals[0].steering_flows', check=False).returncode != 0
            if mode == 'first-before-named':
                assert uci('get', 'network.globals.packet_steering').stdout.strip() == '1'
        rows.append({'case': mode, 'returncode': result.returncode, 'live_policy_calls': 1})
print(json.dumps({'cases': rows, 'shell': shlex.split(args.shell),
                  'init_sha256': hashlib.sha256(init.read_bytes()).hexdigest(),
                  'function_sha256': hashlib.sha256(function.encode()).hexdigest(),
                  'uci_sha256': hashlib.sha256(args.uci.read_bytes()).hexdigest(),
                  'scope': 'Complete steering function, real UCI, private config/delta, observed live-policy helper; not full ECM boot'}))
