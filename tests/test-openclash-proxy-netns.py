#!/usr/bin/env python3
"""Linux-only real nft ingress tests in disposable namespaces (not a router).

Proxy backends are counter/mark sinks, not Mihomo: this proves packet admission
and nft grammar, not DNS resolution, TPROXY delivery or TUN performance.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scope_tests', ROOT / 'tests/test-openclash-proxy-scope.py')
test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test)


def run(*args, input=None):
    result = subprocess.run(args, input=input, text=True, capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f'{args!r}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('init', type=Path, nargs='?')
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.exit(2, 'Requires root in a disposable Linux CI runner; never run on a router\n')
    text = test.proxy.transform(args.init.read_text() if args.init else test.fixture())
    # Every emitted site must first pass the upstream-shape guard.
    test.proxy.check(text)
    available = {(m[2], m[3]) for line in text.splitlines() if (m := test.proxy.SCOPED.fullmatch(line))}
    prefix = f'ax6proxy{os.getpid()}'
    router = prefix + 'r'
    peers = {name: prefix + str(index) for index, name in enumerate(('lan', 'wan', 'zt'), 1)}
    created = []

    def ns(*cmd, **kwargs):
        return run('ip', 'netns', 'exec', router, *cmd, **kwargs)

    def count(name='admitted'):
        value = json.loads(ns('nft', '-j', 'list', 'counter', 'inet', 'fw4', name))
        return next(item['counter']['packets'] for item in value['nftables'] if 'counter' in item)

    def packet(peer, family, protocol, destination=None, port=54321):
        destination = destination or ('198.19.0.99' if family == 4 else 'fd99::99')
        code = '''import socket,sys
family,proto,dest,port=sys.argv[1:]
af=socket.AF_INET if family=='4' else socket.AF_INET6
kind=socket.SOCK_STREAM if proto=='tcp' else socket.SOCK_DGRAM
if proto=='icmp':
 s=socket.socket(af,socket.SOCK_RAW,socket.IPPROTO_ICMP if family=='4' else socket.IPPROTO_ICMPV6)
 s.sendto(bytes.fromhex('0800f7fd00010001' if family=='4' else '8000000000010001'),(dest,0))
else:
 s=socket.socket(af,kind); s.settimeout(0.15)
 try:
  if proto=='tcp': s.connect((dest,int(port)))
  else: s.sendto(b'AX6 ingress fixture',(dest,int(port)))
 except OSError as error: print(repr(error))
 s.close()
'''
        return run('ip', 'netns', 'exec', peer, sys.executable, '-c', code, str(family), protocol, destination, str(port))

    def expect(peer, family, proto, allowed, **kwargs):
        before = count()
        arrival_before = count('arrived')
        sender = packet(peer, family, proto, **kwargs)
        after = count()
        arrival_after = count('arrived')
        if arrival_after <= arrival_before or (after > before) != allowed:
            print('Sender:', sender, flush=True)
            print(ns('nft', '-a', 'list', 'ruleset'), flush=True)
            print(ns('ip', '-s', 'link'), flush=True)
            print(run('ip', '-n', peer, 'route', 'show'), flush=True)
            print(run('ip', '-n', peer, '-s', 'link'), flush=True)
            print(ns('cat', '/proc/net/snmp'), flush=True)
        assert arrival_after > arrival_before, ('probe never reached prerouting', peer, family, proto)
        assert (after > before) == allowed, (mode, peer, family, proto, allowed, before, after)

    try:
        for name in [router, *peers.values()]:
            run('ip', 'netns', 'add', name)
            created.append(name)
            run('ip', '-n', name, 'link', 'set', 'lo', 'up')
        for index, (role, peer) in enumerate(peers.items(), 1):
            run('ip', '-n', router, 'link', 'add', role, 'type', 'veth', 'peer', 'name', 'p' + role)
            run('ip', '-n', router, 'link', 'set', 'p' + role, 'netns', peer)
            for name, device, suffix in ((router, role, 1), (peer, 'p' + role, 2)):
                run('ip', '-n', name, 'addr', 'add', f'198.18.{index}.{suffix}/24', 'dev', device)
                run('ip', '-n', name, '-6', 'addr', 'add', f'fd42:{index}::{suffix}/64', 'dev', device, 'nodad')
                run('ip', '-n', name, 'link', 'set', device, 'up')
            run('ip', '-n', peer, 'route', 'add', 'default', 'via', f'198.18.{index}.1')
            run('ip', '-n', peer, '-6', 'route', 'add', 'default', 'via', f'fd42:{index}::1')
        index = json.loads(ns('ip', '-j', 'link', 'show', 'lan'))[0]['ifindex']
        with tempfile.TemporaryDirectory(prefix='ax6-nft-scope-') as folder:
            resolver = Path(folder) / 'resolver'
            resolver.write_text(f'#!/bin/sh\nprintf \'iifname "lan" meta iif {index}\\n\'\n')
            resolver.chmod(0o755)
            total = 0
            for mode in ('redirect', 'tun', 'mixed'):
                ns('nft', '-f', '-', input='''flush ruleset
table inet fw4 {
 counter admitted {}
 counter arrived {}
 chain dstnat { type nat hook prerouting priority dstnat; policy accept; }
 chain mangle_prerouting { type filter hook prerouting priority mangle; policy accept;
   counter name arrived
 }
 chain mangle_output { type route hook output priority mangle; policy accept;
   udp dport 54322 meta mark set 0x162
 }
 chain openclash { counter name admitted return; }
 chain openclash_v6 { counter name admitted return; }
 chain openclash_mangle {}
 chain openclash_mangle_v6 {}
}
''')
                protocols = '{ tcp, udp }' if mode == 'tun' else 'udp'
                for chain in ('openclash_mangle', 'openclash_mangle_v6'):
                    ns('nft', 'add', 'rule', 'inet', 'fw4', chain, 'meta l4proto', protocols, 'counter name admitted return')
                if mode != 'redirect':
                    ns('nft', 'add', 'rule', 'inet', 'fw4', 'openclash_mangle', 'icmp type echo-request counter name admitted return')
                    ns('nft', 'add', 'rule', 'inet', 'fw4', 'openclash_mangle_v6', 'icmpv6 type echo-request counter name admitted return')
                chosen = [(chain, body) for chain, body in available
                          if (chain != 'dstnat' or mode != 'tun')
                          and (chain != 'mangle_prerouting' or 'ipv4' not in body
                               or ('ip protocol udp' in body) == (mode == 'redirect'))]
                code = test.proxy.HELPERS + '\nLOG_WARN() { :; }; LOG_ERROR() { :; };\nax6_proxy_scope_prepare || exit 1\n'
                code += '\n'.join(f"ax6_proxy_scope_jump '{chain}' '{body}' || exit 1" for chain, body in chosen)
                ns('env', f'AX6_PROXY_SCOPE_BIN={resolver}', 'PROXY_FWMARK=0x162', 'sh', '-c', code)
                # Reapplying the real callback cleans old jumps rather than duplicating.
                first = json.loads(ns('nft', '-j', 'list', 'ruleset'))
                ns('env', f'AX6_PROXY_SCOPE_BIN={resolver}', 'PROXY_FWMARK=0x162', 'sh', '-c', code)
                second = json.loads(ns('nft', '-j', 'list', 'ruleset'))
                n_rules = lambda rules: sum('rule' in item for item in rules['nftables'])
                assert n_rules(first) == n_rules(second), 'reload duplicated rules'
                # NAT lookup bypasses packets without conntrack. Counter-only
                # backends do not acquire it as real REDIRECT/TPROXY rules do.
                # First reproduce the missing prerequisite, then enable it.
                if mode == 'redirect':
                    expect(peers['lan'], 4, 'tcp', False)
                ns('nft', 'add', 'rule', 'inet', 'fw4', 'mangle_prerouting', 'ct state new counter')
                for role, peer in peers.items():
                    for family in (4, 6):
                        for proto in ('tcp', 'udp', 'icmp'):
                            allowed = role == 'lan' and (proto != 'icmp' or mode != 'redirect')
                            expect(peer, family, proto, allowed)
                            total += 1
                for family, address in ((4, '127.0.0.1'), (6, '::1')):
                    expect(router, family, 'udp', False, destination=address)
                    expect(router, family, 'udp', True, destination=address, port=54322)
                    total += 2
                print(f'PASS {mode}: LAN/WAN/ZeroTier v4/v6 TCP/UDP/ICMP; marked/unmarked lo; idempotent cleanup')
                # A stale index cannot authorize an interface just by its name.
                ns('ip', 'link', 'set', 'lan', 'name', 'oldlan')
                expect(peers['lan'], 4, 'udp', False)
                ns('ip', 'link', 'add', 'lan', 'type', 'dummy')
                ns('ip', 'link', 'del', 'lan')
                ns('ip', 'link', 'set', 'oldlan', 'name', 'lan')
                # Positive control: excluded peers can send to this hook. An
                # unscoped legacy jump must produce the forbidden admission.
                ns('nft', 'add', 'rule', 'inet', 'fw4', 'mangle_prerouting',
                   'meta l4proto udp counter jump openclash_mangle')
                expect(peers['wan'], 4, 'udp', True)
                expect(peers['zt'], 6, 'udp', True)
            print(f'PASS {total} real packet admission assertions; 3 reload/rename checks (counter sinks, not full proxy delivery)')
    finally:
        for name in reversed(created):
            subprocess.run(['ip', 'netns', 'del', name], check=False, capture_output=True)


if __name__ == '__main__':
    main()
