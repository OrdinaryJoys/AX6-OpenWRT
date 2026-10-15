#!/usr/bin/env python3
"""Offline fixtures: actual controller and rebased remote script, never real SSH."""
import argparse
import contextlib
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from ax6_restore import InvalidBackup, ROOTS, archive, check_backup, digest

spec = importlib.util.spec_from_file_location("restore", ROOT / "tools/ax6-openclash-restore.py")
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)
SCENARIOS = []
PRECONDITIONS = []


def tar_bytes(files, extra=None):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz", format=tarfile.USTAR_FORMAT) as stream:
        for name, content in list(files.items()) + list(extra or []):
            info = tarfile.TarInfo(name)
            info.mode = 0o700 if content is None else 0o600
            info.type = tarfile.DIRTYPE if content is None else tarfile.REGTYPE
            info.size = len(content) if content is not None else 0
            stream.addfile(info, io.BytesIO(content) if content is not None else None)
    return result.getvalue()


def backup(directory, enabled=1):
    directory.mkdir()
    files = {ROOTS[0]: ("config openclash 'config'\n option enable '%d'\n" % enabled).encode(),
             "etc/openclash/config/main.yaml": b"synthetic subscription, must remain byte identical\n",
             "etc/openclash/custom/hook.sh": b"#!/bin/sh\n# synthetic reviewed user hook\n",
             "etc/openclash/overwrite/user.yaml": b"synthetic overwrite\n"}
    data = {
        "openclash-runtime.tar.gz": tar_bytes(files),
        "FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked": tar_bytes({"etc/config/network": b"forensic only"}),
        "ssh-authorized-keys.tar.gz": tar_bytes({"etc/dropbear/authorized_keys": b"synthetic key"}),
        "zerotier-identity.tar.gz": tar_bytes({"etc/zerotier/identity.public": b"public", "etc/zerotier/identity.secret": b"secret"}),
        "MANIFEST.txt": b"The forensic snapshot must never be restored whole.\n",
        "DO-NOT-RESTORE-WHOLE-BACKUP.txt": b"Never upload FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked in LuCI.\nNever rename it and never pass it to sysupgrade -r.\n",
        "crontab.txt": b"* * * * * /old/openclash-unsafe-helper\n",
    }
    data.update({"uci-" + name + ".txt": b"synthetic reference\n" for name in ("network", "firewall", "dhcp", "wireless")})
    for name, content in data.items():
        (directory / name).write_bytes(content)
    rehash(directory)
    return files


def rehash(directory):
    (directory / "SHA256SUMS.txt").write_text("".join(digest(path.read_bytes()) + "  ./" + path.name + "\n"
                                                  for path in sorted(directory.iterdir()) if path.name != "SHA256SUMS.txt"))


MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, re, subprocess, sys
root = pathlib.Path(os.environ['FIXTURE_ROOT'])
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'mock': name, args = args[0], args[1:]
fault = os.environ.get('FIXTURE_FAULT', '')
with (root / 'events').open('a') as f: f.write(name + ' ' + ' '.join(args) + '\n')
def seen(): (root / 'fault-seen').touch()
def once(key):
    flag = root / ('injected-' + key)
    if flag.exists(): return False
    flag.touch()
    return True
if name == 'init':
    action = args[0]
    if (fault == action or fault == 'rollback-cron' and action == 'start') and once(action): seen(); sys.exit(1)
    if action == 'stop':
        (root / 'running').unlink(missing_ok=True)
        if fault == 'stop-edit':
            seen()
            (root / 'etc/config/openclash').write_text('foreign stop edit\n')
    if action == 'start':
        (root / 'running').touch()
        cron = root / 'etc/crontabs/root'
        if '#openclash-cron-task' not in cron.read_text():
            with cron.open('a') as f: f.write('0 4 * * * /new/openclash.sh #openclash-cron-task\n')
    sys.exit(0)
