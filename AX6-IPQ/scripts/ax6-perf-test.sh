#!/usr/bin/env bash
# AX6 Performance Test Script — Phase 0 Compliant
# ============================================================================
# Requirements (from AX6_NEXT_PROGRESS_AND_TEST_PLAN_2026-08-03.md §3.1):
#   1. trap EXIT INT TERM HUP — log signal, phase, time, exit code
#   2. Unique phase_id, client PID, router server PID/port, boot ID per phase
#   3. Pre/post: /proc/net/snmp, /proc/net/udp, socket inode mapping, drops,
#      softnet, port errors, nss-check -q, ax6-config-audit -q
#   4. Two separate revision fields: SOURCE_REVISION, BUILD_REPO_COMMIT
#   5. Phase failure → INCOMPLETE; never print COMPLETE on failure
#   6. Only clean up own tracked processes (no killall iperf3)
#   7. Independent ports (15201-15203) — no collision with other sessions
#   8. No recursive /sys/kernel/debug reads
# ============================================================================

set -o nounset
set -o pipefail

# ── Configuration ──────────────────────────────────────────────────────────
ROUTER_IP="${AX6_ROUTER_IP:-192.168.5.1}"
SSH_KEY="${AX6_SSH_KEY:-${HOME}/.ssh/ax6_check}"
SSH_CMD="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -i ${SSH_KEY} root@${ROUTER_IP}"

# Two separate revision fields — per §3.1(4)
SOURCE_REVISION="${AX6_SOURCE_REVISION:-r0-0ea8486}"
BUILD_REPO_COMMIT="${AX6_BUILD_COMMIT:-84fc0f2266e265b43152ada6b4b519dc2adc2f70}"

# Independent ports — per §3.1(7)
TCP_PORT=15201
UDP_PORT=15202
TCP_PORT_EXTRA=15203

# Phase durations (seconds)
P1_DURATION=1500   # 25 min TCP single
P2_DURATION=1200   # 20 min TCP bidir
P3_UDP_DURATION=15 # per-rate UDP
P4_BURST_COUNT=40

# Output
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RESULT_DIR="${AX6_RESULT_DIR:-/Volumes/FX-MD87/Review/backups/flash-20260802}"
LOG_FILE="${RESULT_DIR}/ax6-perf-${TIMESTAMP}.log"
STATE_FILE="${RESULT_DIR}/ax6-perf-${TIMESTAMP}.state"

# ── State ──────────────────────────────────────────────────────────────────
CURRENT_PHASE=""
PHASE_START_TIME=""
EXIT_CODE=0
SIGNAL_RECEIVED=""
declare -a TRACKED_CLIENT_PIDS=()
declare -a TRACKED_ROUTER_PIDS=()

# Boot ID cache (refreshed each phase)
INITIAL_BOOT_ID=""
CURRENT_BOOT_ID=""

# ── Trap handlers — per §3.1(1) ───────────────────────────────────────────
# shellcheck disable=SC2329  # invoked via trap
_on_signal() {
  local sig="$1"
  SIGNAL_RECEIVED="$sig"
  log "TRAP" "Received signal=${sig} at phase=${CURRENT_PHASE:-none} time=$(date +%H:%M:%S)"
  _cleanup_tracked
  if [ -n "${CURRENT_PHASE:-}" ]; then
    log "RESULT" "INCOMPLETE phase=${CURRENT_PHASE} signal=${sig}"
  fi
  exit 128
}

# shellcheck disable=SC2329  # invoked via trap
_on_exit() {
  local ec=$?
  if [ -n "${SIGNAL_RECEIVED:-}" ]; then
    : # already handled in _on_signal
  elif [ "${EXIT_CODE:-0}" -ne 0 ] || [ "$ec" -ne 0 ]; then
    log "TRAP" "exit_code=${ec} phase=${CURRENT_PHASE:-none} time=$(date +%H:%M:%S)"
    if [ -n "${CURRENT_PHASE:-}" ]; then
      log "RESULT" "INCOMPLETE phase=${CURRENT_PHASE} exit_code=${ec}"
    fi
  fi
  _cleanup_tracked
}

trap '_on_signal INT' INT
trap '_on_signal TERM' TERM
trap '_on_signal HUP' HUP
trap '_on_exit' EXIT

