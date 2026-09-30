#!/usr/bin/env python3
"""Small OFFLINE contract, NOT a tc/netlink adapter or deployable SQM fix.

No subprocess, filesystem, network or cleanup action is implemented here.
The receipt/token and atomic undo capability are hypothetical mock contracts,
not capabilities claimed for Linux qdisc objects. Automatic cleanup is refused.
"""
from copy import deepcopy
from hashlib import sha256
import json
import re

RELEASE_GATE = 'OFFLINE_ONLY_NOT_DEPLOYABLE'
CAPABILITY = 'SIMULATION_ONLY_ATOMIC_EXACT_UNDO'


class Refused(RuntimeError):
    pass


class NoEffect(RuntimeError):
    """Backend can establish this particular failure changed no resource."""


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_identity(identity):
    # Incarnation is deliberately a mock-only generation, not Linux ifindex.
    required = {'boot', 'netns', 'device', 'ifindex', 'mock_incarnation'}
    if set(identity) != required or type(identity['ifindex']) is not int or identity['ifindex'] <= 0:
        raise Refused('incomplete device identity')
    for field in required - {'ifindex'}:
        if not isinstance(identity[field], str) or not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,80}', identity[field]):
            raise Refused('invalid identity field: ' + field)


class MemoryJournal:
    """Failure-injectable mock storage. NOT a durable/on-router journal."""
    def __init__(self):
        self.records = {}
        self.writes = 0
        self.fail_at = None

    def read(self, key):
        return deepcopy(self.records[key])

    def write(self, key, expected_revision, value):
        self.writes += 1
        if self.writes == self.fail_at:
            raise Refused('simulated journal failure')
        current = self.records.get(key)
        if (current['revision'] if current else 0) != expected_revision:
            raise Refused('stale journal revision')
        stored = deepcopy(value)
        stored['revision'] = expected_revision + 1
        self.records[key] = stored


