#!/usr/bin/env python3
"""Bind one reviewed final EDMA profile and execute actual prepared C on the host.

This is not target, IRQ service, real RCU, firmware/DMA or AX6 acceptance.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / '.github/ax6-edma-prepared-contract.json'
FIXTURE = ROOT / 'tests/fixtures/edma-irq-napi-contract.c'
REL = Path('hal/dp_ops/edma_dp/edma_v1')
FILES = {'hal/soc_ops/ipq807x/nss_ipq807x.h',
         *(str(REL / n) for n in ('edma_regs.h', 'edma_data_plane.h',
                                 'edma_data_plane.c', 'edma_cfg.c', 'edma_tx_rx.c'))}
ASSETS = {'tests/test-edma-tx-slot-ownership.py', 'tests/edma-tx-slot-ownership/fixture.c'}
FLAGS = ['-std=gnu11', '-O1', '-g', '-pthread', '-Wall', '-Wextra', '-Werror',
         '-Wno-unused-parameter', '-Wno-unused-function', '-Wno-unused-variable',
         '-Wno-sign-compare']


def require(ok, why):
    if not ok:
        raise ValueError(why)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def admit(source, prepared):
    profile = json.loads(PROFILE.read_text(), object_pairs_hook=pairs)
    require(type(profile['schema']) is int and profile['schema'] == 1 and
            profile['profile'] == 'IPQ807X_001_019', 'unreviewed profile')
    require(set(profile['prepared_files']) == FILES, 'incomplete prepared profile')
    require(set(profile['test_assets']) == ASSETS, 'incomplete test asset profile')
    require(re.fullmatch(r'[0-9a-f]{40}', profile['upstream_pin']), 'invalid upstream pin')
    require(all(re.fullmatch(r'[0-9a-f]{64}', digest) for group in
                ('patches', 'prepared_files', 'test_assets') for digest in profile[group].values()),
            'invalid profile digest')
    package = source / 'package/qca-nss/qca-nss-dp'
    require(not (package / 'Makefile').is_symlink(), 'recipe must be regular')
    require(re.findall(r'^PKG_SOURCE_VERSION:=(\S+)\s*$',
                       (package / 'Makefile').read_text(), re.M) ==
            [profile['upstream_pin']], 'upstream pin drift')
    patch_files = sorted((package / 'patches').glob('*.patch'))
    require(all(p.is_file() and not p.is_symlink() for p in patch_files),
            'patches must be regular')
    patches = {p.name: sha(p.read_bytes()) for p in patch_files}
    require(patches == profile['patches'] and
            sorted(int(n[:3]) for n in patches) == list(range(1, 20)),
            'patch profile drift or mixed patch chain')
    for group, root in (('prepared_files', prepared), ('test_assets', source)):
        for name, digest in profile[group].items():
            path = root / name
            require(not path.is_symlink() and path.is_file(), 'missing regular input: ' + name)
            require(sha(path.read_bytes()) == digest, group + ' mismatch: ' + name)
    return profile


def load_tx(source):
    path = source / 'tests/test-edma-tx-slot-ownership.py'
    spec = importlib.util.spec_from_file_location('locked_edma_tx', path)
    require(spec is not None and spec.loader is not None, 'TX extractor import')
    tx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tx)
    return tx


def check_build_input_snapshot(snapshot, expected):
    root = snapshot / 'build-inputs'
    names = {row['file'] for row in expected.values()} | {'INDEX.json'}
    require(root.is_dir() and not root.is_symlink() and
            {p.name for p in root.iterdir()} == names,
            'build input snapshot inventory')
    require(all(p.is_file() and not p.is_symlink() for p in root.iterdir()),
            'build input snapshot must contain only regular files')
    require(json.loads((root / 'INDEX.json').read_text(), object_pairs_hook=pairs) == expected,
            'build input snapshot index')
    for row in expected.values():
        require(sha((root / row['file']).read_bytes()) == row['sha256'],
                'build input snapshot bytes: ' + row['file'])


def capture_build_input_snapshot(bound, snapshot):
    allowed = {'.github/scripts/verify-edma-prepared-regressions.py',
               '.github/ax6-edma-prepared-contract.json',
               'tests/fixtures/edma-irq-napi-contract.c'}
    relative = [path.relative_to(ROOT).as_posix() for path in bound]
    require(len(relative) == 3 and set(relative) == allowed, 'build input allowlist')
    for path in bound:
        require(path.is_file() and not path.is_symlink() and
                all(not p.is_symlink() for p in [path.parent, *path.parents]
                    if p == ROOT or ROOT in p.parents), 'build input must be regular')
    expected = {name: {'file': Path(name).name, 'sha256': sha(path.read_bytes())}
                for name, path in zip(relative, bound)}
    root = snapshot / 'build-inputs'
    root.mkdir(parents=True, exist_ok=False)
    for name, path in zip(relative, bound):
        (root / expected[name]['file']).write_bytes(path.read_bytes())
    (root / 'INDEX.json').write_text(json.dumps(expected, indent=2) + '\n')
    check_build_input_snapshot(snapshot, expected)
    return expected


def execute(command, output, name, env=None):
    try:
        p = subprocess.run(list(map(str, command)), capture_output=True,
                           text=True, timeout=120, env=env)
        row = {'command': list(map(str, command)), 'returncode': p.returncode,
               'stdout': p.stdout, 'stderr': p.stderr}
    except subprocess.TimeoutExpired:
        row = {'command': list(map(str, command)), 'returncode': 'timeout',
               'stdout': '', 'stderr': 'command timed out'}
    (output / (name + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    return row


def irq_mutations(tx, functions):
    mutations = {}
    def add(name, function, old, new, marker):
        changed = dict(functions)
        changed[function] = tx.once(changed[function], old, new)
        mutations[name] = (changed, marker)
    for field in ('tx', 'rxfill', 'rxdesc'):
        add('omit-' + field + '-ownership', 'edma_irq_init',
            'edma_hw.' + field + '_irqs_owned++;', '(void)0;',
            'irq-live-ledger' if field == 'tx' else 'irq-free-order')
    add('omit-misc-ownership', 'edma_irq_init',
        'edma_hw.misc_irq_owned = true;', '(void)0;', 'publish-after-registration')
    add('omit-failure-unwind', 'edma_irq_init', 'edma_free_irqs();',
        '(void)0;', 'irq-live-ledger')
    add('wrong-free-owner', 'edma_free_irqs',
        'free_irq(edma_hw.misc_intr, edma_hw.pdev);',
        'free_irq(edma_hw.misc_intr, NULL);', 'irq-free-owner')
    add('wrong-free-order', 'edma_free_irqs',
        'edma_hw.rxdesc_intr[edma_hw.rxdesc_irqs_owned]',
        'edma_hw.rxdesc_intr[0]', 'irq-free-order')
    add('physical-napi-owner', 'edma_register_netdevice',
        'netif_napi_add(edma_hw.napi_dev,', 'netif_napi_add(netdev,', 'napi-dummy-owner')
    add('omit-napi-rollback', 'edma_register_netdevice',
        'netif_napi_del(&edma_hw.napi);', '(void)0;', 'registration-rollback')
    add('publish-before-irq', 'edma_register_netdevice',
        'if (edma_irq_init() < 0)',
        'rcu_assign_pointer(edma_hw.netdev_arr[macid - 1], netdev);\n'
        '\t\tif (edma_irq_init() < 0)', 'publish-after-registration')
    add('duplicate-napi', 'edma_register_netdevice',
        'if (!edma_hw.napi_added)', 'if (true)', 'napi-single-owner')
    add('foreign-refusal-writes-owner', 'edma_register_netdevice',
        'return rcu_access_pointer(edma_hw.netdev_arr[macid - 1]) == netdev ? 0 : -EBUSY;',
        '{ struct net_device *owner = rcu_access_pointer(edma_hw.netdev_arr[macid - 1]);\n'
        '\t\trcu_assign_pointer(edma_hw.netdev_arr[macid - 1], netdev);\n'
        '\t\treturn owner == netdev ? 0 : -EBUSY; }', 'refusal-state')
    return mutations


def irq_text(tx, headers, functions):
    text = FIXTURE.read_text()
    text = tx.once(text, '/* HEADERS */', headers)
    return tx.once(text, '/* FUNCTIONS */', '\n\n'.join(functions.values()))


def irq_expected():
    expected = []
    for rings in (1, 2):
        for fault in range(1, rings * 3 + 2):
            expected.extend('PASS ' + n + ':' + str(rings) + ':' + str(fault)
                            for n in ('lookup-failure-retry', 'request-failure-retry'))
        expected.extend('PASS shared-single-napi:' + str(rings) + ':' + str(port)
                        for port in range(1, 7))
        expected.append('PASS owned-reentry-and-retire-twice:' + str(rings) + ':0')
    expected.extend('PASS invalid-port:1:' + str(i) for i in range(3))
    expected.extend('PASS ' + n + ':1:0' for n in
                    ('null-device', 'not-initialized', 'missing-dummy', 'overridden-id'))
    return '\n'.join(expected) + '\n'


def semantic_rejection(row, marker, prefix=''):
    return (type(row['returncode']) is int and row['returncode'] == 86 and
            row['stderr'] == marker + '\n' and
            prefix.startswith(row['stdout']) and
            (not row['stdout'] or row['stdout'].endswith('\n')))


def positive_result(row, irq=False):
    if type(row['returncode']) is not int or row['returncode'] or row['stderr']:
        return False
    if irq:
        return row['stdout'] == irq_expected()
    match = re.fullmatch(r'cases=74 checks=(\d+) maps=(\d+) unmaps=(\d+) '
                         r'zero_unmaps=(\d+) frees=(\d+)\n', row['stdout'])
    return bool(match and int(match[1]) > 0 and int(match[2]) == int(match[3]) > 0 and
                0 < int(match[4]) <= int(match[2]) and int(match[5]) >= int(match[2]))


def suite(source, prepared, output, compiler, sanitize):
    tx = load_tx(source)
    headers, functions, fragments = tx.extract(prepared, True)
    plane = (prepared / REL / 'edma_data_plane.c').read_text()
    irq = {name: tx.definition(plane, name)[0] for name in
           ('edma_free_irqs', 'edma_irq_init', 'edma_register_netdevice')}
    fragments.extend({'path': str(prepared / REL / 'edma_data_plane.c'),
                      'function': name, 'sha256': sha(code.encode())}
                     for name, code in irq.items())
    (output / 'FRAGMENTS.json').write_text(json.dumps(fragments, indent=2) + '\n')
    # Retain complete actual inputs for an independent offline comparison.
    for name in FILES:
        dest = output / 'prepared' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((prepared / name).read_bytes())
    flags = FLAGS + (['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                      '-fno-omit-frame-pointer'] if sanitize else [])
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1:abort_on_error=0:exitcode=97',
               UBSAN_OPTIONS='halt_on_error=1:abort_on_error=0:exitcode=97')
    rows = []
    def run(name, text, marker=None):
        c, binary = output / (name + '.c'), output / (name + '.host')
        c.write_text(text)
        compiled = execute([compiler, *flags, '-DCANDIDATE=1', c, '-o', binary],
                           output, name + '.compile')
        require(compiled['returncode'] == 0 and not compiled['stdout'] and
                not compiled['stderr'], 'compile must be clean: ' + name)
        result = execute([binary, *(['suite'] if name.startswith('tx-') else [])],
                         output, name + '.run', env)
        if marker:
            require(semantic_rejection(result, marker,
                                       irq_expected() if name.startswith('irq-') else ''),
                    'exact semantic rejection: ' + name)
        else:
            require(positive_result(result, name.startswith('irq-')), 'complete positive suite: ' + name)
        rows.append({'name': name, 'expected_marker': marker, 'run': result,
                     'generated_c_sha256': sha(c.read_bytes()),
                     'binary_sha256': sha(binary.read_bytes())})
        (output / 'RUNS.json').write_text(json.dumps(rows, indent=2) + '\n')
    run('tx-positive', '#define __rcu\n' + tx.fixture(headers, functions, True))
    for name, (changed, marker) in tx.mutants(functions).items():
        run('tx-' + name, '#define __rcu\n' + tx.fixture(headers, changed, True),
            'EDMA_TX_CONTRACT ' + marker)
    run('irq-positive', irq_text(tx, headers, irq))
    for name, (changed, marker) in irq_mutations(tx, irq).items():
        run('irq-' + name, irq_text(tx, headers, changed), 'EDMA_IRQ_CONTRACT ' + marker)
    if sanitize:
        for name, code, marker in (
            ('asan', '#include <stdlib.h>\nint main(void){volatile int n=2;'
             'volatile int *p=malloc(sizeof(int));p[n]=1;free((void*)p);return 0;}\n',
             'AddressSanitizer'),
            ('ubsan', 'int main(void){volatile int n=32;return 1<<n;}\n', 'runtime error:'),
        ):
            c, binary = output / ('canary-' + name + '.c'), output / ('canary-' + name)
            c.write_text(code)
            built = execute([compiler, *flags, c, '-o', binary], output, 'canary-' + name + '.compile')
            require(built['returncode'] == 0 and not built['stdout'] and not built['stderr'],
                    'sanitizer canary compilation: ' + name)
            probe = execute([binary], output, 'canary-' + name + '.run', env)
            require(probe['returncode'] == 97 and marker in probe['stderr'] and not probe['stdout'],
                    'sanitizer must be active: ' + name)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--dp', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--sanitize', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'status': 'INCOMPLETE', 'scope': 'PREPARED_C_HOST_SUBSTITUTES_ONLY',
              'kernel_or_ax6_acceptance': False}
    try:
        compiler = shutil.which(args.cc)
        require(compiler is not None, 'host C compiler missing')
        version = execute([compiler, '--version'], args.output, 'compiler')
        require(version['returncode'] == 0, 'compiler version')
        result['profile'] = admit(args.source_root.resolve(), args.dp.resolve())
        bound = [Path(__file__).resolve(), PROFILE, FIXTURE]
        identities = {str(p): sha(p.read_bytes()) for p in bound}
        result['build_test_inputs'] = identities
        result['compiler'] = {'path': compiler, 'version': version['stdout'],
                              'sha256': sha(Path(compiler).resolve().read_bytes())}
        snapshot = args.output / 'locked-inputs'
        source = args.source_root.resolve()
        paths = [source / name for name in result['profile']['test_assets']]
        package = source / 'package/qca-nss/qca-nss-dp'
        paths += [package / 'Makefile', *(package / 'patches' / n for n in result['profile']['patches'])]
        for path in paths:
            dest = snapshot / path.relative_to(source)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())
        result['build_input_snapshot'] = capture_build_input_snapshot(bound, snapshot)
        result['runs'] = suite(args.source_root.resolve(), args.dp.resolve(),
                               args.output, compiler, args.sanitize)
        require(admit(args.source_root.resolve(), args.dp.resolve()) == result['profile'] and
                {str(p): sha(p.read_bytes()) for p in bound} == identities,
                'bound inputs changed during verification')
        check_build_input_snapshot(snapshot, result['build_input_snapshot'])
        result['status'] = 'PASS_HOST_SUBSTITUTES_ONLY'
        negatives = sum(row['expected_marker'] is not None for row in result['runs'])
        require(negatives == 28 and len(result['runs']) == 30, 'suite inventory drift')
        print(json.dumps({'status': result['status'], 'profile': result['profile']['profile'],
                          'positive_suites': 2, 'runtime_mutations_rejected': negatives,
                          'kernel_or_ax6_acceptance': False}))
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, ImportError) as exc:
        result.update(status='FAIL', error=str(exc))
        print('EDMA prepared regression: ' + str(exc), file=sys.stderr)
        return 1
    finally:
        (args.output / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