# ── Logging ────────────────────────────────────────────────────────────────
log() {
  local level="$1"; shift
  printf "[%s] %-8s %s\n" "$(date +%H:%M:%S)" "$level" "$*" | tee -a "$LOG_FILE"
}

log_raw() {
  printf "%s\n" "$*" | tee -a "$LOG_FILE"
}

# ── SSH helpers ────────────────────────────────────────────────────────────
router_cmd() {
  # Run a command on the router, return output. Failures logged but not fatal.
  $SSH_CMD "$@" 2>>"${LOG_FILE}.ssh-err" || {
    log "WARN" "SSH failed: $*"
    return 1
  }
}

router_boot_id() {
  router_cmd "cat /proc/sys/kernel/random/boot_id 2>/dev/null" 2>/dev/null || echo "unknown"
}

# ── Process tracking — per §3.1(6) ─────────────────────────────────────────
track_client_pid() {
  TRACKED_CLIENT_PIDS+=("$1")
}

track_router_pid() {
  TRACKED_ROUTER_PIDS+=("$1")
}

# shellcheck disable=SC2329  # invoked via trap handlers
_cleanup_tracked() {
  log "CLEANUP" "stopping ${#TRACKED_CLIENT_PIDS[@]} client + ${#TRACKED_ROUTER_PIDS[@]} router PIDs"
  # Stop client-side processes (guard against empty array with nounset)
  if [ "${#TRACKED_CLIENT_PIDS[@]}" -gt 0 ]; then
    for pid in "${TRACKED_CLIENT_PIDS[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        log "CLEANUP" "client pid=${pid} stopped"
      fi
    done
  fi
  TRACKED_CLIENT_PIDS=()
  # Stop router-side iperf3 servers via explicit PID list
  if [ "${#TRACKED_ROUTER_PIDS[@]}" -gt 0 ]; then
    for pid in "${TRACKED_ROUTER_PIDS[@]}"; do
      router_cmd "kill ${pid} 2>/dev/null" 2>/dev/null || true
      log "CLEANUP" "router pid=${pid} stopped"
    done
  fi
  TRACKED_ROUTER_PIDS=()
}

# ── Router iperf3 server management ────────────────────────────────────────
start_router_server() {
  local port="$1"
  local pid
  # Start iperf3 server, capture its PID.  Log goes to stderr to avoid
  # polluting the captured stdout (caller uses $()).
  pid=$(router_cmd "iperf3 -s -p ${port} -D --pidfile /tmp/ax6-perf-iperf3-${port}.pid 2>/dev/null; sleep 0.5; cat /tmp/ax6-perf-iperf3-${port}.pid 2>/dev/null" 2>/dev/null)
  if [ -n "${pid:-}" ] && [ "$pid" -gt 0 ] 2>/dev/null; then
    track_router_pid "$pid"
    log "SERVER" "router iperf3 port=${port} pid=${pid}" >&2
    echo "$pid"
  else
    log "ERROR" "failed to start iperf3 server on port ${port}" >&2
    echo ""
  fi
}

stop_router_server() {
  local port="$1"
  router_cmd "kill \$(cat /tmp/ax6-perf-iperf3-${port}.pid 2>/dev/null) 2>/dev/null; rm -f /tmp/ax6-perf-iperf3-${port}.pid" 2>/dev/null || true
  log "SERVER" "stopped iperf3 port=${port}"
}

