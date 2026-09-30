#!/usr/bin/env python3
"""Real private temporary files + injected I/O failures; no kernel/SQM actions.

Tests process-visible file persistence and refusal. They are NOT power-cut or
tc ownership tests. Corrupt fixtures are deliberately written only under this
test's new TemporaryDirectory; the library never truncates or repairs them.
"""
from copy import deepcopy
import errno
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

LIBRARY = Path(__file__).resolve().parents[1] / '.github/scripts/ax6-sqm-durable-journal.py'
spec = importlib.util.spec_from_file_location('ax6_durable_journal', LIBRARY)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
IDENTITY = {'instance': 'sqm-test0', 'run_id': '01234567-89ab-cdef-0123-456789abcdef',
            'context': {'purpose': 'TEST_ONLY', 'unicode': '测试', 'finite': 0.25,
                        'observations': [None, True, 3]}}
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def rejects(name, callback, expected=module.JournalError):
    try:
        callback()
    except expected as error:
        checks.append(name)
        return error
    raise AssertionError(name)


def child_open(directory):
    script = ('import importlib.util,sys\n'
              's=importlib.util.spec_from_file_location("journal",sys.argv[1])\n'
              'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
              'try:\n'
              ' with m.Journal.open(sys.argv[2]) as j: print(j.recovery()["classification"])\n'
              'except m.JournalLocked: raise SystemExit(23)\n')
    return subprocess.run([sys.executable, '-c', script, str(LIBRARY), str(directory)],
                          text=True, capture_output=True, timeout=10, check=False)


