#!/bin/sh
# AX6 UDP idle baseline and socket ownership capture.
# Read-only: no persistent configuration changes and no service restarts.

set -u

PROC_ROOT="${AX6_PROC_ROOT:-/proc}"
NET_CLASS="${AX6_NET_CLASS:-/sys/class/net}"
INTERVAL="${AX6_BASELINE_INTERVAL:-10}"
SAMPLES="${AX6_BASELINE_SAMPLES:-7}"
BUILD_REPO_COMMIT="${AX6_BUILD_COMMIT:-}"
SOURCE_REVISION="${AX6_SOURCE_REVISION:-}"
NSS_CHECK="${AX6_NSS_CHECK:-nss-check}"
CONFIG_AUDIT="${AX6_CONFIG_AUDIT:-ax6-config-audit}"

if [ -z "$SOURCE_REVISION" ] && [ -r /etc/openwrt_release ]; then
    SOURCE_REVISION=$(grep '^DISTRIB_REVISION=' /etc/openwrt_release 2>/dev/null |
        cut -d= -f2- | tr -d "'\"")
fi
SOURCE_REVISION="${SOURCE_REVISION:-unknown}"

fail_setup() {
    echo "ax6-udp-baseline: INCOMPLETE: $*" >&2
    exit 2
}

case "$INTERVAL:$SAMPLES" in
    *[!0-9:]*|:*) fail_setup "interval and sample count must be integers" ;;
esac
[ "$SAMPLES" -ge 2 ] || fail_setup "at least two samples are required"
[ -n "$BUILD_REPO_COMMIT" ] ||
    fail_setup "set AX6_BUILD_COMMIT to the exact build repository commit"
[ -r "$PROC_ROOT/net/snmp" ] || fail_setup "missing $PROC_ROOT/net/snmp"

udp_values() {
    # shellcheck disable=SC2046 # Split the selected SNMP value row into fields.
    set -- $(grep '^Udp:' "$PROC_ROOT/net/snmp" | tail -1)
    [ "$#" -ge 6 ] || return 1
    printf '%s %s\n' "$4" "$6"
}

softnet_drops() {
    total=0
    while read -r _processed dropped _rest; do
        value=$(printf '%d' "0x${dropped:-0}" 2>/dev/null) || value=0
        total=$((total + value))
    done < "$PROC_ROOT/net/softnet_stat"
    echo "$total"
}

socket_inodes() {
    for pid in "$@"; do
        [ -d "$PROC_ROOT/$pid/fd" ] || continue
        for fd in "$PROC_ROOT/$pid/fd/"*; do
            [ -L "$fd" ] || continue
            readlink "$fd" 2>/dev/null |
                sed -n 's/^socket:\[\([0-9][0-9]*\)\]$/\1/p'
        done
    done | sort -u | tr '\n' ' '
}

process_pids() {
    if [ "$1" = zerotier-one ] && [ -n "${AX6_ZT_PIDS:-}" ]; then
        printf '%s\n' "$AX6_ZT_PIDS"
        return
    fi
    if [ "$1" = clash ] && [ -n "${AX6_CLASH_PIDS:-}" ]; then
        printf '%s\n' "$AX6_CLASH_PIDS"
        return
    fi
    pidof "$1" 2>/dev/null | tr ' ' '\n' | sort -n | tr '\n' ' '
}

