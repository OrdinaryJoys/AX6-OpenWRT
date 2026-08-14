#!/usr/bin/env bash
# AX6 LAN-LAN 转发吞吐测试 (R2 P0-6 入库版)
# ============================================================================
# 拓扑: client(Mac) -- lan2 -- [AX6 交换/桥接路径] -- lan1 -- iperf3 server
# 本脚本测试 AX6 数据面转发路径 (LAN-LAN), 不是路由器本机终结 (见
# ax6-router-local-perf-test.sh), 也不是 WAN-LAN routed (见
# ax6-routed-perf-test.sh)。
#
# R2 P0-6: 参数化端点/密钥/输出目录; P1 真 -P 1, P4 真 -P 4;
# 固件身份 + boot ID 门禁; 端点身份必须显式记录。
# 方法纪律: 逐 stream 解析 (sender.seconds) / 每阶段前后快照 /
# 独立 run 目录 + SHA256 / SSH 严格身份。
# ============================================================================

set -Eeuo pipefail

# ── 配置 ─────────────────────────────────────────────────────────────────────
SERVER_IP="${AX6_LANLAN_SERVER_IP:?AX6_LANLAN_SERVER_IP required (iperf3 server endpoint)}"
ROUTER_IP="${AX6_ROUTER_IP:-192.168.5.1}"
SSH_KEY="${AX6_SSH_KEY:-${HOME}/.ssh/ax6_check}"
KNOWN_HOSTS="${AX6_KNOWN_HOSTS:-${HOME}/.ssh/known_hosts}"
PORT="${AX6_LANLAN_PORT:-5201}"
OUT_BASE="${AX6_LANLAN_OUT_BASE:-/tmp/ax6-lanlan-runs}"
LABEL="${AX6_LANLAN_LABEL:-run}"

# 固件身份门禁 (无默认值, 缺失即拒绝 — R2 T-04/P0-3)
SOURCE_REVISION="${AX6_SOURCE_REVISION:-}"
BUILD_REPO_COMMIT="${AX6_BUILD_COMMIT:-}"
EXPECTED_BOARD="${AX6_EXPECTED_BOARD:-}"
EXPECTED_KERNEL="${AX6_EXPECTED_KERNEL:-}"
EXPECTED_REVISION="${AX6_EXPECTED_REVISION:-}"
# 端点身份 (必须显式记录 — R2 T-04): 如 "Windows AX88179 USB3 driver 1.16.27.321"
ENDPOINT_INFO="${AX6_ENDPOINT_INFO:-}"
CLIENT_NIC_INFO="${AX6_CLIENT_NIC_INFO:-}"

ROUNDS="${AX6_ROUNDS:-3}"
DURATION="${AX6_DURATION:-30}"
LONG_DURATION="${AX6_LONG_DURATION:-600}"
LONG_RETX_LIMIT="${AX6_LONG_RETX_LIMIT:-1000}"
SKIP_TCP="${AX6_SKIP_TCP:-0}"
SKIP_UDP="${AX6_SKIP_UDP:-0}"
SKIP_LONG="${AX6_SKIP_LONG:-0}"
LOG_TEE="${AX6_LANLAN_LOG_TEE:-1}"

OUT="${OUT_BASE}/$(date +%Y%m%d-%H%M%S)-${LABEL}"
mkdir -p "$OUT"
if [ "$LOG_TEE" = 1 ]; then
  exec > >(tee -a "$OUT/runner.log") 2>&1
else
  exec >> "$OUT/runner.log" 2>&1
fi