with tempfile.TemporaryDirectory(prefix='ax6-durable-journal-tests-') as temporary:
    parent = Path(temporary)

    def new_directory():
        return module.new_private_directory(parent)

    def new_journal():
        directory = new_directory()
        return directory, module.Journal.create(directory, deepcopy(IDENTITY))

    def corrupt_case(name, transform):
        directory, journal = new_journal()
        journal.append('INTENT_CREATE', {'object': 'isolated-test-only'})
        journal.close()
        path = directory / module.FILE_NAME
        path.write_bytes(transform(path.read_bytes()))
        before = path.read_bytes()
        rejects(name, lambda: module.Journal.open(directory))
        check(name + ': no repair/truncate', path.read_bytes() == before)

    def rewrite(data, callback):
        rows = [json.loads(line) for line in data.splitlines()]
        callback(rows)
        # Deliberately rehash where possible: state/schema must independently
        # reject invalid records, not merely rely on stale hash detection.
        previous = module.ZERO_HASH
        for row in rows:
            row['prev_hash'] = previous
            row.pop('hash', None)
            row['hash'] = sha256(json.dumps(row, sort_keys=True, separators=(',', ':'),
                                            ensure_ascii=False).encode()).hexdigest()
            previous = row['hash']
        return b''.join(json.dumps(row, sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False).encode() + b'\n' for row in rows)

    creation_trace = []
    directory = module.new_private_directory(parent, trace=creation_trace)
    check('new private directory mode 0700', directory.stat().st_mode & 0o777 == 0o700)
    check('new private directory caller ownership', directory.stat().st_uid == os.geteuid())
    check('new child and parent directory sync confirmed', creation_trace == [
        {'event': 'fsync_directory', 'target': 'new_private_directory'},
        {'event': 'fsync_directory', 'target': 'parent_directory'}])
    with module.Journal.create(directory, IDENTITY) as journal:
        check('journal private regular file mode 0600', (directory / module.FILE_NAME).stat().st_mode & 0o777 == 0o600)
        check('header persisted before return', journal.read()[0]['metadata'] == IDENTITY)
        check('header trace confirms file then directory sync', [row['event'] for row in journal.trace] ==
              ['write_complete', 'fsync_file', 'fsync_directory'])
        original = journal.read()
        original[0]['metadata']['context']['purpose'] = 'MUTATED_COPY'
        check('read returns independent data', journal.read()[0]['metadata'] == IDENTITY)
        observed = [journal.recovery()]
        for phase in module.PHASES[1:]:
            record = journal.append(phase, {'observation': phase, 'not_ownership': True})
            check(phase + ': append confirmed by file fsync', journal.trace[-1] ==
                  {'event': 'fsync_file', 'seq': record['seq']})
            observed.append(journal.recovery())
        check('all five recovery classifications exact', [row['classification'] for row in observed] == list(module.CLASSIFICATIONS))
        check('all recovery stages reject delete and replay', all(
            row['may_delete'] is False and row['may_replay'] is False and
            row['production_gate'] == module.PRODUCTION_GATE for row in observed))
        check('lock held across completed transaction', child_open(directory).returncode == 23)
        rejects('completed transaction cannot be reused', lambda: journal.append('INTENT_CREATE', {}))
        completed = journal.read()
    with module.Journal.open(directory) as reopened:
        check('close and reopen preserves exact records', reopened.read() == completed)
        check('reopen has no synthetic fsync success trace', reopened.trace == [])
    check('separate process reopens after lock release', child_open(directory).returncode == 0)
    # A complete-suffix rollback is intrinsically undetectable to this local
    # hash chain. It is accepted as older observations, NEVER ownership/replay.
    rollback_directory = new_directory()
    rollback_path = rollback_directory / module.FILE_NAME
    rollback_path.write_bytes((directory / module.FILE_NAME).read_bytes().splitlines(keepends=True)[0])
    rollback_path.chmod(0o600)
    with module.Journal.open(rollback_directory) as rollback:
        result = rollback.recovery()
        check('valid whole-record rollback is not claimed detectable', result['classification'] == 'NO_EFFECT_HEADER_ONLY')
        check('header-only rollback cannot authorize actions', result['may_delete'] is False and result['may_replay'] is False)
    before = (directory / module.FILE_NAME).read_bytes()
    rejects('create refuses existing journal', lambda: module.Journal.create(directory, IDENTITY))
    check('existing journal bytes retained', (directory / module.FILE_NAME).read_bytes() == before)

    directory, journal = new_journal()
    for phase in ('APPLIED', 'INTENT_DELETE', 'UNDONE', 'HEADER', 'UNKNOWN'):
        rejects('illegal next stage ' + phase, lambda phase=phase: journal.append(phase, {}))
    for metadata in (None, [], 'text', {'nan': float('nan')}, {'inf': float('inf')},
                     {'too_big': 2 ** 63}, {1: 'nonstring key'}, {'unsupported': (1, 2)},
                     {'surrogate': '\ud800'}, {'huge': 'x' * module.MAX_RECORD_BYTES}):
        rejects('invalid metadata ' + str(len(checks)), lambda metadata=metadata: journal.append('INTENT_CREATE', metadata))
    deep = {}
    for _ in range(module.MAX_DEPTH + 1):
        deep = {'nested': deep}
    rejects('excessive metadata depth rejected', lambda: journal.append('INTENT_CREATE', deep))
    check('validation failures did not mutate file', len(journal.read()) == 1)
    journal.append('INTENT_CREATE', {})
    rejects('duplicate phase rejected', lambda: journal.append('INTENT_CREATE', {}))
    journal.close()
    rejects('closed handle refused', journal.read)

    target, journal = new_journal()
    inherited_child = os.fork()
    if inherited_child == 0:
        try:
            journal.append('INTENT_CREATE', {})
        except module.JournalError:
            os._exit(24)
        os._exit(1)
    _pid, child_status = os.waitpid(inherited_child, 0)
    check('fork child cannot reuse inherited locked handle', os.waitstatus_to_exitcode(child_status) == 24)
    check('fork misuse leaves parent journal unchanged', len(journal.read()) == 1)
    journal.close()

    for identity in ({}, dict(IDENTITY, extra=True), dict(IDENTITY, instance=''),
                     dict(IDENTITY, run_id='a/b'), dict(IDENTITY, instance='a' * 129),
                     dict(IDENTITY, context=[]), dict(IDENTITY, context={'x': 'x' * module.MAX_RECORD_BYTES})):
        target = new_directory()
        rejects('invalid identity ' + str(len(checks)), lambda identity=identity: module.Journal.create(target, identity))
        check('invalid identity creates no file ' + str(len(checks)), list(target.iterdir()) == [])

    corrupt_case('truncated final record rejected', lambda data: data[:-1])
    corrupt_case('truncated final JSON rejected', lambda data: data[:-20])
    corrupt_case('empty journal rejected', lambda _data: b'')
    corrupt_case('blank tail rejected', lambda data: data + b'\n')
    corrupt_case('damaged UTF8 rejected', lambda data: b'\xff' + data[1:])
    corrupt_case('oversized file rejected', lambda _data: b'x' * (module.MAX_FILE_BYTES + 1))
    corrupt_case('duplicate top-level JSON key rejected', lambda data: data.replace(b'{"hash":', b'{"version":1,"hash":', 1))
    corrupt_case('duplicate nested JSON key rejected', lambda data: data.replace(b'"purpose":', b'"purpose":"duplicate","purpose":', 1))
    corrupt_case('NaN rejected on read', lambda data: data.replace(b'0.25', b'NaN', 1))
    corrupt_case('hash tamper rejected', lambda data: data.replace(b'TEST_ONLY', b'TEST_WRONG', 1))
    corrupt_case('last record hash tamper rejected without successor', lambda data: data.replace(b'isolated-test-only', b'foreign-test-only', 1))
    corrupt_case('previous hash chain tamper rejected', lambda data: data.replace(module.ZERO_HASH.encode(), b'1' * 64, 1))
    corrupt_case('noncanonical JSON rejected', lambda data: data.replace(b'"version":1', b'"version": 1', 1))
    corrupt_case('extra schema key rejected independently', lambda data: rewrite(data, lambda rows: rows[1].update(extra=1)))
    corrupt_case('boolean sequence rejected independently', lambda data: rewrite(data, lambda rows: rows[1].update(seq=True)))
    corrupt_case('sequence gap rejected independently', lambda data: rewrite(data, lambda rows: rows[1].update(seq=3)))
    corrupt_case('boolean version rejected independently', lambda data: rewrite(data, lambda rows: rows[1].update(version=True)))
    corrupt_case('unknown version rejected independently', lambda data: rewrite(data, lambda rows: rows[1].update(version=2)))
    corrupt_case('unknown phase rejected independently', lambda data: rewrite(data, lambda rows: rows[1].update(phase='UNKNOWN')))
    corrupt_case('phase skip rejected independently', lambda data: rewrite(data, lambda rows: rows[1].update(phase='APPLIED')))
    corrupt_case('invalid metadata schema rejected independently', lambda data: rewrite(data, lambda rows: rows[1].update(metadata=[])))
    corrupt_case('invalid header identity rejected independently', lambda data: rewrite(data, lambda rows: rows[0]['metadata'].update(instance='')))
    corrupt_case('duplicate sequence record rejected', lambda data: data + data.splitlines(keepends=True)[1])
    corrupt_case('record count bound enforced', lambda data: data + data.splitlines(keepends=True)[1] * 5)
    oversized_record = b'{"large":"' + b'x' * module.MAX_RECORD_BYTES + b'"}\n'
    corrupt_case('record size bound enforced', lambda _data: oversized_record)

    foreign = parent / 'foreign.txt'
    foreign.write_text('FOREIGN FILE MUST SURVIVE')
    symlink_directory = new_directory()
    (symlink_directory / module.FILE_NAME).symlink_to(foreign)
    rejects('symlink journal refused', lambda: module.Journal.open(symlink_directory))
    check('foreign symlink target untouched', foreign.read_text() == 'FOREIGN FILE MUST SURVIVE')
    linked_directory = parent / 'directory-symlink'
    linked_directory.symlink_to(directory, target_is_directory=True)
    rejects('symlink directory refused', lambda: module.Journal.open(linked_directory), OSError)
    rejects('relative private parent refused', lambda: module.new_private_directory(Path('.')))
    unsafe_parent = parent / 'not-private'
    unsafe_parent.mkdir(mode=0o755)
    unsafe_parent.chmod(0o755)
    rejects('non-private parent refused', lambda: module.new_private_directory(unsafe_parent))
    target, journal = new_journal()
    target.chmod(0o755)
    rejects('open directory losing privacy blocks append', lambda: journal.append('INTENT_CREATE', {}))
    target.chmod(0o700)
    journal.close()
    target, journal = new_journal()
    journal.close()
    os.link(target / module.FILE_NAME, parent / 'hardlinked-journal')
    rejects('hardlinked journal refused', lambda: module.Journal.open(target))
    target, journal = new_journal()
    journal.close()
    (target / module.FILE_NAME).chmod(0o644)
    rejects('nonprivate file refused', lambda: module.Journal.open(target))
    target = new_directory()
    os.mkfifo(target / module.FILE_NAME, mode=0o600)
    rejects('FIFO rejected before open without blocking', lambda: module.Journal.open(target))
    target, journal = new_journal()
    journal.close()
    (target / 'unexpected').write_text('not ours')
    rejects('unexpected directory entry refused', lambda: module.Journal.open(target))

    target, journal = new_journal()
    saved = target / 'original-forensic-file'
    (target / module.FILE_NAME).rename(saved)
    (target / module.FILE_NAME).write_bytes(saved.read_bytes())
    (target / module.FILE_NAME).chmod(0o600)
    replacement_before = (target / module.FILE_NAME).read_bytes()
    rejects('replaced file identity refused', lambda: journal.append('INTENT_CREATE', {}))
    check('replacement and original retained', saved.exists() and (target / module.FILE_NAME).read_bytes() == replacement_before)
    journal.close()

    real_write = os.write
    target, journal = new_journal()
    write_sizes = []

    def short_write(fd, data):
        size = real_write(fd, data[:7])
        write_sizes.append(size)
        return size

    with patch.object(module.os, 'write', side_effect=short_write):
        journal.append('INTENT_CREATE', {'short_writes': True})
    check('short writes loop to a complete durable record', len(write_sizes) > 1 and journal.read()[-1]['phase'] == 'INTENT_CREATE')
    journal.close()

    target, journal = new_journal()
    prefix = (target / module.FILE_NAME).read_bytes()
    calls = [0]

    def torn_write(fd, data):
        calls[0] += 1
        if calls[0] == 1:
            return real_write(fd, data[:13])
        raise OSError(errno.ENOSPC, 'injected disk full after partial write')

    with patch.object(module.os, 'write', side_effect=torn_write):
        error = rejects('partial write error propagates', lambda: journal.append('INTENT_CREATE', {}), OSError)
    check('partial write preserves actual errno', error.errno == errno.ENOSPC)
    check('partial write never claims write_complete or sync', [row for row in journal.trace if row.get('seq') == 1] == [])
    rejects('partial write poisons same handle', lambda: journal.append('INTENT_CREATE', {}))
    tail = (target / module.FILE_NAME).read_bytes()
    check('partial bytes kept after failure', tail.startswith(prefix) and len(tail) == len(prefix) + 13)
    journal.close()
    rejects('partial write reopen refuses damaged tail', lambda: module.Journal.open(target))
    check('reopen did not truncate partial bytes', (target / module.FILE_NAME).read_bytes() == tail)

    target, journal = new_journal()
    prefix = (target / module.FILE_NAME).read_bytes()
    with patch.object(module.os, 'write', return_value=0):
        error = rejects('zero write fails rather than loops', lambda: journal.append('INTENT_CREATE', {}), OSError)
    check('zero write is EIO', error.errno == errno.EIO)
    rejects('zero write poisons handle', journal.read)
    check('zero write retains original bytes', (target / module.FILE_NAME).read_bytes() == prefix)
    journal.close()

    target, journal = new_journal()
    with patch.object(module.os, 'fsync', side_effect=OSError(errno.EIO, 'injected file sync failure')):
        error = rejects('file fsync error propagates', lambda: journal.append('INTENT_CREATE', {}), OSError)
    check('file fsync error preserves errno', error.errno == errno.EIO)
    check('fsync failure does not claim durability', [row['event'] for row in journal.trace if row.get('seq') == 1] == ['write_complete'])
    rejects('fsync failure poisons handle', journal.recovery)
    journal.close()
    with module.Journal.open(target) as recovered:
        result = recovered.recovery()
        check('complete unsynced bytes only classify unknown create', result['classification'] == 'UNKNOWN_CREATE_OUTCOME' and result['may_delete'] is False)

    real_fsync = os.fsync
    target = new_directory()
    sync_calls = [0]

    def fail_directory_sync(fd):
        sync_calls[0] += 1
        if sync_calls[0] == 2:
            raise OSError(errno.EIO, 'injected journal directory fsync failure')
        return real_fsync(fd)

    with patch.object(module.os, 'fsync', side_effect=fail_directory_sync):
        rejects('new journal directory fsync error propagates', lambda: module.Journal.create(target, IDENTITY), OSError)
    check('failed create keeps unconfirmed journal for inspection', (target / module.FILE_NAME).is_file())
    rejects('failed create cannot be blindly recreated', lambda: module.Journal.create(target, IDENTITY))
    with module.Journal.open(target) as recovered:
        check('failed create released fd lock', recovered.recovery()['may_replay'] is False)

    target = new_directory()
    with patch.object(module.os, 'fsync', side_effect=OSError(errno.EIO, 'injected header sync failure')):
        rejects('initial header file fsync failure propagates', lambda: module.Journal.create(target, IDENTITY), OSError)
    check('header sync failure preserves written data', (target / module.FILE_NAME).stat().st_size > 0)
    with module.Journal.open(target) as recovered:
        check('unconfirmed header never authorizes a side effect', recovered.recovery()['may_replay'] is False)

    before_dirs = set(parent.iterdir())
    sync_calls[0] = 0
    helper_trace = []
    with patch.object(module.os, 'fsync', side_effect=fail_directory_sync):
        rejects('new private parent directory sync error propagates', lambda: module.new_private_directory(parent, helper_trace), OSError)
    check('failed private-directory create retains child', len(set(parent.iterdir()) - before_dirs) == 1)
    check('failed parent sync never logged as success', helper_trace == [
        {'event': 'fsync_directory', 'target': 'new_private_directory'}])

    helper_trace = []
    with patch.object(module.os, 'fsync', side_effect=OSError(errno.EIO, 'injected child sync failure')):
        rejects('new child directory sync error propagates', lambda: module.new_private_directory(parent, helper_trace), OSError)
    check('failed first directory sync records no success', helper_trace == [])

    target, journal = new_journal()
    with patch.object(module.os, 'read', side_effect=OSError(errno.EIO, 'injected read error')):
        rejects('real read I/O error propagates', journal.read, OSError)
    journal.close()
    target = new_directory()
    with patch.object(module.fcntl, 'flock', side_effect=OSError(errno.EIO, 'injected lock I/O error')):
        rejects('unexpected lock I/O error propagates', lambda: module.Journal.create(target, IDENTITY), OSError)
    check('lock failure retains created empty file', (target / module.FILE_NAME).exists())

print(json.dumps({'result': 'PASS', 'count': len(checks), 'checks': checks,
                  'production_gate': module.PRODUCTION_GATE,
                  'scope': 'real local files and failure injection; process-crash only, not power-cut/kernel ownership',
                  'library_sha256': sha256(LIBRARY.read_bytes()).hexdigest()},
                 ensure_ascii=False, indent=2))
