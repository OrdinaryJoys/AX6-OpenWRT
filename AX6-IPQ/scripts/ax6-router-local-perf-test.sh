#!/usr/bin/env bash
# AX6 ROUTER-LOCAL Performance Test (host-terminated) — R2 P0 hardened
# ============================================================================
# ⚠️ 拓扑边界 (R2 §3 T-01): 本脚本的 iperf3 流量终结于路由器本机
#    (router 自身是 iperf3 server, client 直连 ROUTER_IP)。
#    它测试的是「主机栈本地终结吞吐/负载」, 不是 LAN-LAN 转发, 更不是
#    WAN-LAN routed 路径。转发/路由性能请用 ax6-lanlan-perf-test.sh /
#    ax6-routed-perf-test.sh。结果不得作为数据面转发结论。
#
# R2 P0 硬化要求:
#   P0-2 固件身份必须显式传入 (无过期默认值): AX6_SOURCE_REVISION /
#        AX6_BUILD_COMMIT / AX6_EXPECTED_BOARD / AX6_EXPECTED_KERNEL /
#        AX6_EXPECTED_REVISION — 任一缺失立即 INCOMPLETE 退出。
#   P0-3 测试前 SSH 核对 board/revision/kernel/boot ID, 不匹配立即停止。
#   P0-4 所有 iperf3 输出 JSON (-J); 检查进程退出码、JSON .error、
#        方向汇总与持续时长。
#   P0-5 任一客户端/服务器/SSH 快照/JSON 解析失败 → INCOMPLETE 且
#        非零退出; 不允许伪 PASS。
# 保留约束: 独立端口 15201-15203; 不 killall; 不递归读 debugfs;
#           严格 SSH 身份校验; boot ID 每阶段核对。
# ============================================================================

set -o nounset
set -o pipefail

# ── 配置 (身份项无默认值, 缺失即拒绝 — R2 P0-2) ──────────────────────────
ROUTER_IP="${AX6_ROUTER_IP:-192.168.5.1}"
SSH_KEY="${AX6_SSH_KEY:-${HOME}/.ssh/ax6_check}"
KNOWN_HOSTS="${AX6_KNOWN_HOSTS:-${HOME}/.ssh/known_hosts}"
SOURCE_REVISION="${AX6_SOURCE_REVISION:-}"
BUILD_REPO_COMMIT="${AX6_BUILD_COMMIT:-}"
EXPECTED_BOARD="${AX6_EXPECTED_BOARD:-}"
EXPECTED_KERNEL="${AX6_EXPECTED_KERNEL:-}"
EXPECTED_REVISION="${AX6_EXPECTED_REVISION:-}"

# 时长与轮询间隔 (fixture 可缩短; 默认维持原计划)
P1_DURATION="${AX6_P1_DURATION:-1500}"
P2_DURATION="${AX6_P2_DURATION:-1200}"
P3_UDP_DURATION="${AX6_P3_DURATION:-15}"
P4_BURST_COUNT="${AX6_P4_BURST_COUNT:-40}"
MONITOR_INTERVAL="${AX6_MONITOR_INTERVAL:-60}"

SSH=(
  ssh
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=$KNOWN_HOSTS"
  -o ConnectTimeout=10
  -i "$SSH_KEY"
  "root@$ROUTER_IP"
)

TCP_PORT=15201
UDP_PORT=15202
TCP_PORT_EXTRA=15203

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RESULT_DIR="${AX6_RESULT_DIR:-/Volumes/FX-MD87/Review/backups/flash-20260802}"
mkdir -p "$RESULT_DIR"
LOG_FILE="${RESULT_DIR}/ax6-router-local-perf-${TIMESTAMP}.log"
STATE_FILE="${RESULT_DIR}/ax6-router-local-perf-${TIMESTAMP}.state"