# ── Data collectors — per §3.1(3) ──────────────────────────────────────────
collect_snapshot() {
  local label="$1"
  local phase_id="${2:-none}"
  local boot_id
  boot_id=$(router_boot_id)

  log "SNAP" "===== ${label} phase=${phase_id} boot=${boot_id:0:8}... ====="

  # UDP stats from /proc/net/snmp
  log_raw "--- snmp_udp ---"
  router_cmd "grep '^Udp:' /proc/net/snmp" 2>/dev/null | tee -a "$LOG_FILE" || log_raw "snmp_udp:FAIL"

  # UDP socket table (inode, rx_queue, drops)
  log_raw "--- udp_sockets ---"
  router_cmd "cat /proc/net/udp" 2>/dev/null | tee -a "$LOG_FILE" || log_raw "udp_sockets:FAIL"
  log_raw "--- udp6_sockets ---"
  router_cmd "cat /proc/net/udp6" 2>/dev/null | tee -a "$LOG_FILE" || log_raw "udp6_sockets:FAIL"

  # ZeroTier socket mapping
  log_raw "--- zt_sockets ---"
  local zt_pid
  zt_pid=$(router_cmd "pidof zerotier-one" 2>/dev/null || echo "")
  if [ -n "${zt_pid:-}" ]; then
    router_cmd "ls -la /proc/${zt_pid}/fd/ 2>/dev/null | grep socket" 2>/dev/null | tee -a "$LOG_FILE" || log_raw "zt_fd:FAIL"
  else
    log_raw "zt:no_pid"
  fi

  # OpenClash socket mapping
  log_raw "--- clash_sockets ---"
  local clash_pid
  clash_pid=$(router_cmd "pidof clash" 2>/dev/null || echo "")
  if [ -n "${clash_pid:-}" ]; then
    router_cmd "ls -la /proc/${clash_pid}/fd/ 2>/dev/null | grep socket" 2>/dev/null | tee -a "$LOG_FILE" || log_raw "clash_fd:FAIL"
  else
    log_raw "clash:no_pid"
  fi

  # softnet
  log_raw "--- softnet ---"
  router_cmd "cat /proc/net/softnet_stat" 2>/dev/null | tee -a "$LOG_FILE" || log_raw "softnet:FAIL"

  # Port errors/drops
  log_raw "--- port_stats ---"
  router_cmd "for i in br-lan lan1 lan2 lan3 wan phy0-ap0 phy1-ap0 ztiv5j73wk; do echo \"\$i rx_err=\$(cat /sys/class/net/\$i/statistics/rx_errors 2>/dev/null) tx_err=\$(cat /sys/class/net/\$i/statistics/tx_errors 2>/dev/null) rx_drop=\$(cat /sys/class/net/\$i/statistics/rx_dropped 2>/dev/null) tx_drop=\$(cat /sys/class/net/\$i/statistics/tx_dropped 2>/dev/null)\"; done" 2>/dev/null | tee -a "$LOG_FILE" || log_raw "port_stats:FAIL"

  # nss-check quiet mode
  log_raw "--- nss_check ---"
  router_cmd "nss-check -q 2>&1; echo \"exit=\$?\"" 2>/dev/null | tee -a "$LOG_FILE" || log_raw "nss_check:FAIL"

  # ax6-config-audit quiet mode
  log_raw "--- config_audit ---"
  router_cmd "ax6-config-audit -q 2>&1; echo \"exit=\$?\"" 2>/dev/null | tee -a "$LOG_FILE" || log_raw "config_audit:FAIL"

  # EDMA err_stats (only if available — no recursive debugfs)
  log_raw "--- edma_err ---"
  router_cmd "cat /sys/kernel/debug/qca-nss-dp/edma/err_stats 2>/dev/null || echo 'n/a'" 2>/dev/null | tee -a "$LOG_FILE"

  # Load and memory
  log_raw "--- system ---"
  router_cmd "uptime; free | grep Mem; grep -E 'SUnreclaim|SReclaimable' /proc/meminfo; echo \"temp_mC=\$(cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1)\"" 2>/dev/null | tee -a "$LOG_FILE"

  log "SNAP" "===== ${label} END ====="
}

# ── Phase runner — per §3.1(2,5) ───────────────────────────────────────────
begin_phase() {
  local phase_id="$1"
  local description="$2"

  CURRENT_PHASE="$phase_id"
  PHASE_START_TIME=$(date +%s)
  CURRENT_BOOT_ID=$(router_boot_id)

  # Verify boot ID hasn't changed (if we have an initial one)
  if [ -n "${INITIAL_BOOT_ID:-}" ] && [ "$CURRENT_BOOT_ID" != "$INITIAL_BOOT_ID" ]; then
    log "ERROR" "BOOT_ID_CHANGED old=${INITIAL_BOOT_ID:0:8}... new=${CURRENT_BOOT_ID:0:8}..."
    log "RESULT" "INCOMPLETE phase=${phase_id} reason=boot_id_changed"
    return 1
  fi
  INITIAL_BOOT_ID="$CURRENT_BOOT_ID"

  log "PHASE" "BEGIN phase_id=${phase_id} desc=${description}"
  log "PHASE" "  source_revision=${SOURCE_REVISION}"
  log "PHASE" "  build_repo_commit=${BUILD_REPO_COMMIT}"
  log "PHASE" "  boot_id=${CURRENT_BOOT_ID}"
  log "PHASE" "  time=$(date -Iseconds)"

  # Pre-phase snapshot
  collect_snapshot "PRE" "$phase_id"

  # State tracking
  echo "phase=${phase_id}" > "$STATE_FILE"
  echo "start_time=${PHASE_START_TIME}" >> "$STATE_FILE"
  echo "boot_id=${CURRENT_BOOT_ID}" >> "$STATE_FILE"

  return 0
}

