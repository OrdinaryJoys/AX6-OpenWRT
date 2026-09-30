#!/usr/bin/env python3
"""Exercise the real ucode validator and shell watchdog, never a live router."""
import copy
import itertools
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / 'AX6-IPQ/files/usr/libexec/ax6-openclash-fw-check.uc'
WATCH = ROOT / 'AX6-IPQ/files/usr/sbin/ax6-openclash-fw-health'
UCODE = shlex.split(os.environ.get('AX6_TEST_UCODE', 'ucode'))
SHELL = shlex.split(os.environ.get('AX6_TEST_SHELL', 'sh'))
MODES = ('fake-ip', 'redir-host', 'fake-ip-tun', 'redir-host-tun', 'fake-ip-mix', 'redir-host-mix')
IDENTITY = 'iifname "br-lan" meta iif 12'


def match(key, value):
    left = {'meta': {'key': key}} if '.' not in key else {'payload': dict(zip(('protocol', 'field'), key.split('.')))}
    return {'match': {'op': '==', 'left': left, 'right': value}}


def fixture(mode='fake-ip', v6='1', v6mode='3', udp='1', v6udp='0'):
    args = [IDENTITY, mode, v6, v6mode, udp, v6udp]
    tun, mixed = mode.endswith('-tun'), mode.endswith('-mix')
    mark4 = tun or mixed or udp == '1' or mode == 'fake-ip'
    mark6 = v6 == '1' and (v6udp == '1' or v6mode != '1')
    data = {'fw4': {'nftables': []}, 'rule4': [], 'rule6': [], 'route4': [], 'route6': []}
    data['links_before'] = [{'ifname': 'lo', 'ifindex': 1}, {'ifname': 'br-lan', 'ifindex': 12}, {'ifname': 'wan', 'ifindex': 13}]
    data['links_after'] = copy.deepcopy(data['links_before'])
    items = data['fw4']['nftables']
    for name, kind in [('dstnat', 'nat'), ('mangle_prerouting', 'filter')]:
        items.append({'chain': {'family': 'inet', 'table': 'fw4', 'name': name, 'hook': 'prerouting', 'type': kind}})

    def add(target, chain, family, protocol):
        items.append({'chain': {'family': 'inet', 'table': 'fw4', 'name': target}})
        backend = {'redirect': {'port': 7892}} if chain == 'dstnat' else {'mangle': {'key': {'meta': {'key': 'mark'}}, 'value': 354}}
        items.append({'rule': {'family': 'inet', 'table': 'fw4', 'chain': target, 'expr': [backend]}})
        for interface in (('br-lan', 'lo') if chain == 'mangle_prerouting' else ('br-lan',)):
            expr = [match('iifname', interface), match('iif' if interface != 'lo' else 'mark', 12 if interface != 'lo' else 354), match('nfproto', family)]
            if protocol:
                expr.append(match('ip.protocol' if family == 'ipv4' else 'ip6.nexthdr', protocol))
            expr += [{'counter': {'packets': 0, 'bytes': 0}}, {'jump': {'target': target}}]
            items.append({'rule': {'family': 'inet', 'table': 'fw4', 'chain': chain, 'expr': expr}})

    if not tun:
        add('openclash', 'dstnat', 'ipv4', 'tcp')
    if mark4:
        add('openclash_mangle', 'mangle_prerouting', 'ipv4', None if tun or mixed else 'udp')
    if v6 == '1' and v6mode in ('1', '3'):
        add('openclash_v6', 'dstnat', 'ipv6', 'tcp')
    if mark6:
        add('openclash_mangle_v6', 'mangle_prerouting', 'ipv6', None)
    for family, needed, tunnel in ((4, mark4, tun or mixed), (6, mark6, v6mode in ('2', '3'))):
        if needed:
            data[f'rule{family}'] = [{'priority': 1888, 'src': 'all', 'fwmark': '0x162', 'table': '354'}]
            data[f'route{family}'] = [{'dst': 'default', 'dev': 'utun'} if tunnel else {'dst': 'default', 'dev': 'lo', 'type': 'local'}]
            data[f'route{family}'][0]['table'] = 354
    return args, data