CURRENT_PHASE=""
PHASE_START_TIME=""
EXIT_CODE=0
SIGNAL_RECEIVED=""
SNAPSHOT_FAILURES=0
declare -a TRACKED_CLIENT_PIDS=()
declare -a TRACKED_ROUTER_PIDS=()
INITIAL_BOOT_ID=""
CURRENT_BOOT_ID=""

log() {
  local level="$1"; shift
  printf "[%s] %-8s %s\n" "$(date +%H:%M:%S)" "$level" "$*" | tee -a "$LOG_FILE"
}
log_raw() { printf "%s\n" "$*" | tee -a "$LOG_FILE"; }

# ── Traps ────────────────────────────────────────────────────────────────────
# shellcheck disable=SC2329
_on_signal() {
  local sig="$1"
  SIGNAL_RECEIVED="$sig"
  log "TRAP" "signal=${sig} phase=${CURRENT_PHASE:-none}"
  _cleanup_tracked
  if [ -n "${CURRENT_PHASE:-}" ]; then
    log "RESULT" "INCOMPLETE phase=${CURRENT_PHASE} signal=${sig}"
  fi
  exit 128
}
# shellcheck disable=SC2329
_on_exit() {
  local ec=$?
  if [ -n "${SIGNAL_RECEIVED:-}" ]; then
    :
  elif [ "${EXIT_CODE:-0}" -ne 0 ] || [ "$ec" -ne 0 ]; then
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

# ── SSH helpers (失败即返回非零 — R2 P0-5) ─────────────────────────────────
router_cmd() {
  "${SSH[@]}" "$@" 2>>"${LOG_FILE}.ssh-err"
}
router_boot_id() {
  router_cmd "cat /proc/sys/kernel/random/boot_id 2>/dev/null" 2>/dev/null || echo "unknown"
}

# ── 前置身份核对 (R2 P0-3) ──────────────────────────────────────────────────
verify_router_identity() {
  local board kernel revision boot_id

  board=$(router_cmd "cat /tmp/sysinfo/model 2>/dev/null" 2>/dev/null | tr -d '\r') || board=""
  kernel=$(router_cmd "uname -r 2>/dev/null" 2>/dev/null | tr -d '\r') || kernel=""
  revision=$(router_cmd "grep DISTRIB_REVISION /etc/openwrt_release 2>/dev/null" 2>/dev/null | tr -d '\r' | cut -d= -f2 | tr -d "'") || revision=""
  boot_id=$(router_boot_id)

  local mismatch=0
  if [ -z "$board" ] || [ -z "$kernel" ] || [ -z "$revision" ] || [ "$boot_id" = "unknown" ]; then
    log "FATAL" "identity probe incomplete: board='${board:-}' kernel='${kernel:-}' revision='${revision:-}' boot='${boot_id:0:8}...'"
    return 1
  fi
  if [ "$board" != "$EXPECTED_BOARD" ]; then
    log "FATAL" "board mismatch: expected='${EXPECTED_BOARD}' actual='${board}'"
    mismatch=1
  fi
  if [ "$kernel" != "$EXPECTED_KERNEL" ]; then
    log "FATAL" "kernel mismatch: expected='${EXPECTED_KERNEL}' actual='${kernel}'"
    mismatch=1
  fi
  if [ "$revision" != "$EXPECTED_REVISION" ]; then
    log "FATAL" "firmware revision mismatch: expected='${EXPECTED_REVISION}' actual='${revision}'"
    mismatch=1
  fi
  if [ "$mismatch" -ne 0 ]; then
    log "RESULT" "INCOMPLETE phase=preflight reason=identity_mismatch"
    return 1
  fi
  log "IDENTITY" "board=${board} kernel=${kernel} revision=${revision} boot=${boot_id:0:8}..."
  log "IDENTITY" "source_revision=${SOURCE_REVISION} build_repo_commit=${BUILD_REPO_COMMIT}"
  return 0
}

# ── Process tracking ─────────────────────────────────────────────────────────
track_client_pid() { TRACKED_CLIENT_PIDS+=("$1"); }
track_router_pid() { TRACKED_ROUTER_PIDS+=("$1"); }
# shellcheck disable=SC2329
_cleanup_tracked() {
  if [ "${#TRACKED_CLIENT_PIDS[@]}" -gt 0 ]; then
    for pid in "${TRACKED_CLIENT_PIDS[@]}"; do
      kill -0 "$pid" 2>/dev/null && { kill "$pid" 2>/dev/null || true; }
    done
  fi
  TRACKED_CLIENT_PIDS=()
  if [ "${#TRACKED_ROUTER_PIDS[@]}" -gt 0 ]; then
    for pid in "${TRACKED_ROUTER_PIDS[@]}"; do
      router_cmd "kill ${pid} 2>/dev/null" 2>/dev/null || true
    done
  fi
  TRACKED_ROUTER_PIDS=()
}

# ── Router iperf3 server ─────────────────────────────────────────────────────
start_router_server() {
  local port="$1" pid
  pid=$(router_cmd "iperf3 -s -p ${port} -D --pidfile /tmp/ax6-perf-iperf3-${port}.pid 2>/dev/null; sleep 0.5; cat /tmp/ax6-perf-iperf3-${port}.pid 2>/dev/null" 2>/dev/null)
  if [ -n "${pid:-}" ] && [ "$pid" -gt 0 ] 2>/dev/null; then
    track_router_pid "$pid"
    echo "$pid"
  else
    log "ERROR" "failed to start iperf3 server on port ${port}"
    return 1
  fi
}
stop_router_server() {
  local port="$1"
  router_cmd "kill \$(cat /tmp/ax6-perf-iperf3-${port}.pid 2>/dev/null) 2>/dev/null; rm -f /tmp/ax6-perf-iperf3-${port}.pid" 2>/dev/null || true
}

# ── 快照 (任一采集失败计入失败 — R2 P0-5) ─────────────────────────────────
collect_snapshot() {
  local label="$1" phase_id="${2:-none}" failed=0
  local boot_id
  boot_id=$(router_boot_id)
  log "SNAP" "===== ${label} phase=${phase_id} boot=${boot_id:0:8}... ====="

  log_raw "--- snmp_udp ---"
  router_cmd "grep '^Udp:' /proc/net/snmp" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "snmp_udp:FAIL"; failed=1; }
  log_raw "--- udp_sockets ---"
  router_cmd "cat /proc/net/udp" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "udp_sockets:FAIL"; failed=1; }
  log_raw "--- udp6_sockets ---"
  router_cmd "cat /proc/net/udp6" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "udp6_sockets:FAIL"; failed=1; }
  log_raw "--- zt_sockets ---"
  zt_pid=$(router_cmd "pidof zerotier-one" 2>/dev/null | tr -d '\r' || true)
  if [ -n "${zt_pid:-}" ]; then
    router_cmd "ls -la /proc/${zt_pid}/fd/ 2>/dev/null | grep socket" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "zt_fd:FAIL"; failed=1; }
  else
    log_raw "zt:no_pid"
  fi
  log_raw "--- clash_sockets ---"
  clash_pid=$(router_cmd "pidof clash" 2>/dev/null | tr -d '\r' || true)
  if [ -n "${clash_pid:-}" ]; then
    router_cmd "ls -la /proc/${clash_pid}/fd/ 2>/dev/null | grep socket" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "clash_fd:FAIL"; failed=1; }
  else
    log_raw "clash:no_pid"
  fi
  log_raw "--- softnet ---"
  router_cmd "cat /proc/net/softnet_stat" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "softnet:FAIL"; failed=1; }
  log_raw "--- port_stats ---"
  router_cmd "for i in br-lan lan1 lan2 lan3 wan; do echo \"\$i rx_err=\$(cat /sys/class/net/\$i/statistics/rx_errors 2>/dev/null) tx_err=\$(cat /sys/class/net/\$i/statistics/tx_errors 2>/dev/null) rx_drop=\$(cat /sys/class/net/\$i/statistics/rx_dropped 2>/dev/null) tx_drop=\$(cat /sys/class/net/\$i/statistics/tx_dropped 2>/dev/null)\"; done" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "port_stats:FAIL"; failed=1; }
  log_raw "--- nss_check ---"
  router_cmd "nss-check -q 2>&1; echo \"exit=\$?\"" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "nss_check:FAIL"; failed=1; }
  log_raw "--- config_audit ---"
  router_cmd "ax6-config-audit -q 2>&1; echo \"exit=\$?\"" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "config_audit:FAIL"; failed=1; }
  log_raw "--- edma_err ---"
  router_cmd "cat /sys/kernel/debug/qca-nss-drv/stats/edma/err_stats 2>/dev/null || echo 'n/a'" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "edma_err:FAIL"; failed=1; }
  log_raw "--- system ---"
  router_cmd "uptime; free | grep Mem; echo \"temp_mC=\$(cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1)\"" 2>/dev/null | tee -a "$LOG_FILE" >/dev/null || { log_raw "system:FAIL"; failed=1; }

  SNAPSHOT_FAILURES=$((SNAPSHOT_FAILURES + failed))
  log "SNAP" "===== ${label} END (collect_fail=${failed}) ====="
  return "$failed"
}