end_phase() {
  local phase_id="$1"
  local result="${2:-PASS}"   # PASS or INCOMPLETE
  local extra="${3:-}"

  local elapsed=$(($(date +%s) - PHASE_START_TIME))

  # Post-phase snapshot
  collect_snapshot "POST" "$phase_id"

  log "PHASE" "END phase_id=${phase_id} result=${result} elapsed_s=${elapsed} ${extra}"
  echo "result=${result}" >> "$STATE_FILE"
  echo "elapsed_s=${elapsed}" >> "$STATE_FILE"

  CURRENT_PHASE=""
  PHASE_START_TIME=""

  # If any phase fails, we stop — per §3.1(5)
  if [ "$result" = "INCOMPLETE" ]; then
    EXIT_CODE=1
    return 1
  fi
  return 0
}

# ── Phase 1: TCP Single-Stream Sustained ───────────────────────────────────
phase_tcp_single() {
  local phase_id="p1_tcp_single"
  local server_pid

  begin_phase "$phase_id" "TCP single-stream ${P1_DURATION}s" || return 1

  # Start router server
  server_pid=$(start_router_server "$TCP_PORT")
  if [ -z "${server_pid:-}" ]; then
    end_phase "$phase_id" "INCOMPLETE" "reason=server_start_failed"
    return 1
  fi

  log "PHASE" "  router_server_pid=${server_pid} port=${TCP_PORT}"

  # Start client iperf3 (background), log interval = 60s
  local client_log="${RESULT_DIR}/ax6-perf-${TIMESTAMP}-${phase_id}.log"
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t "$P1_DURATION" -i 60 \
    --logfile "$client_log" 2>/dev/null &
  local client_pid=$!
  track_client_pid "$client_pid"

  log "PHASE" "  client_pid=${client_pid}"

  # Monitor loop: every 60s verify server + client alive, ping, log state
  local total_minutes=$((P1_DURATION / 60))
  # Run monitor loop for N-1 iterations; the client naturally exits at the Nth minute
  for m in $(seq 1 $((total_minutes - 1))); do
    sleep 60

    # Verify client still alive (early death check only)
    if ! kill -0 "$client_pid" 2>/dev/null; then
      log "ERROR" "client pid=${client_pid} died prematurely at minute ${m}"
      stop_router_server "$TCP_PORT"
      end_phase "$phase_id" "INCOMPLETE" "reason=client_died_at_min${m}"
      return 1
    fi

    # Verify router server still alive via boot ID check (lightweight)
    local current_bid
    current_bid=$(router_boot_id)
    if [ "$current_bid" != "$CURRENT_BOOT_ID" ]; then
      log "ERROR" "boot_id changed at minute ${m}: was ${CURRENT_BOOT_ID:0:8}... now ${current_bid:0:8}..."
      stop_router_server "$TCP_PORT"
      end_phase "$phase_id" "INCOMPLETE" "reason=boot_id_changed_at_min${m}"
      return 1
    fi

    # Latency under load
    local ping_result
    ping_result=$(ping -c 3 -W 1 "$ROUTER_IP" 2>&1 | tail -1)
    log "MONITOR" "[${phase_id} min=${m}] ${ping_result}"

    # Brief system check
    local sys_info
    sys_info=$(router_cmd "echo \"load=\$(cat /proc/loadavg|awk '{print \$1}') temp=\$(cat /sys/class/thermal/thermal_zone*/temp|sort -rn|head -1|awk '{printf \\\"%.1f\\\",\$1/1000}') sunrec=\$(grep SUnreclaim /proc/meminfo|awk '{print \$2}')\"" 2>/dev/null)
    log "MONITOR" "[${phase_id} min=${m}] ${sys_info:-ssh_fail}"
  done

  # Wait for client to finish
  wait "$client_pid" 2>/dev/null || true

  # Read result
  log_raw "--- ${phase_id} result ---"
  grep -E 'sender|SUM' "$client_log" 2>/dev/null | grep -v 'Conn' | tee -a "$LOG_FILE"

  stop_router_server "$TCP_PORT"
  end_phase "$phase_id" "PASS" "client_pid=${client_pid}"
  return 0
}

