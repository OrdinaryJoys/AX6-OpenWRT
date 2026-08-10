#!/usr/bin/env bash
# AX6 routed dataplane test. Run this on a LAN client against an iperf3
# server on the WAN side so the router forwards, rather than terminates, flow.

set -euo pipefail

MODE="preflight"
CONFIRM_LOAD=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        preflight|run) MODE="$1" ;;
        --confirm-load-test) CONFIRM_LOAD=1 ;;
        -h|--help)
            cat <<'EOF'
Usage: ax6-routed-perf-test.sh [preflight|run] [--confirm-load-test]

Required environment:
  AX6_IPERF_TARGET       WAN-side iperf3 server IPv4 address
  AX6_BUILD_COMMIT       Exact AX6-OpenWRT build repository commit

Recommended environment:
  AX6_EXPECTED_SOURCE_REVISION  Expected router DISTRIB_REVISION
  AX6_EXPECT_WAN_DEVICE        Expected router egress device (for example wan)

Optional environment:
  AX6_ROUTER_IP, AX6_SSH_KEY, AX6_IPERF_PORT, AX6_RUNS,
  AX6_DURATION, AX6_PARALLEL, AX6_RESULT_DIR

The script never changes router configuration and never starts an iperf3
server on the router. Start the server on the WAN-side endpoint first.
EOF
            exit 0
            ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

ROUTER_IP="${AX6_ROUTER_IP:-192.168.5.1}"
SSH_KEY="${AX6_SSH_KEY:-${HOME}/.ssh/ax6_check}"
IPERF_TARGET="${AX6_IPERF_TARGET:-}"
IPERF_PORT="${AX6_IPERF_PORT:-15211}"
RUNS="${AX6_RUNS:-3}"
DURATION="${AX6_DURATION:-60}"
PARALLEL="${AX6_PARALLEL:-1}"
BUILD_COMMIT="${AX6_BUILD_COMMIT:-}"
EXPECTED_SOURCE_REVISION="${AX6_EXPECTED_SOURCE_REVISION:-}"
EXPECTED_WAN_DEVICE="${AX6_EXPECT_WAN_DEVICE:-}"
RESULT_DIR="${AX6_RESULT_DIR:-$PWD/ax6-routed-results}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$RESULT_DIR/$TIMESTAMP"
SUMMARY="$RUN_DIR/summary.tsv"

SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10 -i "$SSH_KEY" "root@$ROUTER_IP")
PING_PIDS=()

die() {
    echo "ax6-routed-perf-test: $*" >&2
    exit 2
}

is_uint() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

router_cmd() {
    "${SSH[@]}" "$@"
}

cleanup() {
    local pid
    for pid in "${PING_PIDS[@]:-}"; do
        [ -n "$pid" ] || continue
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}

on_signal() {
    cleanup
    exit 130
}

trap cleanup EXIT
trap on_signal INT TERM HUP

