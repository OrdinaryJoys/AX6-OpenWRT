#!/usr/bin/env python3
"""Validate real nft/ip JSON and interface recreation in one disposable netns.

Backends here only redirect/mark; there is no Mihomo or throughput claim.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('proxy_tests', ROOT / 'tests/test-openclash-proxy-scope.py')
test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test)
CHECK = ROOT / 'AX6-IPQ/files/usr/libexec/ax6-openclash-fw-check.uc'
UCODE = shlex.split(os.environ.get('AX6_TEST_UCODE', 'ucode'))


def run(*cmd, input=None):
    result = subprocess.run(cmd, input=input, text=True, capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f'{cmd!r}: {result.returncode}\n{result.stdout}{result.stderr}')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('init', type=Path)
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.exit(2, 'Requires disposable Linux CI root; never run on a router\n')
    text = args.init.read_text()
    test.proxy.check(text)
    sites = {(m[2], m[3]) for line in text.splitlines() if (m := test.proxy.SCOPED.fullmatch(line))}
    name = f'ax6health{os.getpid()}'
    created = False

    def ns(*cmd, **kwargs):
        return run('ip', 'netns', 'exec', name, *cmd, **kwargs)

    def index():
        return json.loads(ns('ip', '-j', 'link', 'show', 'lan'))[0]['ifindex']

    def check(mode, v6mode, status=0):
        snapshot = {'links_before': json.loads(ns('ip', '-j', 'link', 'show'))}
        snapshot['fw4'] = json.loads(ns('nft', '-j', '-n', 'list', 'table', 'inet', 'fw4'))
        for family in (4, 6):
            snapshot[f'rule{family}'] = json.loads(ns('ip', '-j', f'-{family}', 'rule', 'show'))
            snapshot[f'route{family}'] = json.loads(ns('ip', '-j', f'-{family}', 'route', 'show', 'table', 'all'))
        snapshot['links_after'] = json.loads(ns('ip', '-j', 'link', 'show'))
        result = subprocess.run(['ip', 'netns', 'exec', name, *UCODE, str(CHECK),
                                 f'iifname "lan" meta iif {index()}', mode, '1', str(v6mode), '1', '0'],
                                input=json.dumps(snapshot), text=True, capture_output=True, timeout=20)
        assert result.returncode == status, (mode, v6mode, status, result.stdout, result.stderr, snapshot)

    try:
        run('ip', 'netns', 'add', name)
        created = True
        for dev in ('lan', 'utun'):
            ns('ip', 'link', 'add', dev, 'type', 'dummy')
            ns('ip', 'link', 'set', dev, 'up')
        ns('ip', 'link', 'set', 'lo', 'up')
        with tempfile.TemporaryDirectory(prefix='ax6-health-resolver-') as folder:
            resolver = Path(folder) / 'scope'
            resolver.write_text(f'#!/bin/sh\nprintf \'iifname "lan" meta iif {index()}\\n\'\n')
            resolver.chmod(0o755)
            for mode in ('fake-ip', 'fake-ip-tun', 'fake-ip-mix'):
                tun, mixed = mode.endswith('-tun'), mode.endswith('-mix')
                for v6mode in range(4):
                    ns('nft', '-f', '-', input='''flush ruleset
table inet fw4 {
 chain dstnat { type nat hook prerouting priority dstnat; policy accept; }
 chain mangle_prerouting { type filter hook prerouting priority mangle; policy accept; }
 chain openclash { meta l4proto tcp redirect to :7892; }
 chain openclash_v6 { meta l4proto tcp redirect to :7892; }
 chain openclash_mangle { meta mark set 0x162 counter; }
 chain openclash_mangle_v6 { meta mark set 0x162 counter; }
 chain openclash_dns_redirect { counter return; }
}
''')
                    for family in (4, 6):
                        # Only fixture-owned rule/table in this namespace.
                        rules = json.loads(ns('ip', '-j', f'-{family}', 'rule', 'show'))
                        owned = [rule for rule in rules if rule.get('priority') == 1888]
                        if owned:
                            assert len(owned) == 1 and owned[0].get('fwmark') == '0x162' and str(owned[0].get('table')) == '354', owned
                            ns('ip', f'-{family}', 'rule', 'del', 'priority', '1888', 'fwmark', '0x162', 'lookup', '0x162')
                        # A fresh namespace has no IPv4 FIB table 354 yet.
                        # Do not suppress arbitrary ip errors to handle absence.
                        routes = json.loads(ns('ip', '-j', f'-{family}', 'route', 'show', 'table', 'all'))
                        if any(str(route.get('table')) in ('354', '0x162') for route in routes):
                            ns('ip', f'-{family}', 'route', 'flush', 'table', '0x162')
                        if family == 4 or v6mode != 1:
                            ns('ip', f'-{family}', 'rule', 'add', 'priority', '1888', 'fwmark', '0x162', 'lookup', '0x162')
                            tunnel = tun or mixed if family == 4 else v6mode in (2, 3)
                            ns('ip', f'-{family}', 'route', 'add', *(['default', 'dev', 'utun'] if tunnel else ['local', 'default', 'dev', 'lo']), 'table', '0x162')
                    chosen = [(chain, body) for chain, body in sites
                              if not (chain == 'dstnat' and ((body.endswith('jump openclash') and tun) or
                                      (body.endswith('jump openclash_v6') and v6mode not in (1, 3))))
                              and not (chain == 'mangle_prerouting' and 'ipv6' in body and v6mode == 1)
                              and not (chain == 'mangle_prerouting' and 'ipv4' in body and
                                       ('ip protocol udp' in body) == (tun or mixed))]
                    code = test.proxy.HELPERS + '\nLOG_WARN() { :; }; LOG_ERROR() { :; };\nax6_proxy_scope_prepare || exit 1\n'
                    code += '\n'.join(f"ax6_proxy_scope_jump '{chain}' '{body}' || exit 1" for chain, body in chosen)
                    ns('env', f'AX6_PROXY_SCOPE_BIN={resolver}', 'PROXY_FWMARK=0x162', 'sh', '-c', code)
                    check(mode, v6mode)
                    # The same name with a new index must no longer be healthy.
                    old_index = index()
                    ns('ip', 'link', 'del', 'lan')
                    ns('ip', 'link', 'add', 'lan', 'type', 'dummy')
                    ns('ip', 'link', 'set', 'lan', 'up')
                    assert index() != old_index
                    check(mode, v6mode, 1)
                    resolver.write_text(f'#!/bin/sh\nprintf \'iifname "lan" meta iif {index()}\\n\'\n')
                    ns('env', f'AX6_PROXY_SCOPE_BIN={resolver}', 'PROXY_FWMARK=0x162', 'sh', '-c', code)
                    check(mode, v6mode)
                    ns('ip', '-4', 'route', 'flush', 'table', '0x162')
                    check(mode, v6mode, 2 if tun or mixed else 1)
                    # DNS may still be present; it cannot satisfy ingress health.
                    ns('nft', 'flush', 'chain', 'inet', 'fw4', 'dstnat')
                    ns('nft', 'flush', 'chain', 'inet', 'fw4', 'mangle_prerouting')
                    ns('nft', 'add', 'rule', 'inet', 'fw4', 'dstnat', 'jump', 'openclash_dns_redirect')
                    check(mode, v6mode, 1)
                    print(f'PASS {mode}/IPv6 mode {v6mode}: real JSON, stale index, reconcile, absent route, DNS-only negative')
            print('PASS 12 real nft/ip mode cases, 60 snapshot assertions; no real proxy/throughput claim')
    finally:
        if created:
            run('ip', 'netns', 'del', name)


if __name__ == '__main__':
    main()
