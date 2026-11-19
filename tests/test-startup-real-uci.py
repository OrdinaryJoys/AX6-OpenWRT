#!/usr/bin/env python3
"""Explicitly supplied UCI/ash, private config + delta only; no service actions."""
import argparse
import hashlib
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
parser.add_argument('--service', type=Path, default=ROOT / 'AX6-IPQ/files/etc/init.d/ax6-boot-guard')
args = parser.parse_args()
service = args.service.resolve(strict=True)
if Path('/tmp/.uci').exists():
    raise SystemExit('Refusing external default UCI delta directory /tmp/.uci')
cases = []
for mode in ('correct', 'migration', 'no-globals', 'anonymous-globals',
             'first-before-named', 'wrong-type-named', 'missing-required', 'pending', 'parse-error'):
    with tempfile.TemporaryDirectory(prefix='ax6-private-uci-') as temp:
        root = Path(temp)
        config = root / 'etc/config'
        config.mkdir(parents=True)
        delta = root / 'uci-state'
        delta.mkdir()
        config2 = root / 'uci-config2'
        config2.mkdir()
        network = "config globals 'globals'\n option packet_steering '0'\nconfig device 'br'\n option name 'br-lan'\n"
        if mode == 'migration':
            network = network.replace("steering '0'", "steering '1'") + " option flow_offloading '1'\n"
        elif mode == 'no-globals':
            network = "config interface 'lan'\n option proto 'static'\n"
        elif mode in ('anonymous-globals', 'first-before-named'):
            network = network.replace("config globals 'globals'", 'config globals').replace("steering '0'", "steering '1'")
            if mode == 'first-before-named':
                network += "config globals 'globals'\n option packet_steering '1'\n"
        elif mode == 'wrong-type-named':
            network = "config interface 'globals'\n option packet_steering '1'\n"
        elif mode == 'parse-error':
            network = "config globals 'unterminated\n"
        (config / 'network').write_text(network)
        firewall = "config defaults\n option flow_offloading '0'\n option flow_offloading_hw '0'\n"
        if mode == 'missing-required':
            firewall = "config zone\n option name 'lan'\n"
        (config / 'firewall').write_text(firewall.replace("'0'", "'1'") if mode == 'migration' else firewall)
        (config / 'ecm').write_text("config ecm 'general'\n option disable_offloads '1'\n option disable_gro_list '1'\n")
        env = dict(os.environ, FIXTURE_ROOT=temp)
        def uci(*command, check=True):
            return subprocess.run([args.uci, '-c', str(config), '-C', str(config2), '-t', str(delta), *command],
                                  env=env, capture_output=True, text=True, check=check)
        if mode == 'pending':
            uci('set', 'network.lan=interface')
        before = (config / 'network').read_bytes()
        body = '''uci() { "$REAL_UCI" -c "$FIXTURE_ROOT/etc/config" -C "$FIXTURE_ROOT/uci-config2" -t "$FIXTURE_ROOT/uci-state" "$@"; }
logger() { printf '%s\\n' "$*"; }
. "$1"
start
'''
        result = subprocess.run([*shlex.split(args.shell), '-c', body, 'ash', str(service)],
                                env=dict(env, REAL_UCI=args.uci), capture_output=True, text=True, timeout=15)
        assert (result.returncode == 0) == (mode not in ('missing-required', 'pending', 'parse-error')), (mode, result)
        assert uci('get', 'ecm.general.offload_physical_policy').stdout.strip() == 'report'
        if mode == 'missing-required':
            assert uci('get', 'firewall.@defaults[0]', check=False).returncode != 0
        else:
            assert uci('get', 'firewall.@defaults[0].flow_offloading').stdout.strip() == '0'
            assert uci('get', 'firewall.@defaults[0].flow_offloading_hw').stdout.strip() == '0'
        if mode in ('no-globals', 'wrong-type-named', 'pending', 'parse-error'):
            assert (config / 'network').read_bytes() == before
        elif mode in ('anonymous-globals', 'first-before-named'):
            assert uci('get', 'network.@globals[0].packet_steering').stdout.strip() == '0'
            if mode == 'first-before-named':
                assert uci('get', 'network.globals.packet_steering').stdout.strip() == '1'
        else:
            assert uci('get', 'network.globals.packet_steering').stdout.strip() == '0'
            assert uci('get', 'network.br.flow_offloading', check=False).returncode != 0
        cases.append({'mode': mode, 'returncode': result.returncode})
print(json.dumps({'cases': cases, 'shell': shlex.split(args.shell),
                  'service_sha256': hashlib.sha256(service.read_bytes()).hexdigest(),
                  'uci_sha256': hashlib.sha256(Path(args.uci).read_bytes()).hexdigest(),
                  'scope': 'real UCI, supplied shell, private config/config2/delta, no network actions'}))
