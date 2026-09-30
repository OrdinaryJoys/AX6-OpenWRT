#!/usr/bin/env python3
"""Offline tests: execute the actual resolver and injected shell callbacks."""
import argparse
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


proxy = module('proxy', ROOT / '.github/scripts/inject-openclash-proxy-scope.py')
dns_test = module('dns_test', ROOT / 'tests/test-openclash-dns-scope.py')
dns = dns_test.injector
SHELL = shlex.split(os.environ.get('AX6_TEST_SHELL', 'sh'))
ACTUAL = None


def fixture():
    text = dns.transform(dns_test.fixture())
    rules = ''.join(f"   nft 'add rule inet fw4 {chain} {body}'\n" * count
                    for (chain, body), count in proxy.ENTRIES.items())
    return text + 'proxy_entries()\n{\n' + rules + '}\n'


class Contract(unittest.TestCase):
    def test_actual_or_fixture_idempotent(self):
        original = ACTUAL or fixture()
        result = proxy.transform(original)
        self.assertEqual(result, proxy.transform(result))
        proxy.check(result)
        dns.check(result)
        subprocess.run(SHELL + ['-n'], input=result, text=True, check=True)

    def test_non_entry_bytes_unchanged(self):
        original = fixture()
        result = proxy.transform(original).replace(proxy.HELPERS, '').replace(proxy.CALL, '')
        for line in result.splitlines(keepends=True):
            found = proxy.SCOPED.fullmatch(line.rstrip('\n'))
            if found:
                result = result.replace(line, f"{found[1]}nft 'add rule inet fw4 {found[2]} {found[3]}'\n")
        self.assertEqual(original, result)

    def test_entry_drift_rejected(self):
        for change in ('goto openclash', 'jump openclash_new', 'jump openclash'):
            text = fixture() + f"nft 'add rule inet fw4 custom counter {change}'\n"
            if change == 'jump openclash_new':
                # A new owning proxy chain in a base hook must fail closed too.
                text = fixture().replace('jump openclash_v6', 'jump openclash_new')
            with self.subTest(change=change), self.assertRaises(ValueError):
                proxy.transform(text)

    def test_guard_and_order_tampering_rejected(self):
        patched = proxy.transform(fixture())
        for text in (patched.replace(proxy.CALL, ''), patched.replace(' || return 1', '', 1),
                     patched.replace('meta mark "$PROXY_FWMARK"', ''),
                     patched.replace('"$AX6_PROXY_SCOPE" "$expression"', '"$expression"')):
            with self.assertRaises(ValueError):
                proxy.check(text)

    def test_new_base_rule_cannot_bypass_inventory(self):
        for expression in ('counter jump openclash_new', 'meta mark set 0x162',
                           'tcp dport 443 redirect to :7892'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                proxy.transform(fixture() + f"nft 'add rule inet fw4 mangle_prerouting {expression}'\n")


class Resolver(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ax6-proxy-resolver-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.net = self.root / 'net'
        self.net.mkdir()
        self.vlans = self.root / 'vlan'
        self.vlans.mkdir()
        self.library = self.root / 'network.sh'
        self.library.write_text('''network_flush_cache() { :; }
network_get_device() {
 case "$2" in lan) eval "$1=\\\"${LAN_DEVICE:-br-lan}\\\"" ;;
 wan) eval "$1=wan" ;; wan6) return 1 ;; esac
}
network_get_physdev() { network_get_device "$@"; }
''')
        self.uci = self.root / 'uci'
        self.uci.write_text('#!/bin/sh\n[ "$2" = export ] && exit "${UCI_FAIL:-0}"\nexit 1\n')
        self.uci.chmod(0o755)
        self.env = {**os.environ, 'AX6_SCOPE_NET_ROOT': str(self.net),
                    'AX6_SCOPE_VLAN_ROOT': str(self.vlans),
                    'AX6_SCOPE_NETWORK_LIB': str(self.library), 'AX6_SCOPE_UCI': str(self.uci)}
        self.device('br-lan', 12, 'bridge')
        for name, index in (('lan1', 3), ('phy0-ap0', 17)):
            self.device(name, index, 'hardware')
            (self.net / 'br-lan/brif' / name).symlink_to(self.net / name)

    def device(self, name, index=40, kind='unknown'):
        path = self.net / name
        path.mkdir()
        (path / 'ifindex').write_text(str(index))
        (path / 'type').write_text('1')
        if kind == 'hardware':
            (path / 'device').mkdir()
        elif kind == 'bridge':
            (path / 'bridge').mkdir()
            (path / 'brif').mkdir()
        return path

    def run_helper(self, **env):
        return subprocess.run(SHELL + [str(ROOT / 'AX6-IPQ/files/usr/libexec/ax6-openclash-lan-scope')],
                              env={**self.env, **env}, capture_output=True, text=True, timeout=10)

    def denied(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, '')

    def test_lan_bridge(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'iifname "br-lan" meta iif 12\n')

    def test_physical_lan(self):
        result = self.run_helper(LAN_DEVICE='lan1')
        self.assertEqual(result.stdout, 'iifname "lan1" meta iif 3\n')

    def test_vlan_over_lan(self):
        vlan = self.device('lan1.10')
        (self.vlans / 'lan1.10').touch()
        (vlan / 'lower_lan1').symlink_to(self.net / 'lan1')
        self.assertEqual(self.run_helper(LAN_DEVICE='lan1.10').stdout, 'iifname "lan1.10" meta iif 40\n')

    def test_wan_member_denied(self):
        wan = self.device('wan', 2, 'hardware')
        (self.net / 'br-lan/brif/wan').symlink_to(wan)
        self.denied(self.run_helper())

    def test_wan_vlan_denied(self):
        self.device('wan', 2, 'hardware')
        vlan = self.device('wan.10')
        (self.vlans / 'wan.10').touch()
        (vlan / 'lower_wan').symlink_to(self.net / 'wan')
        self.denied(self.run_helper(LAN_DEVICE='wan.10'))

    def test_zerotier_and_renamed_tap_denied(self):
        for name in ('zt123', 'renamed'):
            port = self.device(name)
            (port / 'tun_flags').write_text('0x1002')
            link = self.net / 'br-lan/brif' / name
            link.symlink_to(port)
            self.denied(self.run_helper())
            link.unlink()

    def test_unknown_virtual_member_denied(self):
        port = self.device('not-a-nic')
        (self.net / 'br-lan/brif/virtual').symlink_to(port)
        self.denied(self.run_helper())

    def test_invalid_and_missing_device_denied(self):
        for device in ('missing', 'lo', 'br-*', '../lan1', 'br-lan;echo', 'interface-too-long'):
            with self.subTest(device=device):
                self.denied(self.run_helper(LAN_DEVICE=device))

    def test_invalid_index_denied(self):
        for index in ('0', '1;accept', '12\n13', ''):
            (self.net / 'br-lan/ifindex').write_text(index)
            self.denied(self.run_helper())

    def test_config_failure_denied(self):
        self.denied(self.run_helper(UCI_FAIL='1'))

    def test_interface_recreated_uses_new_identity(self):
        (self.net / 'br-lan/ifindex').write_text('88')
        self.assertEqual(self.run_helper().stdout, 'iifname "br-lan" meta iif 88\n')

    def test_vlan_cycle_bounded(self):
        vlan = self.device('cycle')
        (self.vlans / 'cycle').touch()
        (vlan / 'lower_cycle').symlink_to(vlan)
        self.denied(self.run_helper(LAN_DEVICE='cycle'))

    def test_non_vlan_lower_device_denied(self):
        device = self.device('macvlan')
        (device / 'lower_lan1').symlink_to(self.net / 'lan1')
        self.denied(self.run_helper(LAN_DEVICE='macvlan'))


class Callbacks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ax6-proxy-callback-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = self.root / 'calls'
        self.rules = self.root / 'rules'
        self.batch = self.root / 'batch'
        self.rules.write_text('''chain example {
 meta nfproto ipv4 counter jump openclash # handle 10
 iifname "br-old" counter jump openclash_mangle # handle 11
 counter jump openclash_mangle_v6 # handle 12
 counter jump openclash_v6 comment "owned" # handle 13
 udp dport 53 jump openclash_dns_redirect # handle 14
 counter jump openclash_other # handle 15
 counter accept comment "do not jump openclash" # handle 16
 ct status dnat accept # handle 17
}
''')
        nft = self.root / 'nft'
        nft.write_text('''#!/bin/sh
case "$*" in
 '-a list chain inet fw4 '* ) [ "${LIST_FAIL:-0}" = 0 ] || exit 7; cat "$RULES" ;;
 '-f -') cat > "$BATCH"; exit "${BATCH_FAIL:-0}" ;;
 *) printf '%s\n' "$*" >> "$CALLS"; exit "${ADD_FAIL:-0}" ;;
esac
''')
        nft.chmod(0o755)
        scope = self.root / 'scope'
        scope.write_text('#!/bin/sh\nprintf "%s\\n" "${SCOPE_VALUE:-}"\nexit "${SCOPE_FAIL:-0}"\n')
        scope.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.root) + ':' + os.environ['PATH'],
                    'CALLS': str(self.calls), 'RULES': str(self.rules), 'BATCH': str(self.batch),
                    'AX6_PROXY_SCOPE_BIN': str(scope), 'PROXY_FWMARK': '0x162',
                    'SCOPE_VALUE': 'iifname "br-lan" meta iif 12'}
        text = proxy.transform(ACTUAL or fixture())
        self.helpers = text[text.index(proxy.BEGIN):text.index(proxy.END) + len(proxy.END)]
        self.entries = '\n'.join(line for line in text.splitlines() if proxy.SCOPED.fullmatch(line))

    def run_code(self, code, **env):
        return subprocess.run(SHELL + ['-c', self.helpers + '\nLOG_WARN() { :; }; LOG_ERROR() { :; };\n' + code],
                              env={**self.env, **env}, capture_output=True, text=True, timeout=10)

    def generate(self, **env):
        return self.run_code('generate() {\nax6_proxy_scope_prepare || return 1\n' + self.entries + '\n}\ngenerate', **env)

    def test_lan_and_loopback_entries(self):
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text().splitlines()
        self.assertEqual(len(calls), 10)
        self.assertEqual(sum('iifname "br-lan" meta iif 12' in c for c in calls), 6)
        lo = [c for c in calls if 'iifname lo' in c]
        self.assertEqual(len(lo), 4)
        self.assertTrue(all('mangle_prerouting iifname lo meta mark 0x162' in c for c in lo))
        self.assertTrue(all('output' not in c and 'input' not in c and 'forward' not in c for c in calls))

    def test_cleanup_exact_targets(self):
        self.assertEqual(self.generate().returncode, 0)
        self.assertEqual(self.batch.read_text().splitlines(),
                         [f'delete rule inet fw4 {chain} handle {handle}'
                          for chain in ('dstnat', 'mangle_prerouting') for handle in (10, 11, 12, 13)])

    def test_missing_lan_only_preserves_marked_loopback(self):
        for env in ({'SCOPE_VALUE': ''}, {'SCOPE_FAIL': '3'}):
            self.calls.write_text('')
            self.assertEqual(self.generate(**env).returncode, 0)
            calls = self.calls.read_text().splitlines()
            self.assertEqual(len(calls), 4)
            self.assertTrue(all('iifname lo meta mark 0x162' in c for c in calls))

    def test_reconcile_failure_stops_generation(self):
        for flag in ('LIST_FAIL', 'BATCH_FAIL'):
            self.calls.write_text('')
            self.assertNotEqual(self.generate(**{flag: '9'}).returncode, 0)
            self.assertEqual(self.calls.read_text(), '')

    def test_bad_handle_stops_generation(self):
        self.rules.write_text('counter jump openclash # handle invalid\n')
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_add_failure_preserved(self):
        self.assertNotEqual(self.generate(ADD_FAIL='7').returncode, 0)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('init', type=Path, nargs='?')
    args = parser.parse_args()
    if args.init:
        ACTUAL = args.init.read_text()
    unittest.main(argv=['test-openclash-proxy-scope'], verbosity=2)