validate_inputs() {
    [ -n "$IPERF_TARGET" ] || die "set AX6_IPERF_TARGET"
    [[ "$IPERF_TARGET" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] ||
        die "AX6_IPERF_TARGET must be an IPv4 address"
    [ "$IPERF_TARGET" != "$ROUTER_IP" ] ||
        die "iperf target must not be the router itself"
    [ -n "$BUILD_COMMIT" ] || die "set AX6_BUILD_COMMIT"
    [[ "$BUILD_COMMIT" =~ ^[0-9a-f]{7,40}$ ]] ||
        die "AX6_BUILD_COMMIT must be a Git commit ID"
    if [ -n "$EXPECTED_WAN_DEVICE" ]; then
        [[ "$EXPECTED_WAN_DEVICE" =~ ^[a-zA-Z0-9_.:-]+$ ]] ||
            die "AX6_EXPECTED_WAN_DEVICE contains invalid characters"
    fi
    for value in "$IPERF_PORT" "$RUNS" "$DURATION" "$PARALLEL"; do
        is_uint "$value" || die "numeric test settings must be unsigned integers"
    done
    [ "$IPERF_PORT" -ge 1024 ] && [ "$IPERF_PORT" -le 65535 ] ||
        die "AX6_IPERF_PORT must be between 1024 and 65535"
    [ "$RUNS" -ge 1 ] && [ "$RUNS" -le 10 ] || die "AX6_RUNS must be 1..10"
    [ "$DURATION" -ge 10 ] && [ "$DURATION" -le 1800 ] ||
        die "AX6_DURATION must be 10..1800 seconds"
    [ "$PARALLEL" -ge 1 ] && [ "$PARALLEL" -le 16 ] ||
        die "AX6_PARALLEL must be 1..16"
    [ -r "$SSH_KEY" ] || die "SSH key is not readable: $SSH_KEY"
    command -v iperf3 >/dev/null || die "iperf3 is required on the LAN client"
    command -v jq >/dev/null || die "jq is required on the LAN client"
    iperf3 --help 2>&1 | grep -q -- '--bidir' ||
        die "LAN-client iperf3 does not support --bidir"
}

router_revision() {
    router_cmd ". /etc/openwrt_release; printf '%s\\n' \"\$DISTRIB_REVISION\""
}

router_boot_id() {
    router_cmd "cat /proc/sys/kernel/random/boot_id"
}

router_route() {
    router_cmd "ip route get '$IPERF_TARGET' 2>/dev/null | head -n 1"
}

preflight() {
    local revision route
    revision=$(router_revision) || die "router SSH/revision check failed"
    route=$(router_route) || die "router has no route to $IPERF_TARGET"

    if [ -n "$EXPECTED_SOURCE_REVISION" ] &&
       [ "$revision" != "$EXPECTED_SOURCE_REVISION" ]; then
        die "router revision $revision does not match $EXPECTED_SOURCE_REVISION"
    fi
    case "$route" in
        *" dev br-lan "*|*" dev lan1 "*|*" dev lan2 "*|*" dev lan3 "*)
            die "target route does not cross the routed WAN path: $route"
            ;;
    esac
    if [ -n "$EXPECTED_WAN_DEVICE" ] &&
       ! grep -Eq "(^| )dev ${EXPECTED_WAN_DEVICE}( |$)" <<<"$route"; then
        die "target route does not use expected device $EXPECTED_WAN_DEVICE: $route"
    fi

    echo "mode=$MODE"
    echo "router=$ROUTER_IP"
    echo "source_revision=$revision"
    echo "build_repo_commit=$BUILD_COMMIT"
    echo "iperf_target=$IPERF_TARGET:$IPERF_PORT"
    echo "router_route=$route"
    echo "runs=$RUNS duration=$DURATION parallel=$PARALLEL"
    iperf3 --version 2>&1 | head -n 1 | sed 's/^/iperf_client_version=/'

    if command -v nc >/dev/null 2>&1; then
        nc -z -w 3 "$IPERF_TARGET" "$IPERF_PORT" ||
            die "WAN-side iperf3 server is not reachable on port $IPERF_PORT"
        echo "iperf_server=reachable"
    else
        echo "iperf_server=not_checked (nc unavailable)"
    fi
}

collect_router_snapshot() {
    local label="$1"
    local out="$RUN_DIR/router-${label}.txt"
    router_cmd '
        echo "time=$(date -Iseconds)"
        echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
        echo "uptime=$(cat /proc/uptime)"
        echo "load=$(cat /proc/loadavg)"
        echo "nss_current_freq=$(cat /proc/sys/dev/nss/clock/current_freq 2>/dev/null || echo unavailable)"
        echo "nss_auto_scale=$(cat /proc/sys/dev/nss/clock/auto_scale 2>/dev/null || echo unavailable)"
        echo "--- softnet ---"
        cat /proc/net/softnet_stat
        echo "--- protocol_counters ---"
        grep -E "^(Tcp|Udp):" /proc/net/snmp
        echo "--- ecm_connections ---"
        cat /sys/kernel/debug/ecm/ecm_db/connection_count_simple 2>/dev/null || echo unavailable
        echo "--- edma_errors ---"
        cat /sys/kernel/debug/qca-nss-drv/stats/edma/err_stats 2>/dev/null || echo unavailable
        echo "--- interfaces ---"
        for i in wan br-lan lan1 lan2 lan3; do
            b=/sys/class/net/$i/statistics
            [ -d "$b" ] || continue
            printf "%s rx_bytes=%s tx_bytes=%s rx_err=%s tx_err=%s rx_drop=%s tx_drop=%s\n" \
                "$i" "$(cat "$b/rx_bytes")" "$(cat "$b/tx_bytes")" \
                "$(cat "$b/rx_errors")" "$(cat "$b/tx_errors")" \
                "$(cat "$b/rx_dropped")" "$(cat "$b/tx_dropped")"
        done
        echo "--- interrupts ---"
        grep -Ei "nss|edma|ath11k|reo|reo2host|ce[0-9]" /proc/interrupts || true
        echo "--- health ---"
        nss-check -q; echo "nss_check_rc=$?"
        ax6-config-audit -q; echo "config_audit_rc=$?"
    ' > "$out"
}

