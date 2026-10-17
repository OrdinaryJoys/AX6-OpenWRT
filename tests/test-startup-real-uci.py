#!/usr/bin/env python3
"""Explicitly supplied UCI/ash, private config + delta only; no service actions."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--uci', required=True)
parser.add_argument('--shell', required=True)
args = parser.parse_args()
service = ROOT / 'AX6-IPQ/files/etc/init.d/ax6-boot-guard'
cases = []
for mode in ('correct', 'migration', 'missing-section', 'pending', 'parse-error'):
    with tempfile.TemporaryDirectory(prefix='ax6-private-uci-') as temp:
        root = Path(temp)
        config = root / 'etc/config'
        config.mkdir(parents=True)
        delta = root / 'uci-state'
        delta.mkdir()
        network = "config globals 'globals'\n option packet_steering '0'\nconfig device 'br'\n option name 'br-lan'\n"
        if mode == 'migration':
            network = network.replace("steering '0'", "steering '1'") + " option flow_offloading '1'\n"
        elif mode == 'missing-section':
            network = "config interface 'lan'\n option proto 'static'\n"
        elif mode == 'parse-error':
            network = "config globals 'unterminated\n"
        (config / 'network').write_text(network)
        firewall = "config defaults\n option flow_offloading '0'\n option flow_offloading_hw '0'\n"
        (config / 'firewall').write_text(firewall.replace("'0'", "'1'") if mode == 'migration' else firewall)
        (config / 'ecm').write_text("config ecm 'general'\n option disable_offloads '1'\n option disable_gro_list '1'\n")
        env = dict(os.environ, FIXTURE_ROOT=temp)
        def uci(*command, check=True):
            return subprocess.run([args.uci, '-c', str(config), '-t', str(delta), *command],
                                  env=env, capture_output=True, text=True, check=check)
        if mode == 'pending':
            uci('set', 'network.lan=interface')
        before = (config / 'network').read_bytes()
        body = '''uci() { "$REAL_UCI" -c "$FIXTURE_ROOT/etc/config" -t "$FIXTURE_ROOT/uci-state" "$@"; }
logger() { printf '%s\\n' "$*"; }
. "$1"
start
'''
        result = subprocess.run([*shlex.split(args.shell), '-c', body, 'ash', str(service)],
                                env=dict(env, REAL_UCI=args.uci), capture_output=True, text=True, timeout=15)
        assert (result.returncode == 0) == (mode in ('correct', 'migration')), (mode, result)
        assert uci('get', 'ecm.general.offload_physical_policy').stdout.strip() == 'report'
        assert uci('get', 'firewall.@defaults[0].flow_offloading').stdout.strip() == '0'
        assert uci('get', 'firewall.@defaults[0].flow_offloading_hw').stdout.strip() == '0'
        if mode in ('missing-section', 'pending', 'parse-error'):
            assert (config / 'network').read_bytes() == before
        else:
            assert uci('get', 'network.globals.packet_steering').stdout.strip() == '0'
            assert uci('get', 'network.br.flow_offloading', check=False).returncode != 0
        cases.append({'mode': mode, 'returncode': result.returncode})
print(json.dumps({'cases': cases, 'scope': 'real UCI/ash, private config/delta, no network actions'}))