socket_drop_sum() {
    inodes="$1"
    [ -n "$inodes" ] || {
        echo 0
        return
    }
    total=0
    for table in "$PROC_ROOT/net/udp" "$PROC_ROOT/net/udp6"; do
        [ -r "$table" ] || continue
        value=$(awk -v list=" $inodes" '
            NR > 1 && index(list, " " $10 " ") { sum += $13 }
            END { print sum + 0 }
        ' "$table")
        total=$((total + value))
    done
    echo "$total"
}

show_owned_sockets() {
    owner="$1"
    inodes="$2"
    [ -n "$inodes" ] || {
        echo "  owner=$owner sockets=none"
        return
    }
    for table in "$PROC_ROOT/net/udp" "$PROC_ROOT/net/udp6"; do
        [ -r "$table" ] || continue
        proto=${table##*/}
        awk -v list=" $inodes" -v owner="$owner" -v proto="$proto" '
            NR > 1 && index(list, " " $10 " ") {
                print "  owner=" owner, "proto=" proto, "local=" $2,
                    "rxq=" $5, "drops=" $13, "inode=" $10
            }
        ' "$table"
    done
}

port_stats() {
    for iface in wan lan1 lan2 lan3 br-lan; do
        base="$NET_CLASS/$iface/statistics"
        [ -d "$base" ] || continue
        printf '%s:rx_err=%s,tx_err=%s,rx_drop=%s,tx_drop=%s ' \
            "$iface" \
            "$(cat "$base/rx_errors" 2>/dev/null)" \
            "$(cat "$base/tx_errors" 2>/dev/null)" \
            "$(cat "$base/rx_dropped" 2>/dev/null)" \
            "$(cat "$base/tx_dropped" 2>/dev/null)"
    done
    echo
}

snapshot_processes() {
    ZT_PIDS=$(process_pids zerotier-one)
    CLASH_PIDS=$(process_pids clash)
    # shellcheck disable=SC2086 # Split the normalized PID list intentionally.
    ZT_INODES=$(socket_inodes $ZT_PIDS)
    # shellcheck disable=SC2086 # Split the normalized PID list intentionally.
    CLASH_INODES=$(socket_inodes $CLASH_PIDS)
}

BOOT0=$(cat "$PROC_ROOT/sys/kernel/random/boot_id" 2>/dev/null) ||
    fail_setup "cannot read boot ID"
read -r INERR0 RCVBUF0 <<EOF
$(udp_values)
EOF
SOFT0=$(softnet_drops)
snapshot_processes
ZT_PIDS0=$ZT_PIDS
CLASH_PIDS0=$CLASH_PIDS
ZT_INODES0=$ZT_INODES
CLASH_INODES0=$CLASH_INODES
ZT_DROP0=$(socket_drop_sum "$ZT_INODES0")
CLASH_DROP0=$(socket_drop_sum "$CLASH_INODES0")
PORTS0=$(port_stats)

echo "=== AX6 UDP IDLE BASELINE $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "source_revision=$SOURCE_REVISION"
echo "build_repo_commit=$BUILD_REPO_COMMIT"
echo "boot_id=$BOOT0"
echo "zerotier_pids=${ZT_PIDS0:-none} inodes=${ZT_INODES0:-none}"
echo "clash_pids=${CLASH_PIDS0:-none} inodes=${CLASH_INODES0:-none}"
echo "start InErrors=$INERR0 RcvbufErrors=$RCVBUF0 softnet=$SOFT0 zt_drops=$ZT_DROP0 clash_drops=$CLASH_DROP0"

sample=1
while [ "$sample" -le "$SAMPLES" ]; do
    read -r inerr rcvbuf <<EOF
$(udp_values)
EOF
    soft=$(softnet_drops)
    snapshot_processes
    zt_drop=$(socket_drop_sum "$ZT_INODES")
    clash_drop=$(socket_drop_sum "$CLASH_INODES")
    echo "sample=$sample time=$(date +%H:%M:%S) InErrors=$inerr RcvbufErrors=$rcvbuf softnet=$soft zt_drops=$zt_drop clash_drops=$clash_drop"
    show_owned_sockets zerotier "$ZT_INODES"
    show_owned_sockets clash "$CLASH_INODES"
    [ "$sample" -eq "$SAMPLES" ] || sleep "$INTERVAL"
    sample=$((sample + 1))
done

BOOT1=$(cat "$PROC_ROOT/sys/kernel/random/boot_id" 2>/dev/null)
read -r INERR1 RCVBUF1 <<EOF
$(udp_values)
EOF
SOFT1=$(softnet_drops)
snapshot_processes
ZT_DROP1=$(socket_drop_sum "$ZT_INODES")
CLASH_DROP1=$(socket_drop_sum "$CLASH_INODES")
PORTS1=$(port_stats)

NSS_RC=127
AUDIT_RC=127
if command -v "$NSS_CHECK" >/dev/null 2>&1; then
    "$NSS_CHECK" -q >/dev/null 2>&1
    NSS_RC=$?
fi
if command -v "$CONFIG_AUDIT" >/dev/null 2>&1; then
    "$CONFIG_AUDIT" -q >/dev/null 2>&1
    AUDIT_RC=$?
fi

echo "delta InErrors=$((INERR1 - INERR0)) RcvbufErrors=$((RCVBUF1 - RCVBUF0)) softnet=$((SOFT1 - SOFT0)) zt_drops=$((ZT_DROP1 - ZT_DROP0)) clash_drops=$((CLASH_DROP1 - CLASH_DROP0))"
echo "ports_start=$PORTS0"
echo "ports_end=$PORTS1"
echo "nss_rc=$NSS_RC audit_rc=$AUDIT_RC boot_end=$BOOT1"
echo "socket_set_changed zerotier=$([ "$ZT_INODES0" = "$ZT_INODES" ] && echo 0 || echo 1) clash=$([ "$CLASH_INODES0" = "$CLASH_INODES" ] && echo 0 || echo 1)"

RESULT=PASS
REASON=none
EXIT_RC=0
if [ "$BOOT0" != "$BOOT1" ] || [ "$ZT_PIDS0" != "$ZT_PIDS" ] ||
   [ "$CLASH_PIDS0" != "$CLASH_PIDS" ] || [ "$ZT_INODES0" != "$ZT_INODES" ]; then
    RESULT=INCOMPLETE
    REASON=boot_or_socket_owner_changed
    EXIT_RC=2
elif [ "$INERR1" -ne "$INERR0" ] || [ "$RCVBUF1" -ne "$RCVBUF0" ] ||
     [ "$SOFT1" -ne "$SOFT0" ] || [ "$ZT_DROP1" -gt "$ZT_DROP0" ] ||
     [ "$CLASH_DROP1" -gt "$CLASH_DROP0" ] || [ "$NSS_RC" -ne 0 ] ||
     [ "$AUDIT_RC" -ne 0 ]; then
    RESULT=FAIL
    REASON=counter_or_health_gate_changed
    EXIT_RC=1
fi

echo "result=$RESULT reason=$REASON"
exit "$EXIT_RC"
