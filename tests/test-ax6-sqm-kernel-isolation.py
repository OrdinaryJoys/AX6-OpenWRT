#!/usr/bin/env python3
"""Real Linux objects in ONE disposable CI netns, never a production backend.

Explicit opt-in required. Missing Linux/capabilities/CAKE is ENV-BLOCKED (exit 2),
not PASS. --self-test checks harness guards only and executes no commands.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time

DEV, PEER, IFB = 'ax6d0', 'ax6p0', 'ax6ifb0'
GATE = 'PRODUCTION_BLOCKED_NO_OWNERSHIP_BACKEND'
NAME = re.compile(r'ax6sqm-[0-9a-f]{24}')


class Blocked(RuntimeError):
    pass


class Failed(RuntimeError):
    pass


def identity(path):
    value = os.stat(path)
    return [value.st_dev, value.st_ino]


def interrupted(number, frame):
    raise Failed('interrupted by signal ' + str(number))


def invoke(argv, transcript, timeout=15, own_group=True):
    """Controller owns a worker group; worker tools inherit it for cleanup."""
    row = {'argv': argv, 'started_monotonic': time.monotonic()}
    transcript.append(row)
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=own_group, env=dict(os.environ, LC_ALL='C'))
    try:
        out, err = child.communicate(timeout=timeout)
        row.update(rc=child.returncode, stdout=out, stderr=err)
        return row
    except BaseException as error:
        row['interrupted'] = type(error).__name__
        if child.poll() is None:
            if own_group:
                os.killpg(child.pid, signal.SIGTERM)
            else:
                child.terminate()
            try:
                out, err = child.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                if own_group:
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
                out, err = child.communicate(timeout=4)
            row.update(rc=child.returncode, stdout=out, stderr=err)
        raise


def allowed_commands():
    """Closed argv set: no shell, host device, route, address or module command."""
    allowed = {('ip', '-Version'), ('tc', '-Version')}
    for device in (DEV, IFB):
        allowed.update({('ip', 'link', 'set', 'dev', device, 'up'),
                        ('ip', '-j', 'link', 'show', 'dev', device),
                        ('tc', '-j', 'qdisc', 'show', 'dev', device),
                        ('tc', 'qdisc', 'add', 'dev', device, 'root', 'handle', '1:', 'cake', 'bandwidth', '10mbit')})
    allowed.update({('ip', 'link', 'add', 'name', DEV, 'type', 'veth', 'peer', 'name', PEER),
                    ('ip', 'link', 'add', 'name', IFB, 'type', 'ifb'),
                    ('ip', 'link', 'delete', 'dev', DEV),
                    ('tc', 'qdisc', 'del', 'dev', DEV, 'root', 'handle', '1:'),
                    ('tc', 'qdisc', 'add', 'dev', DEV, 'handle', 'ffff:', 'ingress'),
                    ('tc', 'qdisc', 'del', 'dev', DEV, 'ingress'),
                    ('tc', '-j', 'filter', 'show', 'dev', DEV, 'parent', 'ffff:')})
    for pref, handle in (('49152', '1'), ('49153', '2')):
        allowed.add(('tc', 'filter', 'add', 'dev', DEV, 'parent', 'ffff:', 'protocol', 'all',
                     'pref', pref, 'handle', handle, 'matchall', 'action', 'mirred',
                     'egress', 'redirect', 'dev', IFB))
    return allowed


ALLOWED = allowed_commands()


def deny_cleanup(expected_identity, observed_identity, expected_objects, observed_objects):
    # Even equal snapshots do not grant delete permission: no real atomic CAS.
    if expected_identity != observed_identity:
        return 'REFUSED_STALE_INTERFACE_IDENTITY'
    if expected_objects != observed_objects:
        return 'REFUSED_CHANGED_RESOURCE_SNAPSHOT'
    return 'REFUSED_NO_ATOMIC_OWNERSHIP_PROOF'


def descriptor(rows):
    return [{k: row[k] for k in ('kind', 'handle', 'parent', 'root', 'options') if k in row}
            for row in rows if row.get('kind') == 'cake']


def validate_cake(rows):
    value = descriptor(rows)
    # iproute2 JSON uses bytes/sec: 10 mbit/s == 1,250,000 bytes/sec.
    if (len(value) != 1 or value[0].get('handle') != '1:'
            or value[0].get('options', {}).get('bandwidth') != 1250000):
        raise Failed('CAKE exact handle/bandwidth JSON readback missing or wrong')
    return value


def validate_filters(rows):
    found = []
    for row in rows:
        options = row.get('options', {})
        if not options:  # tc also emits classifier-header rows without a rule.
            continue
        actions = options.get('actions', [])
        if (row.get('kind') != 'matchall' or row.get('protocol') != 'all'
                or row.get('chain', 0) != 0 or len(actions) != 1
                or any(actions[0].get(k) != v for k, v in
                       {'kind': 'mirred', 'mirred_action': 'redirect', 'direction': 'egress', 'to_dev': IFB}.items())):
            raise Failed('unexpected classifier or mirred target/action readback')
        found.append((row.get('pref'), options.get('handle')))
    if sorted(found) != [(49152, 1), (49153, 2)]:
        raise Failed('exact filter pref/handle pairs not read back')
    return {pref for pref, handle in found}


def eligible_name(name, created_identity, current_identity, created):
    return bool(created and NAME.fullmatch(name) and created_identity is not None
                and created_identity == current_identity)


def worker(expected_ns, host_ns):
    report = {'status': 'FAIL', 'mode': 'REAL_KERNEL_ISOLATED', 'release_gate': GATE,
              'commands': [], 'observations': [], 'namespace_identity': identity('/proc/self/ns/net')}
    if (report['namespace_identity'] != expected_ns or expected_ns == host_ns
            or identity('/proc/' + str(os.getppid()) + '/ns/net') != host_ns):
        report['error'] = 'worker is not inside the exact new namespace'
        return report, 1
    paths = {name: shutil.which(name) for name in ('ip', 'tc')}

    def cmd(tool, *args, capability=False):
        if (tool, *args) not in ALLOWED:
            raise Failed('command outside fixed namespace allowlist')
        if identity('/proc/self/ns/net') != expected_ns:
            raise Failed('worker namespace changed')
        row = invoke([paths[tool], *args], report['commands'], own_group=False)
        if row['rc'] != 0:
            error = 'command returned ' + str(row['rc']) + ': ' + ' '.join((tool, *args))
            if capability:
                raise Blocked(error)
            raise Failed(error)
        return row['stdout']

    def parsed(tool, *args):
        value = json.loads(cmd(tool, *args))
        if not isinstance(value, list):
            raise Failed('expected JSON array from ip/tc')
        return value

    def links(device):
        rows = parsed('ip', '-j', 'link', 'show', 'dev', device)
        if len(rows) != 1 or rows[0].get('ifname') != device or type(rows[0].get('ifindex')) is not int:
            raise Failed('unexpected link readback')
        return {'namespace': expected_ns, 'device': device, 'ifindex': rows[0]['ifindex']}

    def qdiscs(device):
        return parsed('tc', '-j', 'qdisc', 'show', 'dev', device)

    def observe(name, **data):
        report['observations'].append({'name': name, **data})

    try:
        if not Path('/sys/module/ifb').is_dir():
            raise Blocked('IFB must be prepared outside test; implicit load may create host ifb0/ifb1')
        report['ip_version'] = cmd('ip', '-Version').strip()
        report['tc_version'] = cmd('tc', '-Version').strip()
        for device, kind in ((DEV, 'veth'), (IFB, 'ifb')):
            extra = ('peer', 'name', PEER) if device == DEV else ()
            cmd('ip', 'link', 'add', 'name', device, 'type', kind, *extra, capability=True)
            cmd('ip', 'link', 'set', 'dev', device, 'up')
            cmd('tc', 'qdisc', 'add', 'dev', device, 'root', 'handle', '1:', 'cake', 'bandwidth', '10mbit', capability=True)
            value = validate_cake(qdiscs(device))
            observe('real-cake-created', device=links(device), qdisc=value,
                    evidence='command exit=0 plus JSON readback; not raw netlink ACK capture')
        before_identity, before_cake = links(DEV), descriptor(qdiscs(DEV))
        # Deliberate destructive NEGATIVE CONTROL, only on the disposable device.
        cmd('tc', 'qdisc', 'del', 'dev', DEV, 'root', 'handle', '1:')
        cmd('tc', 'qdisc', 'add', 'dev', DEV, 'root', 'handle', '1:', 'cake', 'bandwidth', '10mbit')
        recreated = validate_cake(qdiscs(DEV))
        if before_cake != recreated:
            raise Failed('same-parameter recreation was not snapshot-equivalent')
        reason = deny_cleanup(before_identity, links(DEV), before_cake, recreated)
        if reason != 'REFUSED_NO_ATOMIC_OWNERSHIP_PROOF' or descriptor(qdiscs(DEV)) != recreated:
            raise Failed('equal-snapshot refusal did not preserve replacement')
        observe('same-kind-handle-parameters-recreation', snapshot_equal=True, guard=reason,
                replacement_preserved=True, limitation='recreated object is indistinguishable by this snapshot')
        cmd('tc', 'qdisc', 'del', 'dev', DEV, 'root', 'handle', '1:')
        if descriptor(qdiscs(DEV)):
            raise Failed('unsafe stale-identity deletion negative control not observed')
        observe('unsafe-stale-handle-delete', classification='NEGATIVE_CONTROL', observation_matched=True,
                meaning='old identifier also deletes the recreated same-tuple test object')
        cmd('tc', 'qdisc', 'add', 'dev', DEV, 'handle', 'ffff:', 'ingress', capability=True)
        for pref, handle in (('49152', '1'), ('49153', '2')):
            cmd('tc', 'filter', 'add', 'dev', DEV, 'parent', 'ffff:', 'protocol', 'all',
                'pref', pref, 'handle', handle, 'matchall', 'action', 'mirred', 'egress',
                'redirect', 'dev', IFB, capability=True)
        filters = parsed('tc', '-j', 'filter', 'show', 'dev', DEV, 'parent', 'ffff:')
        prefs = validate_filters(filters)
        # Labels come from this experiment, not an owner field supplied by Linux.
        reason = 'REFUSED_UNRECOGNIZED_FILTER_REFERENCE' if prefs - {49152} else None
        preserved = parsed('tc', '-j', 'filter', 'show', 'dev', DEV, 'parent', 'ffff:')
        if not reason or preserved != filters:
            raise Failed('foreign reference refusal did not preserve filters')
        observe('foreign-filter-refusal', guard=reason, filters=filters, objects_preserved=True,
                limitation='fixture declares ownership; kernel does not expose SQM owner tokens')
        cmd('tc', 'qdisc', 'del', 'dev', DEV, 'ingress')
        if any(x.get('kind') == 'ingress' for x in qdiscs(DEV)):
            raise Failed('coarse ingress deletion negative control not observed')
        observe('unsafe-coarse-ingress-delete', classification='NEGATIVE_CONTROL', observation_matched=True,
                meaning='deleting ingress removes the containing qdisc without protecting foreign fixture filter')
        cmd('ip', 'link', 'delete', 'dev', DEV)
        cmd('ip', 'link', 'add', 'name', DEV, 'type', 'veth', 'peer', 'name', PEER)
        after_identity = links(DEV)
        if after_identity['ifindex'] == before_identity['ifindex']:
            observe('same-name-device-recreation', ifindex_reused=True,
                    guard='REFUSED_NO_ATOMIC_OWNERSHIP_PROOF', limitation='ifindex alone cannot identify incarnation')
        else:
            reason = deny_cleanup(before_identity, after_identity, [], [])
            if reason != 'REFUSED_STALE_INTERFACE_IDENTITY':
                raise Failed('recreated device identity was not refused')
            observe('same-name-device-recreation', before=before_identity, after=after_identity, guard=reason,
                    limitation='observed index change only; forced ifindex reuse is NOT tested')
        report['status'] = 'PASS_ISOLATED_KERNEL_EXPERIMENT_ONLY'
        return report, 0
    except Blocked as error:
        report.update(status='ENV-BLOCKED', error=str(error))
        return report, 2
    except Exception as error:
        report.update(status='FAIL', error=repr(error))
        return report, 1


def controller():
    report = {'status': 'FAIL', 'mode': 'REAL_KERNEL_ISOLATED', 'release_gate': GATE,
              'commands': [], 'created_namespace': None, 'cleanup': 'NOT_CREATED',
              'kernel': os.uname().release if hasattr(os, 'uname') else sys.platform,
              'limitations': ['network namespace does not isolate the shared host kernel',
                             'IFB must already be prepared; CAKE/veth/mirred may use/load shared kernel modules; never unloaded here',
                             'no traffic/performance/NSS hardware/journal-crash test',
                             'namespace deletion precheck is not atomic against malicious concurrent host root',
                             'SIGKILL/host loss may prevent finally cleanup; use disposable hosted runners']}
    name, created_ns, created = None, None, False
    rc = 1
    try:
        if os.environ.get('AX6_SQM_KERNEL_ISOLATED_TEST') != '1':
            raise Blocked('requires AX6_SQM_KERNEL_ISOLATED_TEST=1')
        if sys.platform != 'linux' or os.geteuid() != 0:
            raise Blocked('requires Linux and root in an authorised disposable CI runner')
        if (os.environ.get('GITHUB_ACTIONS') != 'true'
                or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
            raise Blocked('requires a GitHub-hosted Actions runner')
        if not shutil.which('ip') or not shutil.which('tc'):
            raise Blocked('iproute2 ip/tc missing')
        if not Path('/sys/module/ifb').is_dir():
            raise Blocked('requires preloaded/builtin IFB; test must not autoload host-default IFB devices')
        report['ifb_module_present'] = True
        parameter = Path('/sys/module/ifb/parameters/numifbs')
        report['ifb_numifbs_parameter'] = parameter.read_text().strip() if parameter.exists() else 'unavailable'
        ip = shutil.which('ip')
        host_ns = identity('/proc/self/ns/net')
        report['host_namespace_identity'] = host_ns
        report['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        name = 'ax6sqm-' + secrets.token_hex(12)
        path = Path('/run/netns') / name
        if not NAME.fullmatch(name) or os.path.lexists(path):
            raise Failed('unsafe or pre-existing namespace target; nothing deleted')
        report['requested_namespace'] = name
        added = invoke([ip, 'netns', 'add', name], report['commands'])
        if added['rc']:
            raise Blocked('cannot create namespace (CAP_SYS_ADMIN/CAP_NET_ADMIN or mount restrictions)')
        created = True
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            raise Failed('unexpected namespace path type; cleanup identity unavailable')
        candidate_ns = identity(path)
        if candidate_ns == host_ns:
            raise Failed('created namespace equals controller namespace')
        created_ns = candidate_ns
        report['created_namespace'] = {'name': name, 'identity': created_ns}
        # Enter by name once; worker verifies its own namespace before commands.
        args = [ip, 'netns', 'exec', name, sys.executable, str(Path(__file__).resolve()),
                '--worker', *map(str, created_ns + host_ns)]
        done = invoke(args, report['commands'], timeout=180)
        report['worker'] = json.loads(done['stdout'])
        rc = done['rc']
        if rc not in (0, 1, 2) or report['worker'].get('release_gate') != GATE:
            raise Failed('unexpected worker result')
        report['status'] = report['worker']['status']
    except Blocked as error:
        report.update(status='ENV-BLOCKED', error=str(error))
        rc = 2
    except Exception as error:
        report.update(status='FAIL', error=repr(error))
        rc = 1
    finally:
        # A second handled termination must not interrupt bounded cleanup.
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if created:
            try:
                path = Path('/run/netns') / name
                current = None if path.is_symlink() else identity(path)
                if not eligible_name(name, created_ns, current, created):
                    raise Failed('namespace identity drift; refusing delete')
                deleted = invoke([ip, 'netns', 'delete', name], report['commands'])
                if deleted['rc'] or os.path.lexists(path):
                    raise Failed('namespace cleanup did not remove the exact created name')
                report['cleanup'] = 'REMOVED_EXACT_CREATED_NAMESPACE'
            except Exception as error:
                report.update(status='FAIL', cleanup='FAILED_OR_REFUSED', cleanup_error=repr(error))
                rc = 1
    return report, rc


def self_test():
    checks = []
    def check(name, condition):
        if not condition:
            raise Failed(name)
        checks.append(name)
    check('host link forbidden', ('ip', 'link', 'delete', 'dev', 'eth0') not in ALLOWED)
    check('shell forbidden', ('sh', '-c', 'tc qdisc del dev eth0 root') not in ALLOWED)
    check('module unload forbidden', ('rmmod', 'ifb') not in ALLOWED)
    check('route mutation forbidden', ('ip', 'route', 'flush', 'table', 'all') not in ALLOWED)
    check('fixed own command allowed', ('ip', 'link', 'delete', 'dev', DEV) in ALLOWED)
    check('same snapshot never authorizes cleanup', deny_cleanup([1], [1], [], []) == 'REFUSED_NO_ATOMIC_OWNERSHIP_PROOF')
    check('changed snapshot refuses', deny_cleanup([1], [1], [1], [2]) == 'REFUSED_CHANGED_RESOURCE_SNAPSHOT')
    check('stale interface refuses', deny_cleanup([1], [2], [], []) == 'REFUSED_STALE_INTERFACE_IDENTITY')
    own = 'ax6sqm-' + 'a' * 24
    check('exact recorded namespace eligible', eligible_name(own, [1, 2], [1, 2], True))
    check('pre-existing namespace not eligible', not eligible_name(own, [1, 2], [1, 2], False))
    check('namespace replacement not eligible', not eligible_name(own, [1, 2], [1, 3], True))
    check('path traversal not eligible', not eligible_name('../' + own, [1], [1], True))
    check('missing identity not eligible', not eligible_name(own, None, None, True))
    cake = [{'kind': 'cake', 'handle': '1:', 'options': {'bandwidth': 1250000}}]
    check('CAKE JSON byte-rate verified', validate_cake(cake) == cake)
    try:
        validate_cake([{'kind': 'cake', 'handle': '1:', 'options': {'bandwidth': 10000000}}])
        raise Failed('incorrect rate accepted')
    except Failed as error:
        check('bit-rate misinterpretation refused', 'JSON readback' in str(error))
    filters = [{'kind': 'matchall', 'protocol': 'all', 'chain': 0, 'pref': pref,
                'options': {'handle': handle, 'actions': [{'kind': 'mirred', 'mirred_action': 'redirect',
                            'direction': 'egress', 'to_dev': IFB}]}}
               for pref, handle in ((49152, 1), (49153, 2))]
    check('filter exact selectors and IFB target verified', validate_filters(filters) == {49152, 49153})
    filters[1]['options']['actions'][0]['to_dev'] = 'eth0'
    try:
        validate_filters(filters)
        raise Failed('foreign target accepted')
    except Failed as error:
        check('wrong mirred target refused', 'mirred target' in str(error))
    return {'status': 'PASS_HARNESS_SELF_TEST_ONLY', 'release_gate': GATE,
            'checks': checks, 'real_kernel_executed': False}, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--report', type=Path, help='new JSON file only; existing file/symlink is never overwritten')
    parser.add_argument('--worker', nargs=4, type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    report_stream = None
    if args.report:
        try:
            # Reserve before any kernel action; never run if evidence cannot be saved.
            fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            report_stream = os.fdopen(fd, 'w')
        except OSError as error:
            print(json.dumps({'status': 'FAIL', 'release_gate': GATE, 'report_error': repr(error), 'commands': []}))
            return 1
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    if args.self_test:
        report, rc = self_test()
    elif args.worker:
        if os.environ.get('AX6_SQM_KERNEL_ISOLATED_TEST') != '1':
            report, rc = {'status': 'ENV-BLOCKED', 'error': 'worker opt-in absent', 'release_gate': GATE}, 2
        elif sys.platform != 'linux' or os.geteuid() != 0:
            report, rc = {'status': 'ENV-BLOCKED', 'error': 'worker requires isolated Linux root', 'release_gate': GATE}, 2
        elif (os.environ.get('GITHUB_ACTIONS') != 'true'
                or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
            report, rc = {'status': 'ENV-BLOCKED', 'error': 'worker requires GitHub-hosted Actions', 'release_gate': GATE}, 2
        else:
            report, rc = worker(args.worker[:2], args.worker[2:])
    else:
        report, rc = controller()
    if report_stream:
        try:
            with report_stream:
                json.dump(report, report_stream, indent=2)
                report_stream.write('\n')
        except OSError as error:
            report.update(status='FAIL', report_error=repr(error))
            rc = 1
    print(json.dumps(report, indent=2))
    return rc


if __name__ == '__main__':
    sys.exit(main())
