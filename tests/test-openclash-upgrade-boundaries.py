#!/usr/bin/env python3
"""Reproduce reviewed upgrade hazards, not certify an installer as safe.

Execute real package/job functions with absolute paths projected into a private
temporary directory. Never run opkg, apk, the updater or a real service. The job
tests stub flock to inspect restart ordering, not to prove concurrency safety.
"""
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest
from unittest import mock


SHELL = shlex.split(os.environ.get('AX6_TEST_SHELL', 'sh'))
# Primary 631d7065 (0.47.159) moved backend choice outside the version function.
# These are the exact reviewed installer initializer bytes, not a fabricated
# PKG_TYPE assignment or execution of the updater/installer itself.
PKG_TYPE_INITIALIZER = '''if [ -x "/usr/bin/apk" ]; then
   PKG_TYPE="apk"
else
   PKG_TYPE="opkg"
fi
'''
INSTALLER_ANCHOR = '   cat > /tmp/openclash_update.sh <<"EOF"\n'
# Refuse to execute an unknown future version-function body even inside the
# sandbox. These are exact c3a33c1 (legacy) and e553e82 (current) definitions.
VERSION_FUNCTION_SHA256 = {
    'legacy': 'cb59e869fa56cab7010b196a7dcff54e8a6f3959320e3a0a7cac3d81f1763beb',
    'current': '1af94ccdf7fa503e72cd114abf47b8595dc25799bc0d3b460d8e6b25cae618fc',
}


def function(source, name):
    pattern = rf'^{re.escape(name)}\(\)(?: \{{|\n\{{)\n.*?^\}}\n'
    found = re.findall(pattern, source, re.M | re.S)
    if len(found) != 1:
        raise ValueError(f'Expected one reviewed function: {name}')
    return found[0]


def backend_initializer(source):
    body = function(source, 'check_install_success')
    layout = 'current' if '$PKG_TYPE' in body else 'legacy'
    if hashlib.sha256(body.encode()).hexdigest() != VERSION_FUNCTION_SHA256[layout]:
        raise ValueError('Reviewed version function body changed; fresh review required')
    if '$PKG_TYPE' not in body:
        if (body.count('if [ -x "/bin/opkg" ]; then') != 1 or
                body.count('elif [ -x "/usr/bin/apk" ]; then') != 1):
            raise ValueError('Legacy version backend layout changed')
        return ''
    if body.count('if [ "$PKG_TYPE" = "opkg" ]; then') != 1:
        raise ValueError('Version backend global consumer changed')
    if source.count(INSTALLER_ANCHOR) != 1:
        raise ValueError('Generated installer boundary changed')
    installer, delimiter, _ = source.split(INSTALLER_ANCHOR, 1)[1].partition('\nEOF\n')
    if not delimiter:
        raise ValueError('Generated installer closing delimiter changed')
    before_check = installer.split(body, 1)
    if (len(before_check) != 2 or
            before_check[0].count(PKG_TYPE_INITIALIZER) != 1 or
            installer.count(PKG_TYPE_INITIALIZER) != 1 or
            source.count(PKG_TYPE_INITIALIZER) != 2):
        raise ValueError('Reviewed APK-first installer initializer changed or ambiguous')
    # Return the actual source slice, preserving its complete control flow.
    start = before_check[0].index(PKG_TYPE_INITIALIZER)
    return before_check[0][start:start + len(PKG_TYPE_INITIALIZER)]


class UpgradeBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions = Path(os.environ['AX6_PACKAGE_FUNCTIONS']).read_text()
        cls.ps = Path(os.environ['AX6_OPENCLASH_PS']).read_text()
        cls.pack = Path(os.environ['AX6_PACKAGE_PACK']).read_text()
        cls.updater = Path(os.environ['AX6_OPENCLASH_UPDATE']).read_text()
        # Required real source boundaries; drift must trigger fresh review.
        for name in ('default_prerm', 'default_postinst'):
            function(cls.functions, name)
        function(cls.ps, 'dec_job_counter_and_restart')
        function(cls.updater, 'check_install_success')
        cls.pkg_type_initializer = backend_initializer(cls.updater)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ax6-upgrade-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = self.root / 'events'

    def write(self, path, text, executable=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if executable:
            path.chmod(0o755)

    def project(self, text):
        # Only filesystem prefixes change; control flow remains upstream's.
        return re.sub(r'/(?:bin|etc|usr|lib|tmp|var)/',
                      lambda match: str(self.root) + match[0], text)

    def run_shell(self, text, **variables):
        env = os.environ.copy()
        for name in ('IPKG_INSTROOT', 'PKG_UPGRADE', 'pkgname', 'PKG_TYPE'):
            env.pop(name, None)
        env.update({k: str(v) for k, v in variables.items()})
        env['AX6_TEST_EVENTS'] = str(self.events)
        result = subprocess.run(SHELL + ['-c', text], env=env,
                                text=True, capture_output=True, timeout=10)
        return result, self.events.read_text().splitlines() if self.events.exists() else []

    def package(self, action, upgrade=True, hook=0, init_status=0,
                manager='opkg', staged=False):
        install_root = self.root / 'staged' if staged else Path('/')
        projected_root = Path(str(install_root).rstrip('/') + str(self.root))
        init = self.root / 'etc/init.d/openclash'
        installed_init = projected_root / 'etc/init.d/openclash'
        self.write(installed_init, '#!/bin/sh\n'
                   'echo "official-init:$1" >> "$AX6_TEST_EVENTS"\n'
                   f'exit {init_status}\n', executable=True)
        info = projected_root / 'usr/lib/opkg/info'
        listing = info / 'luci-app-openclash.list'
        if manager == 'apk':
            listing = projected_root / 'lib/apk/packages/luci-app-openclash.list'
        self.write(listing, str(init) + '\n')
        maint = 'postinst' if action == 'default_postinst' else 'prerm'
        if manager == 'opkg':
            self.write(info / f'luci-app-openclash.{maint}-pkg',
                       'echo custom-hook >> "$AX6_TEST_EVENTS"\n'
                       f'exit {hook}\n')
        self.write(projected_root / 'etc/rc.common', '#!/bin/sh\n'
                   'echo "staged-rc:$2" >> "$AX6_TEST_EVENTS"\n')
        text = ('add_group_and_user() { :; }\n'
                + self.project(function(self.functions, action))
                + f'{action}\n')
        if manager == 'apk':
            # package-pack.mk appends postinst-pkg after default_postinst.
            text += 'echo custom-hook >> "$AX6_TEST_EVENTS"\n' + f'exit {hook}\n'
        return self.run_shell(text, pkgname='luci-app-openclash',
                              PKG_UPGRADE='1' if upgrade else '0',
                              IPKG_INSTROOT=str(install_root) if staged else '')

    def test_opkg_upgrade_stops_old_service(self):
        result, events = self.package('default_prerm')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['custom-hook', 'official-init:stop'])

    def test_removal_disables_then_stops(self):
        result, events = self.package('default_prerm', upgrade=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['custom-hook', 'official-init:disable', 'official-init:stop'])

    def test_opkg_upgrade_starts_replaced_init(self):
        result, events = self.package('default_postinst')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['custom-hook', 'official-init:start'])

    def test_install_enables_then_starts(self):
        result, events = self.package('default_postinst', upgrade=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['custom-hook', 'official-init:enable', 'official-init:start'])

    def test_postinst_rejection_does_not_guard_start(self):
        result, events = self.package('default_postinst', hook=23)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(events, ['custom-hook', 'official-init:start'])

    def test_prerm_rejection_does_not_guard_stop(self):
        result, events = self.package('default_prerm', hook=23)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(events, ['custom-hook', 'official-init:stop'])

    def test_start_failure_not_reported_as_package_failure(self):
        result, events = self.package('default_postinst', init_status=17)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['custom-hook', 'official-init:start'])

    def test_apk_shared_default_starts(self):
        result, events = self.package('default_postinst', manager='apk')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['official-init:start', 'custom-hook'])

    def test_apk_postupgrade_rejection_is_after_start(self):
        result, events = self.package('default_postinst', manager='apk', hook=23)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(events, ['official-init:start', 'custom-hook'])

    def test_apk_wrapper_order_matches_locked_make(self):
        begin = '\techo "default_postinst"; \\\n'
        finish = '\t) > $$(ADIR_$(1))/post-install;'
        self.assertEqual(self.pack.count(begin), 1)
        self.assertEqual(self.pack.count(finish), 1)
        wrapper = self.pack.split(begin, 1)[1].split(finish, 1)[0]
        self.assertIn('/postinst-pkg', wrapper)
        self.assertNotIn('return', wrapper)
        self.assertNotIn('exit', wrapper)
        self.assertIn('export PKG_UPGRADE=1', self.pack)
        self.assertIn('/post-install"; \\', self.pack)

    def test_image_staging_enables_without_starting(self):
        result, events = self.package('default_postinst', staged=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ['custom-hook', 'staged-rc:enable'])

    def job(self, counter, flag=0, busy=0):
        jobs = self.root / 'tmp/openclash_jobs'
        (self.root / 'tmp/lock').mkdir(parents=True)
        self.write(jobs, counter + '\n')
        self.write(self.root / 'etc/init.d/openclash', '#!/bin/sh\n'
                   'echo "official-init:$1" >> "$AX6_TEST_EVENTS"\n', executable=True)
        text = ('flock() { :; }\n'
                f'unify_ps_prevent() {{ echo {busy}; }}\n'
                f'JOB_COUNTER_FILE={shlex.quote(str(jobs))}\n'
                + self.project(function(self.ps, 'dec_job_counter_and_restart'))
                + f'dec_job_counter_and_restart {flag}\nwait\n')
        result, events = self.run_shell(text)
        self.assertEqual(result.returncode, 0, result.stderr)
        return jobs, events

    def test_zero_restart_flag_can_consume_preexisting_restart(self):
        jobs, events = self.job('1 1', flag=0)
        self.assertEqual(events, ['official-init:restart'])
        self.assertFalse(jobs.exists())

    def test_no_pending_restart_leaves_service_alone(self):
        jobs, events = self.job('1 0')
        self.assertEqual(events, [])
        self.assertEqual(jobs.read_text(), '0 0\n')

    def test_remaining_job_defers_restart(self):
        jobs, events = self.job('2 1')
        self.assertEqual(events, [])
        self.assertEqual(jobs.read_text(), '1 1\n')

    def test_active_init_defers_restart(self):
        jobs, events = self.job('1 1', busy=1)
        self.assertEqual(events, [])
        self.assertEqual(jobs.read_text(), '0 1\n')

    def version_check(self, installed, status=0, manager='opkg', output=True,
                      both_backends=False, initialize=True, expected_manager=None):
        self.assertIn(manager, ('opkg', 'apk'))
        # Sentinels always shadow any host opkg/apk. Only projected presence
        # probes choose the reviewed source branch; no real manager can run.
        for backend in ('opkg', 'apk'):
            self.write(self.root / 'backend-mocks' / backend, '#!/bin/sh\n'
                       f'echo "backend:{backend}:$*" >> "$AX6_TEST_EVENTS"\nexit 99\n', executable=True)
        managers = ('opkg', 'apk') if both_backends else (manager,)
        for backend in managers:
            path = 'bin/opkg' if backend == 'opkg' else 'usr/bin/apk'
            version = f'Version: {installed}' if backend == 'opkg' else f'luci-app-openclash-{installed}-r1 installed'
            stdout = f'echo "{version}"\n' if output else ''
            self.write(self.root / path, '#!/bin/sh\n'
                       f'echo "backend:{backend}:$*" >> "$AX6_TEST_EVENTS"\n'
                       + stdout + f'exit {status}\n', executable=True)
        (self.root / 'var/lock').mkdir(parents=True)
        initializer = self.pkg_type_initializer if initialize else ''
        text = self.project(initializer + function(self.updater, 'check_install_success'))
        text += 'check_install_success 1.2.3\n'
        env_path = os.pathsep.join([str(self.root / 'bin'), str(self.root / 'usr/bin'),
                                   str(self.root / 'backend-mocks'), os.environ['PATH']])
        result, events = self.run_shell(text, PATH=env_path)
        expected = expected_manager or manager
        argv = 'status luci-app-openclash' if expected == 'opkg' else 'list luci-app-openclash'
        self.assertEqual(events, [f'backend:{expected}:{argv}'])
        return result

    def test_version_check_matches_without_content_or_start_proof(self):
        self.assertEqual(self.version_check('1.2.3').returncode, 0)

    def test_version_check_rejects_other_version(self):
        self.assertEqual(self.version_check('1.2.2').returncode, 1)

    def test_version_pipeline_loses_status_failure(self):
        self.assertEqual(self.version_check('1.2.3', status=42).returncode, 0)

    def test_apk_version_check_matches_without_content_or_start_proof(self):
        self.assertEqual(self.version_check('1.2.3', manager='apk').returncode, 0)

    def test_apk_version_check_rejects_other_version(self):
        self.assertEqual(self.version_check('1.2.2', manager='apk').returncode, 1)

    def test_apk_version_pipeline_loses_status_failure(self):
        self.assertEqual(self.version_check('1.2.3', status=42, manager='apk').returncode, 0)

    def test_opkg_empty_output_rejected(self):
        self.assertEqual(self.version_check('1.2.3', output=False).returncode, 1)

    def test_apk_empty_output_rejected(self):
        self.assertEqual(self.version_check('1.2.3', manager='apk', output=False).returncode, 1)

    def test_opkg_failure_with_empty_output_rejected(self):
        self.assertEqual(self.version_check('1.2.3', status=42, output=False).returncode, 1)

    def test_apk_failure_with_empty_output_rejected(self):
        self.assertEqual(self.version_check('1.2.3', status=42, manager='apk', output=False).returncode, 1)

    def test_ambient_backend_is_isolated(self):
        if not self.pkg_type_initializer:
            self.skipTest('Legacy source has no global initializer; not current-backend coverage')
        with mock.patch.dict(os.environ, {'PKG_TYPE': 'apk'}):
            self.assertEqual(self.version_check('1.2.3', manager='opkg').returncode, 0)

    def test_current_selector_prefers_apk_when_both_present(self):
        if not self.pkg_type_initializer:
            self.skipTest('Legacy source prefers opkg; not current APK-first coverage')
        self.assertEqual(self.version_check('1.2.3', manager='apk', both_backends=True).returncode, 0)

    def test_missing_initializer_reproduces_method_failure(self):
        if not self.pkg_type_initializer:
            self.skipTest('Legacy function performs its own probes')
        # With mock opkg present but omitted required global, the actual
        # current function reaches only the failing private APK sentinel.
        self.assertEqual(self.version_check('1.2.3', initialize=False,
                                          expected_manager='apk').returncode, 1)

    def test_backend_initializer_drift_is_rejected(self):
        if not self.pkg_type_initializer:
            self.skipTest('Legacy source uses the reviewed in-function probe layout')
        negatives = (
            self.updater.replace(PKG_TYPE_INITIALIZER, '', 1),
            self.updater.replace(INSTALLER_ANCHOR, INSTALLER_ANCHOR + PKG_TYPE_INITIALIZER, 1),
            self.updater.replace('if [ -x "/usr/bin/apk" ]; then', 'if [ -x "/usr/bin/apk2" ]; then'),
            self.updater.replace('PKG_TYPE="apk"', 'PKG_TYPE="unknown"'),
            self.updater.replace('if [ "$PKG_TYPE" = "opkg" ]; then', 'if [ "$PKG_TYPE" = "apk" ]; then'),
        )
        for bad in negatives:
            with self.assertRaises(ValueError):
                backend_initializer(bad)

    def test_unlinking_lock_allows_a_second_inode_lock(self):
        path = self.root / 'package.lock'
        with path.open('w') as first:
            fcntl.lockf(first, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Separate process: fcntl locks are per process, not per descriptor.
            code = ('import fcntl,sys\n'
                    'with open(sys.argv[1], "w") as f:\n'
                    ' try: fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
                    ' except BlockingIOError: sys.exit(7)\n')
            before = subprocess.run(['python3', '-c', code, str(path)], timeout=10)
            self.assertEqual(before.returncode, 7)
            path.unlink()
            after = subprocess.run(['python3', '-c', code, str(path)], timeout=10)
            self.assertEqual(after.returncode, 0)
            self.assertNotEqual(os.fstat(first.fileno()).st_ino, path.stat().st_ino)


if __name__ == '__main__':
    print('UPGRADE_SAFETY=BLOCKED: these tests reproduce known hazards; '
          'a green test run is not deployment approval', flush=True)
    unittest.main(verbosity=2)
