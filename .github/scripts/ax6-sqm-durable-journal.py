#!/usr/bin/env python3
"""TEST ONLY: bounded, fail-closed, single-resource process-crash journal.

This is not an SQM backend. No kernel command, recovery replay, deletion,
truncation, migration or automatic repair is implemented. A valid hash chain is
an integrity check, NOT authentication, ownership or an atomic tc generation.
Removal of a complete valid suffix (rollback) is not detectable without an
external monotonic authority; even valid records never authorize replay/undo.
fsync success is recorded; this test does not prove storage power-loss safety.

Use a new private 0700 parent owned by the caller. Path/metadata checks defend
against ordinary mistakes, not malicious same-UID/root concurrent replacement.
All participating writers must honor flock. A directory fd pins the directory;
the library does not claim adversarial path-identity CAS. Caller metadata is
observational and its kernel meaning is not validated here.
"""
from copy import deepcopy
import errno
import fcntl
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import threading

PRODUCTION_GATE = 'BLOCKED_TEST_ONLY_NO_OWNERSHIP'
FILE_NAME = 'journal.jsonl'
MAX_RECORD_BYTES = 32 * 1024
MAX_FILE_BYTES = 5 * MAX_RECORD_BYTES
MAX_DEPTH = 12
PHASES = ('HEADER', 'INTENT_CREATE', 'APPLIED', 'INTENT_DELETE', 'UNDONE')
CLASSIFICATIONS = (
    'NO_EFFECT_HEADER_ONLY', 'UNKNOWN_CREATE_OUTCOME',
    'OBSERVED_APPLIED_NO_OWNERSHIP', 'UNKNOWN_DELETE_OUTCOME',
    'OBSERVED_UNDONE_NO_REPLAY',
)
ZERO_HASH = '0' * 64


class JournalError(RuntimeError):
    """Invalid, unsafe, ambiguous or damaged journal; no recovery action."""


class JournalLocked(JournalError):
    """Another cooperating process holds the exclusive journal lock."""


def _json_value(value, depth=0):
    if depth > MAX_DEPTH:
        raise JournalError('JSON nesting exceeds bound')
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if not -(2 ** 63) <= value < 2 ** 63:
            raise JournalError('integer outside signed 64-bit range')
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise JournalError('non-finite float')
        return
    if type(value) is str:
        try:
            value.encode('utf-8')
        except UnicodeError as error:
            raise JournalError('invalid Unicode string') from error
        return
    if type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise JournalError('JSON object key must be a string')
            _json_value(key, depth + 1)
            _json_value(item, depth + 1)
        return
    raise JournalError('unsupported JSON type')


def _canonical(value):
    _json_value(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _identity(identity):
    if type(identity) is not dict or set(identity) != {'instance', 'run_id', 'context'}:
        raise JournalError('identity must contain exactly instance/run_id/context')
    for key in ('instance', 'run_id'):
        if type(identity[key]) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', identity[key]):
            raise JournalError('invalid identity label: ' + key)
    if type(identity['context']) is not dict:
        raise JournalError('identity context must be a JSON object')
    _canonical(identity)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise JournalError('duplicate JSON key')
        result[key] = value
    return result


def _bad_constant(_value):
    raise JournalError('non-standard JSON constant')


def _safe_directory(path):
    path = Path(path)
    if not path.is_absolute():
        raise JournalError('absolute private-directory path required')
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
            raise JournalError('directory must be caller-owned mode 0700')
    except BaseException:
        os.close(fd)
        raise
    return path, fd


def _directory_sync(fd, trace, target):
    os.fsync(fd)
    trace.append({'event': 'fsync_directory', 'target': target})


def new_private_directory(parent, trace=None):
    """Create one random 0700 child; sync child and parent. Never remove it.

    If synchronization fails, an unconfirmed child may remain for inspection;
    callers must not silently retry by adopting it. Only this new child entry
    and parent are synced, not the creation of any caller-created ancestor.
    """
    trace = [] if trace is None else trace
    parent_path, parent_fd = _safe_directory(parent)
    child_fd = None
    try:
        name = 'ax6-sqm-journal-' + secrets.token_hex(16)
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                           dir_fd=parent_fd)
        info = os.fstat(child_fd)
        if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
            raise JournalError('new directory permissions changed or umask is incompatible')
        _directory_sync(child_fd, trace, 'new_private_directory')
        _directory_sync(parent_fd, trace, 'parent_directory')
        return parent_path / name
    finally:
        try:
            if child_fd is not None:
                os.close(child_fd)
        finally:
            os.close(parent_fd)