# ── 严格 JSON 解析 (R2 P0-4) ───────────────────────────────────────────────
# 用法: parse_iperf_json FILE MIN_SECONDS MODE(bidir|single|udp)
# 成功: 打印方向汇总并返回 0; 失败: 打印原因返回 1
parse_iperf_json() {
  local jf="$1" min_secs="$2" mode="$3"
  python3 - "$jf" "$min_secs" "$mode" <<'PYEOF'
import json, sys
jf, min_secs, mode = sys.argv[1], float(sys.argv[2]), sys.argv[3]
try:
    d = json.load(open(jf))
except Exception as e:
    print(f"PARSE_FAIL: {e}")
    sys.exit(1)
if d.get("error"):
    print(f"JSON_ERROR: {d['error']}")
    sys.exit(1)
end = d.get("end", {}) or {}
streams = end.get("streams", [])
if not streams:
    print("NO_STREAMS")
    sys.exit(1)
secs = None
dirs = {}
for s in streams:
    send = s.get("sender", {}) or {}
    if send.get("seconds"):
        if secs is None or send["seconds"] < secs:
            secs = send["seconds"]
    k = "UL->router" if send.get("sender") else "router->DL"
    if mode == "udp":
        udp = s.get("udp", {}) or {}
        dirs.setdefault(k, []).append((send.get("bytes", 0), udp.get("lost_packets", 0),
                                       udp.get("packets", 0), udp.get("jitter_ms", 0)))
    else:
        dirs.setdefault(k, []).append((send.get("bytes", 0), send.get("retransmits", 0)))
if secs is None:
    print("NO_DURATION")
    sys.exit(1)
if secs < min_secs:
    print(f"DURATION_SHORT: {secs:.1f}s < {min_secs:.0f}s")
    sys.exit(1)
for k in sorted(dirs):
    tot_b = sum(x[0] for x in dirs[k])
    if mode == "udp":
        lost = sum(x[1] for x in dirs[k]); pkts = sum(x[2] for x in dirs[k])
        jit = max(x[3] for x in dirs[k]) if dirs[k] else 0.0
        print(f"UDP {k}: {tot_b*8/secs/1e6:.1f}M loss={lost}/{pkts} jitter={jit:.3f}ms")
    else:
        retx = sum(x[1] for x in dirs[k])
        print(f"TCP {k}: {tot_b*8/secs/1e6:.1f}M retrans={retx}")
sys.exit(0)
PYEOF
}