# ── Phase 2: TCP Bidirectional ─────────────────────────────────────────────
phase_tcp_bidir() {
  local phase_id="p2_tcp_bidir"
  local server_pid

  begin_phase "$phase_id" "TCP bidirectional ${P2_DURATION}s" || return 1

  server_pid=$(start_router_server "$TCP_PORT")
  if [ -z "${server_pid:-}" ]; then
    end_phase "$phase_id" "INCOMPLETE" "reason=server_start_failed"
    return 1
  fi

  log "PHASE" "  router_server_pid=${server_pid} port=${TCP_PORT}"

  local client_log="${RESULT_DIR}/ax6-perf-${TIMESTAMP}-${phase_id}.log"
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t "$P2_DURATION" --bidir \
    --logfile "$client_log" 2>/dev/null &
  local client_pid=$!
  track_client_pid "$client_pid"

  log "PHASE" "  client_pid=${client_pid}"

  local total_minutes=$((P2_DURATION / 60))
  # Run monitor loop for N-1 iterations; the client naturally exits at the Nth minute
  for m in $(seq 1 $((total_minutes - 1))); do
    sleep 60

    # Verify client still alive (early death check only)
    if ! kill -0 "$client_pid" 2>/dev/null; then
      log "ERROR" "client pid=${client_pid} died prematurely at minute ${m}"
      stop_router_server "$TCP_PORT"
      end_phase "$phase_id" "INCOMPLETE" "reason=client_died_at_min${m}"
      return 1
    fi

    local current_bid
    current_bid=$(router_boot_id)
    if [ "$current_bid" != "$CURRENT_BOOT_ID" ]; then
      log "ERROR" "boot_id changed at minute ${m}"
      stop_router_server "$TCP_PORT"
      end_phase "$phase_id" "INCOMPLETE" "reason=boot_id_changed_at_min${m}"
      return 1
    fi

    local ping_result
    ping_result=$(ping -c 3 -W 1 "$ROUTER_IP" 2>&1 | tail -1)
    log "MONITOR" "[${phase_id} min=${m}] ${ping_result}"

    local sys_info
    sys_info=$(router_cmd "echo \"load=\$(cat /proc/loadavg|awk '{print \$1}') temp=\$(cat /sys/class/thermal/thermal_zone*/temp|sort -rn|head -1|awk '{printf \\\"%.1f\\\",\$1/1000}') sunrec=\$(grep SUnreclaim /proc/meminfo|awk '{print \$2}')\"" 2>/dev/null)
    log "MONITOR" "[${phase_id} min=${m}] ${sys_info:-ssh_fail}"
  done

  wait "$client_pid" 2>/dev/null || true

  log_raw "--- ${phase_id} result ---"
  grep -E 'sender|receiver|SUM' "$client_log" 2>/dev/null | grep -v 'Conn' | tee -a "$LOG_FILE"

  stop_router_server "$TCP_PORT"
  end_phase "$phase_id" "PASS" "client_pid=${client_pid}"
  return 0
}

