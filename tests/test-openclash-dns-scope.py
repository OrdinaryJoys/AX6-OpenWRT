#!/usr/bin/env python3
"""Execute extracted DNS rule statements/helpers with mocks, never full init."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
# Independently retained upstream helper bytes, not injector-supplied fixture.
# Primary: vernesong/OpenClash e553e82e01c697aefbe1555261a503f425e00ccd,
# luci-app-openclash/root/etc/init.d/openclash, function plus final newline.
ROUTER_FIXTURE = ROOT / 'tests/fixtures/openclash-router-output-e553e82.txt'
ROUTER_FIXTURE_SHA256 = '341697912c521a8b3d975ef29d8bc7f6b978aec577580ed942acca78e8228103'
spec = importlib.util.spec_from_file_location('dns_scope', ROOT / '.github/scripts/inject-openclash-dns-scope.py')
injector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(injector)


def fixture():
    lines = [injector.ANCHOR, '{\n   :\n}\n', 'set_firewall()\n{\n', injector.START]
    for family in ('ipv4', 'ipv6'):
        for chain in ('dstnat', 'openclash_dns_redirect'):
            for acl in ('${ACBLACKDNSFILTER}', 'ip saddr @lan_ac_white_ips', 'ether saddr @lan_ac_white_macs'):
                lines.append(f'   nft add rule inet fw4 {chain} meta nfproto {{{family}}} meta l4proto {{tcp,udp}} th dport 53 {acl} counter redirect to "$dns_port" comment \\"OpenClash DNS Hijack\\"\n')
        lines.append(f"   nft 'insert rule inet fw4 dstnat position 0 meta nfproto {{{family}}} meta l4proto {{tcp,udp}} th dport 53 counter jump openclash_dns_redirect'\n")
        for _ in range(2):
            lines.append(f'   nft insert rule inet fw4 nat_output position 0 meta nfproto {{{family}}} th dport 53 counter redirect to "$dns_port"\n')
    lines.append('}\n')
    return ''.join(lines)


def helper_fixture():
    helper = ROUTER_FIXTURE.read_bytes()
    assert hashlib.sha256(helper).hexdigest() == ROUTER_FIXTURE_SHA256
    old = fixture()
    inbound_only = ''.join(line for line in old.splitlines(keepends=True)
                           if 'rule inet fw4 nat_output ' not in line)
    # Two family calls expand two source templates to four runtime rules.
    body, closing = inbound_only.rsplit('}\n', 1)
    assert closing == ''
    return helper.decode() + '\n' + body + '   add_router_dns_hijack_nft ipv4\n   add_router_dns_hijack_nft ipv6\n}\n'


def verify_router_output_layouts():
    for name, original in [('legacy-four-inline', fixture()), ('reviewed-two-helper-templates', helper_fixture())]:
        before = injector.router_output_contract(original)
        fixed = injector.transform(original)
        assert injector.router_output_contract(fixed) == before, name
        assert injector.transform(fixed) == fixed, name
        subprocess.run(['sh', '-n'], input=fixed, text=True, check=True)
    current = helper_fixture()
    negatives = {
        'helper-unknown-body': current.replace('100.64.0.0/10', '0.0.0.0/0', 1),
        'helper-self-gate': current.replace('[ "$router_self_proxy" != 1 ]', '[ "$router_self_proxy" = 1 ]', 1),
        'helper-mode-gate': current.replace('[ "$enable_redirect_dns" -eq 1 ]', '[ "$enable_redirect_dns" -eq 3 ]', 1),
        'helper-owner-bypass': current.replace('meta skgid != 65534', 'meta skgid != 65533', 1),
        'helper-scope-pollution': current.replace('$dnsproto th dport 53', '$dnsproto "$AX6_DNS_SCOPE" th dport 53', 1),
        'helper-iif-pollution': current.replace('$dnsproto th dport 53', '$dnsproto iifname "br-lan" th dport 53', 1),
        'missing-ipv4-call': current.replace('   add_router_dns_hijack_nft ipv4\n', '', 1),
        'missing-ipv6-call': current.replace('   add_router_dns_hijack_nft ipv6\n', '', 1),
        'duplicate-ipv4-call': current + 'add_router_dns_hijack_nft ipv4\n',
        'unknown-family-call': current + 'add_router_dns_hijack_nft ipv7\n',
        'duplicate-helper': current + ROUTER_FIXTURE.read_text(),
        'unknown-helper-name': current.replace('add_router_dns_hijack_nft', 'add_router_dns_hijack_nft_v2'),
        'extra-output-producer': current + 'nft add rule inet fw4 nat_output th dport 53 redirect to 53\n',
        'legacy-extra-output-producer': fixture() + 'nft add rule inet fw4 nat_output th dport 53 redirect to 53\n',
        'inline-extra-helper-call': current + 'if true; then add_router_dns_hijack_nft ipv4; fi\n',
        'command-substitution-helper-call': current + 'value=$(add_router_dns_hijack_nft ipv4)\n',
        'extra-udp53-output-producer': current + 'nft add rule inet fw4 nat_output udp dport 53 redirect to 53\n',
        'extra-owned5353-output-producer': current + 'nft add rule inet fw4 nat_output th dport 5353 redirect to 53 comment "OpenClash Router DNS Hijack"\n',
    }
    for name, bad in negatives.items():
        try:
            injector.transform(bad)
        except ValueError:
            continue
        raise AssertionError('router OUTPUT negative accepted: ' + name)
    print('PASS legacy/current OUTPUT contracts preserved, idempotent; 18 helper/family/producer/scope negatives rejected')


def verify_router_output_runtime():
    # Only the actual retained helper runs, with nft replaced by a logger.
    # No init/service, firewall, namespace or router operation is executed.
    helper = ROUTER_FIXTURE.read_text()
    assert hashlib.sha256(helper.encode()).hexdigest() == ROUTER_FIXTURE_SHA256
    with tempfile.TemporaryDirectory(prefix='ax6-openclash-router-output-') as folder:
        temp = Path(folder)
        calls, rules = temp / 'calls', temp / 'rules'
        stub = temp / 'nft'
        stub.write_text('''#!/bin/sh
case "$*" in
  '-a list chain inet fw4 nat_output') cat "$ROUTER_RULES" ;;
  *) printf '%s\\n' "$*" >> "$ROUTER_CALLS" ;;
esac
''')
        stub.chmod(0o755)
        rules.write_text('''chain nat_output {
 meta nfproto ipv4 meta l4proto { tcp, udp } th dport 53 redirect to :53 comment "OpenClash Router DNS Hijack" # handle 12
 meta nfproto ipv6 ip6 nexthdr { tcp, udp } th dport 53 redirect to :53 comment "OpenClash Router DNS Hijack" # handle 15
 meta nfproto ipv4 udp dport 53 redirect to :1053 comment "Other Router DNS" # handle 88
}
''')
        env = {**os.environ, 'PATH': str(temp) + ':' + os.environ['PATH'],
               'ROUTER_RULES': str(rules), 'ROUTER_CALLS': str(calls)}
        for mode, port in [(1, 53), (2, 7874)]:
            calls.write_text('')
            shell(helper + '\nrouter_self_proxy=1; enable_redirect_dns=' + str(mode)
                  + '\nDNSPORT=53; dns_port=7874\nadd_router_dns_hijack_nft ipv4\nadd_router_dns_hijack_nft ipv6\n', env)
            emitted = calls.read_text().splitlines()
            insertions = [line for line in emitted if line.startswith('insert rule inet fw4 nat_output ')]
            assert len(insertions) == 4, emitted
            assert sum('meta nfproto {ipv4}' in line for line in insertions) == 2
            assert sum('meta nfproto {ipv6}' in line for line in insertions) == 2
            assert sum('fib daddr type local' in line for line in insertions) == 2
            assert sum('ip daddr 100.64.0.0/10' in line for line in insertions) == 1
            assert sum('ip6 daddr fd7a:115c:a1e0::/48' in line for line in insertions) == 1
            assert all('meta skgid != 65534' in line and f'redirect to {port} ' in line
                       and 'AX6_DNS_SCOPE' not in line and 'iifname' not in line for line in insertions)
            assert [line for line in emitted if line.startswith('delete rule ')] == [
                'delete rule inet fw4 nat_output handle 12', 'delete rule inet fw4 nat_output handle 15']
            assert all('handle 88' not in line for line in emitted)
        for self_proxy, mode in [(0, 1), (0, 2), (1, 0)]:
            calls.write_text('')
            # Bare upstream return in the mode0 branch inherits the false
            # numeric condition's rc1. This fixture records it, not rc0.
            expected_rc = 1 if self_proxy == 1 and mode == 0 else 0
            shell(helper + f'\nrouter_self_proxy={self_proxy}; enable_redirect_dns={mode}\n'
                  + 'DNSPORT=53; dns_port=7874\nadd_router_dns_hijack_nft ipv4\nv4_rc=$?\nadd_router_dns_hijack_nft ipv6\nv6_rc=$?\n'
                  + f'[ "$v4_rc" -eq {expected_rc} ] && [ "$v6_rc" -eq {expected_rc} ]\n', env)
            assert calls.read_text() == '', (self_proxy, mode)
    print('PASS actual router helper IPv4/IPv6 x DNS modes: four runtime rules per mode; owned delete/third-party retain; self-off rc0/mode0 rc1 both no emit (mocks only)')


def shell(code, env):
    result = subprocess.run(['sh', '-c', code], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return result


def verify(text):
    injector.check(text)
    inbound = [line.strip() for line in text.splitlines() if injector.relevant(line)]
    with tempfile.TemporaryDirectory(prefix='ax6-openclash-dns-scope-') as folder:
        temp = Path(folder)
        calls, batch, rules, logs = [temp / name for name in ('calls', 'batch', 'rules', 'logs')]
        mode2_rules = temp / 'mode2-rules'
        stub = temp / 'nft'
        stub.write_text('''#!/bin/sh
case "$*" in
  '-a list chain inet fw4 dstnat')
    [ "${LIST_FAIL:-0}" = 0 ] || exit 1
    cat "$RULES" ;;
  '-a list chain inet fw4 openclash_dns_redirect')
    [ "${MODE2_ABSENT:-0}" = 0 ] || exit 1
    cat "$MODE2_RULES" ;;
  '-f -') cat > "$BATCH"; [ "${DELETE_FAIL:-0}" = 0 ] ;;
  *) printf '%s\n' "$*" >> "$CALLS" ;;
esac
''')
        stub.chmod(0o755)
        helper = temp / 'scope'
        helper.write_text('''#!/bin/sh
[ "${SCOPE_FAIL:-0}" = 0 ] || exit 1
printf '%s\n' "${SCOPE_VALUE:-}"
''')
        helper.chmod(0o755)
        env = {**os.environ, 'PATH': str(temp) + ':' + os.environ['PATH'], 'CALLS':str(calls), 'BATCH':str(batch), 'RULES':str(rules), 'MODE2_RULES':str(mode2_rules), 'LOGS':str(logs), 'DNS_REDIRECT_SCOPE_BIN':str(helper)}
        trusted = 'iifname { "br-lan", "zt-approved" }'
        env['SCOPE_VALUE'] = trusted
        rules.write_text('''chain dstnat {
 meta nfproto ipv4 udp dport 53 counter redirect to :53 comment "OpenClash DNS Hijack" # handle 12
 meta nfproto ipv6 th dport 53 counter jump openclash_dns_redirect # handle 15
 udp dport 53 redirect to :1053 comment "Other DNS" # handle 88
 tcp dport 80 redirect to :8080 comment "OpenClash DNS Hijack" # handle 99
}
''')
        mode2_rules.write_text('''chain openclash_dns_redirect {
 meta nfproto ipv4 udp dport 53 redirect to :7874 comment "OpenClash DNS Hijack" # handle 21
 meta nfproto ipv6 tcp dport 53 redirect to :7874 comment "OpenClash DNS Hijack" # handle 22
 udp dport 53 redirect to :1053 comment "Other DNS" # handle 23
}
''')
        prelude = injector.HELPERS + '\nLOG_WARN() { printf "%s\\n" "$*" >> "$LOGS"; }; LOG_ERROR() { LOG_WARN "$@"; };\n'
        generate = '\nDNSPORT=53; dns_port=7874; ACBLACKDNSFILTER="ip saddr != @lan_ac_black_ips"\n' + '\n'.join(inbound) + '\n:\n'
        shell(prelude + 'ax6_dns_scope_prepare || exit 10\n' + generate, env)
        emitted = calls.read_text().splitlines()
        assert len(emitted) == 14, len(emitted)
        assert all(trusted in command for command in emitted), emitted
        assert sum('jump openclash_dns_redirect' in c for c in emitted) == 2
        assert batch.read_text().splitlines() == ['delete rule inet fw4 dstnat handle 12', 'delete rule inet fw4 dstnat handle 15', 'delete rule inet fw4 openclash_dns_redirect handle 21', 'delete rule inet fw4 openclash_dns_redirect handle 22']
        # The exact statement matrix retains black/white ACL expressions.
        assert sum('ip saddr != @lan_ac_black_ips' in c for c in emitted) == 4
        print('PASS actual 12 redirect / 2 jump statements, trusted set and ACL preservation')
        for value, failure in [('', '0'), (trusted, '1')]:
            calls.write_text('')
            shell(prelude + 'ax6_dns_scope_prepare || exit 10\n' + generate, {**env,'SCOPE_VALUE':value,'SCOPE_FAIL':failure})
            assert calls.read_text() == '', 'empty or failed resolution generated a global rule'
        assert 'skip inbound DNS redirects' in logs.read_text()
        print('PASS empty/failing resolver: no inbound rule, old owned rules removed, warning emitted')
        for flag in ('LIST_FAIL','DELETE_FAIL'):
            shell(prelude + 'if ax6_dns_scope_prepare; then exit 11; fi\n', {**env,flag:'1'})
        shell(prelude + 'ax6_dns_scope_prepare || exit 13\n', {**env,'MODE2_ABSENT':'1'})
        assert batch.read_text().splitlines() == ['delete rule inet fw4 dstnat handle 12', 'delete rule inet fw4 dstnat handle 15']
        mode2_rules.write_text('udp dport 53 redirect to :7874 comment "OpenClash DNS Hijack" # handle BAD\n')
        shell(prelude + 'if ax6_dns_scope_prepare; then exit 14; fi\n', env)
        mode2_rules.write_text('')
        rules.write_text('udp dport 53 redirect to :53 comment "OpenClash DNS Hijack" # handle BAD\n')
        shell(prelude + 'if ax6_dns_scope_prepare; then exit 12; fi\n', env)
        print('PASS inspection/deletion/handle drift abort; third-party/OUTPUT rules untouched')
        # Structural negative controls use actual target statements.
        for bad in (text.replace(injector.SCOPE, '', 1), text.replace(injector.CALL, '', 1), text.replace(injector.GUARD, '', 1),
                    text + 'nft add rule inet fw4 dstnat udp dport 53 redirect to 53 comment "OpenClash DNS Hijack"\n',
                    text.replace('th dport 53 ', 'th dport 5353 ', 1)):
            try:
                injector.check(bad)
            except ValueError:
                continue
            raise AssertionError('scope omission negative control accepted')
        print('PASS scope/call/guard negative controls')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', nargs='?', type=Path, help='Already injected actual init; extracted pieces only')
    args = parser.parse_args()
    verify_router_output_layouts()
    verify_router_output_runtime()
    original = fixture()
    fixed = injector.transform(original)
    assert injector.transform(fixed) == fixed
    original_output = [l for l in original.splitlines() if 'nft ' in l and 'rule inet fw4 nat_output ' in l]
    fixed_output = [l for l in fixed.splitlines() if 'nft ' in l and 'rule inet fw4 nat_output ' in l]
    assert original_output == fixed_output, 'router OUTPUT changed during injection'
    try:
        injector.check(original)
    except ValueError:
        pass
    else:
        raise AssertionError('old unscoped init accepted')
    try:
        injector.transform(original.replace('th dport 53', 'th dport 54', 1))
    except ValueError:
        pass
    else:
        raise AssertionError('upstream anchor drift accepted')
    try:
        injector.transform(original + 'nft add rule inet fw4 new_dns_chain th dport 53 redirect to 53 comment "OpenClash DNS Hijack"\n')
    except ValueError:
        pass
    else:
        raise AssertionError('new unreviewed DNS producer accepted')
    subprocess.run(['sh','-n'], input=fixed, text=True, check=True)
    verify(args.target.read_text() if args.target else fixed)
    print('test-openclash-dns-scope: PASS (offline mocks; not a netfilter or WAN reachability test)')


if __name__ == '__main__':
    main()
