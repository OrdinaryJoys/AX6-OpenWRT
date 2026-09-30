#!/usr/bin/env python3
"""Generate an OFFLINE, NON-DEPLOYABLE SQM error/state candidate.

Locked algorithm sources: generic 20ba92639546, NSS 4b4ed8639229.
This is NOT a resource transaction or ownership fix. The explicit acknowledgement
and persistent blocker manifest prevent this prototype being mistaken for one.
Never run this transformer against a live router root; it executes no SQM code.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

FIXTURES = Path(__file__).resolve().parents[2] / 'tests/fixtures/sqm-locked'
MARKER = '# AX6 SQM error-state candidate v1; OWNERSHIP INCOMPLETE — NOT DEPLOYABLE\n'
FILES = ('usr/lib/sqm/functions.sh', 'usr/lib/sqm/nss-zk.qos',
         'usr/lib/sqm/start-sqm', 'usr/lib/sqm/stop-sqm', 'usr/lib/sqm/run.sh',
         'etc/init.d/sqm', 'etc/hotplug.d/iface/11-sqm')
BLOCKERS = [
    'No resource ownership journal (instance, ifindex, exact qdisc/filter/IFB identities).',
    'NSS/generic stop and cleanup still contain legacy deletion of potentially foreign resources.',
    'Some legacy stop/cleanup internals still mask errors; this patch only preserves returned callback errors.',
    'No compensating rollback; failed start preserves .pending and refuses automatic cleanup or retry.',
    'No netlink multi-command atomicity; no interruption/SIGKILL or stale-lock recovery claim.',
    'rc.common/procd outer lock/close/kill failures are not fully covered; shared rc.common is unchanged.',
    'No on-device lifecycle, kernel qdisc, BusyBox target, or real CAKE/NSS performance validation.',
]


def replace_one(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Exact anchor count changed: ' + repr(old[:90]))
    return text.replace(old, new, 1)


def replace_function(text, name, new):
    pattern = re.compile(r'(?ms)^' + re.escape(name) + r'\(\)\s*\{\n.*?^\}')
    if len(pattern.findall(text)) != 1:
        raise ValueError('Function anchor changed: ' + name)
    return pattern.sub(lambda _: new.strip(), text, count=1)


WRITE_STATE = r'''
write_state_file() (
    # Subshell: private cleanup trap, umask and variables do not leak to SQM.
    umask 077
    filename=$1
    vars= sorted= staged=
    trap '[ -z "$vars" ] || rm -f -- "$vars"; [ -z "$sorted" ] || rm -f -- "$sorted"; [ -z "$staged" ] || rm -f -- "$staged"' 0
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
    vars=$(mktemp "${filename}.vars.XXXXXX") || exit $?
    sorted=$(mktemp "${filename}.sorted.XXXXXX") || exit $?
    staged=$(mktemp "${filename}.tmp.XXXXXX") || exit $?
    awk 'match($0, /[A-Z0-9_]+=/) {print substr($0, RSTART, RLENGTH-1)}' \
        "${SQM_LIB_DIR}/defaults.sh" > "$vars" || exit $?
    sort -u "$vars" > "$sorted" || exit $?
    [ -s "$sorted" ] || exit 65
    while IFS= read -r var; do
        case "$var" in ''|[0-9]*|*[!A-Z0-9_]*) exit 65 ;; esac
        eval "val=\${$var-}"
        # Sentinel preserves trailing newlines across command substitution.
        escaped=$(printf '%sX' "$val" | sed "s/'/'\\\\''/g") || exit $?
        escaped=${escaped%X}
        printf "%s='%s'\n" "$var" "$escaped" || exit $?
    done < "$sorted" > "$staged" || exit $?
    [ -s "$staged" ] || exit 65
    mv -f -- "$staged" "$filename" || exit $?
    staged=
    exit 0
)
'''

NSS_START = r'''
sqm_start() {
  local protocol rc
  [ -n "$IFACE" ] || return 1
  network_get_protocol protocol "$IFACE"
  if [ "$protocol" = wireguard ]; then
    sqm_error "sqm_start: Wireguard interfaces (${IFACE}) are NOT supported by NSS"
    return 1
  fi
  DEV="ifb@${IFACE}"
  # Source-time guards must never skip stop. A pre-existing IFB is not ours.
  if [ -e "/sys/class/net/${DEV}" ]; then
    sqm_error "sqm_start: existing ${DEV}; ownership unknown, refusing to start"
    return 73
  fi
  ipt_log_restart || return $?
  check_addr || return $?
  sqm_prepare_script || return $?
  if [ "${UPLINK}" -ne 0 ]; then
    CUR_DIRECTION=egress
    fn_exists egress || return 69
    egress || { rc=$?; sqm_error "sqm_start: egress failed"; return "$rc"; }
    sqm_log "sqm_start: egress shaping activated"
  else
    # A disabled direction is not authorization to delete an existing root.
    sqm_log "sqm_start: egress shaping disabled; no deletion"
  fi
  if [ "${DOWNLINK}" -ne 0 ]; then
    CUR_DIRECTION=ingress
    fn_exists ingress || return 69
    ingress || { rc=$?; sqm_error "sqm_start: ingress failed"; return "$rc"; }
    sqm_log "sqm_start: ingress shaping activated"
  else
    sqm_log "sqm_start: ingress shaping disabled; no deletion"
  fi
  return 0
}
'''

START_TAIL = r'''
# Persist parameters BEFORE the first callback. A .pending file is NOT ownership
# proof and must never authorize automatic cleanup. It blocks automatic retry.
PENDING_FILE="${SQM_STATE_DIR}/${IFACE}.pending"
write_state_file "$PENDING_FILE" || exit $?
if fn_exists sqm_start; then
    sqm_start
else
    sqm_start_default
fi
rc=$?
if [ "$rc" -ne 0 ]; then
    sqm_error "SQM start failed on ${IFACE}; pending parameters retained, no automatic rollback"
    exit "$rc"
fi
write_state_file "$STATE_FILE" || exit $?
rm -f -- "$PENDING_FILE" || exit $?
sqm_log "${SCRIPT} was started on ${IFACE} successfully"
exit 0
'''


def transforms(original):
    result = dict(original)
    fun = result['usr/lib/sqm/functions.sh']
    fun = replace_function(fun, 'write_state_file', WRITE_STATE)
    fun = replace_function(fun, 'do_modules', r'''
do_modules() {
    for m in $ALL_MODULES; do
        [ -d "/sys/module/${m}" ] || ${INSMOD} "$m" 2>>"${OUTPUT_TARGET}" || return $?
    done
    return 0
}''')
    fun = replace_one(fun, '        sqm_prepare_script\n', '        sqm_prepare_script || return $?\n')
    fun = replace_one(fun, '    do_modules\n', '    do_modules || return $?\n')
    for direction in ('egress', 'ingress'):
        old = '\tfn_exists ' + direction + ' && ' + direction + ' || sqm_warn "sqm_start_default: ${SCRIPT} lacks an ' + direction + '() function"'
        new = '\tfn_exists ' + direction + ' || return 69\n\t' + direction + ' || return $?'
        fun = replace_one(fun, old, new)
    # No deletion is authorised by an explicit disabled direction.
    fun = replace_one(fun, '        SILENT=1 $TC qdisc del dev ${IFACE} root\n', '')
    fun = replace_one(fun, '        SILENT=1 $TC qdisc del dev ${DEV} root\n        SILENT=1 $TC qdisc del dev ${IFACE} ingress\n', '')
    result['usr/lib/sqm/functions.sh'] = fun

    nss = result['usr/lib/sqm/nss-zk.qos']
    start = nss.index('if [ -n "${ACTION}" ]')
    end = nss.index('# the maximum', start)
    nss = nss[:start] + '# Start preflight lives in sqm_start; sourcing must not exit stop-sqm.\n\n' + nss[end:]
    # Preserve locked algorithms and parameters byte-for-byte; add only guards.
    for name in ('add_nsstbl', 'add_nssfq_codel', 'ingress'):
        match = re.search(r'(?ms)^' + name + r'\(\)\s*\{\n.*?^\}', nss)
        body = match.group(0)
        patched = re.sub(r'(?m)^(  \$(?:TC|IP) .+)$', r'\1 || return $?', body)
        nss = nss[:match.start()] + patched + nss[match.end():]
    nss = replace_function(nss, 'sqm_start', NSS_START)
    # Preserve the real child error even if logging fails.
    for name in ('egress', 'ingress', 'sqm_prepare_script'):
        match = re.search(r'(?ms)^' + name + r'\(\)\s*\{\n.*?^\}', nss)
        body = match.group(0)
        body = body.replace(name + '() {\n', name + '() {\n  local rc\n', 1)
        body = re.sub(r'(\|\| \{\n)(\s+sqm_error [^\n]+\n)(\s+)return 1',
                      r'\1\3rc=$?\n\2\3return "$rc"', body)
        nss = nss[:match.start()] + body + nss[match.end():]
    result['usr/lib/sqm/nss-zk.qos'] = nss

    start = result['usr/lib/sqm/start-sqm']
    start = replace_one(start, '[ -n "$IFACE" ] || exit 1',
                        '[ -n "$IFACE" ] || exit 1\ncase "$IFACE" in *[!A-Za-z0-9_.:@-]*) exit 64 ;; esac')
    start = replace_one(start, 'if [ -f "${STATE_FILE}" ]; then',
                        'if [ -f "${STATE_FILE}" ] || [ -e "${SQM_STATE_DIR}/${IFACE}.pending" ]; then')
    start = start[:start.index('if fn_exists sqm_start ; then')] + START_TAIL.lstrip()
    result['usr/lib/sqm/start-sqm'] = start

    stop = result['usr/lib/sqm/stop-sqm']
    stop = replace_one(stop, '[ -n "$IFACE" ] || exit 1',
                       '[ -n "$IFACE" ] || exit 1\ncase "$IFACE" in *[!A-Za-z0-9_.:@-]*) exit 64 ;; esac')
    stop = replace_one(stop, 'if [ ! -f "${SQM_STATE_DIR}/${IFACE}.state" ] ; then\n    sqm_error "State file does not exist; SQM was not running on interface ${IFACE}"\n    exit 1\nfi',
                       'if [ -e "${SQM_STATE_DIR}/${IFACE}.pending" ]; then\n    sqm_error "Unfinished SQM start on ${IFACE}; no ownership proof, refusing automatic cleanup"\n    exit 75\nfi\nif [ ! -f "${SQM_STATE_DIR}/${IFACE}.state" ]; then\n    # Idempotent no-state stop: do not inspect or delete kernel resources.\n    exit 0\nfi')
    stop = replace_one(stop, '    sqm_cleanup 1\n', '    sqm_cleanup 1 || exit $?\n')
    stop = replace_one(stop, '    sqm_stop\n', '    sqm_stop || exit $?\n')
    stop = replace_one(stop, 'rm -f "${STATE_FILE}"', 'rm -f -- "${STATE_FILE}" || exit $?')
    result['usr/lib/sqm/stop-sqm'] = stop

    run = result['usr/lib/sqm/run.sh']
    run = replace_one(run, 'RUN_IFACE="$2"', 'RUN_IFACE="$2"\nFIRST_RC=0\ncase "$ACTION" in start|stop|cleanup) ;; *) exit 64 ;; esac')
    run = replace_one(run, '    [ -f "$f" ] && ( . "$f";',
                      '    if [ -e "${f%.state}.pending" ]; then\n        sqm_error "Unfinished SQM start; automatic cleanup blocked: ${f%.state}.pending"\n        return 75\n    fi\n    [ -f "$f" ] || return 0\n    ( . "$f";')
    run = replace_one(run, '    "${SQM_LIB_DIR}/start-sqm"\n',
                      '    "${SQM_LIB_DIR}/start-sqm"\n    local rc=$?\n    [ "$FIRST_RC" -ne 0 ] || FIRST_RC=$rc\n    return 0\n')
    run = replace_one(run, '    [ -f "${SQM_STATE_DIR}/${IFACE}.state" ] && return',
                      '    [ -f "${SQM_STATE_DIR}/${IFACE}.state" ] && [ ! -e "${SQM_STATE_DIR}/${IFACE}.pending" ] && return 0')
    run = replace_one(run, '    rm -rf "$LOCKDIR"\n    return 0',
                      '    rm -f -- "$LOCKDIR/pid" || return $?\n    rmdir -- "$LOCKDIR"')
    run = replace_one(run, '        echo $$ > "$LOCKDIR/pid"',
                      '        echo $$ > "$LOCKDIR/pid" || { rc=$?; rmdir -- "$LOCKDIR"; return "$rc"; }')
    tail = r'''
if [ "$ACTION" = stop ]; then
    if [ -z "$RUN_IFACE" ]; then
        for f in "${SQM_STATE_DIR}"/*.state "${SQM_STATE_DIR}"/*.pending; do
            case "$f" in *.pending) f="${f%.pending}.state" ;; esac
            stop_statefile "$f"
            rc=$?
            [ "$FIRST_RC" -ne 0 ] || FIRST_RC=$rc
        done
    else
        stop_statefile "${SQM_STATE_DIR}/${RUN_IFACE}.state"
        FIRST_RC=$?
    fi
else
    config_load sqm || exit $?
    config_foreach start_sqm_section
    rc=$?
    [ "$FIRST_RC" -ne 0 ] || FIRST_RC=$rc
fi
exit "$FIRST_RC"
'''
    run = run[:run.index('if [ "$ACTION" = "stop" ]; then')] + tail.lstrip()
    result['usr/lib/sqm/run.sh'] = run

    init = result['etc/init.d/sqm']
    init = replace_one(init, '\tstop "$@"\n\tstart "$@"',
                       '\t# Avoid rc.common stop/start masking this callback status.\n\tstop_service "$@" || return $?\n\tstart_service "$@"')
    init = replace_one(init, '\t/usr/lib/sqm/run.sh start "$@"',
                       '\t/usr/lib/sqm/run.sh start "$@"\n\tAX6_SQM_START_RC=$?\n\treturn "$AX6_SQM_START_RC"')
    init = replace_one(init, '\t/usr/lib/sqm/run.sh stop "$@"',
                       '\t/usr/lib/sqm/run.sh stop "$@"\n\tAX6_SQM_STOP_RC=$?\n\treturn "$AX6_SQM_STOP_RC"')
    init += '\n# Preserve returned SQM errors through rc.common hooks; outer procd errors remain a blocker.\nservice_started() { return "${AX6_SQM_START_RC:-1}"; }\nservice_stopped() { return "${AX6_SQM_STOP_RC:-1}"; }\n'
    init += '\n# rc.common restart otherwise unconditionally starts after a failed stop.\nrestart() { reload_service "$@"; }\n'
    result['etc/init.d/sqm'] = init

    hotplug = result['etc/hotplug.d/iface/11-sqm']
    hotplug = replace_function(hotplug, 'restart_sqm', r'''
restart_sqm() {
    local dev rc first=0
    for dev in $ALL_DEVICES; do
        /usr/lib/sqm/run.sh stop "$dev"
        rc=$?
        if [ "$rc" -eq 0 ]; then
            /usr/lib/sqm/run.sh start "$dev"
            rc=$?
        fi
        [ "$first" -ne 0 ] || first=$rc
    done
    return "$first"
}''')
    hotplug = hotplug[:hotplug.index('[ "$ACTION" = ifup ]')] + r'''
case "$ACTION" in
    ifup)
        /etc/init.d/sqm enabled || exit 0
        restart_sqm
        exit $?
        ;;
    ifdown)
        first=0
        for dev in $ALL_DEVICES; do
            /usr/lib/sqm/run.sh stop "$dev"
            rc=$?
            [ "$first" -ne 0 ] || first=$rc
        done
        exit "$first"
        ;;
esac
exit 0
'''
    result['etc/hotplug.d/iface/11-sqm'] = hotplug
    return {name: text.replace('\n', '\n' + MARKER, 1) for name, text in result.items()}


def expected():
    # The reference data must not silently redefine the claimed locked input.
    hashes = {}
    for line in (FIXTURES / 'SHA256SUMS.txt').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if name in hashes or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('Invalid locked fixture checksum manifest')
        hashes[name] = digest
    required = set(FILES) | {'usr/lib/sqm/defaults.sh', 'etc/rc.common', 'lib/functions.sh'}
    if set(hashes) != required:
        raise ValueError('Incomplete locked fixture checksum manifest')
    for name, digest in hashes.items():
        path = FIXTURES / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Locked reference fixture drift: ' + name)
    return {name: (FIXTURES / name).read_text() for name in FILES}


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def apply(root, acknowledge=False, check=False):
    if not acknowledge:
        raise ValueError('OWNERSHIP BLOCKER: requires --acknowledge-incomplete-ownership; offline evaluation only')
    root = root.resolve()
    if root in (Path('/'), Path('/usr'), Path('/etc')):
        raise ValueError('Refusing live/system root')
    old = expected()
    new = transforms(old)
    # Validate EVERY file before ANY write; exact pinned old or exact generated new.
    for name in FILES:
        path = root / name
        if path.is_symlink() or root not in path.resolve().parents:
            raise ValueError('Symlink/path escape: ' + name)
        current = path.read_text()
        if current not in (old[name], new[name]):
            raise ValueError('Locked input drift (no files changed): ' + name)
        if check and current != new[name]:
            raise ValueError('Unpatched candidate: ' + name)
    manifest = {'status': 'OFFLINE_ONLY_NOT_DEPLOYABLE', 'ownership_gate': 'FAIL_NOT_IMPLEMENTED',
                'blockers': BLOCKERS, 'generic_commit': '20ba92639546075d8e39346dcb88a3cdfe8ee903',
                'nss_commit': '4b4ed8639229be5e70cf94b73cdf7dbc09e66d5d',
                'files': {name: {'before_sha256': sha(old[name]), 'after_sha256': sha(new[name])} for name in FILES}}
    if not check:
        for name in FILES:
            path = root / name
            with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as temporary:
                temporary.write(new[name])
                staging = Path(temporary.name)
            staging.chmod(path.stat().st_mode & 0o777)
            os.replace(staging, path)
        (root / 'AX6-SQM-INCOMPLETE-OWNERSHIP.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='offline extracted/staged rootfs, never a live root')
    parser.add_argument('--acknowledge-incomplete-ownership', action='store_true')
    parser.add_argument('--check', action='store_true', help='validate exact patched bytes without writing')
    args = parser.parse_args()
    try:
        report = apply(args.root, args.acknowledge_incomplete_ownership, args.check)
    except (ValueError, OSError) as error:
        parser.exit(1, 'SQM offline candidate refused: ' + str(error) + '\n')
    print(json.dumps(report, indent=2))