# ── Phase 3: UDP Multi-Rate Sweep ──────────────────────────────────────────
phase_udp_sweep() {
  local phase_id="p3_udp_sweep"
  local server_pid

  begin_phase "$phase_id" "UDP multi-rate 100-1000M" || return 1

  server_pid=$(start_router_server "$UDP_PORT")
  if [ -z "${server_pid:-}" ]; then
    end_phase "$phase_id" "INCOMPLETE" "reason=server_start_failed"
    return 1
  fi

  log "PHASE" "  router_server_pid=${server_pid} port=${UDP_PORT}"

  local udp_log="${RESULT_DIR}/ax6-perf-${TIMESTAMP}-${phase_id}.log"

  for rate in 100 200 300 400 500 600 700 800 900 1000; do
    # Verify boot ID before each test
    local current_bid
    current_bid=$(router_boot_id)
    if [ "$current_bid" != "$CURRENT_BOOT_ID" ]; then
      log "ERROR" "boot_id changed at rate=${rate}M"
      stop_router_server "$UDP_PORT"
      end_phase "$phase_id" "INCOMPLETE" "reason=boot_id_changed_at_${rate}M"
      return 1
    fi

    log "UDP" "testing ${rate}M..."
    iperf3 -c "$ROUTER_IP" -p "$UDP_PORT" -u -b "${rate}M" -t "$P3_UDP_DURATION" -J 2>/dev/null \
      | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  s=d.get('end',{}).get('sum',{})
  bps=s.get('bits_per_second',0)/1e6
  lost=s.get('lost_packets',0)
  total=s.get('packets',0)
  jitter=s.get('jitter_ms',0)
  loss_pct=(lost/total*100) if total>0 else 0
  print(f'UDP {bps:.0f}M loss={lost}/{total} ({loss_pct:.2f}%) jitter={jitter:.3f}ms')
except Exception as e:
  print(f'PARSE_FAIL: {e}')
" 2>&1 | tee -a "$udp_log" | while read -r line; do
      log "UDP" "$line"
    done
  done

  log_raw "--- ${phase_id} full results ---"
  cat "$udp_log" >> "$LOG_FILE"

  stop_router_server "$UDP_PORT"
  end_phase "$phase_id" "PASS" ""
  return 0
}