class Journal:
    """Exclusive-fd, append-only test journal. One strict four-stage operation.

    create() also durably creates HEADER and its directory entry. append()
    returns only after the entire record and fsync complete. A write/fsync
    failure poisons that handle; close and inspect using a fresh open, never retry the
    side effect based on an exception. read()/recovery() never write or repair.
    """
    def __init__(self, directory, dir_fd, fd):
        self.directory = directory
        self.trace = []
        self._dir_fd, self._fd = dir_fd, fd
        self._poisoned = False
        self._mutex = threading.RLock()
        self._file_identity = None
        self._owner_pid = os.getpid()

    @classmethod
    def create(cls, directory, identity):
        _identity(identity)
        header = cls._record(0, 'HEADER', identity, ZERO_HASH)
        cls._encode(header)  # Fail invalid/oversized input before file creation.
        return cls._acquire(directory, header)

    @classmethod
    def open(cls, directory):
        return cls._acquire(directory, None)

    @classmethod
    def _acquire(cls, directory, header):
        path, dir_fd = _safe_directory(directory)
        fd = None
        try:
            entries = os.listdir(dir_fd)
            if header is not None:
                if entries:
                    raise JournalError('create requires a new empty private directory')
            elif entries != [FILE_NAME]:
                raise JournalError('journal directory has missing or unexpected entries')
            flags = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if header is not None:
                flags |= os.O_CREAT | os.O_EXCL
            else:
                cls._safe_file(os.stat(FILE_NAME, dir_fd=dir_fd, follow_symlinks=False))
            fd = os.open(FILE_NAME, flags, 0o600, dir_fd=dir_fd)
            cls._safe_file(os.fstat(fd))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EAGAIN, errno.EACCES):
                    raise JournalLocked('journal is exclusively locked') from error
                raise
            journal = cls(path, dir_fd, fd)
            info = os.fstat(fd)
            journal._file_identity = (info.st_dev, info.st_ino)
            if header is not None:
                journal._write(header)
                _directory_sync(dir_fd, journal.trace, 'journal_directory')
            journal.read()
            return journal
        except BaseException:
            # Preserve every byte/directory entry, including uncertain writes.
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                os.close(dir_fd)
            raise

    @staticmethod
    def _safe_file(info):
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid() or info.st_nlink != 1):
            raise JournalError('journal must be private caller-owned single-link regular file')
        if info.st_size > MAX_FILE_BYTES:
            raise JournalError('journal exceeds size bound')

    @staticmethod
    def _record(seq, phase, metadata, previous):
        record = {'version': 1, 'seq': seq, 'phase': phase,
                  'metadata': deepcopy(metadata), 'prev_hash': previous}
        record['hash'] = sha256(_canonical(record)).hexdigest()
        return record

    @staticmethod
    def _encode(record):
        data = _canonical(record) + b'\n'
        if len(data) > MAX_RECORD_BYTES:
            raise JournalError('record exceeds size bound')
        return data

    def _check_process(self):
        if os.getpid() != self._owner_pid:
            raise JournalError('live journal handle cannot be reused after fork; independently open instead')

    def _check_fd(self):
        self._check_process()
        if self._fd is None:
            raise JournalError('journal is closed')
        if self._poisoned:
            raise JournalError('uncertain I/O: handle poisoned; close and inspect separately')
        directory = os.fstat(self._dir_fd)
        if stat.S_IMODE(directory.st_mode) != 0o700 or directory.st_uid != os.geteuid():
            raise JournalError('open private directory metadata changed')
        info = os.fstat(self._fd)
        self._safe_file(info)
        linked = os.stat(FILE_NAME, dir_fd=self._dir_fd, follow_symlinks=False)
        self._safe_file(linked)
        if (linked.st_dev, linked.st_ino) != self._file_identity or (info.st_dev, info.st_ino) != self._file_identity:
            raise JournalError('journal file identity changed')
        return info

    def read(self):
        self._check_process()  # Before mutex: a lock inherited across fork may be held.
        with self._mutex:
            before = self._check_fd()
            os.lseek(self._fd, 0, os.SEEK_SET)
            chunks = []
            remaining = MAX_FILE_BYTES + 1
            while remaining:
                chunk = os.read(self._fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b''.join(chunks)
            after = self._check_fd()
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise JournalError('journal changed during read')
            if not data or len(data) > MAX_FILE_BYTES or not data.endswith(b'\n'):
                raise JournalError('empty, oversized or incomplete journal')
            lines = data.splitlines(keepends=True)
            if len(lines) > len(PHASES):
                raise JournalError('too many records')
            records = []
            previous = ZERO_HASH
            for seq, line in enumerate(lines):
                if len(line) > MAX_RECORD_BYTES:
                    raise JournalError('record exceeds size bound')
                try:
                    record = json.loads(line.decode('utf-8'), object_pairs_hook=_unique_object,
                                        parse_constant=_bad_constant)
                except (ValueError, UnicodeError, RecursionError) as error:
                    raise JournalError('invalid JSON record') from error
                if type(record) is not dict or set(record) != {'version', 'seq', 'phase', 'metadata', 'prev_hash', 'hash'}:
                    raise JournalError('invalid record schema')
                if (type(record['version']) is not int or record['version'] != 1
                        or type(record['seq']) is not int or record['seq'] != seq
                        or record['phase'] != PHASES[seq] or type(record['metadata']) is not dict):
                    raise JournalError('invalid version, sequence, phase or metadata')
                if seq == 0:
                    _identity(record['metadata'])
                if record['prev_hash'] != previous:
                    raise JournalError('broken previous-hash chain')
                unsigned = {key: value for key, value in record.items() if key != 'hash'}
                expected = sha256(_canonical(unsigned)).hexdigest()
                if record['hash'] != expected or self._encode(record) != line:
                    raise JournalError('hash mismatch or noncanonical record')
                records.append(record)
                previous = expected
            return deepcopy(records)

    def _write(self, record):
        data = self._encode(record)
        if self._check_fd().st_size + len(data) > MAX_FILE_BYTES:
            raise JournalError('append would exceed file bound')
        try:
            offset = 0
            while offset < len(data):
                written = os.write(self._fd, data[offset:])
                if written <= 0:
                    raise OSError(errno.EIO, 'zero-length journal write')
                offset += written
            self.trace.append({'event': 'write_complete', 'seq': record['seq'], 'bytes': len(data)})
            os.fsync(self._fd)
            self.trace.append({'event': 'fsync_file', 'seq': record['seq']})
        except BaseException:
            self._poisoned = True
            raise

    def append(self, phase, metadata):
        self._check_process()
        with self._mutex:
            records = self.read()
            seq = len(records)
            if seq >= len(PHASES) or phase != PHASES[seq] or type(metadata) is not dict:
                raise JournalError('illegal next phase or metadata type')
            record = self._record(seq, phase, metadata, records[-1]['hash'])
            self._write(record)
            return deepcopy(record)

    def recovery(self):
        records = self.read()
        return {'phase': records[-1]['phase'], 'seq': records[-1]['seq'],
                'classification': CLASSIFICATIONS[len(records) - 1],
                'identity': deepcopy(records[0]['metadata']),
                'may_delete': False, 'may_replay': False,
                'production_gate': PRODUCTION_GATE}

    def close(self):
        self._check_process()
        with self._mutex:
            fd, dir_fd = self._fd, self._dir_fd
            self._fd = self._dir_fd = None
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                if dir_fd is not None:
                    os.close(dir_fd)

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()


if __name__ == '__main__':
    raise SystemExit('TEST-ONLY library: no command runner or automatic recovery; production BLOCKED')