class Protocol:
    def __init__(self, journal, backend, *, simulation=False):
        if not simulation or getattr(backend, 'capability', None) != CAPABILITY:
            raise Refused('no production backend; simulation capability required')
        self.journal, self.backend = journal, backend

    def _save(self, key, record):
        self.journal.write(key, record.get('revision', 0), record)
        return self.journal.read(key)

    def start(self, instance, run_nonce, identity, steps):
        """A single device's explicitly enumerated creates; no replace/adoption.

        Link creation/up, module loading and IFB binding are intentionally NOT
        represented. A future adapter must journal them separately or refuse.
        This is not an NSS/CAKE command translator.
        """
        validate_identity(identity)
        for label in (instance, run_nonce):
            if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', label):
                raise Refused('invalid instance/run identity')
        if instance in self.journal.records:
            raise Refused('existing instance journal must not be overwritten')
        if not steps or len({step['locator'] for step in steps}) != len(steps):
            raise Refused('empty or duplicate resource plan')
        seen = set()
        for step in steps:
            if set(step) != {'operation', 'locator', 'parameters', 'depends_on'} or step['operation'] != 'create':
                raise Refused('only exact create is represented; no replace/adopt/link/module operation')
            if not isinstance(step['locator'], str) or not step['locator'] or not isinstance(step['parameters'], dict):
                raise Refused('invalid exact resource specification')
            dependencies = step['depends_on']
            if (not isinstance(dependencies, list) or not all(isinstance(x, str) for x in dependencies)
                    or len(set(dependencies)) != len(dependencies) or not set(dependencies) <= seen):
                raise Refused('missing, duplicate, self, cyclic or out-of-order dependency')
            parent = step['parameters'].get('parent')
            if parent is not None and parent not in dependencies:
                raise Refused('parent dependency must be explicit')
            seen.add(step['locator'])
        owner = {'instance': instance, 'run': run_nonce}
        record = {'revision': 0, 'owner': owner, 'identity': deepcopy(identity),
                  'plan_digest': fingerprint(steps), 'state': 'STARTING', 'first_error': None,
                  'steps': [], 'release_gate': RELEASE_GATE}
        record = self._save(instance, record)
        for step in steps:
            dependencies = {entry['spec']['locator']: deepcopy(entry['receipt'])
                            for entry in record['steps'] if entry['phase'] == 'APPLIED'
                            and entry['spec']['locator'] in step['depends_on']}
            if set(dependencies) != set(step['depends_on']):
                raise Refused('dependency lacks a committed successful receipt')
            # This intent must precede every side effect. A crash here is unknown,
            # not evidence that nothing happened and not permission to clean up.
            entry = {'spec': deepcopy(step), 'phase': 'INTENT', 'receipt': None}
            record['steps'].append(entry)
            record = self._save(instance, record)
            try:
                receipt = self.backend.create(owner, identity, deepcopy(step), deepcopy(dependencies))
            except NoEffect as error:
                record['steps'][-1]['phase'] = 'REJECTED_NO_EFFECT'
                record['state'] = 'FAILED'
                record['first_error'] = str(error)
                self._save(instance, record)
                return False
            except Exception as error:
                record['state'] = 'UNKNOWN'
                record['first_error'] = str(error)
                self._save(instance, record)
                return False
            expected = {'owner': owner, 'identity': identity, 'spec_digest': fingerprint(step),
                        'dependencies': dependencies}
            if (not isinstance(receipt, dict) or set(receipt) != {*expected, 'mock_token'}
                    or any(receipt.get(k) != v for k, v in expected.items())
                    or not isinstance(receipt['mock_token'], str) or not receipt['mock_token']):
                record['state'] = 'UNKNOWN'
                record['first_error'] = 'invalid backend receipt'
                self._save(instance, record)
                return False
            record['steps'][-1].update(phase='APPLIED', receipt=deepcopy(receipt))
            # A write failure leaves the stored INTENT, blocking compensation.
            record = self._save(instance, record)
        record['state'] = 'ACTIVE'
        self._save(instance, record)
        return True

    def compensate(self, instance, *, allow_simulation=False):
        if not allow_simulation:
            raise Refused('automatic cleanup denied; explicit simulation only')
        record = self.journal.read(instance)
        if record['release_gate'] != RELEASE_GATE:
            raise Refused('journal release marker drift')
        if record['state'] == 'COMPENSATED':
            return True
        if any(step['phase'] in {'INTENT', 'UNDO_INTENT'} for step in record['steps']):
            raise Refused('unknown side-effect window; no automatic replay or parent deletion')
        for index in range(len(record['steps']) - 1, -1, -1):
            step = record['steps'][index]
            if step['phase'] in {'REJECTED_NO_EFFECT', 'UNDONE'}:
                continue
            if step['phase'] != 'APPLIED':
                raise Refused('invalid journal phase')
            step['phase'] = 'UNDO_INTENT'
            record = self._save(instance, record)
            try:
                # Backend must atomically validate receipt AND dependencies AND
                # undo the exact object. Read/compare/tc-del does not qualify.
                self.backend.undo(deepcopy(step['receipt']), deepcopy(step['spec']))
            except NoEffect as error:
                record['steps'][index]['phase'] = 'APPLIED'
                record['state'] = 'CLEANUP_FAILED'
                record['first_error'] = record['first_error'] or str(error)
                self._save(instance, record)
                return False
            except Exception as error:
                record['state'] = 'UNKNOWN'
                record['first_error'] = record['first_error'] or str(error)
                self._save(instance, record)
                return False
            record['steps'][index]['phase'] = 'UNDONE'
            record = self._save(instance, record)
        record['state'] = 'COMPENSATED'
        self._save(instance, record)
        return True


if __name__ == '__main__':
    raise SystemExit('OFFLINE ONLY: import into mocks; no production or cleanup CLI exists')
