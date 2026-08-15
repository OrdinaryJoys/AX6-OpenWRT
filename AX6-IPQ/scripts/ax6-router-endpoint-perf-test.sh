#!/usr/bin/env bash
# Test router host-terminated TCP throughput against a Mac endpoint.
# This is not an NSS forwarding benchmark. Router configuration is read-only.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAMPLER="${AX6_ROUTER_SAMPLER:-$SCRIPT_DIR/ax6-router-sync-sampler.sh}"
ROUTER_IP="${AX6_ROUTER_IP:-192.168.5.1}"
ENDPOINT_IP="${AX6_ENDPOINT_IP:?AX6_ENDPOINT_IP required}"
ENDPOINT_MAC="${AX6_ENDPOINT_MAC:-}"
SSH_KEY="${AX6_SSH_KEY:-${HOME}/.ssh/ax6_check}"
KNOWN_HOSTS="${AX6_KNOWN_HOSTS:-${HOME}/.ssh/known_hosts}"
PORT="${AX6_ENDPOINT_PORT:-15221}"
ROUNDS="${AX6_ROUNDS:-3}"
DURATION="${AX6_DURATION:-30}"
SAMPLE_INTERVAL="${AX6_SAMPLE_INTERVAL:-2}"
SAMPLE_GRACE="${AX6_SAMPLE_GRACE:-4}"
TIMEOUT_GRACE="${AX6_IPERF_TIMEOUT_GRACE:-20}"
STAGE_PAUSE="${AX6_STAGE_PAUSE:-2}"
OUT_BASE="${AX6_RESULT_BASE:-/tmp/ax6-router-endpoint-runs}"
LABEL="${AX6_RESULT_LABEL:-router-endpoint}"
EXPECTED_BOARD="${AX6_EXPECTED_BOARD:-}"
EXPECTED_KERNEL="${AX6_EXPECTED_KERNEL:-}"
EXPECTED_REVISION="${AX6_EXPECTED_REVISION:-}"

case "$ENDPOINT_IP" in
  ''|*[!0-9.]*) echo "invalid endpoint IPv4 address" >&2; exit 2 ;;
esac
for value in "$PORT" "$ROUNDS" "$DURATION" "$SAMPLE_INTERVAL" "$SAMPLE_GRACE" "$TIMEOUT_GRACE"; do
  case "$value" in
    ''|*[!0-9]*|0) echo "invalid positive numeric test contract" >&2; exit 2 ;;
  esac
done
case "$STAGE_PAUSE" in
  ''|*[!0-9]*) echo "stage pause must be a non-negative integer" >&2; exit 2 ;;
esac
[ -n "$EXPECTED_BOARD" ] && [ -n "$EXPECTED_KERNEL" ] && [ -n "$EXPECTED_REVISION" ] || {
  echo "expected board/kernel/revision required" >&2
  exit 2
}
[ -r "$SAMPLER" ] || { echo "router sampler missing: $SAMPLER" >&2; exit 2; }

OUT="$OUT_BASE/$(date +%Y%m%d-%H%M%S)-$LABEL"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/runner.log") 2>&1