if name == 'pidof': sys.exit(0 if (root / 'running').exists() else 1)
if name == 'uci':
    if 'changes' in args:
        if fault == 'pending': seen(); print('openclash.config.enable=1')
        sys.exit(0)
    if 'commit' in args:
        if fault == 'commit' and once('commit'): seen(); sys.exit(1)
        sys.exit(0)
    config = root / 'etc/config/openclash'
    if '-c' in args: config = pathlib.Path(args[args.index('-c') + 1]) / 'openclash'
    match = re.search(r"option enable ['\"]?([01])", config.read_text())
    sys.exit(1) if match is None else None
    print(match[1]); sys.exit(0)
if name in ('dns-health', 'fw-health', 'config-audit'):
    if fault == 'foreign-write' and name == 'fw-health':
        seen(); (root / 'etc/openclash/config/foreign').write_text('external writer'); sys.exit(1)
    if fault == name:
        seen()
        if fault == 'fw-health' and (root / 'foreign').exists():
            (root / 'etc/openclash/config/foreign').write_text('external writer')
        sys.exit(1)
    sys.exit(0)
if name == 'crontab':
    if fault in ('crontab', 'rollback-cron'): seen(); sys.exit(1)
    (root / 'etc/crontabs/root').write_bytes(pathlib.Path(args[0]).read_bytes()); sys.exit(0)
if name == 'df':
    if fault == 'space': seen()
    print('Filesystem 1024-blocks Used Available Capacity Mounted on')
    print('fixture 1000000 10 ' + ('1' if fault == 'space' else '999990') + ' 1% /etc')
    sys.exit(0)
if name == 'nft':
    if fault == 'disabled-residual': seen()
    print(json.dumps({'nftables': ([{'rule': {'chain': 'dstnat', 'expr': [{'jump': {'target': 'openclash'}}]}}] if fault == 'disabled-residual' else [])})); sys.exit(0)
if name == 'ip': print('[]'); sys.exit(0)
if name == 'sleep': sys.exit(0)
if name == 'timeout': os.execvp(args[1], args[1:])
if name == 'mv' and fault == 'move-config' and args[-1] == str(root / 'etc/openclash/config') and '/new/' in args[0] and once('move-config'):
    seen()
    sys.exit(1)
if name == 'mv' and fault == 'move-uci' and args[-1] == str(root / 'etc/config/openclash') and '/new/' in args[0] and once('move-uci'):
    seen()
    sys.exit(1)
if name == 'tar' and fault == 'extract' and '-xzf' in args:
    seen()
    sys.exit(2)
if name == 'tar' and fault == 'bad-capture' and any(arg.endswith('/before.tar') for arg in args):
    seen()
    pathlib.Path(args[args.index('-cf') + 1]).write_bytes(b'bad capture'); sys.exit(0)
