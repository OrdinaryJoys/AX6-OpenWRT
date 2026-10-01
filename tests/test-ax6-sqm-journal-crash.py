#!/usr/bin/env python3
"""Real journal/SIGKILL boundaries in one new disposable hosted-runner netns.

No production SQM backend. Pending journal records NEVER authorize deletion.
--self-test executes no external commands. Real mode needs explicit opt-in.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

GATE = 'PRODUCTION_BLOCKED_NO_OWNERSHIP_BACKEND'
NAME = re.compile(r'ax6sj-[0-9a-f]{24}')
DEVICES = {'create': ('sjca0', 'sjpa0'), 'delete': ('sjcb0', 'sjpb0'),
           'normal': ('sjcn0', 'sjpn0')}
MAX_CHECKPOINT = 1024 * 1024
LIBRARY_PATH = Path(__file__).resolve().parents[1] / '.github/scripts/ax6-sqm-durable-journal.py'


class Failed(RuntimeError):
    pass


class Blocked(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Failed(message)


def identity(path):
    value = os.stat(path)
    return [value.st_dev, value.st_ino]


def process_identity(pid):
    value = Path('/proc/' + str(pid) + '/stat').read_text()
    # comm may contain spaces or parentheses; the final ')' ends field 2.
    fields = value.rsplit(')', 1)[1].split()
    require(int(value.split('(', 1)[0].strip()) == pid and len(fields) > 19,
            'unexpected process stat identity')
    return {'pid': pid, 'start_ticks': int(fields[19]), 'process_group': os.getpgid(pid)}


def sync_directory(path, trace):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
        trace.append({'event': 'fsync_directory', 'target': str(path)})
    finally:
        os.close(fd)


def interrupted(number, frame):
    raise Failed('interrupted by signal ' + str(number))


def environment_allowed():
    return (sys.platform == 'linux' and os.geteuid() == 0
            and os.environ.get('AX6_SQM_JOURNAL_CRASH_TEST') == '1'
            and os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted')


def load_library():
    spec = importlib.util.spec_from_file_location('ax6_sqm_crash_journal', LIBRARY_PATH)
    require(spec is not None and spec.loader is not None, 'journal library missing')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def allowed_commands():
    result = {('ip', '-Version'), ('tc', '-Version')}
    for device, peer in DEVICES.values():
        result.update({
            ('ip', 'link', 'add', 'name', device, 'type', 'veth', 'peer', 'name', peer),
            ('ip', 'link', 'set', 'dev', device, 'up'),
            ('ip', '-j', 'link', 'show', 'dev', device),
            ('tc', '-j', 'qdisc', 'show', 'dev', device),
            ('tc', 'qdisc', 'add', 'dev', device, 'root', 'handle', '1:', 'cake', 'bandwidth', '10mbit'),
            ('tc', 'qdisc', 'del', 'dev', device, 'root', 'handle', '1:'),
        })
    return result


ALLOWED = allowed_commands()


def terminate_owned(child, group=True):
    """Only a Popen created by this process, never an input PID or name search."""
    if child.poll() is None:
        if group:
            os.killpg(child.pid, signal.SIGTERM)
        else:
            child.terminate()
        try:
            return child.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            if group:
                os.killpg(child.pid, signal.SIGKILL)
            else:
                child.kill()
    return child.communicate(timeout=3)


def invoke(argv, transcript, timeout=20, own_group=True):
    row = {'argv': argv, 'started_monotonic': time.monotonic()}
    transcript.append(row)
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=own_group,
                             env=dict(os.environ, LC_ALL='C', PYTHONDONTWRITEBYTECODE='1'))
    try:
        out, err = child.communicate(timeout=timeout)
    except BaseException as error:
        row['interrupted'] = type(error).__name__
        out, err = terminate_owned(child, own_group)
        row.update(rc=child.returncode, stdout=out, stderr=err)
        raise
    row.update(rc=child.returncode, stdout=out, stderr=err)
    return row


def cake(rows):
    require(isinstance(rows, list), 'qdisc JSON must be a list')
    return [{key: row[key] for key in ('kind', 'handle', 'root', 'parent', 'options') if key in row}
            for row in rows if row.get('kind') == 'cake']


def exact_cake(rows):
    value = cake(rows)
    require(len(value) == 1 and value[0].get('root') is True
            and value[0].get('handle') == '1:'
            and value[0].get('options', {}).get('bandwidth') == 1250000,
            'expected exact root CAKE/1:/1250000 bytes per second')
    return value


def checked_private(path, parent=None, expected=None):
    path = Path(path)
    metadata = path.lstat()
    require(path.is_absolute() and not path.is_symlink() and stat.S_ISDIR(metadata.st_mode)
            and stat.S_IMODE(metadata.st_mode) == 0o700 and metadata.st_uid == os.geteuid(),
            'private journal directory identity/permission mismatch')
    if parent is not None:
        require(path.parent == Path(parent), 'journal directory is not the exact private child')
    if expected is not None:
        require(identity(path) == expected, 'private journal directory was replaced')
    return path


def journal_files(directory):
    """Bounded, nonrecursive, no-follow capture of only our private journal files."""
    directory = checked_private(directory)
    paths = sorted(directory.iterdir())
    require(len(paths) <= 10, 'unexpected journal directory contents')
    records = []
    for path in paths:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_size <= 1024 * 1024,
                    'journal evidence file is not a bounded regular file')
            data = os.read(fd, 1024 * 1024 + 1)
            require(len(data) == info.st_size, 'journal evidence short/unstable read')
            records.append({'name': path.name, 'mode': oct(stat.S_IMODE(info.st_mode)),
                            'sha256': hashlib.sha256(data).hexdigest(),
                            'base64': base64.b64encode(data).decode('ascii')})
        finally:
            os.close(fd)
    return records


def checked_recovery(value, phase, classification):
    require(value.get('phase') == phase and value.get('classification') == classification
            and value.get('may_delete') is False and value.get('may_replay') is False
            and value.get('production_gate') == 'BLOCKED_TEST_ONLY_NO_OWNERSHIP',
            'recovery did not preserve fail-closed pending/no-owner policy')
    return value


def publish_checkpoint(report, fd, label):
    require(type(fd) is int and fd > 2, 'checkpoint pipe descriptor absent')
    require(stat.S_ISFIFO(os.fstat(fd).st_mode), 'checkpoint descriptor is not a pipe')
    report.update(checkpoint=label, worker_pid=os.getpid(), status='WAITING_FOR_CONTROLLED_SIGKILL')
    data = json.dumps(report, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    require(len(data) <= MAX_CHECKPOINT, 'checkpoint exceeds bounded protocol size')
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        require(written > 0, 'checkpoint pipe short write')
        offset += written
    os.close(fd)
    # No more journal/kernel operations are reachable after publication.
    while True:
        signal.pause()


def worker(args):
    report = {'status': 'FAIL', 'release_gate': GATE, 'commands': [], 'mode': args.worker,
              'namespace_identity': identity('/proc/self/ns/net'), 'fsync_trace': []}
    require(report['namespace_identity'] == args.expected_ns
            and args.expected_ns != args.host_ns
            and identity('/proc/' + str(os.getppid()) + '/ns/net') == args.host_ns,
            'worker must be in exact new namespace with controller parent outside it')
    checked_private(args.private_parent)
    module = load_library()
    paths = {name: shutil.which(name) for name in ('ip', 'tc')}
    require(all(paths.values()), 'ip/tc missing in worker')
    scenario = args.worker.split('-')[0]
    require(scenario in DEVICES, 'unknown scenario')
    device, peer = DEVICES[scenario]

    def cmd(tool, *tail, capability=False):
        require((tool, *tail) in ALLOWED, 'command outside closed synthetic-device allowlist')
        require(not any(other in tail for pair in DEVICES.values() for other in pair
                        if other not in (device, peer)), 'different scenario device denied')
        if args.worker.endswith('-recover'):
            read_only = tail[:1] == ('-Version',) or tail[:1] == ('-j',)
            foreign_add = (args.worker == 'delete-recover' and
                           tail == ('qdisc', 'add', 'dev', device, 'root', 'handle', '1:',
                                    'cake', 'bandwidth', '10mbit'))
            require(read_only or foreign_add, 'recovery role forbids cleanup or unplanned mutation')
        require(identity('/proc/self/ns/net') == args.expected_ns, 'worker namespace drift')
        row = invoke([paths[tool], *tail], report['commands'], own_group=False)
        if row['rc']:
            error = 'command failed: ' + ' '.join((tool, *tail))
            if capability:
                raise Blocked(error)
            raise Failed(error)
        return row['stdout']

    def qdiscs():
        return json.loads(cmd('tc', '-j', 'qdisc', 'show', 'dev', device))

    def link_identity():
        rows = json.loads(cmd('ip', '-j', 'link', 'show', 'dev', device))
        require(isinstance(rows, list) and len(rows) == 1 and rows[0].get('ifname') == device
                and type(rows[0].get('ifindex')) is int, 'unexpected synthetic link readback')
        return {'namespace': args.expected_ns, 'ifindex': rows[0]['ifindex'], 'device': device}

    def add_cake():
        cmd('tc', 'qdisc', 'add', 'dev', device, 'root', 'handle', '1:', 'cake',
            'bandwidth', '10mbit', capability=True)
        return exact_cake(qdiscs())

    def capture(journal, directory):
        records, trace = journal.read(), list(journal.trace)
        if not args.worker.endswith('-recover'):
            expected = [record['seq'] for record in records]
            require([event['seq'] for event in trace if event['event'] == 'write_complete'] == expected
                    and [event['seq'] for event in trace if event['event'] == 'fsync_file'] == expected,
                    'every complete journal record must have its successful file fsync trace')
            require(any(event == {'event': 'fsync_directory', 'target': 'journal_directory'} for event in trace)
                    and report['fsync_trace'] == [
                        {'event': 'fsync_directory', 'target': 'new_private_directory'},
                        {'event': 'fsync_directory', 'target': 'parent_directory'}],
                    'journal creation must include child/parent/file-entry directory syncs')
        report.update(journal_directory=str(directory), journal_directory_identity=identity(directory),
                      journal_records=records, journal_trace=trace,
                      journal_files=journal_files(directory))

    try:
        if not Path('/sys/module/ifb').is_dir() or not Path('/sys/module/sch_cake').is_dir():
            raise Blocked('IFB/CAKE must be prepared explicitly before the experiment')
        report['ip_version'] = cmd('ip', '-Version').strip()
        report['tc_version'] = cmd('tc', '-Version').strip()
        if args.worker.endswith('-recover'):
            directory = checked_private(args.journal_dir, args.private_parent, args.journal_identity)
            report['device'] = link_identity()
            if scenario == 'delete':
                require(not cake(qdiscs()), 'delete checkpoint did not leave absent CAKE')
                report['fixture_role'] = 'EXPLICIT_FOREIGN_SAME_TUPLE_RECREATION_NOT_RECOVERY'
                report['foreign_recreation'] = add_cake()
            before = exact_cake(qdiscs())
            with module.Journal.open(directory) as journal:
                phase, classification = (('INTENT_CREATE', 'UNKNOWN_CREATE_OUTCOME') if scenario == 'create'
                                         else ('INTENT_DELETE', 'UNKNOWN_DELETE_OUTCOME'))
                report['recovery'] = checked_recovery(journal.recovery(), phase, classification)
                capture(journal, directory)
            after = exact_cake(qdiscs())
            require(before == after, 'read-only journal recovery changed current object')
            report.update(before_recovery=before, after_recovery=after, current_object_preserved=True,
                          automatic_delete_executed=False, automatic_replay_executed=False,
                          status='PASS_PENDING_RECOVERY_REFUSAL_ONLY')
            return report, 0

        require(args.worker in ('create-crash', 'delete-crash', 'normal'), 'unknown creation mode')
        cmd('ip', 'link', 'add', 'name', device, 'type', 'veth', 'peer', 'name', peer, capability=True)
        cmd('ip', 'link', 'set', 'dev', device, 'up')
        report['device'] = link_identity()
        directory = module.new_private_directory(args.private_parent, trace=report['fsync_trace'])
        checked_private(directory, args.private_parent)
        context = {'kernel': os.uname().release,
                   'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                   'namespace': args.expected_ns, 'ifindex': report['device']['ifindex'],
                   'resource': {'device': device, 'kind': 'cake', 'handle': '1:',
                                'bandwidth_bytes_per_second': 1250000},
                   'scope': 'synthetic-test-fixture-not-owner-token'}
        with module.Journal.create(directory, identity={'instance': 'ci-sqm',
                                   'run_id': args.private_parent.name, 'context': context}) as journal:
            journal.append('INTENT_CREATE', {'test_intent': 'create-CAKE-only'})
            report['created_cake'] = add_cake()
            if scenario == 'create':
                capture(journal, directory)
                publish_checkpoint(report, args.checkpoint_fd, 'CREATE_BEFORE_APPLIED')
            journal.append('APPLIED', {'observed_cake': report['created_cake']})
            journal.append('INTENT_DELETE', {'test_intent': 'delete-own-fixture-not-production-cleanup'})
            cmd('tc', 'qdisc', 'del', 'dev', device, 'root', 'handle', '1:')
            report['after_fixture_delete'] = qdiscs()
            require(not cake(report['after_fixture_delete']), 'test deletion left CAKE present')
            if scenario == 'delete':
                capture(journal, directory)
                publish_checkpoint(report, args.checkpoint_fd, 'DELETE_BEFORE_UNDONE')
            journal.append('UNDONE', {'observed_cake_absent': True})
            report['recovery'] = checked_recovery(journal.recovery(), 'UNDONE', 'OBSERVED_UNDONE_NO_REPLAY')
            capture(journal, directory)
        # Reopen after a graceful close as the normal lifecycle control.
        with module.Journal.open(directory) as reopened:
            report['reopened_recovery'] = checked_recovery(reopened.recovery(), 'UNDONE', 'OBSERVED_UNDONE_NO_REPLAY')
            require(reopened.read() == report['journal_records'], 'normal reopen changed journal records')
        report['status'] = 'PASS_NORMAL_JOURNAL_LIFECYCLE_ONLY'
        return report, 0
    except Blocked as error:
        report.update(status='ENV-BLOCKED', error=str(error))
        return report, 2
    except Exception as error:
        report.update(status='FAIL', error=repr(error))
        return report, 1


def await_checkpoint(child, read_fd, label, namespace, owned_identity, command_record):
    data, deadline = bytearray(), time.monotonic() + 45
    os.set_blocking(read_fd, False)
    with selectors.DefaultSelector() as selector:
        selector.register(read_fd, selectors.EVENT_READ)
        while b'\n' not in data:
            require(time.monotonic() < deadline, 'checkpoint timeout')
            ready = selector.select(timeout=0.1)
            if ready:
                chunk = os.read(read_fd, 65536)
                require(chunk, 'worker closed checkpoint pipe before a complete checkpoint')
                data.extend(chunk)
                require(len(data) <= MAX_CHECKPOINT, 'oversized checkpoint')
            elif child.poll() is not None:
                raise Failed('worker exited before checkpoint')
    require(data.endswith(b'\n') and data.count(b'\n') == 1, 'checkpoint framing mismatch')
    value = json.loads(data)
    require(value.get('checkpoint') == label and value.get('worker_pid') == child.pid
            and value.get('namespace_identity') == namespace
            and value.get('release_gate') == GATE, 'checkpoint identity mismatch')
    command_record['received_checkpoint'] = value
    # On the hosted Linux runner, verify the exact Popen is actually waiting in
    # pause before SIGKILL. A hidden/unavailable wchan is fail-closed, not guessed.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        require(child.poll() is None, 'checkpoint worker exited before controlled kill')
        state = Path('/proc/' + str(child.pid) + '/status').read_text()
        wchan = Path('/proc/' + str(child.pid) + '/wchan').read_text().strip()
        if re.search(r'^State:\s+S\b', state, re.M) and 'pause' in wchan:
            current = process_identity(child.pid)
            require(current == owned_identity and current['process_group'] == child.pid,
                    'checkpoint worker process identity changed')
            require(identity('/proc/' + str(child.pid) + '/ns/net') == namespace,
                    'paused worker namespace changed')
            observed = dict(current, wchan=wchan, namespace_identity=namespace,
                            proc_status=[line for line in state.splitlines()
                                         if line.split(':', 1)[0] in ('State', 'Pid', 'PPid', 'NSpid')])
            return value, observed
        time.sleep(0.01)
    raise Failed('worker checkpoint received but signal.pause was not observable')


def crash_worker(argv, transcript, label, namespace):
    read_fd, write_fd = os.pipe()
    row = {'argv': argv + ['--checkpoint-fd', str(write_fd)], 'expected_sigkill': True,
           'started_monotonic': time.monotonic()}
    transcript.append(row)
    child = None
    try:
        child = subprocess.Popen(row['argv'], pass_fds=(write_fd,), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 start_new_session=True,
                                 env=dict(os.environ, LC_ALL='C', PYTHONDONTWRITEBYTECODE='1'))
        os.close(write_fd)
        write_fd = None
        owned_identity = process_identity(child.pid)
        require(owned_identity['process_group'] == child.pid, 'worker process group is not privately owned')
        row['popen_process_identity'] = owned_identity
        checkpoint, paused = await_checkpoint(child, read_fd, label, namespace, owned_identity, row)
        row.update(checkpoint=label, checkpoint_worker_pid=child.pid, paused_process_evidence=paused,
                   signal_sent='SIGKILL', signal_target='OWN_POPEN_PROCESS_GROUP')
        require(child.poll() is None and process_identity(child.pid) == owned_identity,
                'worker exited or changed identity immediately before signal')
        row['kill_sent_monotonic'] = time.monotonic()
        os.killpg(child.pid, signal.SIGKILL)
        out, err = child.communicate(timeout=5)
        row.update(rc=child.returncode, stdout=out, stderr=err, waited_monotonic=time.monotonic())
        require(child.returncode == -signal.SIGKILL, 'worker did not terminate from expected SIGKILL')
        return checkpoint
    except BaseException as error:
        row['error'] = repr(error)
        if child is not None:
            out, err = terminate_owned(child)
            row.update(rc=child.returncode, stdout=out, stderr=err)
            if child.returncode == 2:
                try:
                    stopped = json.loads(out)
                except (ValueError, TypeError):
                    stopped = {}
                if stopped.get('status') == 'ENV-BLOCKED' and stopped.get('release_gate') == GATE:
                    raise Blocked('checkpoint worker environment blocked: ' + stopped.get('error', 'unknown')) from error
        raise
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


def namespace_eligible(name, created, current, owned):
    return bool(owned and NAME.fullmatch(name) and created is not None and created == current)


def controller():
    report = {'status': 'FAIL', 'release_gate': GATE, 'mode': 'REAL_JOURNAL_SIGKILL_ISOLATED',
              'commands': [], 'cases': [], 'cleanup': 'NOT_CREATED', 'controller_fsync_trace': [],
              'limitations': ['SIGKILL process crash is NOT power-loss durability proof',
                              'fsync success is NOT kernel object ownership or atomic compare-delete',
                              'pending recovery never deletes or replays; production backend absent',
                              'shared kernel/modules are not isolated by a network namespace',
                              'no traffic, AX6 hardware, NSS, performance or concurrent hostile-root test',
                              'namespace cleanup guard is not atomic against malicious host root',
                              'SIGKILL of the controller/host loss can bypass finally; disposable runner only']}
    created, name, created_ns = False, None, None
    rc = 1
    try:
        if not environment_allowed():
            raise Blocked('requires Linux root, GitHub-hosted Actions and AX6_SQM_JOURNAL_CRASH_TEST=1')
        if not all(shutil.which(name) for name in ('ip', 'tc')):
            raise Blocked('iproute2 tools unavailable')
        if not Path('/sys/module/ifb').is_dir() or not Path('/sys/module/sch_cake').is_dir():
            raise Blocked('explicit IFB/CAKE preparation missing; no implicit preparation here')
        base = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
        private = Path(tempfile.mkdtemp(prefix='ax6-sqm-journal-', dir=base))
        checked_private(private)
        sync_directory(private, report['controller_fsync_trace'])
        sync_directory(base, report['controller_fsync_trace'])
        report.update(private_evidence_directory=str(private), private_directory_identity=identity(private),
                      private_directory_cleanup='RETAINED_FOR_DISPOSABLE_RUNNER_TEARDOWN',
                      kernel=os.uname().release,
                      boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                      harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      journal_library_sha256=hashlib.sha256(LIBRARY_PATH.read_bytes()).hexdigest())
        ip = shutil.which('ip')
        host_ns = identity('/proc/self/ns/net')
        report['host_namespace_identity'] = host_ns
        name = 'ax6sj-' + secrets.token_hex(12)
        path = Path('/run/netns') / name
        require(NAME.fullmatch(name) and not os.path.lexists(path), 'unsafe/preexisting namespace name')
        added = invoke([ip, 'netns', 'add', name], report['commands'])
        if added['rc']:
            raise Blocked('cannot create namespace; capabilities or mount restrictions')
        created = True
        require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), 'unexpected namespace path')
        created_ns = identity(path)
        require(created_ns != host_ns, 'created namespace must differ from host')
        report['created_namespace'] = {'name': name, 'identity': created_ns}

        def argv(mode, parent, directory=None, directory_identity=None):
            require(not path.is_symlink() and identity(path) == created_ns, 'namespace name replaced')
            command = [ip, 'netns', 'exec', name, sys.executable, str(Path(__file__).resolve()),
                       '--worker', mode, '--expected-ns', *map(str, created_ns),
                       '--host-ns', *map(str, host_ns), '--private-parent', str(parent)]
            if directory is not None:
                command += ['--journal-dir', str(directory), '--journal-identity', *map(str, directory_identity)]
            return command

        for case, label in (('create', 'CREATE_BEFORE_APPLIED'), ('delete', 'DELETE_BEFORE_UNDONE')):
            parent = private / (case + '-' + secrets.token_hex(8))
            parent.mkdir(mode=0o700)
            sync_directory(parent, report['controller_fsync_trace'])
            sync_directory(private, report['controller_fsync_trace'])
            checkpoint = crash_worker(argv(case + '-crash', parent), report['commands'], label, created_ns)
            case_record = {'name': case, 'checkpoint': checkpoint}
            report['cases'].append(case_record)
            directory = checked_private(checkpoint['journal_directory'], parent,
                                        checkpoint['journal_directory_identity'])
            recovered = invoke(argv(case + '-recover', parent, directory, identity(directory)),
                               report['commands'], timeout=45)
            result = json.loads(recovered['stdout'])
            case_record['recovered'] = result
            if recovered['rc'] == 2 and result.get('status') == 'ENV-BLOCKED':
                raise Blocked('post-crash worker environment blocked: ' + result.get('error', 'unknown'))
            require(recovered['rc'] == 0, 'post-crash recovery worker failed')
            require(result['status'] == 'PASS_PENDING_RECOVERY_REFUSAL_ONLY'
                    and result['release_gate'] == GATE, 'unexpected post-crash recovery report')
            require(checkpoint['journal_records'] == result['journal_records'],
                    'SIGKILL recovery mutated or lost durable records')
            require(checkpoint['created_cake'] == result['before_recovery'],
                    'current/recreated object does not match original same-tuple descriptor')
        parent = private / ('normal-' + secrets.token_hex(8))
        parent.mkdir(mode=0o700)
        sync_directory(parent, report['controller_fsync_trace'])
        sync_directory(private, report['controller_fsync_trace'])
        normal = invoke(argv('normal', parent), report['commands'], timeout=45)
        normal_result = json.loads(normal['stdout'])
        report['cases'].append({'name': 'normal', 'result': normal_result})
        if normal['rc'] == 2 and normal_result.get('status') == 'ENV-BLOCKED':
            raise Blocked('normal worker environment blocked: ' + normal_result.get('error', 'unknown'))
        require(normal['rc'] == 0, 'normal lifecycle control failed')
        require(normal_result['status'] == 'PASS_NORMAL_JOURNAL_LIFECYCLE_ONLY'
                and normal_result['release_gate'] == GATE, 'normal lifecycle status mismatch')
        report['status'], rc = 'PASS_REAL_JOURNAL_SIGKILL_EXPERIMENT_ONLY', 0
    except Blocked as error:
        report.update(status='ENV-BLOCKED', error=str(error))
        rc = 2
    except Exception as error:
        report.update(status='FAIL', error=repr(error))
        rc = 1
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if created:
            try:
                path = Path('/run/netns') / name
                current = None if path.is_symlink() else identity(path)
                require(namespace_eligible(name, created_ns, current, created),
                        'namespace identity drift; refusing deletion')
                deleted = invoke([shutil.which('ip'), 'netns', 'delete', name], report['commands'])
                require(deleted['rc'] == 0 and not os.path.lexists(path), 'exact namespace cleanup failed')
                report['cleanup'] = 'REMOVED_EXACT_CREATED_NAMESPACE'
            except Exception as error:
                report.update(status='FAIL', cleanup='FAILED_OR_REFUSED', cleanup_error=repr(error))
                rc = 1
    return report, rc


def self_test():
    checks = []
    def check(name, value):
        require(value, name)
        checks.append(name)
    check('host interface mutation denied', ('ip', 'link', 'delete', 'dev', 'eth0') not in ALLOWED)
    check('shell denied', ('sh', '-c', 'true') not in ALLOWED)
    check('module commands denied', all(row[0] not in ('modprobe', 'rmmod') for row in ALLOWED))
    check('address and route commands denied', all('route' not in row and 'address' not in row for row in ALLOWED))
    check('only synthetic qdisc deletions allowed', all(row[4] in {x[0] for x in DEVICES.values()}
          for row in ALLOWED if row[:3] == ('tc', 'qdisc', 'del')))
    check('no link deletion exposed to recovery', all(row[:3] != ('ip', 'link', 'delete') for row in ALLOWED))
    own = 'ax6sj-' + 'a' * 24
    check('exact newly-created namespace eligible', namespace_eligible(own, [4, 1], [4, 1], True))
    check('preexisting namespace refused', not namespace_eligible(own, [4, 1], [4, 1], False))
    check('changed namespace refused', not namespace_eligible(own, [4, 1], [4, 2], True))
    check('missing namespace identity refused', not namespace_eligible(own, None, None, True))
    check('path traversal refused', not namespace_eligible('../' + own, [1], [1], True))
    good = [{'kind': 'cake', 'handle': '1:', 'root': True, 'options': {'bandwidth': 1250000}}]
    check('exact CAKE byte-rate verified', exact_cake(good) == good)
    for name, bad in [('wrong rate', [{'kind': 'cake', 'handle': '1:', 'root': True, 'options': {'bandwidth': 10000000}}]),
                      ('missing root', [{'kind': 'cake', 'handle': '1:', 'options': {'bandwidth': 1250000}}]),
                      ('missing CAKE', [])]:
        try:
            exact_cake(bad)
        except Failed:
            checks.append(name + ' rejected')
        else:
            raise Failed(name + ' unexpectedly accepted')
    for phase, kind in [('INTENT_CREATE', 'UNKNOWN_CREATE_OUTCOME'),
                        ('INTENT_DELETE', 'UNKNOWN_DELETE_OUTCOME'), ('UNDONE', 'OBSERVED_UNDONE_NO_REPLAY')]:
        value = {'phase': phase, 'classification': kind, 'may_delete': False, 'may_replay': False,
                 'production_gate': 'BLOCKED_TEST_ONLY_NO_OWNERSHIP'}
        check(phase + ' keeps production blocked', checked_recovery(value, phase, kind) == value)
        try:
            checked_recovery(dict(value, may_delete=True), phase, kind)
        except Failed:
            checks.append(phase + ' cleanup authorization rejected')
        else:
            raise Failed('unsafe recovery authorized')
    return {'status': 'PASS_JOURNAL_CRASH_HARNESS_SELF_TEST_ONLY', 'release_gate': GATE,
            'checks': checks, 'external_commands_executed': False, 'real_kernel_executed': False}, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--report', type=Path, help='new file only; required for real controller')
    parser.add_argument('--worker', choices=('create-crash', 'delete-crash', 'create-recover', 'delete-recover', 'normal'), help=argparse.SUPPRESS)
    parser.add_argument('--expected-ns', nargs=2, type=int, help=argparse.SUPPRESS)
    parser.add_argument('--host-ns', nargs=2, type=int, help=argparse.SUPPRESS)
    parser.add_argument('--private-parent', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--journal-dir', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--journal-identity', nargs=2, type=int, help=argparse.SUPPRESS)
    parser.add_argument('--checkpoint-fd', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    stream = None
    if args.report:
        try:
            fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            stream = os.fdopen(fd, 'w')
        except OSError as error:
            print(json.dumps({'status': 'FAIL', 'release_gate': GATE, 'commands': [], 'report_error': repr(error)}))
            return 1
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        if args.self_test:
            report, rc = self_test()
        elif args.worker:
            if not environment_allowed():
                raise Blocked('worker requires explicit hosted Linux root opt-in')
            require(args.expected_ns and args.host_ns and args.private_parent,
                    'missing worker namespace/private-directory arguments')
            report, rc = worker(args)
        elif not args.report:
            raise Blocked('real controller requires a new --report path before any action')
        else:
            report, rc = controller()
    except Blocked as error:
        report, rc = {'status': 'ENV-BLOCKED', 'release_gate': GATE, 'commands': [], 'error': str(error)}, 2
    except Exception as error:
        report, rc = {'status': 'FAIL', 'release_gate': GATE, 'commands': [], 'error': repr(error)}, 1
    if stream:
        try:
            with stream:
                json.dump(report, stream, indent=2, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            report.update(status='FAIL', report_error=repr(error))
            rc = 1
    print(json.dumps(report, indent=2, allow_nan=False))
    return rc


if __name__ == '__main__':
    sys.exit(main())