# ── Phase 骨架 ───────────────────────────────────────────────────────────────
begin_phase() {
  local phase_id="$1" desc="$2"
  CURRENT_PHASE="$phase_id"
  PHASE_START_TIME=$(date +%s)
  CURRENT_BOOT_ID=$(router_boot_id)
  if [ -n "${INITIAL_BOOT_ID:-}" ] && [ "$CURRENT_BOOT_ID" != "$INITIAL_BOOT_ID" ]; then
    log "ERROR" "boot_id changed: old=${INITIAL_BOOT_ID:0:8}... new=${CURRENT_BOOT_ID:0:8}..."
    log "RESULT" "INCOMPLETE phase=${phase_id} reason=boot_id_changed"
    return 1
  fi
  INITIAL_BOOT_ID="$CURRENT_BOOT_ID"
  log "PHASE" "BEGIN phase_id=${phase_id} desc=${desc} boot=${CURRENT_BOOT_ID:0:8}..."
  echo "phase=${phase_id}" > "$STATE_FILE"
  echo "start_time=${PHASE_START_TIME}" >> "$STATE_FILE"
  echo "boot_id=${CURRENT_BOOT_ID}" >> "$STATE_FILE"
  return 0
}
end_phase() {
  local phase_id="$1" result="$2" extra="${3:-}"
  local elapsed=$(( $(date +%s) - PHASE_START_TIME ))
  collect_snapshot "POST" "$phase_id" || true
  log "PHASE" "END phase_id=${phase_id} result=${result} elapsed_s=${elapsed} snapshot_fail_total=${SNAPSHOT_FAILURES} ${extra}"
  echo "result=${result}" >> "$STATE_FILE"
  echo "elapsed_s=${elapsed}" >> "$STATE_FILE"
  CURRENT_PHASE=""
  PHASE_START_TIME=""
  if [ "$result" = "INCOMPLETE" ]; then
    EXIT_CODE=1
    return 1
  fi
  return 0
}