SSH=(ssh -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KNOWN_HOSTS" root@"$ROUTER_IP")
log() { echo "[$(date +%H:%M:%S)] $*"; }
trap 'log "FAILED at line $LINENO"; exit 1' ERR

# ── 前置: 固件身份 + 端点身份 (R2 P0-3/T-04) ──────────────────────────────
preflight_identity() {
  local board kernel revision boot_id
  board=$("${SSH[@]}" cat /tmp/sysinfo/model 2>/dev/null | tr -d '\r') || board=""
  kernel=$("${SSH[@]}" uname -r 2>/dev/null | tr -d '\r') || kernel=""
  revision=$("${SSH[@]}" "grep DISTRIB_REVISION /etc/openwrt_release 2>/dev/null" 2>/dev/null | tr -d '\r' | cut -d= -f2 | tr -d "'") || revision=""
  boot_id=$("${SSH[@]}" cat /proc/sys/kernel/random/boot_id 2>/dev/null | tr -d '\r') || boot_id=""

  local ok=1
  [ "$board" = "$EXPECTED_BOARD" ] || { log "FATAL board mismatch: expected=$EXPECTED_BOARD actual=$board"; ok=0; }
  [ "$kernel" = "$EXPECTED_KERNEL" ] || { log "FATAL kernel mismatch: expected=$EXPECTED_KERNEL actual=$kernel"; ok=0; }
  [ "$revision" = "$EXPECTED_REVISION" ] || { log "FATAL revision mismatch: expected=$EXPECTED_REVISION actual=$revision"; ok=0; }
  [ "$ok" = 1 ] || { log "RESULT INCOMPLETE phase=preflight reason=identity_mismatch"; exit 1; }

  # 记录环境 (供 analyzer 与证据链使用)
  {
    echo "server_ip=${SERVER_IP}"
    echo "router_ip=${ROUTER_IP}"
    echo "port=${PORT}"
    echo "source_revision=${SOURCE_REVISION}"
    echo "build_repo_commit=${BUILD_REPO_COMMIT}"
    echo "board=${board}"
    echo "kernel=${kernel}"
    echo "firmware_revision=${revision}"
    echo "boot_id=${boot_id}"
    echo "endpoint_info=${ENDPOINT_INFO}"
    echo "client_nic_info=${CLIENT_NIC_INFO}"
    echo "iperf3_version=$(iperf3 --version 2>&1 | head -1)"
    echo "rounds=${ROUNDS}"
    echo "duration=${DURATION}"
    echo "long_duration=${LONG_DURATION}"
    echo "long_retx_limit=${LONG_RETX_LIMIT}"
    echo "skip_tcp=${SKIP_TCP}"
    echo "skip_udp=${SKIP_UDP}"
    echo "skip_long=${SKIP_LONG}"
    date +%Y-%m-%dT%H:%M:%S%z
  } > "$OUT/env.txt"
  log "IDENTITY board=${board} kernel=${kernel} rev=${revision} boot=${boot_id:0:8}..."
  log "ENDPOINT ${ENDPOINT_INFO} | client=${CLIENT_NIC_INFO}"
}

# ── AX6 快照 (只读固定安全路径; softnet hex→dec) ──────────────────────────
ax6_snapshot() {
  local f="$1"
  {
    echo "=== boot_id ==="; "${SSH[@]}" cat /proc/sys/kernel/random/boot_id
    echo "=== uptime ==="; "${SSH[@]}" cat /proc/uptime
    echo "=== edma_err_stats ==="; "${SSH[@]}" cat /sys/kernel/debug/qca-nss-drv/stats/edma/err_stats
    echo "=== softnet_stat_raw ==="; "${SSH[@]}" cat /proc/net/softnet_stat
    for d in lan1 lan2; do
      echo "=== $d ==="
      "${SSH[@]}" "for c in rx_bytes tx_bytes rx_packets tx_packets rx_errors rx_dropped tx_errors tx_dropped; do echo -n \"\$c=\"; cat /sys/class/net/$d/statistics/\$c 2>/dev/null; done"
    done
    echo "=== temp ==="; "${SSH[@]}" "cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1" || true
  } > "$f"
  python3 - "$f" <<'EOF'
import sys
p = sys.argv[1]
lines = open(p).read().split("\n")
out, in_soft = [], False
for ln in lines:
    if ln.startswith("=== softnet_stat_raw"):
        in_soft = True; out.append(ln.replace("raw", "dec")); continue
    if ln.startswith("=== ") and not ln.startswith("=== softnet_stat_dec"):
        in_soft = False; out.append(ln); continue
    if in_soft and ln.strip():
        out.append(" ".join(str(int(x, 16)) for x in ln.split())); continue
    out.append(ln)
open(p, "w").write("\n".join(out))
EOF
}

# ── iperf3 一轮 (严格: 退出码 + JSON + 逐 stream) ─────────────────────────
run_tcp() { # $1=阶段 $2=轮次 $3=模式(fwd/rev/bidir) $4=并行数
  local phase=$1 r=$2 mode=$3 pcount=$4
  local j="$OUT/$phase-$mode-r$r.json"
  local args=(-c "$SERVER_IP" -p "$PORT" -P "$pcount" -t "$DURATION" -J)
  [ "$mode" = rev ] && args+=(-R)
  [ "$mode" = bidir ] && args+=(--bidir)
  log "TCP $phase-$mode r$r (${DURATION}s -P $pcount)"
  iperf3 "${args[@]}" > "$j" 2> "$OUT/$phase-$mode-r$r.err"
  local rc=$?
  [ "$rc" -eq 0 ] || { log "RESULT INCOMPLETE $phase-$mode-r$r reason=iperf_rc=${rc}"; return 1; }
  python3 - "$j" "$phase" "$mode" "$r" <<'EOF'
import json, sys
j = json.load(open(sys.argv[1]))
if j.get("error"):
    print(f"RESULT INCOMPLETE {sys.argv[2]}-{sys.argv[3]}-r{sys.argv[4]} reason=json_error"); sys.exit(1)
e = j.get("end", {}) or {}
dirs = {}
for s in e.get("streams", []):
    send = s.get("sender", {}) or {}
    secs = send.get("seconds")
    if not secs:
        print(f"RESULT INCOMPLETE {sys.argv[2]}-{sys.argv[3]}-r{sys.argv[4]} reason=no_duration"); sys.exit(1)
    k = "MAC->WIN" if send.get("sender") else "WIN->MAC"
    d = dirs.setdefault(k, [0, 0])
    d[0] += send.get("bytes", 0) * 8 / secs / 1e6
    d[1] += send.get("retransmits", 0)
for k, (bps, rt) in sorted(dirs.items()):
    print(f"RESULT {sys.argv[2]}-{sys.argv[3]}-r{sys.argv[4]} {k}: {bps:.1f} Mbps retrans={rt}")
EOF
}

run_udp() { # $1=速率 $2=轮次 $3=方向(fwd/rev)
  local rate=$1 r=$2 dir=$3
  local j="$OUT/udp-$rate-$dir-r$r.json"
  local args=(-c "$SERVER_IP" -p "$PORT" -u -b "${rate}M" -t "$DURATION" -J)
  [ "$dir" = rev ] && args+=(-R)
  log "UDP ${rate}M-$dir r$r (${DURATION}s)"
  iperf3 "${args[@]}" > "$j" 2> "$OUT/udp-$rate-$dir-r$r.err"
  local rc=$?
  [ "$rc" -eq 0 ] || { log "RESULT INCOMPLETE udp-$rate-$dir-r$r reason=iperf_rc=${rc}"; return 1; }
  python3 - "$j" "$rate" "$dir" "$r" "$DURATION" <<'EOF'
import json, sys
j = json.load(open(sys.argv[1]))
dur = float(sys.argv[5])
if j.get("error"):
    print(f"RESULT INCOMPLETE udp-{sys.argv[2]}-{sys.argv[3]}-r{sys.argv[4]} reason=json_error"); sys.exit(1)
e = j.get("end", {}) or {}
streams = e.get("streams", [])
if not streams:
    print(f"RESULT INCOMPLETE udp-{sys.argv[2]}-{sys.argv[3]}-r{sys.argv[4]} reason=no_streams"); sys.exit(1)
for s in streams:
    # iperf3 3.21 UDP: 数据在 stream.udp (含 seconds/lost_percent), sender 为 None
    udp = s.get("udp", {}) or {}
    secs = udp.get("seconds")
    if not secs:
        print(f"RESULT INCOMPLETE udp-{sys.argv[2]}-{sys.argv[3]}-r{sys.argv[4]} reason=no_duration"); sys.exit(1)
    if secs < dur * 0.9:
        print(f"RESULT INCOMPLETE udp-{sys.argv[2]}-{sys.argv[3]}-r{sys.argv[4]} reason=duration_short={secs:.1f}s"); sys.exit(1)
    bps = udp.get("bytes", 0) * 8 / secs / 1e6
    print(f"RESULT UDP-{sys.argv[2]}-{sys.argv[3]}-r{sys.argv[4]}: {bps:.1f} Mbps loss={udp.get('lost_percent', 0):.2f}% jitter={udp.get('jitter_ms', 0):.2f}ms")
EOF
}

# ── 主流程 ───────────────────────────────────────────────────────────────────
main() {
  [ -n "$SOURCE_REVISION" ] && [ -n "$BUILD_REPO_COMMIT" ] && \
    [ -n "$EXPECTED_BOARD" ] && [ -n "$EXPECTED_KERNEL" ] && [ -n "$EXPECTED_REVISION" ] || {
    log "FATAL identity env required: AX6_SOURCE_REVISION AX6_BUILD_COMMIT AX6_EXPECTED_BOARD AX6_EXPECTED_KERNEL AX6_EXPECTED_REVISION"
    log "RESULT INCOMPLETE phase=preflight reason=identity_env_missing"
    exit 1
  }
  [ -n "$ENDPOINT_INFO" ] || {
    log "FATAL AX6_ENDPOINT_INFO required (endpoint NIC/driver/OS identity)"
    log "RESULT INCOMPLETE phase=preflight reason=endpoint_info_missing"
    exit 1
  }
  # 拓扑误用防护 (R2 P0-7): iperf3 server 不得是路由器本机 (那是 router-local 场景)
  if [ "$SERVER_IP" = "$ROUTER_IP" ]; then
    log "FATAL topology misuse: SERVER_IP == ROUTER_IP (host-terminated traffic); use ax6-router-local-perf-test.sh"
    log "RESULT INCOMPLETE phase=preflight reason=topology_misuse"
    exit 1
  fi
  # 服务器可达性
  iperf3 -c "$SERVER_IP" -p "$PORT" -t 1 -J > "$OUT/probe.json" 2>/dev/null || {
    log "FATAL iperf3 server unreachable at ${SERVER_IP}:${PORT}"
    log "RESULT INCOMPLETE phase=preflight reason=server_unreachable"
    exit 1
  }

  preflight_identity
  ax6_snapshot "$OUT/pre-all.txt"

  abort_run() { log "RESULT INCOMPLETE run=aborted reason=$1"; exit 1; }
  if [ "$SKIP_TCP" != 1 ]; then
    for r in $(seq 1 "$ROUNDS"); do
      # P1 = 单流 (真 -P 1), P4 = 四流 (真 -P 4) — R2 P0-6
      run_tcp "P1" "$r" "fwd" 1   || abort_run "P1-fwd-r$r";   ax6_snapshot "$OUT/P1-fwd-r$r-post.txt"
      run_tcp "P1" "$r" "rev" 1   || abort_run "P1-rev-r$r";   ax6_snapshot "$OUT/P1-rev-r$r-post.txt"
      run_tcp "P1" "$r" "bidir" 1 || abort_run "P1-bidir-r$r"; ax6_snapshot "$OUT/P1-bidir-r$r-post.txt"
      run_tcp "P4" "$r" "fwd" 4   || abort_run "P4-fwd-r$r";   ax6_snapshot "$OUT/P4-fwd-r$r-post.txt"
      run_tcp "P4" "$r" "rev" 4   || abort_run "P4-rev-r$r";   ax6_snapshot "$OUT/P4-rev-r$r-post.txt"
      run_tcp "P4" "$r" "bidir" 4 || abort_run "P4-bidir-r$r"; ax6_snapshot "$OUT/P4-bidir-r$r-post.txt"
    done
  fi

  if [ "$SKIP_UDP" != 1 ]; then
    for r in $(seq 1 "$ROUNDS"); do
      run_udp 300 "$r" fwd || abort_run "udp-300-fwd-r$r"; ax6_snapshot "$OUT/udp-300-fwd-r$r-post.txt"
      run_udp 300 "$r" rev || abort_run "udp-300-rev-r$r"; ax6_snapshot "$OUT/udp-300-rev-r$r-post.txt"
      run_udp 600 "$r" fwd || abort_run "udp-600-fwd-r$r"; ax6_snapshot "$OUT/udp-600-fwd-r$r-post.txt"
      run_udp 600 "$r" rev || abort_run "udp-600-rev-r$r"; ax6_snapshot "$OUT/udp-600-rev-r$r-post.txt"
      run_udp 900 "$r" fwd || abort_run "udp-900-fwd-r$r"; ax6_snapshot "$OUT/udp-900-fwd-r$r-post.txt"
      run_udp 900 "$r" rev || abort_run "udp-900-rev-r$r"; ax6_snapshot "$OUT/udp-900-rev-r$r-post.txt"
    done
  fi

  if [ "$SKIP_LONG" != 1 ]; then
    local j="$OUT/long-bidir.json"
    log "LONG bidir (${LONG_DURATION}s -P 4)"
    iperf3 -c "$SERVER_IP" -p "$PORT" -P 4 -t "$LONG_DURATION" --bidir -J > "$j" 2> "$OUT/long-bidir.err"
    local rc=$?
    [ "$rc" -eq 0 ] || { log "RESULT INCOMPLETE long-bidir reason=iperf_rc=${rc}"; exit 1; }
    python3 - "$j" <<'EOF'
import json, sys
j = json.load(open(sys.argv[1]))
if j.get("error"):
    print("RESULT INCOMPLETE long-bidir reason=json_error"); sys.exit(1)
e = j.get("end", {}) or {}
dirs = {}
for s in e.get("streams", []):
    send = s.get("sender", {}) or {}
    secs = send.get("seconds")
    if not secs:
        print("RESULT INCOMPLETE long-bidir reason=no_duration"); sys.exit(1)
    k = "MAC->WIN" if send.get("sender") else "WIN->MAC"
    d = dirs.setdefault(k, [0, 0])
    d[0] += send.get("bytes", 0) * 8 / secs / 1e6
    d[1] += send.get("retransmits", 0)
for k, (bps, rt) in sorted(dirs.items()):
    print(f"RESULT long-bidir {k}: {bps:.1f} Mbps retrans={rt}")
EOF
    ax6_snapshot "$OUT/long-bidir-post.txt"
  fi

  ax6_snapshot "$OUT/post-all.txt"

  # SHA 归档必须是 run 目录最后一次写入 (其后 runner.log 冻结, 保证可校验)
  log "SHA256 归档: $OUT/SHA256SUMS.txt (runner.log 冻结后生成)"
  log "RUN COMPLETE: $OUT (判定交由 ax6-perf-analyzer.sh, 执行完成 ≠ 通过 — R2 P0-8)"
  (cd "$OUT" && find . -type f ! -name '.DS_Store' ! -name 'SHA256SUMS.txt' | sort | xargs shasum -a 256 > SHA256SUMS.txt)
  exit 0
}

main "$@"