run_ping() {
    local label="$1"
    ping -n -i 0.2 "$IPERF_TARGET" > "$RUN_DIR/ping-${label}.txt" 2>&1 &
    PING_PIDS+=("$!")
}

stop_last_ping() {
    local index=$(( ${#PING_PIDS[@]} - 1 ))
    local pid="${PING_PIDS[$index]}"
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    PING_PIDS=()
}

record_result() {
    local direction="$1" repetition="$2" json="$3"
    local sent received retrans reverse_sent reverse_received reverse_retrans version
    sent=$(jq -r '(.end.sum_sent.bits_per_second // 0) / 1000000' "$json")
    received=$(jq -r '(.end.sum_received.bits_per_second // 0) / 1000000' "$json")
    retrans=$(jq -r '.end.sum_sent.retransmits // 0' "$json")
    reverse_sent=$(jq -r '(.end.sum_sent_bidir_reverse.bits_per_second // 0) / 1000000' "$json")
    reverse_received=$(jq -r '(.end.sum_received_bidir_reverse.bits_per_second // 0) / 1000000' "$json")
    reverse_retrans=$(jq -r '.end.sum_sent_bidir_reverse.retransmits // 0' "$json")
    version=$(jq -r '.start.version // "unknown"' "$json")
    if [ "$direction" = bidirectional ] &&
       { [ "$reverse_sent" = 0 ] || [ "$reverse_received" = 0 ]; }; then
        echo "INCOMPLETE: iperf3 JSON lacks bidirectional reverse-channel summaries" >&2
        return 1
    fi
    printf '%s\t%s\t%.3f\t%.3f\t%s\t%.3f\t%.3f\t%s\t%s\t%s\n' \
        "$direction" "$repetition" "$sent" "$received" "$retrans" \
        "$reverse_sent" "$reverse_received" "$reverse_retrans" "$version" "$json" >> "$SUMMARY"
}

run_one() {
    local direction="$1" repetition="$2"
    local label="${direction}-${repetition}"
    local json="$RUN_DIR/iperf-${label}.json"
    local -a args=(-c "$IPERF_TARGET" -p "$IPERF_PORT" -t "$DURATION" -P "$PARALLEL" -J)

    case "$direction" in
        lan_to_wan) ;;
        wan_to_lan) args+=(-R) ;;
        bidirectional) args+=(--bidir) ;;
        *) die "internal direction error: $direction" ;;
    esac

    run_ping "$label"
    if ! iperf3 "${args[@]}" > "$json"; then
        stop_last_ping
        echo "INCOMPLETE: iperf3 failed for $label" >&2
        return 1
    fi
    stop_last_ping
    if jq -e '.error? // empty' "$json" >/dev/null; then
        echo "INCOMPLETE: iperf3 reported an error for $label" >&2
        return 1
    fi
    record_result "$direction" "$repetition" "$json" || return 1
}

run_suite() {
    local boot_start boot_end repetition direction
    [ "$CONFIRM_LOAD" -eq 1 ] ||
        die "run mode requires --confirm-load-test"
    [ -n "$EXPECTED_SOURCE_REVISION" ] ||
        die "run mode requires AX6_EXPECTED_SOURCE_REVISION"

    mkdir -p "$RUN_DIR"
    printf 'direction\trepetition\tsent_mbps\treceived_mbps\tretransmits\treverse_sent_mbps\treverse_received_mbps\treverse_retransmits\tiperf_version\tjson\n' > "$SUMMARY"
    preflight | tee "$RUN_DIR/preflight.txt"
    boot_start=$(router_boot_id)
    collect_router_snapshot before

    for repetition in $(seq 1 "$RUNS"); do
        for direction in lan_to_wan wan_to_lan bidirectional; do
            run_one "$direction" "$repetition" || {
                collect_router_snapshot incomplete || true
                echo "result=INCOMPLETE" | tee -a "$RUN_DIR/result.txt"
                return 1
            }
            collect_router_snapshot "${direction}-${repetition}"
        done
    done

    collect_router_snapshot after
    boot_end=$(router_boot_id)
    [ "$boot_start" = "$boot_end" ] || {
        echo "result=INCOMPLETE reason=router_rebooted" | tee "$RUN_DIR/result.txt"
        return 1
    }
    echo "result=COMPLETE boot_id=$boot_end" | tee "$RUN_DIR/result.txt"
    echo "summary=$SUMMARY"
}

validate_inputs
case "$MODE" in
    preflight) preflight ;;
    run) run_suite ;;
esac