SSH=(ssh -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KNOWN_HOSTS" root@"$ROUTER_IP")
SERVER_PID=""
CLIENT_PID=""
SAMPLER_PID=""

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

cleanup() {
  local pid
  for pid in "$CLIENT_PID" "$SERVER_PID" "$SAMPLER_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    [ -n "$pid" ] && wait "$pid" 2>/dev/null || true
  done
  CLIENT_PID="" SERVER_PID="" SAMPLER_PID=""
}

# shellcheck disable=SC2329  # Invoked through the EXIT trap below.
on_exit() {
  local rc=$?
  cleanup
  exit "$rc"
}

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

wait_pid_deadline() { # pid timeout
  local pid="$1" timeout="$2" deadline now rc=0
  deadline=$(($(date +%s) + timeout))
  while kill -0 "$pid" 2>/dev/null; do
    now=$(date +%s)
    [ "$now" -lt "$deadline" ] || return 124
    sleep 1
  done
  wait "$pid" || rc=$?
  return "$rc"
}

station_snapshot() { # output file
  local output="$1"
  {
    echo "=== date ==="; date -u +%Y-%m-%dT%H:%M:%SZ
    echo "=== station ==="
    if [ -n "$ENDPOINT_MAC" ]; then
      "${SSH[@]}" "for i in phy0-ap0 phy1-ap0; do iw dev \$i station get '$ENDPOINT_MAC' 2>/dev/null && echo interface=\$i; done; true" || true
    fi
    echo "=== interfaces ==="
    "${SSH[@]}" "for i in br-lan lan1 lan2 lan3 wan; do for c in rx_bytes tx_bytes rx_packets tx_packets rx_errors rx_dropped tx_errors tx_dropped; do printf '%s.%s=' \$i \$c; cat /sys/class/net/\$i/statistics/\$c 2>/dev/null; done; done; true" || true
  } > "$output"
}

start_sampler() { # label
  local label="$1" count ready=0
  count=$(((DURATION + SAMPLE_GRACE + SAMPLE_INTERVAL - 1) / SAMPLE_INTERVAL))
  "${SSH[@]}" "sh -s -- '$SAMPLE_INTERVAL' '$count' '$ENDPOINT_MAC'" < "$SAMPLER" \
    > "$OUT/$label-router-samples.tsv" 2> "$OUT/$label-router-samples.err" &
  SAMPLER_PID=$!
  for _ in $(seq 1 100); do
    if grep -q '^@@END_SAMPLE seq=0$' "$OUT/$label-router-samples.tsv" 2>/dev/null; then
      ready=1; break
    fi
    kill -0 "$SAMPLER_PID" 2>/dev/null || break
    sleep 0.1
  done
  [ "$ready" -eq 1 ] || { log "INCOMPLETE $label sampler_not_ready"; return 1; }
}

finish_sampler() { # label
  local label="$1" rc=0
  wait "$SAMPLER_PID" || rc=$?
  SAMPLER_PID=""
  if [ "$rc" -ne 0 ] || ! grep -q '^@@DONE ' "$OUT/$label-router-samples.tsv"; then
    log "INCOMPLETE $label sampler_incomplete rc=$rc"
    return 1
  fi
}

run_stage() { # phase mode streams round
  local phase="$1" mode="$2" streams="$3" round="$4"
  local label="$phase-$mode-r$round" timeout rc=0
  local client_json="$OUT/$label-client.json" server_json="$OUT/$label-server.json"
  local remote="iperf3 -c '$ENDPOINT_IP' -p '$PORT' -P '$streams' -t '$DURATION' -J"
  [ "$mode" = rev ] && remote="$remote -R"
  [ "$mode" = bidir ] && remote="$remote --bidir"
  timeout=$((DURATION + TIMEOUT_GRACE))

  log "START $label duration=${DURATION}s"
  iperf3 -s -B "$ENDPOINT_IP" -p "$PORT" -1 -J > "$server_json" \
    2> "$OUT/$label-server.err" &
  SERVER_PID=$!
  sleep 1
  start_sampler "$label" || return 1
  "${SSH[@]}" "$remote" > "$client_json" 2> "$OUT/$label-client.err" &
  CLIENT_PID=$!
  wait_pid_deadline "$CLIENT_PID" "$timeout" || rc=$?
  if [ "$rc" -eq 124 ]; then
    log "INCOMPLETE $label client_timeout"
    cleanup
    return 1
  fi
  CLIENT_PID=""
  [ "$rc" -eq 0 ] || { log "INCOMPLETE $label client_rc=$rc"; cleanup; return 1; }
  wait_pid_deadline "$SERVER_PID" 5 || rc=$?
  SERVER_PID=""
  [ "$rc" -eq 0 ] || { log "INCOMPLETE $label server_rc=$rc"; cleanup; return 1; }
  finish_sampler "$label" || return 1

  python3 - "$client_json" "$mode" "$label" <<'PY'
import json, sys
j = json.load(open(sys.argv[1]))
mode, label = sys.argv[2:4]
if j.get("error"):
    raise SystemExit(f"INCOMPLETE {label} json_error={j['error']}")
e = j.get("end", {})
def emit(direction, key):
    d = e.get(key) or {}
    if not d.get("seconds") or not d.get("bits_per_second"):
        raise SystemExit(f"INCOMPLETE {label} missing={key}")
    print(f"RESULT {label} {direction}: {d['bits_per_second']/1e6:.1f} Mbps retrans={d.get('retransmits', 0)}")
if mode == "fwd":
    emit("ROUTER->MAC", "sum_sent")
elif mode == "rev":
    emit("MAC->ROUTER", "sum_sent")
else:
    emit("ROUTER->MAC", "sum_sent")
    emit("MAC->ROUTER", "sum_sent_bidir_reverse")
PY
  station_snapshot "$OUT/$label-post.txt"
  [ "$STAGE_PAUSE" -eq 0 ] || sleep "$STAGE_PAUSE"
}

board=$("${SSH[@]}" cat /tmp/sysinfo/model | tr -d '\r')
kernel=$("${SSH[@]}" uname -r | tr -d '\r')
revision=$("${SSH[@]}" "grep '^DISTRIB_REVISION=' /etc/openwrt_release" | cut -d= -f2 | tr -d "'\r")
boot_id=$("${SSH[@]}" cat /proc/sys/kernel/random/boot_id | tr -d '\r')
[ "$board" = "$EXPECTED_BOARD" ] && [ "$kernel" = "$EXPECTED_KERNEL" ] && \
  [ "$revision" = "$EXPECTED_REVISION" ] || {
  log "INCOMPLETE identity mismatch board=$board kernel=$kernel revision=$revision"
  exit 1
}
{
  echo "topology=router-host-terminated"
  echo "router_ip=$ROUTER_IP"
  echo "endpoint_ip=$ENDPOINT_IP"
  echo "endpoint_mac=$ENDPOINT_MAC"
  echo "board=$board"
  echo "kernel=$kernel"
  echo "revision=$revision"
  echo "boot_id=$boot_id"
  echo "rounds=$ROUNDS"
  echo "duration=$DURATION"
  echo "sample_interval=$SAMPLE_INTERVAL"
  echo "sample_grace=$SAMPLE_GRACE"
} > "$OUT/env.txt"
station_snapshot "$OUT/pre-all.txt"

for round in $(seq 1 "$ROUNDS"); do
  run_stage P1 fwd 1 "$round"
  run_stage P1 rev 1 "$round"
  run_stage P1 bidir 1 "$round"
  run_stage P4 fwd 4 "$round"
  run_stage P4 rev 4 "$round"
  run_stage P4 bidir 4 "$round"
done

station_snapshot "$OUT/post-all.txt"
log "RUN COMPLETE $OUT"
checksum_tmp=$(mktemp "${TMPDIR:-/tmp}/ax6-router-endpoint-sha.XXXXXX")
(
  cd "$OUT" || exit 1
  find . -type f ! -name SHA256SUMS.txt -print0 |
    sort -z | xargs -0 shasum -a 256 > "$checksum_tmp"
)
mv "$checksum_tmp" "$OUT/SHA256SUMS.txt"