def entries(data):
    return [item['rule'] for item in data['fw4']['nftables'] if 'rule' in item and item['rule']['chain'] in ('dstnat', 'mangle_prerouting')]


class Validator(unittest.TestCase):
    def check(self, args, data, status=0):
        raw = data if isinstance(data, str) else json.dumps(data)
        result = subprocess.run([*UCODE, str(CHECK), *args], input=raw, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)

    def test_all_192_mode_combinations(self):
        for combo in itertools.product(MODES, ('0', '1'), ('0', '1', '2', '3'), ('0', '1'), ('0', '1')):
            with self.subTest(combo=combo):
                self.check(*fixture(*combo))

    def test_all_192_numeric_kernel_canonical_combinations(self):
        for combo in itertools.product(MODES, ('0', '1'), ('0', '1', '2', '3'), ('0', '1'), ('0', '1')):
            args, data = fixture(*combo)
            for rule in entries(data):
                implicit = any(e.get('match', {}).get('left', {}).get('payload') for e in rule['expr'])
                if implicit:
                    rule['expr'] = [e for e in rule['expr'] if e.get('match', {}).get('left', {}).get('meta', {}).get('key') != 'nfproto']
                for expr in rule['expr']:
                    m = expr.get('match', {})
                    m['right'] = {'ipv4': 2, 'ipv6': 10, 'tcp': 6, 'udp': 17}.get(m.get('right'), m.get('right'))
            with self.subTest(combo=combo):
                self.check(args, data)

    def test_dns_jump_is_not_proxy(self):
        args, data = fixture()
        data['fw4']['nftables'] = [item for item in data['fw4']['nftables'] if 'rule' not in item or item['rule']['chain'] not in ('dstnat', 'mangle_prerouting')]
        data['fw4']['nftables'].append({'rule': {'family': 'inet', 'table': 'fw4', 'chain': 'dstnat', 'comment': 'jump openclash', 'expr': [{'jump': {'target': 'openclash_dns_redirect'}}]}})
        self.check(args, data, 1)

    def test_all_192_symbolic_index_combinations(self):
        for combo in itertools.product(MODES, ('0', '1'), ('0', '1', '2', '3'), ('0', '1'), ('0', '1')):
            args, data = fixture(*combo)
            for rule in entries(data):
                for expr in rule['expr']:
                    if expr.get('match', {}).get('left') == {'meta': {'key': 'iif'}}:
                        expr['match']['right'] = 'br-lan'
            with self.subTest(combo=combo):
                self.check(args, data)

    def test_interface_identity_negative_controls(self):
        for mutation in ('missing', 'malformed', 'scalar', 'name-duplicate', 'index-duplicate', 'changed', 'lan-mismatch', 'unknown-symbol', 'numeric-name'):
            args, data = fixture()
            first = next(e['match'] for e in entries(data)[0]['expr'] if e.get('match', {}).get('left') == {'meta': {'key': 'iif'}})
            if mutation == 'missing':
                del data['links_before']
            elif mutation == 'malformed':
                data['links_after'] = [{}]
            elif mutation == 'scalar':
                data['links_after'] = [1]
            elif mutation == 'name-duplicate':
                data['links_before'].append({'ifname': 'br-lan', 'ifindex': 90})
            elif mutation == 'index-duplicate':
                data['links_before'].append({'ifname': 'other', 'ifindex': 12})
            elif mutation == 'changed':
                data['links_after'][1]['ifindex'] = 99
            elif mutation == 'lan-mismatch':
                data['links_before'][1]['ifindex'] = data['links_after'][1]['ifindex'] = 99
            elif mutation == 'unknown-symbol':
                first['right'] = 'vanished'
            else:
                data['links_before'].append({'ifname': '12', 'ifindex': 90})
                data['links_after'] = copy.deepcopy(data['links_before'])
                first['right'] = '12'
            with self.subTest(mutation=mutation):
                self.check(args, data, 2)
        args, data = fixture()
        data['links_after'].reverse()
        self.check(args, data)
        first = next(e['match'] for e in entries(data)[0]['expr'] if e.get('match', {}).get('left') == {'meta': {'key': 'iif'}})
        first['right'] = 'wan'
        self.check(args, data, 1)

    def test_entry_mutations(self):
        args, original = fixture()
        for key, value in [('iif', 99), ('iifname', 'ztabcd'), ('nfproto', 'ipv6'), ('ip.protocol', 'udp')]:
            data = copy.deepcopy(original)
            rule = entries(data)[0]
            for expr in rule['expr']:
                if expr.get('match', {}).get('left') == match(key, value)['match']['left']:
                    expr['match']['right'] = value
            self.check(args, data, 1)
        for mutation in ('unscoped', 'duplicate', 'extra', 'goto', 'lo-unmarked', 'lo-wrong-mark', 'wrong-hook', 'no-backend', 'counter-backend'):
            data = copy.deepcopy(original)
            rule = entries(data)[0]
            if mutation == 'unscoped':
                rule['expr'] = [e for e in rule['expr'] if e.get('match', {}).get('left', {}).get('meta', {}).get('key') not in ('iif', 'iifname')]
            elif mutation in ('duplicate', 'extra'):
                extra = copy.deepcopy(rule)
                if mutation == 'extra':
                    extra['expr'] = [{'jump': {'target': 'openclash'}}]
                data['fw4']['nftables'].append({'rule': extra})
            elif mutation == 'goto':
                rule['expr'][-1] = {'goto': {'target': 'openclash'}}
            elif mutation.startswith('lo-'):
                lo = next(r for r in entries(data) if any(e.get('match', {}).get('right') == 'lo' for e in r['expr']))
                lo['expr'] = [e for e in lo['expr'] if e.get('match', {}).get('left', {}).get('meta', {}).get('key') != 'mark']
                if mutation == 'lo-wrong-mark':
                    lo['expr'].insert(0, match('mark', 355))
            elif mutation == 'wrong-hook':
                data['fw4']['nftables'][0]['chain']['hook'] = 'output'
            else:
                backend = next(item['rule'] for item in data['fw4']['nftables'] if item.get('rule', {}).get('chain') == 'openclash')
                backend['expr'] = [] if mutation == 'no-backend' else [{'counter': {}}, {'return': None}]
            with self.subTest(mutation=mutation):
                self.check(args, data, 1)

    def test_policy_mutations(self):
        for family in (4, 6):
            for mutation in ('absent', 'duplicate', 'table', 'mask', 'source', 'route', 'route-duplicate', 'route-extra'):
                args, data = fixture()
                rules, routes = data[f'rule{family}'], data[f'route{family}']
                if mutation == 'absent':
                    rules.clear()
                elif mutation == 'duplicate':
                    rules.append(copy.deepcopy(rules[0]))
                elif mutation == 'table':
                    rules[0]['table'] = 162
                elif mutation == 'mask':
                    rules[0]['fwmask'] = '0xff'
                elif mutation == 'source':
                    rules[0]['src'] = '192.0.2.0/24'
                elif mutation == 'route':
                    routes[0]['dev'] = 'wan'
                elif mutation == 'route-duplicate':
                    routes.append(copy.deepcopy(routes[0]))
                else:
                    routes.append({'dst': 'default', 'table': 354, 'gateway': '192.0.2.1', 'dev': 'wan'})
                with self.subTest(family=family, mutation=mutation):
                    self.check(args, data, 2 if family == 6 else 1)

    def test_json_and_argument_errors(self):
        args, data = fixture()
        for raw in ('', '{', '{}', '[]', '{"fw4":{"nftables":[]},"rule4":null}'):
            self.check(args, raw, 2)
        for index, value in ((0, 'iifname "wan"; flush ruleset'), (1, 'unknown'), (2, ''), (3, '9'), (4, 'yes'), (5, '')):
            changed = args[:]
            changed[index] = value
            self.check(changed, data, 2)

    def test_nft_singleton_sets_and_ip_full_mask(self):
        args, data = fixture()
        for rule in entries(data):
            for expr in rule['expr']:
                if 'match' in expr:
                    expr['match']['right'] = {'set': [expr['match']['right']]}
        for family in (4, 6):
            data[f'rule{family}'][0]['fwmask'] = '0xffffffff'
            data[f'rule{family}'][0]['table'] = 354
        self.check(args, data)

    def test_upstream_ipv6_tcp_implies_family(self):
        args, data = fixture()
        rule = next(r for r in entries(data) if r['expr'][-1]['jump']['target'] == 'openclash_v6')
        rule['expr'] = [e for e in rule['expr'] if e.get('match', {}).get('left', {}).get('meta', {}).get('key') != 'nfproto']
        self.check(args, data)
        rule['expr'][2]['match']['right'] = 'udp'
        self.check(args, data, 1)

    def test_other_route_tables_and_linkdown(self):
        args, data = fixture()
        data['route4'].append({'dst': 'default', 'table': 'main', 'gateway': '192.0.2.1', 'dev': 'wan'})
        self.check(args, data)
        data['route4'][0]['flags'] = ['linkdown']
        self.check(args, data, 1)