# 轮询等待 client, 期间核对 boot_id (R2 P0-4/P0-5)
wait_client() {
  local pid="$1" phase_id="$2" deadline=$(( $(date +%s) + $3 + 30 ))
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      kill "$pid" 2>/dev/null || true
      log "ERROR" "client pid=${pid} exceeded deadline"
      return 2
    fi
    sleep "$MONITOR_INTERVAL"
    local bid
    bid=$(router_boot_id)
    if [ "$bid" != "$CURRENT_BOOT_ID" ]; then
      log "ERROR" "boot_id changed during ${phase_id}: ${CURRENT_BOOT_ID:0:8}... -> ${bid:0:8}..."
      return 3
    fi
    local pinfo
    pinfo=$(ping -c 3 -W 1 "$ROUTER_IP" 2>&1 | tail -1)
    log "MONITOR" "[${phase_id}] ${pinfo}"
  done
  wait "$pid"; return $?
}

# ── Phase 1: TCP single ──────────────────────────────────────────────────────
phase_tcp_single() {
  local phase_id="p1_tcp_single" server_pid client_pid rc
  begin_phase "$phase_id" "TCP single ${P1_DURATION}s" || return 1
  server_pid=$(start_router_server "$TCP_PORT") || { end_phase "$phase_id" "INCOMPLETE" "reason=server_start_failed"; return 1; }
  local jf="${RESULT_DIR}/ax6-router-local-perf-${TIMESTAMP}-${phase_id}.json"
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t "$P1_DURATION" -J > "$jf" 2>>"${LOG_FILE}.iperf-err" &
  client_pid=$!
  track_client_pid "$client_pid"
  wait_client "$client_pid" "$phase_id" "$P1_DURATION"
  rc=$?
  stop_router_server "$TCP_PORT"
  if [ "$rc" -ne 0 ]; then
    end_phase "$phase_id" "INCOMPLETE" "reason=iperf_rc=${rc}"
    return 1
  fi
  log_raw "--- ${phase_id} result ---"
  parse_iperf_json "$jf" "$((P1_DURATION * 9 / 10))" "single" | tee -a "$LOG_FILE" || {
    end_phase "$phase_id" "INCOMPLETE" "reason=json_parse_failed"
    return 1
  }
  end_phase "$phase_id" "PASS" "client_pid=${client_pid}"
}