real = json.loads(os.environ['FIXTURE_REAL'])[name]
os.execv(real[0], real + args)
'''


class LocalRestore(restore.Restore):
    def rpc(self, action, data=b""):
        fixture = self.fixture
        script = self.script.replace('"/rom$path"', '"' + str(fixture) + '/rom${path#' + str(fixture) + '}"')
        script = re.sub(r"(?<![A-Za-z0-9_/$])/(etc|usr|sbin|lib|rom|overlay|proc)(?=/|[\s\";])",
                        lambda match: str(fixture) + match.group(0), script)
        script = script.replace('"/$relative"', '"' + str(fixture) + '/$relative"')
        script = script.replace('-C / ', '-C ' + shlex.quote(str(fixture)) + ' ')
        script = re.sub(r'^PATH=.*$', 'PATH=' + shlex.quote(str(fixture / 'bin')) + ':/usr/bin:/bin', script, flags=re.M)
        # Never allow a missed absolute host path into an executable fixture.
        assert not re.search(r"(?<![A-Za-z0-9_/])/(etc|rom|overlay|proc)(?=/|[\s\";])", script), script
        assert '-C / ' not in script
        env = dict(os.environ, FIXTURE_ROOT=str(fixture), FIXTURE_FAULT=self.fault,
                   FIXTURE_REAL=json.dumps(self.real), TEST_MOCK=str(fixture / 'bin/mock'),
                   COPYFILE_DISABLE='1')
        shell = shlex.split(os.environ.get('AX6_TEST_SHELL', '/bin/sh'))
        if os.environ.get('AX6_TEST_TRACE') == '1': shell.append('-x')
        if self.fault == 'transport' and action == 'commit':
            (fixture / 'fault-seen').touch()
            raise restore.RemoteFailure(action, 255)
        if self.fault == 'concurrent-config' and action == 'commit':
            (fixture / 'fault-seen').touch()
            (fixture / 'etc/config/openclash').write_text("config openclash 'config'\n option enable '0'\n# external writer\n")
        if self.fault == 'boot-change' and action == 'commit':
            (fixture / 'fault-seen').touch()
            (fixture / 'proc/sys/kernel/random/boot_id').write_text('different-boot\n')
        if self.fault == 'interrupt' and action == 'commit':
            (fixture / 'fault-seen').touch()
            raise restore.RestoreInterrupted('synthetic host interrupt, not a real-device signal test')
        completed = subprocess.run(shell + ['-c', script, 'remote-fixture', action] + self.args,
                                   input=data, capture_output=True, env=env, timeout=20)
        (self.output / (action + '.stderr')).write_bytes(completed.stderr)
        (self.output / (action + '.stdout')).write_bytes(completed.stdout)
        if completed.returncode:
            raise restore.RemoteFailure(action, completed.returncode)
        if self.fault == 'transport-after' and action == 'commit':
            (fixture / 'fault-seen').touch()
            raise restore.RemoteFailure(action, 255)
        return completed.stdout


class ArchiveTests(unittest.TestCase):
    def test_valid_and_complete_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'backup'
            backup(directory)
            report, _ = check_backup(directory)
            self.assertEqual(report['status'], 'PASS_STRUCTURAL_ONLY')
            self.assertFalse(report['restoration_authorized'])
            (directory / 'extra').write_text('unindexed')
            with self.assertRaises(InvalidBackup): check_backup(directory)

    def test_negative_archive_matrix(self):
        base = {ROOTS[0]: b'configuration'}
        valid = tar_bytes(base)
        cases = [b'not gzip', valid[:-4], gzip.compress(gzip.decompress(valid) + b'trailing data'),
                 tar_bytes(base, [(ROOTS[0], b'duplicate')]),
                 tar_bytes({'etc/openclash/custom/../escape': b'x'}),
                 tar_bytes({'/etc/config/openclash': b'x'}),
                 tar_bytes({'etc/openclash/core/clash_meta': b'x'}),
                 tar_bytes({'etc/shadow': b'x'}),
                 tar_bytes({'etc/openclash/custom/a': b'x', 'etc/openclash/custom/a/b': b'x', **base})]
        for number, data in enumerate(cases):
            with self.subTest(number=number):
                with self.assertRaises((InvalidBackup, OSError, EOFError, tarfile.TarError)): archive(data)
        for member_type in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            out = io.BytesIO()
            with tarfile.open(fileobj=out, mode='w:gz') as stream:
                info = tarfile.TarInfo(ROOTS[0]); info.type = member_type; info.linkname = '/etc/shadow'
                stream.addfile(info)
            with self.assertRaises(InvalidBackup): archive(out.getvalue())

    def test_approval_is_exact_and_not_a_check_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); backup(root / 'backup')
            report, _ = check_backup(root / 'backup')
            path = root / 'approval'; path.write_text(json.dumps(report))
            with self.assertRaises(InvalidBackup): restore.approved(report, path)

    def test_valid_receipt_and_drift_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); backup(root / 'backup')
            report, _ = check_backup(root / 'backup')
            receipt = dict(report, schema=1, reviewed=True, schema_reviewed=True, enabled=1,
                           target_init_sha256='a' * 64, target_core_sha256='b' * 64)
            path = root / 'receipt'; path.write_text(json.dumps(receipt))
            self.assertEqual(restore.approved(report, path), receipt)
            for field in ('manifest_sha256', 'archive_sha256', 'hook_sha256', 'reviewed', 'schema_reviewed', 'enabled'):
                changed = dict(receipt); changed[field] = None
                path.write_text(json.dumps(changed))
                with self.subTest(field=field):
                    with self.assertRaises(InvalidBackup): restore.approved(report, path)

    def test_identity_role_completeness_is_not_crypto_validation(self):
        with self.assertRaises(InvalidBackup):
            archive(tar_bytes({'etc/dropbear/authorized_keys': b''}), 'ssh')
        with self.assertRaises(InvalidBackup):
            archive(tar_bytes({'etc/zerotier/identity.public': b'public', 'etc/zerotier/identity.secret': b''}), 'zerotier')
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'backup'; backup(directory)
            (directory / 'zerotier-identity.tar.gz').write_bytes(tar_bytes({
                'etc/zerotier/identity.public': b'', 'etc/zerotier/identity.secret': b'synthetic secret'}))
            rehash(directory)
            report, _ = check_backup(directory)
            self.assertTrue(report['zerotier_public_empty'])
            self.assertFalse(report['zerotier_crypto_validated'])

    def test_apply_is_unreleased_even_with_a_valid_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); backup(root / 'backup')
            report, _ = check_backup(root / 'backup')
            receipt = dict(report, schema=1, reviewed=True, schema_reviewed=True, enabled=1,
                           target_init_sha256='a' * 64, target_core_sha256='b' * 64)
            path = root / 'receipt'; path.write_text(json.dumps(receipt))
            (root / 'bin').mkdir()
            ssh = root / 'bin/ssh'; ssh.write_text('#!/bin/sh\necho UNEXPECTED_SSH >&2\nexit 99\n'); ssh.chmod(0o700)
            env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'])
            result = subprocess.run(['sh', str(ROOT / 'deploy-openclash-runtime.sh'), '--apply', str(root / 'backup'),
                                     '--approval', str(path), '--output', str(root / 'output')],
                                    capture_output=True, env=env, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b'apply is not released', result.stderr)
            self.assertNotIn(b'UNEXPECTED_SSH', result.stderr)
            self.assertFalse((root / 'output').exists())

    def test_disabled_snapshot_shape_and_numeric_table(self):
        good = {'nft': {'nftables': []}, **{key: [] for key in ('rule4', 'rule6', 'route4', 'route6')}}
        restore.disabled_clean(good)
        for table in (354, '354', '0x00000162', 'openclash'):
            bad = dict(good, rule4=[{'table': table}])
            with self.subTest(table=table):
                with self.assertRaises(InvalidBackup): restore.disabled_clean(bad)
        with self.assertRaises(InvalidBackup): restore.disabled_clean(dict(good, nft={'nftables': ['malformed']}))

    def test_offline_cli_never_calls_ssh(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); backup(root / 'backup')
            (root / 'bin').mkdir()
            ssh = root / 'bin/ssh'; ssh.write_text('#!/bin/sh\necho UNEXPECTED_SSH >&2\nexit 99\n'); ssh.chmod(0o700)
            env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'])
            for flags in ([], ['--check'], ['--apply']):
                result = subprocess.run(['sh', str(ROOT / 'deploy-openclash-runtime.sh')] + flags + [str(root / 'backup')],
                                        capture_output=True, env=env, timeout=10)
                self.assertNotIn(b'UNEXPECTED_SSH', result.stderr)
                self.assertEqual(result.returncode, 2 if flags == ['--apply'] else 0)


class TransactionTests(unittest.TestCase):
    def fixture(self, temp, fault='', enabled=1, baseline=0):
        base = Path(temp); fixture = base / 'router'; fixture.mkdir()
        for directory in ('etc/config', 'etc/openclash/config', 'etc/openclash/custom', 'etc/openclash/overwrite', 'etc/openclash/core',
                          'etc/crontabs', 'rom/etc/openclash/core', 'lib/upgrade/keep.d', 'proc/sys/kernel/random', 'bin'):
            (fixture / directory).mkdir(parents=True, exist_ok=True)
        (fixture / 'proc/sys/kernel/random/boot_id').write_text('synthetic-boot\n')
        (fixture / 'etc/config/openclash').write_text("config openclash 'config'\n option enable '%d'\n" % baseline)
        if baseline: (fixture / 'running').touch()
        (fixture / 'etc/openclash/config/old.yaml').write_text('old data')
        (fixture / 'etc/crontabs/root').write_text('7 * * * * /unrelated/job\n*/2 * * * * /usr/sbin/ax6-openclash-fw-health\n')
        (fixture / 'rom/etc/openclash/core/clash_meta').write_bytes(b'synthetic core')
        (fixture / 'etc/openclash/core/clash_meta').write_bytes(b'synthetic core')
        (fixture / 'lib/upgrade/keep.d/luci-app-openclash').write_text(''.join(str(fixture) + '/' + name + '/\n' for name in ROOTS[1:]))
        mock = fixture / 'bin/mock'; mock.write_text(MOCK); mock.chmod(0o700)
        for command in ('uci', 'pidof', 'crontab', 'df', 'nft', 'ip', 'sleep', 'timeout', 'mv', 'tar'):
            (fixture / 'bin' / command).symlink_to('mock')
        if os.environ.get('AX6_TEST_BUSYBOX') == '1':
            busybox = shutil.which('busybox')
            self.assertIsNotNone(busybox, 'BusyBox applets were explicitly requested')
            for utility in ('sha256sum', 'cat', 'gzip', 'cmp', 'find', 'du', 'sed', 'dirname', 'mkdir', 'rm', 'cp', 'sh', 'awk'):
                (fixture / 'bin' / utility).symlink_to(busybox)
        else:
            (fixture / 'bin/sha256sum').symlink_to(shutil.which('sha256sum'))
        markers = ('AX6 proxy ingress scope v1 begin', 'AX6 DNS ingress scope v1 begin', 'AX6 R-11 v2',
                   'avoid copying the immutable ROM core', 'ax6-openclash-zerotier-bypass')
        programs = {'etc/init.d/openclash': 'init', 'sbin/ax6-config-audit': 'config-audit',
                    'usr/sbin/ax6-openclash-dns-health': 'dns-health', 'usr/sbin/ax6-openclash-fw-health': 'fw-health',
                    'usr/libexec/ax6-openclash-lan-scope': 'scope', 'usr/libexec/ax6-openclash-fw-check.uc': 'checker'}
        for path, command in programs.items():
            file = fixture / path; file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('#!/bin/sh\n' + ''.join('# ' + marker + '\n' for marker in markers) +
                            'exec "$TEST_MOCK" ' + command + ' "$@"\n')
            file.chmod(0o700)
            rom = fixture / 'rom' / path; rom.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(file, rom)
        backup(base / 'backup', enabled)
        report, payload = check_backup(base / 'backup')
        approval = dict(report, schema=1, reviewed=True, schema_reviewed=True, enabled=enabled,
                        target_init_sha256=digest((fixture / 'etc/init.d/openclash').read_bytes()),
                        target_core_sha256=digest(b'synthetic core'))
        key = base / 'key'; key.write_text('synthetic key')
        prior = os.environ.get('SSH_KEY'); os.environ['SSH_KEY'] = str(key)
        try:
            transaction = LocalRestore(argparse.Namespace(router='192.0.2.1', output=base / 'result'), report, payload, approval)
        finally:
            if prior is None: os.environ.pop('SSH_KEY')
            else: os.environ['SSH_KEY'] = prior
        transaction.fixture = fixture; transaction.fault = fault
        transaction.real = {name: ([shutil.which('busybox'), name] if os.environ.get('AX6_TEST_BUSYBOX') == '1'
                                    else [shutil.which(name)]) for name in ('mv', 'tar')}
        return transaction

    def exercise(self, fault='', enabled=1, baseline=0):
        with tempfile.TemporaryDirectory() as temp:
            transaction = self.fixture(temp, fault, enabled, baseline)
            with contextlib.redirect_stdout(io.StringIO()):
                code = transaction.execute()
            result = json.loads((transaction.output / 'RESULT.json').read_text())
            events = (transaction.fixture / 'events').read_text() if (transaction.fixture / 'events').exists() else ''
            state = (transaction.fixture / 'etc/config/openclash').read_text() if (transaction.fixture / 'etc/config/openclash').exists() else '<missing>'
            self.assertNotIn('cron restart', events)
            self.assertNotIn('/old/openclash-unsafe-helper', events)
            if fault:
                self.assertTrue((transaction.fixture / 'fault-seen').exists(), ('failure never reached injection', fault, events))
                self.assertEqual(code, 2, (fault, result, events))
                self.assertNotEqual(result['status'], 'RESTORED_AND_VERIFIED')
                if fault in ('commit', 'move-uci', 'move-config', 'start', 'dns-health', 'fw-health', 'stop'):
                    self.assertEqual(result.get('rollback'), 'VERIFIED_CURRENT_CONTRACT', (fault, result))
                    self.assertEqual(state, "config openclash 'config'\n option enable '%d'\n" % baseline)
                if fault == 'rollback-cron':
                    self.assertIn('crontab ', events)
                    self.assertEqual(result.get('rollback'), 'NOT_VERIFIED_MANUAL_RECOVERY_REQUIRED')
                if fault == 'config-audit':
                    self.assertEqual(result.get('rollback'), 'NOT_VERIFIED_MANUAL_RECOVERY_REQUIRED')
                if fault in ('transport', 'transport-after', 'interrupt'):
                    self.assertEqual(result['status'], 'REMOTE_STATE_UNKNOWN_MANUAL_REVIEW_REQUIRED')
                    self.assertNotIn('crontab ', events)
                if fault == 'concurrent-config':
                    self.assertIn('# external writer', state)
                    self.assertNotIn('init stop', events)
                if fault == 'boot-change':
                    self.assertNotIn('init stop', events)
                    self.assertEqual(result.get('rollback'), 'NOT_VERIFIED_MANUAL_RECOVERY_REQUIRED')
                if fault == 'foreign-write':
                    self.assertEqual((transaction.fixture / 'etc/openclash/config/foreign').read_text(), 'external writer')
                    self.assertEqual(result.get('rollback'), 'NOT_VERIFIED_MANUAL_RECOVERY_REQUIRED')
            else:
                self.assertEqual(code, 0, (result, [(x.name, x.read_text()) for x in transaction.output.glob('*.stderr')]))
                self.assertEqual(result['status'], 'RESTORED_AND_VERIFIED')
                self.assertFalse((transaction.fixture / 'etc/.ax6-openclash-restore').exists())
                self.assertEqual((transaction.fixture / 'etc/openclash/config/main.yaml').read_bytes(),
                                 b'synthetic subscription, must remain byte identical\n')
                self.assertIn('/unrelated/job', (transaction.fixture / 'etc/crontabs/root').read_text())
            SCENARIOS.append({'fault': fault or 'none', 'enabled': enabled, 'baseline': baseline,
                              'injection_reached': not fault or (transaction.fixture / 'fault-seen').exists(),
                              'status': result['status'], 'rollback': result.get('rollback')})
            return result, state, events

    def test_success_enabled(self): self.exercise()
    def test_success_disabled(self): self.exercise(enabled=0)
    def test_success_from_running(self): self.exercise(baseline=1)
    def test_disable_from_running(self): self.exercise(enabled=0, baseline=1)
    def test_rollback_to_running(self): self.exercise('commit', baseline=1)
    def test_failures(self):
        for fault in ('space', 'extract', 'stop', 'commit', 'move-uci', 'move-config', 'start',
                      'dns-health', 'fw-health', 'config-audit', 'transport', 'transport-after', 'pending', 'stop-edit',
                      'rollback-cron', 'concurrent-config', 'bad-capture', 'boot-change', 'foreign-write', 'interrupt'):
            with self.subTest(fault=fault): self.exercise(fault)
    def test_disabled_residual_is_not_a_success(self): self.exercise('disabled-residual', enabled=0)

    def test_target_preconditions_do_not_reach_stop(self):
        cases = ('missing-init', 'missing-fw-probe', 'auditor-mode', 'core-drift', 'dangling-overlay-core',
                 'regular-overlay-core', 'symlink-custom', 'existing-transaction', 'wrong-keep')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                transaction = self.fixture(temp)
                router = transaction.fixture
                config_before = (router / 'etc/config/openclash').read_bytes()
                if case == 'missing-init': (router / 'etc/init.d/openclash').unlink()
                elif case == 'missing-fw-probe': (router / 'usr/sbin/ax6-openclash-fw-health').unlink()
                elif case == 'auditor-mode': (router / 'sbin/ax6-config-audit').chmod(0o600)
                elif case == 'core-drift': (router / 'etc/openclash/core/clash_meta').write_bytes(b'unreviewed core')
                elif case in ('dangling-overlay-core', 'regular-overlay-core'):
                    overlay = router / 'overlay/upper/etc/openclash/core/clash_meta'
                    overlay.parent.mkdir(parents=True)
                    if case.startswith('dangling'): overlay.symlink_to(router / 'absent-core')
                    else: overlay.write_bytes(b'synthetic core')
                elif case == 'symlink-custom':
                    (router / 'etc/openclash/custom').rmdir()
                    (router / 'etc/openclash/custom').symlink_to(router / 'etc/openclash/core')
                elif case == 'existing-transaction':
                    work = router / 'etc/.ax6-openclash-restore'; work.mkdir()
                    (work / 'token').write_text('another owner')
                elif case == 'wrong-keep': (router / 'lib/upgrade/keep.d/luci-app-openclash').write_text('/etc/openclash/\n')
                with contextlib.redirect_stdout(io.StringIO()): code = transaction.execute()
                events = (router / 'events').read_text() if (router / 'events').exists() else ''
                self.assertEqual(code, 2)
                self.assertNotIn('init stop', events)
                self.assertNotIn('tar -xzf', events)
                self.assertEqual((router / 'etc/config/openclash').read_bytes(), config_before)
                if case == 'existing-transaction': self.assertEqual((work / 'token').read_text(), 'another owner')
                PRECONDITIONS.append({'case': case, 'target_data_unchanged': True, 'reached_stop': False})


if __name__ == '__main__':
    result = unittest.main(exit=False).result
    if os.environ.get('AX6_TEST_REPORT'):
        Path(os.environ['AX6_TEST_REPORT']).write_text(json.dumps({
            'shell': os.environ.get('AX6_TEST_SHELL', '/bin/sh'), 'test_groups': result.testsRun,
            'busybox_applets_requested': os.environ.get('AX6_TEST_BUSYBOX') == '1',
            'failures': len(result.failures), 'errors': len(result.errors),
            'skipped': len(result.skipped), 'scenarios': SCENARIOS, 'preconditions': PRECONDITIONS}, indent=2) + '\n')
    sys.exit(0 if result.wasSuccessful() else 1)