class Watchdog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ax6-fw-health-')
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'], MOCK_ROOT=str(self.root))
        self.env.update({f'AX6_FW_{key}': str(self.bin / value) for key, value in [('UCI', 'uci'), ('NFT', 'nft'), ('IP', 'ip'), ('UCODE', 'ucode'), ('PIDOF', 'pidof')]})
        self.env.update(AX6_FW_INIT=str(self.root / 'init'), AX6_FW_SCOPE=str(self.bin / 'scope'), AX6_FW_CHECK=str(CHECK), AX6_FW_STATE=str(self.root / 'state'), AX6_FW_UPTIME=str(self.root / 'uptime'))
        self.write('uptime', '1000.00 900.00\n')
        self.write('config', 'config openclash\n')
        self.write('scope', IDENTITY + '\n')
        self.write('settings', json.dumps(dict(zip(('enable', 'en_mode', 'ipv6_enable', 'ipv6_mode', 'enable_udp_proxy', 'enable_v6_udp_proxy'), ('1', 'fake-ip', '1', '3', '1', '0')))))
        self.write('snapshot', json.dumps(fixture()[1]))
        self.script('uci', '''import json,os,pathlib,sys
p=pathlib.Path(os.environ['MOCK_ROOT'])
if (p/'uci-fail').exists(): sys.exit(1)
if sys.argv[2]=='export': print((p/'config').read_text()); sys.exit(0)
v=json.loads((p/'settings').read_text()).get(sys.argv[3].split('.')[-1])
if v is None: sys.exit(1)
print(v)
''')
        self.script('nft', '''import json,os,pathlib,sys
p=pathlib.Path(os.environ['MOCK_ROOT'])
if (p/'nft-fail').exists(): sys.exit(1)
print(json.dumps(json.loads((p/'snapshot').read_text())['fw4']))
''')
        self.script('ip', '''import json,os,pathlib,sys
p=pathlib.Path(os.environ['MOCK_ROOT'])
if (p/'ip-fail').exists(): sys.exit(1)
if sys.argv[1:]==['-j','link','show']:
 n=int((p/'link-calls').read_text()) if (p/'link-calls').exists() else 0
 (p/'link-calls').write_text(str(n+1))
 data=json.loads((p/'snapshot').read_text())['links_before']
 if (p/'link-race').exists() and n%2: data[1]['ifindex']=99
 print(json.dumps(data)); sys.exit(0)
assert sys.argv[1]=='-j' and sys.argv[2] in ('-4','-6')
if sys.argv[3]=='route': assert sys.argv[5:] == ['table','all']
print(json.dumps(json.loads((p/'snapshot').read_text())[sys.argv[3]+sys.argv[2][1:]]))
''')
        self.script('scope', '''import os,pathlib,sys
p=pathlib.Path(os.environ['MOCK_ROOT'])
if (p/'scope-fail').exists(): sys.exit(1)
print((p/'scope').read_text(),end='')
''')
        self.script('pidof', '''import os,pathlib,sys
sys.exit(int((pathlib.Path(os.environ['MOCK_ROOT'])/'core-stopped').exists()))
''')
        self.script('sleep', '''import os,pathlib
p=pathlib.Path(os.environ['MOCK_ROOT'])
if (p/'during-sleep').exists(): exec((p/'during-sleep').read_text())
''')
        self.script('logger', 'import sys\n')
        self.script('flock', '''import os,pathlib,sys
sys.exit(int((pathlib.Path(os.environ['MOCK_ROOT'])/'lock-busy').exists()))
''')
        (self.bin / 'ucode').write_text('#!/bin/sh\nexec ' + shlex.join(UCODE) + ' "$@"\n')
        (self.bin / 'ucode').chmod(0o755)
        markers = ['# AX6 proxy ingress scope v1 begin', 'ax6_proxy_apply_firewall() { :; }', '# AX6 DNS ingress scope v1 begin', '# AX6 R-11 v2', '# ax6-openclash-zerotier-bypass', '# avoid copying the immutable ROM core', '# "${AX6_FW_HEALTH_BIN:-/usr/sbin/ax6-openclash-fw-health}" --probe']
        self.write('init', '#!/bin/sh\n' + '\n'.join(markers) + '\nf() {\n' + '      ax6_proxy_apply_firewall || return $?\n' * 4 + '}\n' + '''printf '%s\\n' "$*" >> "$MOCK_ROOT/reloads"
[ ! -f "$MOCK_ROOT/reload-fail" ] || exit 1
[ ! -f "$MOCK_ROOT/repaired" ] || cp "$MOCK_ROOT/repaired" "$MOCK_ROOT/snapshot"
''')
        (self.root / 'init').chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        (self.root / name).write_text(text)

    def script(self, name, text):
        path = self.bin / name
        path.write_text('#!' + os.path.realpath(os.sys.executable) + '\n' + text)
        path.chmod(0o755)

    def run_watch(self, status=0, probe=False):
        result = subprocess.run([*SHELL, str(WATCH), *(['--probe'] if probe else [])], env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return result

    def broken(self):
        args, data = fixture()
        data['fw4']['nftables'].remove(next(item for item in data['fw4']['nftables'] if item.get('rule') in entries(data)))
        self.write('snapshot', json.dumps(data))

    def test_missing_tun_route_is_not_auto_repaired(self):
        args, data = fixture()
        data['route6'].clear()
        self.write('snapshot', json.dumps(data))
        self.run_watch(2)
        self.no_reload()

    def no_reload(self):
        self.assertFalse((self.root / 'reloads').exists())

    def test_healthy_readonly_probe_and_cron(self):
        self.run_watch(probe=True)
        self.run_watch()
        self.no_reload()
        self.assertFalse((self.root / 'state').exists())

    def test_probe_missing_is_readonly(self):
        self.broken()
        self.run_watch(1, probe=True)
        self.no_reload()
        self.assertFalse((self.root / 'state').exists())

    def test_symbolic_snapshot_and_link_race(self):
        args, data = fixture()
        for rule in entries(data):
            for expr in rule['expr']:
                if expr.get('match', {}).get('left') == {'meta': {'key': 'iif'}}:
                    expr['match']['right'] = 'br-lan'
        self.write('snapshot', json.dumps(data))
        self.run_watch(probe=True)
        self.write('link-race', '')
        self.run_watch(2)
        self.no_reload()
        self.assertFalse((self.root / 'state').exists())

    def test_actual_composed_init_contract_when_supplied(self):
        if not os.environ.get('AX6_TEST_INIT'):
            self.skipTest('actual init supplied in the separate upstream-composition CI step')
        self.write('init', Path(os.environ['AX6_TEST_INIT']).read_text())
        self.run_watch(probe=True)
        self.no_reload()

    def test_disabled_or_core_stopped(self):
        for flag in ('disable', 'core-stopped'):
            if flag == 'disable':
                settings = json.loads((self.root / 'settings').read_text())
                settings['enable'] = '0'
                self.write('settings', json.dumps(settings))
            else:
                self.write(flag, '')
            self.run_watch(3, probe=True)
            self.run_watch()
            self.no_reload()

    def test_unverifiable_never_repairs(self):
        for flag in ('uci-fail', 'ip-fail', 'nft-fail', 'scope-fail'):
            self.write(flag, '')
            self.run_watch(2)
            self.no_reload()
            (self.root / flag).unlink()
        self.write('init', '#!/bin/sh\nexit 0\n')
        self.run_watch(2)
        self.no_reload()

    def test_wait_window_state_changes(self):
        for action, status in (("(p/'snapshot').write_text((p/'repaired').read_text())", 0),
                               ("(p/'core-stopped').touch()", 0),
                               ("(p/'scope').write_text('iifname \\\"br-lan\\\" meta iif 13\\n')", 2),
                               ("(p/'config').write_text('changed')", 2),
                               ("(p/'init').write_text('#!/bin/sh\\nexit 0\\n')", 2)):
            with self.subTest(action=action):
                try:
                    self.broken()
                    self.write('repaired', json.dumps(fixture()[1]))
                    self.write('during-sleep', action)
                    self.run_watch(status)
                    self.no_reload()
                finally:
                    self.tearDown()
                    self.setUp()

    def test_repair_and_cooldown(self):
        self.broken()
        self.write('repaired', json.dumps(fixture()[1]))
        self.run_watch()
        self.assertEqual((self.root / 'reloads').read_text(), 'reload manual\n')
        self.assertEqual((self.root / 'state/last-attempt').read_text(), '1000\n')
        self.broken()
        self.run_watch()
        self.assertEqual((self.root / 'reloads').read_text(), 'reload manual\n')
        self.write('uptime', '1301.00 999.00\n')
        self.run_watch()
        self.assertEqual(len((self.root / 'reloads').read_text().splitlines()), 2)

    def test_reload_or_postverification_failure(self):
        for reload_failure in (False, True):
            self.broken()
            if reload_failure:
                self.write('reload-fail', '')
            self.run_watch(1)
            self.assertEqual((self.root / 'reloads').read_text(), 'reload manual\n')
            self.assertTrue((self.root / 'state/last-attempt').exists())
            self.tearDown()
            self.setUp()

    def test_lock_busy_or_corrupt_cooldown(self):
        self.broken()
        self.write('lock-busy', '')
        self.run_watch()
        self.no_reload()
        (self.root / 'lock-busy').unlink()
        self.write('state/last-attempt', 'invalid\n')
        self.run_watch(2)
        self.no_reload()

    def test_real_flock_excludes_second_owner(self):
        flock = shutil.which('flock', path=os.environ['PATH'])
        if not flock:
            self.skipTest('actual flock is validated on the Linux runner')
        import fcntl
        self.broken()
        state = self.root / 'state'
        state.mkdir()
        (self.bin / 'flock').unlink()
        with (state / 'lock').open('w') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_watch()
            self.no_reload()


if __name__ == '__main__':
    unittest.main(verbosity=2)