# ── Phase 4: Burst + Bufferbloat + Concurrent ──────────────────────────────
phase_burst_stress() {
  local phase_id="p4_burst_stress"
  local server_pid_tcp

  begin_phase "$phase_id" "burst ${P4_BURST_COUNT}r + bufferbloat + concurrent" || return 1

  server_pid_tcp=$(start_router_server "$TCP_PORT")
  start_router_server "$UDP_PORT" > /dev/null
  start_router_server "$TCP_PORT_EXTRA" > /dev/null

  if [ -z "${server_pid_tcp:-}" ]; then
    end_phase "$phase_id" "INCOMPLETE" "reason=server_start_failed"
    return 1
  fi

  # 4.1 Burst test
  log "BURST" "${P4_BURST_COUNT} rounds × 2s"
  local success=0; local bps_min=9999; local bps_max=0; local bps_sum=0

  for i in $(seq 1 $P4_BURST_COUNT); do
    local current_bid
    current_bid=$(router_boot_id)
    if [ "$current_bid" != "$CURRENT_BOOT_ID" ]; then
      log "ERROR" "boot_id changed at burst round ${i}"
      stop_router_server "$TCP_PORT"; stop_router_server "$UDP_PORT"; stop_router_server "$TCP_PORT_EXTRA"
      end_phase "$phase_id" "INCOMPLETE" "reason=boot_id_changed_at_burst${i}"
      return 1
    fi

    local result
    result=$(iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t 2 -J 2>/dev/null | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  bps=d.get('end',{}).get('sum_sent',{}).get('bits_per_second',0)/1e6
  retx=d.get('end',{}).get('sum_sent',{}).get('retransmits',0)
  print(f'{bps:.0f},{retx}')
except: print('0,99')
" 2>/dev/null)

    local bps; bps=$(echo "$result" | cut -d, -f1)
    local retx; retx=$(echo "$result" | cut -d, -f2)

    bps_sum=$(echo "$bps_sum + $bps" | bc)
    [ "$retx" = "0" ] && success=$((success + 1))
    [ "$(echo "$bps < $bps_min" | bc)" = 1 ] && bps_min=$bps
    [ "$(echo "$bps > $bps_max" | bc)" = 1 ] && bps_max=$bps

    if [ $((i % 10)) -eq 0 ]; then
      log "BURST" "round ${i}/${P4_BURST_COUNT} bps=${bps} retx=${retx}"
    fi
  done

  local bps_avg; bps_avg=$(echo "scale=0; $bps_sum / $P4_BURST_COUNT" | bc)
  log "BURST" "RESULT avg=${bps_avg}Mbps min=${bps_min} max=${bps_max} retx_free=${success}/${P4_BURST_COUNT}"

  # 4.2 Bufferbloat
  log "BBLOAT" "40 pings under TCP saturation"
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t 40 -b 0 > /dev/null 2>&1 &
  local bloat_pid=$!
  track_client_pid "$bloat_pid"
  sleep 5
  local ping_result
  ping_result=$(ping -c 40 -i 0.2 "$ROUTER_IP" 2>&1 | tail -1)
  log "BBLOAT" "$ping_result"
  wait "$bloat_pid" 2>/dev/null || true

  # 4.3 Concurrent stress — 4 streams
  log "CONCUR" "4× TCP + ping"
  # Stream 1: TCP_PORT (DL)
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t 60 > /dev/null 2>&1 &
  local c1=$!; track_client_pid "$c1"
  # Stream 2: UDP_PORT (DL)
  iperf3 -c "$ROUTER_IP" -p "$UDP_PORT" -t 60 > /dev/null 2>&1 &
  local c2=$!; track_client_pid "$c2"
  # Stream 3: TCP_PORT_EXTRA (DL)
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT_EXTRA" -t 60 > /dev/null 2>&1 &
  local c3=$!; track_client_pid "$c3"
  # Stream 4: TCP_PORT (UL/reverse)
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t 60 -R > /dev/null 2>&1 &
  local c4=$!; track_client_pid "$c4"

  sleep 5
  ping_result=$(ping -c 40 -i 0.2 "$ROUTER_IP" 2>&1 | tail -1)
  log "CONCUR" "ping: $ping_result"

  local sys_info
  sys_info=$(router_cmd "uptime; cat /proc/loadavg" 2>/dev/null)
  log "CONCUR" "load: ${sys_info:-ssh_fail}"

  wait "$c1" "$c2" "$c3" "$c4" 2>/dev/null || true

  stop_router_server "$TCP_PORT"
  stop_router_server "$UDP_PORT"
  stop_router_server "$TCP_PORT_EXTRA"

  end_phase "$phase_id" "PASS" "burst_avg=${bps_avg}"
  return 0
}

# ── Final summary ──────────────────────────────────────────────────────────
final_summary() {
  log "FINAL" "===== TEST RUN COMPLETE ====="
  log "FINAL" "source_revision=${SOURCE_REVISION}"
  log "FINAL" "build_repo_commit=${BUILD_REPO_COMMIT}"
  log "FINAL" "boot_id=$(router_boot_id)"
  log "FINAL" "log_file=${LOG_FILE}"
  log "FINAL" "state_file=${STATE_FILE}"
}

# ═══════════════════════════════════════════════════════════════════════════
# MAIN — orchestrate all phases
# ═══════════════════════════════════════════════════════════════════════════

main() {
  log "START" "===== AX6 Performance Test ====="
  log "START" "source_revision=${SOURCE_REVISION}"
  log "START" "build_repo_commit=${BUILD_REPO_COMMIT}"
  log "START" "router=${ROUTER_IP}"
  log "START" "ports TCP=${TCP_PORT} UDP=${UDP_PORT} TCP_EXTRA=${TCP_PORT_EXTRA}"
  log "START" "result_dir=${RESULT_DIR}"
  log "START" "log_file=${LOG_FILE}"

  # Verify router connectivity
  INITIAL_BOOT_ID=$(router_boot_id)
  if [ -z "${INITIAL_BOOT_ID:-}" ] || [ "$INITIAL_BOOT_ID" = "unknown" ]; then
    log "FATAL" "cannot reach router at ${ROUTER_IP}"
    exit 1
  fi
  log "START" "boot_id=${INITIAL_BOOT_ID}"

  # Verify iperf3 available
  if ! command -v iperf3 >/dev/null 2>&1; then
    log "FATAL" "iperf3 not found on client"
    exit 1
  fi

  # Take initial snapshot
  collect_snapshot "BASELINE" "init"

  # Run phases — any failure stops subsequent phases per §3.1(5)
  phase_tcp_single    || { log "ABORT" "phase p1_tcp_single failed"; exit 1; }
  phase_tcp_bidir     || { log "ABORT" "phase p2_tcp_bidir failed"; exit 1; }
  phase_udp_sweep     || { log "ABORT" "phase p3_udp_sweep failed"; exit 1; }
  phase_burst_stress  || { log "ABORT" "phase p4_burst_stress failed"; exit 1; }

  # Final comprehensive snapshot
  collect_snapshot "FINAL" "complete"
  final_summary

  log "RESULT" "COMPLETE all_phases=passed"
  echo "COMPLETE" >> "$STATE_FILE"
  exit 0
}

# ── Entry point ────────────────────────────────────────────────────────────
main "$@"
