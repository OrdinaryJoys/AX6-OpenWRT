#!/usr/bin/env python3
"""Offline startup fault injection; never calls system UCI or network helpers."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'AX6-IPQ/files'
SHELL = shlex.split(os.environ.get('AX6_TEST_SHELL', 'sh'))


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ax6-startup-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        uci = self.bin / 'uci'
        shutil.copyfile(ROOT / 'tests/fixtures/boot-guard-uci.py', uci)
        uci.chmod(0o700)
        logger = self.bin / 'logger'
        logger.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$LOGGER_LOG"\nexit "${LOGGER_RC:-0}"\n')
        logger.chmod(0o700)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        UCI_FIXTURE_STATE=str(self.base / 'uci.json'), LOGGER_LOG=str(self.base / 'log'))
        self.values = {'network.globals': 'globals', 'network.globals.packet_steering': '0',
                       'network.br': 'device', 'network.br.name': 'br-lan',
                       'firewall.cfgdefaults': 'defaults', 'firewall.cfgdefaults.flow_offloading': '0',
                       'firewall.cfgdefaults.flow_offloading_hw': '0', 'ecm.general': 'ecm',
                       'ecm.general.disable_offloads': '1', 'ecm.general.disable_gro_list': '1',
                       'ecm.general.offload_host_ifaces': 'br-lan', 'ecm.general.offload_physical_policy': 'report'}

    def guard(self, values=None, repeat=False, **extra):
        state = dict(values=self.values if values is None else values, pending={}, calls=[])
        state.update(extra)
        path = self.base / 'uci.json'
        path.write_text(json.dumps(state))
        body = '. "$1"; start'
        if repeat:
            body += '; first=$?; start; second=$?; [ "$first" = 0 ] && exit "$second"'
        result = subprocess.run([*SHELL, '-c', body, 'sh', str(FILES / 'etc/init.d/ax6-boot-guard')],
                                env=self.env, capture_output=True, text=True, timeout=15)
        return result, json.loads(path.read_text())

    def test_idempotent(self):
        result, state = self.guard(repeat=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse([c for c in state['calls'] if c[0] in ('set', 'delete', 'commit')])

    def test_migrate_and_repeat(self):
        values = dict(self.values)
        del values['ecm.general.offload_host_ifaces']
        del values['ecm.general.offload_physical_policy']
        values['network.globals.packet_steering'] = '1'
        values['network.br.packet_steering'] = '1'
        result, state = self.guard(values, repeat=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('network.br.packet_steering', state['values'])
        self.assertEqual(state['values']['ecm.general.offload_host_ifaces'], 'br-lan')
        self.assertEqual([c for c in state['calls'] if c[0] == 'commit'], [['commit', 'network'], ['commit', 'ecm']])

    def test_failures_preserved_and_independent_packages_continue(self):
        for command, key, code in [('get', 'network.globals.packet_steering', 13),
                                    ('show', 'network', 14), ('changes', 'network', 15),
                                    ('set', 'network.', 17), ('commit', 'network', 23),
                                    ('delete', 'network.br.packet_steering', 19)]:
            with self.subTest(command=command):
                values = dict(self.values, **{'network.globals.packet_steering': '1',
                                             'network.br.packet_steering': '1',
                                             'ecm.general.disable_offloads': '0'})
                result, state = self.guard(values, failure=dict(cmd=command, key=key, rc=code))
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn(['commit', 'ecm'], state['calls'])
                log = (self.base / 'log').read_text()
                self.assertNotIn('network: NSS-owned settings committed and verified', log)

    def test_missing_section_and_pending_edits_left_untouched(self):
        values = {k: v for k, v in self.values.items() if not k.startswith('network.globals')}
        for config in [dict(values=values), dict(pending={'network': ['network.lan.ipaddr=192.0.2.1']})]:
            result, state = self.guard(**config)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse([c for c in state['calls'] if c[0] in ('set', 'delete', 'commit')])

    def test_silent_mutation_and_commit_readback_fail(self):
        values = dict(self.values, **{'network.globals.packet_steering': '1', 'network.br.packet_steering': '1'})
        for config in [dict(ignore_set='network.globals.packet_steering'),
                       dict(ignore_delete='network.br.packet_steering'), dict(corrupt_commit='network')]:
            result, _ = self.guard(values, **config)
            self.assertNotEqual(result.returncode, 0)

    def test_logger_cannot_mask_or_create_config_failure(self):
        self.env['LOGGER_RC'] = '31'
        result, _ = self.guard()
        self.assertEqual(result.returncode, 0)
        result, _ = self.guard(failure=dict(cmd='show', key='network', rc=17))
        self.assertEqual(result.returncode, 17)

    def test_first_failure_survives_later_read_and_other_package_failures(self):
        result, _ = self.guard(failures=[
            dict(cmd='get', key='network.globals.packet_steering', rc=17),
            dict(cmd='show', key='network', nth=3, rc=23),
            dict(cmd='get', key='ecm.general.disable_offloads', rc=29)])
        self.assertEqual(result.returncode, 17, result.stderr)

    def test_wrapper_failures(self):
        source = (FILES / 'etc/init.d/ax6-network-invariants').read_text()
        command = self.base / 'invariants'
        helper = self.base / 'policy.sh'
        mapped = source.replace('/usr/sbin/ax6-network-invariants', str(command)).replace(
            '/lib/netifd/offload/disable_offloads.sh', str(helper))
        service = self.base / 'service'
        service.write_text(mapped)
        for first, policy, expected in [(0, 0, 0), (17, 0, 17), (0, 19, 19), (17, 19, 17),
                                         (0, None, 1), (17, None, 17), (0, 'return 29', 29),
                                         (0, ':', 127), (0, 'if', (1, 2)), (17, 'if', 17)]:
            with self.subTest(first=first, policy=policy):
                command.write_text('#!/bin/sh\nexit ' + str(first) + '\n')
                command.chmod(0o700)
                if helper.exists():
                    helper.unlink()
                if policy is not None:
                    helper.write_text('disable_offload() { return ' + str(policy) + '; }\n'
                                      if isinstance(policy, int) else policy + '\n')
                result = subprocess.run([*SHELL, '-c', '. "$1"; start', 'sh', str(service)],
                                        env=self.env, capture_output=True, timeout=5)
                if isinstance(expected, tuple):
                    # Syntax failure status differs between Darwin sh and ash.
                    self.assertIn(result.returncode, expected, result.stderr)
                else:
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_sysctl_read_write_and_failure(self):
        root = self.base / 'sysctl'
        for interface in ('all', 'lo', 'br-lan'):
            directory = root / interface
            directory.mkdir(parents=True)
            for key in ('send_redirects', 'accept_redirects', 'arp_ignore'):
                (directory / key).write_text('9\n')
        env = dict(self.env, AX6_IPV4_CONF_ROOT=str(root))
        helper = str(FILES / 'usr/sbin/ax6-network-invariants')
        result = subprocess.run([*SHELL, helper, '--all'], env=env, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((root / 'lo/arp_ignore').read_text(), '9\n')
        self.assertEqual((root / 'br-lan/arp_ignore').read_text(), '1\n')
        (root / 'all/send_redirects').unlink()
        result = subprocess.run([*SHELL, helper, '--all'], env=env, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'cannot read', result.stderr)


if __name__ == '__main__':
    unittest.main()