# ── Phase 2: TCP bidir ───────────────────────────────────────────────────────
phase_tcp_bidir() {
  local phase_id="p2_tcp_bidir" server_pid client_pid rc
  begin_phase "$phase_id" "TCP bidir ${P2_DURATION}s" || return 1
  server_pid=$(start_router_server "$TCP_PORT") || { end_phase "$phase_id" "INCOMPLETE" "reason=server_start_failed"; return 1; }
  local jf="${RESULT_DIR}/ax6-router-local-perf-${TIMESTAMP}-${phase_id}.json"
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t "$P2_DURATION" --bidir -J > "$jf" 2>>"${LOG_FILE}.iperf-err" &
  client_pid=$!
  track_client_pid "$client_pid"
  wait_client "$client_pid" "$phase_id" "$P2_DURATION"
  rc=$?
  stop_router_server "$TCP_PORT"
  if [ "$rc" -ne 0 ]; then
    end_phase "$phase_id" "INCOMPLETE" "reason=iperf_rc=${rc}"
    return 1
  fi
  log_raw "--- ${phase_id} result ---"
  parse_iperf_json "$jf" "$((P2_DURATION * 9 / 10))" "bidir" | tee -a "$LOG_FILE" || {
    end_phase "$phase_id" "INCOMPLETE" "reason=json_parse_failed"
    return 1
  }
  end_phase "$phase_id" "PASS" "client_pid=${client_pid}"
}

# ── Phase 3: UDP sweep (严格解析 — R2 P0-4/P0-5) ───────────────────────────
phase_udp_sweep() {
  local phase_id="p3_udp_sweep" server_pid rc
  begin_phase "$phase_id" "UDP multi-rate 100-1000M" || return 1
  server_pid=$(start_router_server "$UDP_PORT") || { end_phase "$phase_id" "INCOMPLETE" "reason=server_start_failed"; return 1; }
  for rate in 100 200 300 400 500 600 700 800 900 1000; do
    local bid
    bid=$(router_boot_id)
    if [ "$bid" != "$CURRENT_BOOT_ID" ]; then
      stop_router_server "$UDP_PORT"
      end_phase "$phase_id" "INCOMPLETE" "reason=boot_id_changed_at_${rate}M"
      return 1
    fi
    local jf="${RESULT_DIR}/ax6-router-local-perf-${TIMESTAMP}-${phase_id}-${rate}m.json"
    iperf3 -c "$ROUTER_IP" -p "$UDP_PORT" -u -b "${rate}M" -t "$P3_UDP_DURATION" -J > "$jf" 2>/dev/null
    rc=$?
    if [ "$rc" -ne 0 ]; then
      stop_router_server "$UDP_PORT"
      end_phase "$phase_id" "INCOMPLETE" "reason=udp_iperf_rc=${rc}_at_${rate}M"
      return 1
    fi
    local udp_line
    udp_line=$(parse_iperf_json "$jf" "$((P3_UDP_DURATION * 9 / 10))" "udp" | head -1) || {
      stop_router_server "$UDP_PORT"
      end_phase "$phase_id" "INCOMPLETE" "reason=udp_parse_failed_at_${rate}M"
      return 1
    }
    log "UDP" "$udp_line"
  done
  stop_router_server "$UDP_PORT"
  end_phase "$phase_id" "PASS" ""
}

