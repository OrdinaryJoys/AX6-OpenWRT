#!/usr/bin/env python3
"""Offline contract tests; no tc/ip/modules/procd/router calls are permitted.

Green tests describe bounded error/state fixes, NOT production readiness.
Known ownership and lower stop masking failures are explicitly retained below.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sqm_fix', ROOT / '.github/scripts/inject-ax6-sqm-transaction-fix.py')
FIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX)
OLD = FIX.expected()
NEW = FIX.transforms(OLD)
RESULTS = []
KNOWN = []
SHELL = '/bin/sh'
RUN_CWD = None


def extract(text, name):
    match = re.search(r'(?ms)^' + re.escape(name) + r'\(\)\s*[({]\n.*?^[})]', text)
    if not match:
        raise ValueError('Missing function ' + name)
    return match.group(0)


MOCK = r'''
sqm_debug() { :; }; sqm_trace() { :; }
sqm_log() { printf 'log:%s\n' "$*"; }
sqm_warn() { printf 'warn:%s\n' "$*"; }
sqm_error() { printf 'error:%s\n' "$*"; return "${LOGGER_RC:-0}"; }
get_burst() { echo 1500; }; get_ecn() { :; }
get_limit() { echo "limit $1"; }; get_target() { echo "target $1"; }
get_quantum() { echo "quantum $1"; }; get_mtu() { echo 1500; }
calc_limit() { echo 500; }; network_get_protocol() { protocol=dhcp; }
ipt_log_restart() { return "${IPT_RC:-0}"; }
check_addr() { return "${ADDR_RC:-0}"; }
fn_exists() { return "${FN_RC:-0}"; }
sqm_prepare_script() { echo prepare; return "${PREPARE_RC:-0}"; }
egress() { echo egress; return "${EGRESS_RC:-0}"; }
ingress() { echo ingress; return "${INGRESS_RC:-0}"; }
do_modules() { echo modules; return "${MODULE_RC:-0}"; }
verify_qdisc() { return "${VERIFY_RC:-0}"; }
get_ifb_for_if() { echo ifb@wan; }
tc_count=0; ip_count=0
mock_tc() {
  tc_count=$((tc_count + 1)); printf 'tc:%s:%s\n' "$tc_count" "$*"
  [ "$tc_count" != "${TC_FAIL_AT:-0}" ] || return 7
  return 0
}
mock_ip() {
  ip_count=$((ip_count + 1)); printf 'ip:%s:%s\n' "$ip_count" "$*"
  [ "$ip_count" != "${IP_FAIL_AT:-0}" ] || return 8
  return 0
}
tc() { echo UNMOCKED_TC >&2; return 98; }
ip() { echo UNMOCKED_IP >&2; return 98; }
insmod() { echo mock-insmod; return 17; }
modprobe() { echo mock-modprobe; return 18; }
rmmod() { echo mock-rmmod; return 19; }
uci() { echo UNMOCKED_UCI >&2; return 98; }
TC=mock_tc IP=mock_ip OVERHEAD=18 IFACE=wan DEV=ifb@wan
UPLINK=100000 DOWNLINK=100000 SCRIPT=nss-zk.qos SILENT=0
ESHAPER_BURST_DUR_US=1000 ISHAPER_BURST_DUR_US=1000 EECN=NOECN IECN=NOECN
OUTPUT_TARGET=/dev/null
'''


def run(label, body, expected=0, contains=(), absent=(), environment=None, known=False):
    result = subprocess.run([SHELL], input=MOCK + '\n' + body, text=True,
                            capture_output=True, timeout=15, cwd=RUN_CWD,
                            env={'PATH': '/usr/bin:/bin', **(environment or {})})
    ok = result.returncode == expected and all(s in result.stdout for s in contains) and all(s not in result.stdout for s in absent)
    row = {'case': label, 'pass': ok, 'expected_exit': expected, 'actual_exit': result.returncode,
           'stdout': result.stdout, 'stderr': result.stderr}
    if known:
        row['classification'] = 'KNOWN_UNFIXED' if label.startswith('BLOCKER:') else 'BASELINE_NEGATIVE_CONTROL'
        row['observation_matched'] = row.pop('pass')
    (KNOWN if known else RESULTS).append(row)
    if not ok:
        raise AssertionError(json.dumps(row, indent=2))
    return result


def require(label, condition):
    if not condition:
        raise AssertionError(label)
    RESULTS.append({'case': label, 'pass': True})


def test_injector(folder):
    staged = folder / 'inject-root'
    shutil.copytree(FIX.FIXTURES, staged)
    before = {p: (staged / p).read_bytes() for p in FIX.FILES}
    try:
        FIX.apply(staged)
        raise AssertionError('Missing acknowledgement accepted')
    except ValueError as error:
        require('deployment-blocker acknowledgement required', 'OWNERSHIP BLOCKER' in str(error))
    require('blocked injector writes nothing', all((staged / p).read_bytes() == value for p, value in before.items()))
    report = FIX.apply(staged, True)
    require('manifest cannot advertise release-ready', report['ownership_gate'] == 'FAIL_NOT_IMPLEMENTED')
    FIX.apply(staged, True, True)
    FIX.apply(staged, True)
    require('injector idempotent exact bytes', all((staged / p).read_text() == NEW[p] for p in FIX.FILES))
    drift = staged / FIX.FILES[-1]
    drift.write_text(drift.read_text() + '# upstream drift\n')
    snapshots = {p: (staged / p).read_bytes() for p in FIX.FILES}
    try:
        FIX.apply(staged, True)
        raise AssertionError('Drift accepted')
    except ValueError:
        pass
    require('all-file preflight prevents partial writes on drift', all((staged / p).read_bytes() == value for p, value in snapshots.items()))
    for name, text in NEW.items():
        result = subprocess.run([SHELL, '-n'], input=text, text=True, capture_output=True)
        require('shell syntax ' + name, result.returncode == 0)


def test_nss(folder):
    nss = NEW['usr/lib/sqm/nss-zk.qos']
    for failure in range(7):
        run('NSS add_nsstbl exact failure ' + str(failure), extract(nss, 'add_nsstbl') +
            f'\nTC_FAIL_AT={failure}\nadd_nsstbl wan 100000 1000 1500 NOECN\n',
            7 if failure else 0, contains=[f'tc:{failure if failure else 6}:'],
            absent=[f'tc:{failure + 1}:'] if failure else [])
    for failure in (0, 1):
        run('NSS child fq_codel failure ' + str(failure), extract(nss, 'add_nssfq_codel') +
            f'\nTC_FAIL_AT={failure}\nadd_nssfq_codel wan 100000 5ms 500 1500 "interval 100ms quantum 1500 flows 1024"\n', 7 if failure else 0)
    for kind, step, expected in [('IP_FAIL_AT', 1, 8), ('IP_FAIL_AT', 2, 8), ('TC_FAIL_AT', 1, 7), ('TC_FAIL_AT', 2, 7)]:
        run(f'NSS ingress stops at {kind}={step}', extract(nss, 'ingress') +
            f'\nadd_nsstbl() {{ echo CHILD; }}; add_nssfq_codel() {{ echo CHILD; }}\n{kind}={step}\ningress\n', expected, absent=['CHILD'])
    for child in ('add_nsstbl', 'add_nssfq_codel'):
        for direction in ('egress', 'ingress'):
            run(f'NSS {direction} preserves child rc {child}', extract(nss, direction) +
                f'\nadd_nsstbl() {{ return 0; }}; add_nssfq_codel() {{ return 0; }}\n{child}() {{ return 27; }}\nLOGGER_RC=99\n{direction}\n', 27)
    for var in ('IPT_RC', 'ADDR_RC', 'PREPARE_RC', 'EGRESS_RC', 'INGRESS_RC'):
        run('NSS start stops on ' + var, extract(nss, 'sqm_start') +
            f'\n{var}=23\nLOGGER_RC=99\nsqm_start\n', 23,
            absent=['ingress'] if var not in ('INGRESS_RC',) else [])
    run('NSS positive two directions', extract(nss, 'sqm_start') + '\nsqm_start\n',
        contains=['egress shaping activated', 'ingress shaping activated'])
    run('NSS disabled directions do not delete resources', extract(nss, 'sqm_start') + '\nUPLINK=0 DOWNLINK=0\nsqm_start\n', absent=['tc:', 'ip:'])
    run('NSS missing function fails', extract(nss, 'sqm_start') + '\nFN_RC=1\nsqm_start\n', 69)
    net = folder / 'nss-net'
    (net / 'ifb@wan').mkdir(parents=True)
    start = extract(nss, 'sqm_start').replace('/sys/class/net/', str(net) + '/')
    run('NSS existing IFB preflight refuses unknown ownership', start + '\nsqm_start\n', 73, absent=['prepare', 'tc:', 'ip:'])
    require('source-time hotplug guard removed', 'if [ -n "${ACTION}" ]' not in nss)
    # All qdisc creation algorithm tokens remain unchanged, apart from guards.
    old_cmds = re.findall(r'(?m)^  \$(?:TC|IP) .+$', OLD['usr/lib/sqm/nss-zk.qos'][:OLD['usr/lib/sqm/nss-zk.qos'].index('sqm_start()')])
    new_cmds = [s.removesuffix(' || return $?') for s in re.findall(r'(?m)^  \$(?:TC|IP) .+$', nss[:nss.index('sqm_start()')])]
    require('NSS tc/ip algorithm arguments unchanged', old_cmds == new_cmds)


def test_generic():
    fun = NEW['usr/lib/sqm/functions.sh']
    for var in ('PREPARE_RC', 'MODULE_RC', 'EGRESS_RC', 'INGRESS_RC'):
        run('generic start preserves ' + var, extract(fun, 'sqm_start_default') +
            f'\n{var}=31\nsqm_start_default\n', 31)
    run('generic CAKE callback successful path', extract(fun, 'sqm_start_default') + '\nQDISC=cake\nsqm_start_default\n', contains=['egress', 'ingress'])
    run('generic disabled directions do not delete resources', extract(fun, 'sqm_start_default') + '\nUPLINK=0 DOWNLINK=0\nsqm_start_default\n', absent=['tc:', 'ip:'])


def test_state_writer(folder):
    lib = folder / 'state-lib'
    lib.mkdir()
    (lib / 'defaults.sh').write_text('[ -z "$IFACE" ] && IFACE=wan\n[ -z "$PAYLOAD" ] && PAYLOAD=\n')
    target = folder / 'atomic.state'
    writer = extract(NEW['usr/lib/sqm/functions.sh'], 'write_state_file')
    setup = f'\nSQM_LIB_DIR={shlex.quote(str(lib))}\n'
    payload = "a'\";$(touch SENTINEL);`touch SECOND`\\line\nsecond line\n\n"
    run('state writer safely round-trips shell metacharacters', writer + setup +
        f'PAYLOAD={shlex.quote(payload)}\nwrite_state_file {shlex.quote(str(target))} || exit $?\nPAYLOAD=\n. {shlex.quote(str(target))}\nprintf "%s" "$PAYLOAD"\n', contains=[payload])
    require('state source cannot execute metacharacters', not (folder / 'SENTINEL').exists() and not (folder / 'SECOND').exists())
    for tool in ('awk', 'sort', 'sed', 'mv'):
        target.write_text('previous-complete-state\n')
        run('state writer preserves old file on ' + tool + ' failure', writer + setup +
            f'{tool}() {{ return 37; }}\nwrite_state_file {shlex.quote(str(target))}\n', 37)
        require(tool + ' failure preserves exact previous state', target.read_text() == 'previous-complete-state\n')
        require(tool + ' failure removes only owned temporaries', list(folder.glob('atomic.state.*')) == [])


def test_entries(folder):
    lib = folder / 'entries-lib'
    state = folder / 'entries-state'
    sysnet = folder / 'entries-net'
    lib.mkdir(); state.mkdir(); (sysnet / 'wan').mkdir(parents=True)
    conf = folder / 'entries.conf'
    conf.write_text(f'SQM_LIB_DIR={lib}\nSQM_STATE_DIR={state}\nSQM_QDISC_STATE_DIR={state}/available\n')
    (lib / 'defaults.sh').write_text('[ -z "$IFACE" ] && IFACE=wan\n[ -z "$SCRIPT" ] && SCRIPT=fixture.qos\n[ -z "$SQM_DEBUG" ] && SQM_DEBUG=0\n')
    functions = MOCK + '\n' + extract(NEW['usr/lib/sqm/functions.sh'], 'write_state_file') + r'''
check_state_dir() { :; }
get_ifb_associated_with_if() { echo ifb@wan; }; ifb_name() { echo ifb@wan; }
'''
    (lib / 'functions.sh').write_text(functions)
    (lib / 'fixture.qos').write_text('sqm_start() { echo CALLBACK_START; return "${START_RC:-0}"; }\nsqm_stop() { echo CALLBACK_STOP; return "${STOP_RC:-0}"; }\nsqm_cleanup() { echo CALLBACK_CLEANUP; return "${STOP_RC:-0}"; }\n')
    for entry in ('start-sqm', 'stop-sqm'):
        text = NEW['usr/lib/sqm/' + entry].replace('/etc/sqm/sqm.conf', str(conf)).replace('/sys/class/net/', str(sysnet) + '/')
        (folder / entry).write_text(text)
    # MOCK sets SCRIPT; override after sourcing to exercise generic entry path.
    (lib / 'functions.sh').write_text(functions + '\nSCRIPT=fixture.qos\n')
    entry_env = {'IFACE': 'wan', 'SCRIPT': 'fixture.qos', 'SQM_DEBUG': '0', 'CLEANUP': '0'}
    run('entry successful start creates active state', f'{SHELL} {folder}/start-sqm\n', contains=['CALLBACK_START'], environment=entry_env)
    require('active start state exists; pending gone', (state / 'wan.state').exists() and not (state / 'wan.pending').exists())
    old_state = (state / 'wan.state').read_bytes()
    run('entry duplicate active start refuses', f'{SHELL} {folder}/start-sqm\n', 1, absent=['CALLBACK_START'], environment=entry_env)
    for cleanup in ('0', '1'):
        run('entry stop returned failure preserves state cleanup=' + cleanup, f'{SHELL} {folder}/stop-sqm\n', 29,
            environment={**entry_env, 'STOP_RC': '29', 'CLEANUP': cleanup})
        require('failed stop retains exact state cleanup=' + cleanup, (state / 'wan.state').read_bytes() == old_state)
    run('entry successful stop removes state', f'{SHELL} {folder}/stop-sqm\n', environment=entry_env)
    require('successful stop removed active state', not (state / 'wan.state').exists())
    run('entry repeated no-state stop is idempotent no-op', f'{SHELL} {folder}/stop-sqm\n', absent=['CALLBACK_STOP', 'CALLBACK_CLEANUP'], environment=entry_env)
    # Actual writer and entries: fail publishing each stage, not a fake writer.
    for suffix, called in [('pending', False), ('state', True)]:
        (lib / 'functions.sh').write_text(functions + '\nSCRIPT=fixture.qos\n' + f'''
mv() {{
    for last do :; done
    case "$last" in *.{suffix}) return 38 ;; esac
    command mv "$@"
}}
''')
        run('entry failed publishing ' + suffix, f'{SHELL} {folder}/start-sqm\n', 38,
            contains=['CALLBACK_START'] if called else [], absent=[] if called else ['CALLBACK_START'], environment=entry_env)
        require('publish ' + suffix + ' never creates false active state', not (state / 'wan.state').exists())
        require('publish ' + suffix + ' preserves pending iff callback ran', (state / 'wan.pending').exists() == called)
        if called:
            (state / 'wan.pending').unlink()
    (lib / 'functions.sh').write_text(functions + '\nSCRIPT=fixture.qos\n')
    run('entry failed start returns original error', f'{SHELL} {folder}/start-sqm\n', 23, environment={**entry_env, 'START_RC': '23'})
    require('failed start keeps pending not active state', (state / 'wan.pending').exists() and not (state / 'wan.state').exists())
    run('entry pending blocks stop without guessing ownership', f'{SHELL} {folder}/stop-sqm\n', 75, absent=['CALLBACK_STOP'], environment=entry_env)
    run('entry pending blocks retry', f'{SHELL} {folder}/start-sqm\n', 1, absent=['CALLBACK_START'], environment=entry_env)
    run('entry path-like interface rejected before source', f'IFACE=../wan {SHELL} {folder}/start-sqm\n', 64,
        absent=['CALLBACK_START'], environment=entry_env)


def test_service(folder):
    init = NEW['etc/init.d/sqm']
    run('reload stop failure cannot start', extract(init, 'reload_service') + '\nstop_service() { echo STOP; return 43; }; start_service() { echo START; return 0; }; reload_service\n', 43, contains=['STOP'], absent=['START'])
    run('reload start failure preserved', extract(init, 'reload_service') + '\nstop_service() { return 0; }; start_service() { return 44; }; reload_service\n', 44)
    # Real rc.common control flow; only system/procd service effects mocked.
    host = folder / 'rc-host'
    (host / 'lib/functions').mkdir(parents=True)
    (host / 'lib/functions.sh').write_text(extract((FIX.FIXTURES / 'lib/functions.sh').read_text(), 'list_contains') + '\n')
    (host / 'lib/functions/service.sh').write_text(':\n')
    (host / 'lib/functions/procd.sh').write_text('procd_open_service() { :; }; procd_close_service() { :; }; procd_lock() { :; }; procd_kill() { :; }; procd_add_reload_trigger() { :; }\n')
    runner = folder / 'mock-run'
    runner.write_text('#!/bin/sh\necho CLI:$1\ncase "$1" in start) exit "${START_RC:-0}" ;; stop) exit "${STOP_RC:-0}" ;; esac\n')
    runner.chmod(0o755)
    initfile = folder / 'sqm.init'
    initfile.write_text(init.replace('/usr/lib/sqm/run.sh', str(runner)))
    rcfile = FIX.FIXTURES / 'etc/rc.common'
    for action, env, expected, absent in [('start', {'START_RC': '41'}, 41, []), ('stop', {'STOP_RC': '42'}, 42, []),
                                         ('reload', {'STOP_RC': '43'}, 43, ['CLI:start']),
                                         ('restart', {'STOP_RC': '43'}, 43, ['CLI:start']),
                                         ('restart', {'START_RC': '44'}, 44, []),
                                         ('start', {}, 0, []), ('stop', {}, 0, [])]:
        run('actual rc.common CLI ' + action + ' ' + str(env), f'{SHELL} {rcfile} {initfile} {action}\n', expected,
            absent=absent, environment={'IPKG_INSTROOT': str(host), **env})
    hotplug = NEW['etc/hotplug.d/iface/11-sqm']
    body = extract(hotplug, 'restart_sqm').replace('/usr/lib/sqm/run.sh', 'mock_run')
    for order in ('bad good', 'good bad'):
        run('hotplug preserves first failure order ' + order, body + f'''
ALL_DEVICES='{order}'
mock_run() {{ echo "$1:$2"; [ "$1:$2" != stop:bad ] || return 45; return 0; }}
restart_sqm
''', 45, contains=['start:good'], absent=['start:bad'])


def test_run_aggregation(folder):
    lib = folder / 'run-lib'; state = folder / 'run-state'
    lib.mkdir(); state.mkdir(); (state / 'available').mkdir()
    config = folder / 'run.conf'
    config.write_text(f'SQM_LIB_DIR={lib}\nSQM_STATE_DIR={state}\nSQM_QDISC_STATE_DIR={state}/available\n')
    callbacks = folder / 'run-functions.sh'
    callbacks.write_text(r'''
config_load() { return 0; }
config_get() { case "$2" in interface) echo "$1" ;; enabled) echo 1 ;; *) echo '' ;; esac; }
config_foreach() { for section in $SECTIONS; do "$1" "$section"; done; }
''')
    (lib / 'functions.sh').write_text('sqm_trace() { :; }; sqm_error() { echo "$*"; }; sqm_warn() { echo "$*"; }; check_state_dir() { :; }\n')
    for action in ('start', 'stop'):
        file = lib / (action + '-sqm')
        file.write_text('#!/bin/sh\necho ' + action + ':$IFACE\n[ "$IFACE" != bad ] || exit 31\n[ "$IFACE" != late ] || exit 47\nexit 0\n')
        file.chmod(0o755)
    runner = folder / 'run.sh'
    runner.write_text(NEW['usr/lib/sqm/run.sh'].replace('/lib/functions.sh', str(callbacks)).replace('/etc/sqm/sqm.conf', str(config)))
    for order in ('bad good', 'good bad'):
        run('run actual start aggregation ' + order, f'{SHELL} {runner} start\n', 31, contains=['start:bad', 'start:good'], environment={'SECTIONS': order})
    for order, expected in [('bad late good', 31), ('late bad good', 47)]:
        run('run preserves earliest distinct error ' + order, f'{SHELL} {runner} start\n', expected,
            contains=['start:bad', 'start:late', 'start:good'], environment={'SECTIONS': order})
    for name in ('bad', 'good'):
        (state / (name + '.state')).write_text(f'IFACE={name}\nSCRIPT=fixture.qos\n')
    run('run actual stop aggregation keeps earlier failure', f'{SHELL} {runner} stop\n', 31, contains=['stop:bad', 'stop:good'])
    run('run selected missing-state stop no-op', f'{SHELL} {runner} stop missing\n', absent=['stop:'])
    (state / 'pending.pending').write_text('IFACE=pending\n')
    run('run selected pending stop blocks', f'{SHELL} {runner} stop pending\n', 75, absent=['stop:pending'])


def test_known_blockers(folder):
    nss = NEW['usr/lib/sqm/nss-zk.qos']
    body = extract(nss, 'sqm_stop').replace('/sys/devices/virtual/net', str(folder / 'no-virtual')).replace('/sys/module', str(folder / 'no-modules'))
    run('BLOCKER: NSS legacy stop still tries foreign qdiscs and masks failure', body + r'''
tc() {
 case "$*" in
 'qdisc list dev wan') echo 'qdisc fq_codel 10: parent 1:1' ;;
 'qdisc show dev wan root') echo 'qdisc cake 1: root refcnt 2' ;;
 'qdisc show dev wan') echo 'qdisc ingress ffff: parent ffff:fff1' ;;
 esac
 return 0
}
mock_tc() { echo "FOREIGN_DELETE:$*"; return 7; }
sqm_stop
''', 0, contains=['FOREIGN_DELETE:qdisc del dev wan root'], known=True)
    run('NEGATIVE: original NSS add masks mid-chain failure', extract(OLD['usr/lib/sqm/nss-zk.qos'], 'add_nsstbl') +
        '\nTC_FAIL_AT=2\nadd_nsstbl wan 100000 1000 1500 NOECN\n', 0, contains=['tc:6:'], known=True)
    run('NEGATIVE: original reload starts after stop failure', extract(OLD['etc/init.d/sqm'], 'reload_service') +
        '\nstop() { return 43; }; start() { echo UNSAFE_START; return 0; }; reload_service\n', 0, contains=['UNSAFE_START'], known=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shell', default='/bin/bash', help='ash-compatible shell executable; default host bash, not target proof')
    args = parser.parse_args()
    SHELL = args.shell
    # Locked NSS code uses ash's [[ ... ]] extension. Dash may print an error
    # yet return success later, falsely greening mocks; reject it up front.
    probe = subprocess.run([SHELL, '-c', '[[ 1 == 1 ]]'], text=True, capture_output=True)
    if probe.returncode != 0 or probe.stderr.strip():
        parser.error('selected shell lacks required ash-compatible [[ ]] semantics')
    with tempfile.TemporaryDirectory(prefix='ax6-sqm-offline-') as tmp:
        folder = Path(tmp)
        RUN_CWD = folder
        test_injector(folder)
        test_nss(folder)
        test_generic()
        test_state_writer(folder)
        test_entries(folder)
        test_service(folder)
        test_run_aggregation(folder)
        test_known_blockers(folder)
    print(json.dumps({'shell': SHELL, 'method': 'actual locked functions/entries/rc.common with mocked side effects',
                      'release_gate': 'BLOCKED_OWNERSHIP_AND_TRANSACTION_INCOMPLETE',
                      'bounded_contract_tests': len(RESULTS), 'results': RESULTS,
                      'negative_controls_and_known_blockers': KNOWN}, indent=2))
