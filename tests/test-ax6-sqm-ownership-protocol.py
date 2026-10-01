#!/usr/bin/env python3
"""Minimal ownership protocol fixtures, not a live tc or kernel acceptance test."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load('ownership_protocol', ROOT / '.github/scripts/ax6-sqm-ownership-protocol.py')
IDENTITY = {'boot': 'boot-a', 'netns': 'ns-a', 'device': 'wan', 'ifindex': 7, 'mock_incarnation': 'epoch-a'}
PLAN = [{'operation': 'create', 'locator': name, 'parameters': {'kind': kind, 'parent': parent},
         'depends_on': [parent] if parent else []}
        for name, kind, parent in [('root-1', 'nsstbl', None), ('child-10', 'nssprio', 'root-1'),
                                   ('leaf-300', 'nssfq_codel', 'child-10')]]


class MockBackend:
    """Synthetic atomic dictionary model. Linux does not expose these tokens."""
    capability = P.CAPABILITY

    def __init__(self):
        self.identity = deepcopy(IDENTITY)
        self.objects, self.calls = {}, []
        self.serial, self.create_count, self.undo_count = 0, 0, 0
        self.fail_create = self.fail_undo = None
        self.unknown_create = self.unknown_undo = None

    def dependencies_match(self, dependencies):
        return all(self.objects.get(name, {}).get('receipt') == receipt
                   and P.fingerprint(self.objects[name]['spec']) == receipt['spec_digest']
                   and self.dependencies_match(receipt['dependencies'])
                   for name, receipt in dependencies.items())

    def create(self, owner, identity, spec, dependencies):
        self.create_count += 1
        self.calls.append(('create', spec['locator']))
        if identity != self.identity or spec['locator'] in self.objects:
            raise P.NoEffect('foreign object or stale device')
        if (set(dependencies) != set(spec['depends_on']) or not self.dependencies_match(dependencies)
                or any(receipt['owner'] != owner or receipt['identity'] != identity
                       for name, receipt in dependencies.items())):
            raise P.NoEffect('missing, foreign or replaced dependency')
        if self.create_count == self.fail_create:
            raise P.NoEffect('create rejected')
        self.serial += 1
        receipt = {'owner': deepcopy(owner), 'identity': deepcopy(identity),
                   'spec_digest': P.fingerprint(spec), 'dependencies': deepcopy(dependencies),
                   'mock_token': str(self.serial)}
        self.objects[spec['locator']] = {'receipt': deepcopy(receipt), 'spec': deepcopy(spec)}
        if self.create_count == self.unknown_create:
            raise RuntimeError('lost create reply after effect')
        return receipt

    def undo(self, receipt, spec):
        self.undo_count += 1
        self.calls.append(('undo', spec['locator']))
        expected = {'receipt': receipt, 'spec': spec}
        # ONE indivisible mock operation, including identity and child checks.
        if (receipt['identity'] != self.identity or self.objects.get(spec['locator']) != expected
                or not self.dependencies_match(receipt['dependencies'])
                or any(x['spec']['parameters'].get('parent') == spec['locator']
                       or spec['locator'] in x['spec'].get('depends_on', []) for x in self.objects.values())):
            raise P.NoEffect('foreign/stale/dependent object; no deletion')
        if self.undo_count == self.fail_undo:
            raise P.NoEffect('undo rejected')
        del self.objects[spec['locator']]
        if self.undo_count == self.unknown_undo:
            raise RuntimeError('lost undo reply after effect')


RESULTS = []


def fixture():
    journal, backend = P.MemoryJournal(), MockBackend()
    return journal, backend, P.Protocol(journal, backend, simulation=True)


def check(name, condition):
    assert condition, name
    RESULTS.append({'contract': name, 'pass': True})


def refused(action):
    try:
        action()
    except P.Refused:
        return True
    return False


def start(engine, instance='sqm-a', plan=PLAN):
    return engine.start(instance, 'run-001', IDENTITY, plan)


def main():
    j, b, e = fixture()
    check('no production default backend', refused(lambda: P.Protocol(j, b)))
    b.capability = 'read-compare-delete'
    check('non-atomic backend refused', refused(lambda: P.Protocol(j, b, simulation=True)))
    j, b, e = fixture()
    check('success receipts recorded', start(e) and len(j.read('sqm-a')['steps']) == 3)
    check('automatic compensation denied', refused(lambda: e.compensate('sqm-a')) and len(b.objects) == 3)
    check('journal cannot be overwritten', refused(lambda: start(e)))
    check('reverse exact compensation', e.compensate('sqm-a', allow_simulation=True)
          and b.calls[3:] == [('undo', 'leaf-300'), ('undo', 'child-10'), ('undo', 'root-1')])
    count = len(b.calls)
    check('repeated completed compensation has no calls', e.compensate('sqm-a', allow_simulation=True) and len(b.calls) == count)
    for failure in (1, 2, 3):
        j, b, e = fixture()
        b.fail_create = failure
        check(f'forward failure {failure} stops and journals only successes', not start(e)
              and [s['phase'] for s in j.read('sqm-a')['steps']] == ['APPLIED'] * (failure - 1) + ['REJECTED_NO_EFFECT'])
        check(f'forward failure {failure} reverse compensates success prefix',
              e.compensate('sqm-a', allow_simulation=True) and not b.objects)
    for failure in (1, 2, 3):
        j, b, e = fixture()
        start(e)
        b.fail_undo = failure
        check(f'cleanup failure {failure} retains remaining ownership receipts',
              not e.compensate('sqm-a', allow_simulation=True) and len(b.objects) == 4 - failure
              and j.read('sqm-a')['state'] == 'CLEANUP_FAILED')
        b.fail_undo = None
        check(f'definite no-effect failure {failure} permits explicit retry',
              e.compensate('sqm-a', allow_simulation=True) and not b.objects)
    for field, value in [('boot', 'boot-b'), ('netns', 'ns-b'), ('ifindex', 9), ('mock_incarnation', 'epoch-b')]:
        j, b, e = fixture()
        start(e)
        b.identity[field] = value
        check('stale device rejects cleanup: ' + field, not e.compensate('sqm-a', allow_simulation=True) and len(b.objects) == 3)
    for change in ('owner', 'mock_token', 'parameters'):
        j, b, e = fixture()
        start(e)
        foreign = b.objects['leaf-300']
        if change == 'parameters':
            foreign['spec']['parameters']['rate'] = 999
        elif change == 'owner':
            foreign['receipt']['owner']['instance'] = 'foreign'
        else:
            foreign['receipt'][change] = 'recreated-same-kind-handle'
        check('foreign replacement preserved: ' + change, not e.compensate('sqm-a', allow_simulation=True) and len(b.objects) == 3)
    j, b, e = fixture()
    start(e)
    check('other instance refuses resource collision', not start(e, 'sqm-b') and len(b.objects) == 3)
    check('second instance cannot clean first instance', e.compensate('sqm-b', allow_simulation=True) and len(b.objects) == 3)
    b.objects['foreign-child'] = {'spec': {'parameters': {'parent': 'leaf-300'}}, 'receipt': {}}
    check('foreign dependency blocks parent deletion', not e.compensate('sqm-a', allow_simulation=True) and len(b.objects) == 4)
    for stage in ('create', 'undo'):
        j, b, e = fixture()
        if stage == 'create':
            b.unknown_create = 2
            check('lost create reply remains unknown', not start(e))
        else:
            start(e)
            b.unknown_undo = 1
            check('lost undo reply remains unknown', not e.compensate('sqm-a', allow_simulation=True))
        count = len(b.calls)
        check(stage + ' uncertain receipt prevents any replay', refused(lambda: e.compensate('sqm-a', allow_simulation=True)) and len(b.calls) == count)
    for fail_at, expected_objects in [(1, 0), (2, 0), (3, 1)]:
        j, b, e = fixture()
        j.fail_at = fail_at
        check(f'journal failure write {fail_at} halts forward effects', refused(lambda: start(e)) and len(b.objects) == expected_objects)
        if fail_at == 3:
            check('unrecorded create receipt cannot authorize undo', refused(lambda: e.compensate('sqm-a', allow_simulation=True)))
    j, b, e = fixture()
    start(e)
    j.fail_at = j.writes + 2  # undo succeeds but receipt publication fails
    check('undo acknowledgement failure retains unknown intent', refused(lambda: e.compensate('sqm-a', allow_simulation=True))
          and j.read('sqm-a')['steps'][-1]['phase'] == 'UNDO_INTENT' and len(b.objects) == 2)
    check('unknown undo cannot be replayed', refused(lambda: e.compensate('sqm-a', allow_simulation=True)))
    old_revision = j.read('sqm-a')['revision']
    j.write('sqm-a', old_revision, j.read('sqm-a'))
    check('stale controller revision refused', refused(lambda: j.write('sqm-a', old_revision, j.read('sqm-a'))))
    j, b, e = fixture()
    check('replace/adopt unsupported fail closed', refused(lambda: start(e, plan=[dict(PLAN[0], operation='replace')])) and not b.calls)
    for name, plan in [('child-before-parent', [PLAN[1], PLAN[0]]),
                       ('foreign parent not in plan', [PLAN[1]]),
                       ('undeclared parent', [PLAN[0], dict(PLAN[1], depends_on=[])]),
                       ('dependency cycle', [dict(PLAN[0], depends_on=['child-10']), PLAN[1]])]:
        j, b, e = fixture()
        check(name + ' rejected before any effect', refused(lambda: start(e, plan=plan)) and not b.calls)
    for alteration in ('missing', 'foreign', 'replaced'):
        j, b, e = fixture()
        original_create = b.create
        def mutate_dependency(owner, identity, spec, dependencies):
            if spec['locator'] == 'child-10':
                if alteration == 'missing':
                    del b.objects['root-1']
                elif alteration == 'foreign':
                    b.objects['root-1']['receipt']['owner']['run'] = 'foreign-run'
                else:
                    b.objects['root-1']['receipt']['mock_token'] = 'replacement'
            return original_create(owner, identity, spec, dependencies)
        b.create = mutate_dependency
        check(alteration + ' dependency prevents child creation', not start(e) and 'child-10' not in b.objects)
    j, b, e = fixture()
    start(e)
    b.objects['root-1']['receipt']['mock_token'] = 'foreign-parent'
    check('parent replacement prevents child cleanup', not e.compensate('sqm-a', allow_simulation=True) and len(b.objects) == 3)
    j, b, e = fixture()
    start(e)
    b.objects['root-1']['spec']['parameters']['rate'] = 12
    check('parent parameter change prevents descendant cleanup', not e.compensate('sqm-a', allow_simulation=True) and len(b.objects) == 3)
    j, b, e = fixture()
    start(e)
    b.objects['foreign-filter'] = {'spec': {'parameters': {'parent': None}, 'depends_on': ['leaf-300']}, 'receipt': {}}
    check('foreign non-parent dependency prevents target deletion', not e.compensate('sqm-a', allow_simulation=True) and len(b.objects) == 4)
    j, b, e = fixture()
    filter_step = {'operation': 'create', 'locator': 'filter-ref', 'parameters': {'kind': 'filter', 'parent': None}, 'depends_on': ['leaf-300']}
    check('owned non-parent dependency removed before target', start(e, plan=PLAN + [filter_step])
          and e.compensate('sqm-a', allow_simulation=True) and not b.objects
          and b.calls[4:] == [('undo', 'filter-ref'), ('undo', 'leaf-300'), ('undo', 'child-10'), ('undo', 'root-1')])
    # Read-only original-byte gate and actual legacy function negative controls.
    old_suite = load('legacy_contract_tests', ROOT / 'tests/test-ax6-sqm-transaction.py')
    old_suite.SHELL = '/bin/bash'
    old_suite.SHELL_ARGV = ['/bin/bash']
    with tempfile.TemporaryDirectory(prefix='ax6-sqm-legacy-negative-') as directory:
        folder = Path(directory)
        (folder / 'no-virtual').mkdir()
        (folder / 'no-modules').mkdir()
        old_suite.test_known_blockers(folder)
    check('all three prior legacy observations reproduced', len(old_suite.KNOWN) == 3 and all(x['observation_matched'] for x in old_suite.KNOWN))
    nss = (ROOT / 'tests/fixtures/sqm-locked/usr/lib/sqm/nss-zk.qos').read_text()
    ingress = old_suite.extract(nss, 'ingress')
    anchors = ['$IP link add name $DEV type ifb', '$IP link set dev $DEV up',
               '$TC qdisc add dev $IFACE handle ffff: ingress',
               '$TC filter add dev $IFACE parent ffff: protocol all u32 match u32 0 0 action nssmirred redirect dev $DEV fromdev $IFACE',
               'add_nsstbl ${DEV}', 'add_nssfq_codel ${DEV}']
    positions = [ingress.index(x) for x in anchors]
    check('locked NSS ingress producer order anchored', positions == sorted(positions))
    check('locked NSS root subtree has six plus one creations', old_suite.extract(nss, 'add_nsstbl').count('$TC qdisc add ') == 6
          and old_suite.extract(nss, 'add_nssfq_codel').count('$TC qdisc add ') == 1)
    # Deterministic race counterexample: matching kind/handle is not ownership.
    unsafe_slot = {'value': {'kind': 'nsstbl', 'handle': '1:', 'owner': 'ours'}}
    observed = deepcopy(unsafe_slot['value'])
    unsafe_slot['value'] = {'kind': 'nsstbl', 'handle': '1:', 'owner': 'foreign'}
    if observed['kind'] == 'nsstbl' and observed['handle'] == '1:':
        del unsafe_slot['value']
    negative = {'classification': 'KNOWN_UNSAFE_COMPARE_DELETE', 'observation_matched': 'value' not in unsafe_slot,
                'meaning': 'read-compare-delete removed foreign replacement; mock CAS is not a Linux capability'}
    assert negative['observation_matched']
    print(json.dumps({'release_gate': P.RELEASE_GATE, 'protocol_contracts': RESULTS,
                      'contracts_passed': len(RESULTS), 'legacy_observations': old_suite.KNOWN,
                      'race_negative_control': negative,
                      'not_proven': ['real kernel ownership', 'durable journal', 'tc/netlink atomic undo',
                                     'IFB/module lifecycle', 'concurrent real actors', 'CAKE/NSS performance']}, indent=2))


if __name__ == '__main__':
    main()