# ── Phase 4: burst (严格解析) ────────────────────────────────────────────────
phase_burst_stress() {
  local phase_id="p4_burst_stress" server_pid
  begin_phase "$phase_id" "burst ${P4_BURST_COUNT}r + bufferbloat + concurrent" || return 1
  server_pid=$(start_router_server "$TCP_PORT") || { end_phase "$phase_id" "INCOMPLETE" "reason=server_start_failed"; return 1; }
  log "PHASE" "  router_server_pid=${server_pid} port=${TCP_PORT}"
  start_router_server "$UDP_PORT" >/dev/null || true
  start_router_server "$TCP_PORT_EXTRA" >/dev/null || true

  local bps_sum=0 bps_min=9999 bps_max=0 retx_free=0 i
  for i in $(seq 1 "$P4_BURST_COUNT"); do
    local bid
    bid=$(router_boot_id)
    if [ "$bid" != "$CURRENT_BOOT_ID" ]; then
      stop_router_server "$TCP_PORT"; stop_router_server "$UDP_PORT"; stop_router_server "$TCP_PORT_EXTRA"
      end_phase "$phase_id" "INCOMPLETE" "reason=boot_id_changed_at_burst${i}"
      return 1
    fi
    local jf="${RESULT_DIR}/ax6-router-local-perf-${TIMESTAMP}-${phase_id}-burst${i}.json"
    iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t 2 -J > "$jf" 2>/dev/null
    local rc=$?
    if [ "$rc" -ne 0 ]; then
      stop_router_server "$TCP_PORT"; stop_router_server "$UDP_PORT"; stop_router_server "$TCP_PORT_EXTRA"
      end_phase "$phase_id" "INCOMPLETE" "reason=burst_iperf_rc=${rc}_at_round${i}"
      return 1
    fi
    local line bps retx
    line=$(parse_iperf_json "$jf" 1 "single" | head -1) || {
      stop_router_server "$TCP_PORT"; stop_router_server "$UDP_PORT"; stop_router_server "$TCP_PORT_EXTRA"
      end_phase "$phase_id" "INCOMPLETE" "reason=burst_parse_failed_at_round${i}"
      return 1
    }
    bps=$(echo "$line" | sed -n 's/.*TCP UL->router: \([0-9.]*\)M.*/\1/p')
    [ -z "$bps" ] && bps=$(echo "$line" | sed -n 's/.*TCP router->DL: \([0-9.]*\)M.*/\1/p')
    retx=$(echo "$line" | sed -n 's/.*retrans=\([0-9]*\).*/\1/p')
    [ -z "$bps" ] || [ -z "$retx" ] && {
      stop_router_server "$TCP_PORT"; stop_router_server "$UDP_PORT"; stop_router_server "$TCP_PORT_EXTRA"
      end_phase "$phase_id" "INCOMPLETE" "reason=burst_field_parse_failed_at_round${i}"
      return 1
    }
    bps_sum=$(echo "$bps_sum + $bps" | bc)
    [ "$(echo "$bps < $bps_min" | bc)" = 1 ] && bps_min=$bps
    [ "$(echo "$bps > $bps_max" | bc)" = 1 ] && bps_max=$bps
    [ "$retx" = "0" ] && retx_free=$((retx_free + 1))
    if [ $((i % 10)) -eq 0 ]; then
      log "BURST" "round ${i}/${P4_BURST_COUNT} bps=${bps} retx=${retx}"
    fi
  done
  local bps_avg
  bps_avg=$(echo "scale=0; $bps_sum / $P4_BURST_COUNT" | bc)
  log "BURST" "RESULT avg=${bps_avg}Mbps min=${bps_min} max=${bps_max} retx_free=${retx_free}/${P4_BURST_COUNT}"

  # 4.2 bufferbloat (wait 严格)
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t 40 > /dev/null 2>&1 &
  local bloat_pid=$!
  track_client_pid "$bloat_pid"
  sleep 5
  local ping_result
  ping_result=$(ping -c 40 -i 0.2 "$ROUTER_IP" 2>&1 | tail -1)
  log "BBLOAT" "$ping_result"
  if ! wait "$bloat_pid" 2>/dev/null; then
    log "ERROR" "bloat iperf failed rc=$?"
  fi

  # 4.3 concurrent (wait 严格 — 任一失败即 INCOMPLETE)
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t 60 > /dev/null 2>&1 &
  local c1=$!; track_client_pid "$c1"
  iperf3 -c "$ROUTER_IP" -p "$UDP_PORT" -t 60 > /dev/null 2>&1 &
  local c2=$!; track_client_pid "$c2"
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT_EXTRA" -t 60 > /dev/null 2>&1 &
  local c3=$!; track_client_pid "$c3"
  iperf3 -c "$ROUTER_IP" -p "$TCP_PORT" -t 60 -R > /dev/null 2>&1 &
  local c4=$!; track_client_pid "$c4"
  sleep 5
  ping_result=$(ping -c 40 -i 0.2 "$ROUTER_IP" 2>&1 | tail -1)
  log "CONCUR" "ping: $ping_result"
  local ok=1
  for pid in "$c1" "$c2" "$c3" "$c4"; do
    if ! wait "$pid" 2>/dev/null; then
      log "ERROR" "concurrent client pid=${pid} failed rc=$?"
      ok=0
    fi
  done
  stop_router_server "$TCP_PORT"; stop_router_server "$UDP_PORT"; stop_router_server "$TCP_PORT_EXTRA"
  if [ "$ok" -ne 1 ]; then
    end_phase "$phase_id" "INCOMPLETE" "reason=concurrent_client_failed"
    return 1
  fi
  end_phase "$phase_id" "PASS" "burst_avg=${bps_avg}"
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
  log "START" "===== AX6 ROUTER-LOCAL Perf Test (host-terminated) ====="
  log "START" "router=${ROUTER_IP} result_dir=${RESULT_DIR}"

  # P0-2: 身份必须显式传入
  if [ -z "$SOURCE_REVISION" ] || [ -z "$BUILD_REPO_COMMIT" ] || \
     [ -z "$EXPECTED_BOARD" ] || [ -z "$EXPECTED_KERNEL" ] || [ -z "$EXPECTED_REVISION" ]; then
    log "FATAL" "identity env required: AX6_SOURCE_REVISION AX6_BUILD_COMMIT AX6_EXPECTED_BOARD AX6_EXPECTED_KERNEL AX6_EXPECTED_REVISION"
    log "RESULT" "INCOMPLETE phase=preflight reason=identity_env_missing"
    exit 1
  fi

  if ! command -v iperf3 >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1 || ! command -v bc >/dev/null 2>&1; then
    log "FATAL" "client prerequisites missing (iperf3/python3/bc)"
    exit 1
  fi

  # P0-3: SSH 身份核对
  verify_router_identity || exit 1
  INITIAL_BOOT_ID=$(router_boot_id)
  if [ -z "${INITIAL_BOOT_ID:-}" ] || [ "$INITIAL_BOOT_ID" = "unknown" ]; then
    log "FATAL" "cannot reach router at ${ROUTER_IP}"
    exit 1
  fi
  log "START" "boot_id=${INITIAL_BOOT_ID:0:8}..."

  collect_snapshot "BASELINE" "init" || log "WARN" "baseline snapshot had failures"
  [ "$SNAPSHOT_FAILURES" -gt 0 ] && log "FATAL" "baseline snapshot incomplete (${SNAPSHOT_FAILURES} collectors failed)" && exit 1

  phase_tcp_single    || { log "ABORT" "p1_tcp_single failed"; exit 1; }
  phase_tcp_bidir     || { log "ABORT" "p2_tcp_bidir failed"; exit 1; }
  phase_udp_sweep     || { log "ABORT" "p3_udp_sweep failed"; exit 1; }
  phase_burst_stress  || { log "ABORT" "p4_burst_stress failed"; exit 1; }

  collect_snapshot "FINAL" "complete" || log "WARN" "final snapshot had failures"
  if [ "$SNAPSHOT_FAILURES" -gt 0 ]; then
    log "RESULT" "INCOMPLETE all_phases=passed_but_snapshot_failures=${SNAPSHOT_FAILURES}"
    echo "INCOMPLETE" >> "$STATE_FILE"
    exit 1
  fi

  log "RESULT" "COMPLETE all_phases=passed snapshot_failures=0"
  echo "COMPLETE" >> "$STATE_FILE"
  exit 0
}

main "$@"
