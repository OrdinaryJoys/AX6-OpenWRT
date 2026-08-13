#!/usr/bin/env bash
# AX6 测试工具硬化 fixture (R2 P0-7) — 离线负样本/正样本, 不接触实机
# ============================================================================
# 8 场景: ① 身份缺失拒绝 ② P1/P4 参数 ③ 错误 JSON ④ iperf 非零退出
#         ⑤ boot ID 变化 ⑥ LAN/WAN 拓扑误用 ⑦ SHA 归档损坏 ⑧ analyzer 四状态
# 核心断言: 任何失败路径绝不产生 PASS/COMPLETE (无伪 PASS)。
# ============================================================================

set -uo pipefail

TEST_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$TEST_DIR/scripts"
ROUTER_LOCAL="$SCRIPTS/ax6-router-local-perf-test.sh"
LANLAN="$SCRIPTS/ax6-lanlan-perf-test.sh"
ANALYZER="$SCRIPTS/ax6-perf-analyzer.sh"
WORK="$(mktemp -d /tmp/ax6-perf-hardening.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

# ── 前置: 脚本存在 + 语法 ──────────────────────────────────────────────────
echo "== 前置: 存在性与语法 =="
for s in "$ROUTER_LOCAL" "$LANLAN" "$ANALYZER"; do
  [ -f "$s" ] && bash -n "$s" 2>/dev/null && ok "bash -n $(basename "$s")" || bad "bash -n $(basename "$s")"
done

# ── Mock 环境 ───────────────────────────────────────────────────────────────
MOCK="$WORK/mock"; CTRL="$WORK/ctrl"
mkdir -p "$MOCK" "$CTRL"
echo "fixed-boot-id-0000" > "$CTRL/boot_id"
echo "0" > "$CTRL/ssh_fail_after"     # 0=永不失败
echo "0" > "$CTRL/boot_change_after" # 0=永不变化
echo "good" > "$CTRL/iperf_mode"
echo "0.0" > "$CTRL/udp_loss"
: > "$CTRL/args.log"

cat > "$MOCK/ssh" <<'MOCKEOF'
#!/usr/bin/env bash
# 解析远端命令串 (最后一个参数), 按模式返回; 计数器控制 boot_id 变化与失败
CTRL="$AX6_MOCK_CTRL"
cmd="${*}"
cmd="${cmd#*root@192.168.5.1 }"
n=$(cat "$CTRL/ssh_calls" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$CTRL/ssh_calls"
fail_after=$(cat "$CTRL/ssh_fail_after")
[ "$fail_after" != 0 ] && [ "$n" -ge "$fail_after" ] && { echo "ssh: simulated failure" >&2; exit 255; }
change_after=$(cat "$CTRL/boot_change_after")
case "$cmd" in
  *boot_id*) if [ "$change_after" != 0 ] && [ "$n" -ge "$change_after" ]; then echo "changed-boot-id-9999"; else cat "$CTRL/boot_id"; fi ;;
  *sysinfo/model*) echo "Redmi AX6" ;;
  *"uname -r"*) echo "6.18.38" ;;
  *DISTRIB_REVISION*) echo "DISTRIB_REVISION='r0-4e35043'" ;;
  *ax6-perf-iperf3-15*) echo "42421" ;;
  *) echo "" ;;
esac
exit 0
MOCKEOF
chmod +x "$MOCK/ssh"

cat > "$MOCK/iperf3" <<'MOCKEOF'
#!/usr/bin/env python3
import sys, os, json
CTRL = os.environ["AX6_MOCK_CTRL"]
args = sys.argv[1:]
with open(os.path.join(CTRL, "args.log"), "a") as f:
    f.write(" ".join(args) + "\n")
mode = open(os.path.join(CTRL, "iperf_mode")).read().strip()
if mode == "exit1":
    sys.stderr.write("simulated iperf3 failure\n"); sys.exit(1)
def streams(n, t, sender, loss=0.0):
    out = []
    per = (930e6 / 8) * t / n
    for i in range(n):
        s = {"id": i + 1, "bytes": int(per), "seconds": float(t),
             "sender": {"sender": sender, "bytes": int(per), "seconds": float(t),
                        "retransmits": 0, "max_rtt_ms": 2.0}}
        if loss:
            s["udp"] = {"lost_percent": loss, "jitter_ms": 0.05, "packets": int(per/1400),
                        "seconds": float(t), "bytes": int(per)}
            s["sender"]["udp"] = {"lost_percent": loss}
        out.append(s)
    return out
def dur(args, default=30):
    if "-t" in args:
        return float(args[args.index("-t") + 1])
    return default
t = dur(args)
if mode == "badjson":
    sys.stdout.write("{ not json !!!"); sys.exit(0)
if "-u" in args:
    rate = float(args[args.index("-b") + 1].replace("M", ""))
    loss = float(open(os.path.join(CTRL, "udp_loss")).read().strip())
    rev = "-R" in args
    st = streams(1, t, sender=not rev, loss=loss)
    st[0]["bytes"] = int(rate * 1e6 * t / 8); st[0]["sender"]["bytes"] = st[0]["bytes"]
    d = {"end": {"sum_sent": {"bits_per_second": rate * 1e6}, "streams": st}}
elif "--bidir" in args:
    n = int(args[args.index("-P") + 1])
    st = streams(n, t, True) + streams(n, t, False)
    d = {"end": {"streams": st}}
else:
    n = int(args[args.index("-P") + 1]) if "-P" in args else 1
    rev = "-R" in args
    d = {"end": {"streams": streams(n, t, sender=not rev)}}
json.dump(d, sys.stdout)
sys.exit(0)
MOCKEOF
chmod +x "$MOCK/iperf3"

export AX6_MOCK_CTRL="$CTRL"
export PATH="$MOCK:$PATH"

# 通用环境
export AX6_ROUTER_IP=192.168.5.1
export AX6_SSH_KEY=/nonexistent/key
export AX6_KNOWN_HOSTS=/dev/null
export AX6_SOURCE_REVISION=r0-4e35043
export AX6_BUILD_COMMIT=83bda4162daba0e854bec8ef0ba21cecb712b189
export AX6_EXPECTED_BOARD="Redmi AX6"
export AX6_EXPECTED_KERNEL=6.18.38
export AX6_EXPECTED_REVISION=r0-4e35043
export AX6_RESULT_DIR="$WORK/runs"

# ── 场景 ①: 身份 env 缺失 → 拒绝, 非零退出 ────────────────────────────────
echo "== ① 身份缺失拒绝 (P0-2) =="
for var in AX6_SOURCE_REVISION AX6_BUILD_COMMIT AX6_EXPECTED_BOARD AX6_EXPECTED_KERNEL AX6_EXPECTED_REVISION; do
  rm -rf "$AX6_RESULT_DIR"
  if env -u "$var" bash "$ROUTER_LOCAL" >/dev/null 2>&1; then
    bad "router-local: missing $var 未拒绝 (exit=0)"
  else
    ok "router-local: missing $var → 拒绝非零退出"
  fi
done
rm -rf "$AX6_RESULT_DIR"
env -u AX6_ENDPOINT_INFO bash "$LANLAN" >/dev/null 2>&1 && bad "lanlan: 缺 ENDPOINT_INFO 未拒绝" || ok "lanlan: 缺 ENDPOINT_INFO → 拒绝"

# ── 场景 ②: P1/P4 参数 (真 -P 1 / -P 4) ────────────────────────────────────
echo "== ② P1/P4 参数 (P0-6) =="
export AX6_ENDPOINT_INFO="Mock Linux endpoint RTL8153"
export AX6_LANLAN_SERVER_IP=192.168.5.111
export AX6_LANLAN_OUT_BASE="$WORK/lanlan-runs"
export AX6_ROUNDS=1 AX6_DURATION=2 AX6_SKIP_UDP=1 AX6_SKIP_LONG=1
rm -rf "$AX6_LANLAN_OUT_BASE"; : > "$CTRL/args.log"
bash "$LANLAN" >/dev/null 2>&1 || bad "lanlan 正样本运行失败"
grep -q -- "-P 1 -t 2" "$CTRL/args.log" && ok "P1 使用 -P 1" || bad "P1 未使用 -P 1"
grep -q -- "-P 4 -t 2" "$CTRL/args.log" && ok "P4 使用 -P 4" || bad "P4 未使用 -P 4"
grep -q -- "-P 4.*--bidir" "$CTRL/args.log" && ok "bidir 使用 -P 4" || bad "bidir 参数异常"

# ── 场景 ③: 错误 JSON → INCOMPLETE 非零 ────────────────────────────────────
echo "== ③ 错误 JSON (P0-4) =="
rm -rf "$AX6_RESULT_DIR"; echo "badjson" > "$CTRL/iperf_mode"
export AX6_P1_DURATION=2 AX6_P2_DURATION=2 AX6_P3_DURATION=2 AX6_P4_BURST_COUNT=2 AX6_MONITOR_INTERVAL=1
if bash "$ROUTER_LOCAL" >/dev/null 2>&1; then
  bad "badjson 下 router-local 仍 exit=0 (伪 PASS)"
else
  grep -q "INCOMPLETE" "$AX6_RESULT_DIR"/ax6-router-local-perf-*.log 2>/dev/null && \
    ok "badjson → INCOMPLETE 非零" || bad "badjson → 未标记 INCOMPLETE"
fi
echo "good" > "$CTRL/iperf_mode"

# ── 场景 ④: iperf 非零退出 → INCOMPLETE ────────────────────────────────────
echo "== ④ iperf 非零退出 (P0-5) =="
rm -rf "$AX6_RESULT_DIR"; echo "exit1" > "$CTRL/iperf_mode"
bash "$ROUTER_LOCAL" >/dev/null 2>&1 && bad "iperf 非零下仍 exit=0" || ok "iperf 非零 → 非零退出"
echo "good" > "$CTRL/iperf_mode"

# ── 场景 ⑤: boot ID 变化 → INCOMPLETE ──────────────────────────────────────
echo "== ⑤ boot ID 变化 (P0-5) =="
rm -rf "$AX6_RESULT_DIR"; echo "8" > "$CTRL/boot_change_after"
bash "$ROUTER_LOCAL" >/dev/null 2>&1 && bad "boot 变化下仍 exit=0" || ok "boot 变化 → 非零退出"
echo "0" > "$CTRL/boot_change_after"

# ── 场景 ⑥: LAN/WAN 拓扑误用 ───────────────────────────────────────────────
echo "== ⑥ 拓扑误用 (P0-7) =="
AX6_LANLAN_SERVER_IP=192.168.5.1 bash "$LANLAN" >/dev/null 2>&1 && \
  bad "SERVER==ROUTER 未拒绝" || ok "SERVER==ROUTER → 拒绝 (topology_misuse)"
export AX6_LANLAN_SERVER_IP=192.168.5.111

# ── 场景 ⑦: SHA 归档损坏 → analyzer INCOMPLETE ────────────────────────────
echo "== ⑦ SHA 归档损坏 =="
RUN7="$WORK/sha-corrupt-run"; mkdir -p "$RUN7"
echo "endpoint_info=Mock Linux endpoint RTL8153" > "$RUN7/env.txt"
echo "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef  ./env.txt" > "$RUN7/SHA256SUMS.txt"
"$ANALYZER" "$RUN7" >/dev/null 2>&1
rc=$?
[ "$rc" -eq 2 ] && ok "SHA 损坏 → INCOMPLETE (exit=2)" || bad "SHA 损坏 → exit=$rc (期望 2)"

# ── 场景 ⑧: analyzer 四状态 (正/负样本) ────────────────────────────────────
echo "== ⑧ analyzer 四状态 =="
python3 - "$WORK" <<'PYEOF'
import json, os, sys, hashlib
w = sys.argv[1]

def build(name, bps_fwd, bps_rev, loss300, loss900, endpoint, snapshots=True):
    d = os.path.join(w, name)
    os.makedirs(d, exist_ok=True)
    env = f"endpoint_info={endpoint}\nfirmware_revision=r0-4e35043\n"
    open(os.path.join(d, "env.txt"), "w").write(env)
    def tcp(fn, n_streams, mode, bps):
        t = 30.0
        per = bps * 1e6 * t / 8 / n_streams
        st = []
        senders = {"fwd": [True], "rev": [False], "bidir": [True, False]}
        for k, snd in enumerate(senders[mode] * (n_streams if mode != "bidir" else 1)):
            if mode == "bidir":
                snd = k < n_streams
            st.append({"bytes": int(per), "seconds": t,
                       "sender": {"sender": snd, "bytes": int(per), "seconds": t, "retransmits": 0}})
        json.dump({"end": {"streams": st}}, open(os.path.join(d, fn), "w"))
    tcp("P1-fwd-r1.json", 1, "fwd", bps_fwd); tcp("P1-fwd-r2.json", 1, "fwd", bps_fwd); tcp("P1-fwd-r3.json", 1, "fwd", bps_fwd)
    tcp("P1-rev-r1.json", 1, "rev", bps_rev); tcp("P1-rev-r2.json", 1, "rev", bps_rev); tcp("P1-rev-r3.json", 1, "rev", bps_rev)
    tcp("P1-bidir-r1.json", 1, "bidir", bps_fwd); tcp("P1-bidir-r2.json", 1, "bidir", bps_fwd); tcp("P1-bidir-r3.json", 1, "bidir", bps_fwd)
    def udp(fn, loss):
        t = 30.0
        st = [{"udp": {"lost_percent": loss, "jitter_ms": 0.05,
                       "seconds": t, "bytes": 300 * 1e6 * t / 8}}]
        json.dump({"end": {"streams": st}}, open(os.path.join(d, fn), "w"))
    udp("udp-300-fwd-r1.json", loss300); udp("udp-300-rev-r1.json", 0.0)
    udp("udp-600-fwd-r1.json", 0.05); udp("udp-600-rev-r1.json", 0.0)
    udp("udp-900-fwd-r1.json", loss900); udp("udp-900-rev-r1.json", 0.0)
    if snapshots:
        def snap(fn, extra=""):
            open(os.path.join(d, fn), "w").write(
                "=== lan1 ===\nrx_errors=0\nrx_dropped=0\ntx_errors=0\ntx_dropped=0\n"
                "rx_bytes=1000\ntx_bytes=1000\n"
                "=== lan2 ===\nrx_errors=0\nrx_dropped=0\ntx_errors=0\ntx_dropped=0\n"
                "rx_bytes=1000\ntx_bytes=1000\n"
                "=== edma_err_stats ===\nedma_err_alloc_fail_cnt = 4990\n"
                "=== softnet_stat_dec ===\n100 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n" + extra)
        snap("pre-all.txt"); snap("post-all.txt")
    # SHA
    lines = []
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if f == "SHA256SUMS.txt": continue
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        lines.append(f"{h}  ./{f}")
    open(os.path.join(d, "SHA256SUMS.txt"), "w").write("\n".join(lines) + "\n")

build("s8-pass", 940, 945, 0.0, 0.2, "MacBook onboard RTL8153", True)
build("s8-fail", 700, 945, 0.0, 0.2, "MacBook onboard RTL8153", True)
build("s8-ax88179", 940, 945, 0.0, 0.2, "Windows AX88179 USB3 driver 1.16.27.321", True)
build("s8-ax88179-degraded", 600, 700, 1.2, 2.5, "Windows AX88179 USB3 driver 1.16.27.321", True)
build("s8-incomplete", 940, 945, 0.0, 0.2, "MacBook onboard RTL8153", False)
PYEOF
check_rc() { # dir expected_rc label
  "$ANALYZER" "$1" >/dev/null 2>&1; rc=$?
  [ "$rc" -eq "$2" ] && ok "$3 (exit=$rc)" || bad "$3: exit=$rc 期望 $2"
}
check_rc "$WORK/s8-pass" 0 "PASS 样本 → PASS"
check_rc "$WORK/s8-fail" 1 "低吞吐样本 → FAIL"
check_rc "$WORK/s8-ax88179" 3 "AX88179 双向 → ENV-BLOCKED"
check_rc "$WORK/s8-ax88179-degraded" 3 "AX88179 低吞吐 → ENV-BLOCKED (非 FAIL, R2 §6)"
check_rc "$WORK/s8-incomplete" 2 "缺快照 → INCOMPLETE"

# ── 核心断言: 无伪 PASS ─────────────────────────────────────────────────────
echo "== 无伪 PASS 断言 =="
for d in "$WORK"/runs/ax6-router-local-perf-*.log; do
  [ -f "$d" ] || continue
  if grep -q "INCOMPLETE" "$d"; then
    if grep -q "RESULT COMPLETE all_phases=passed" "$d"; then
      bad "$(basename "$d"): INCOMPLETE 与成功 COMPLETE 并存 (伪 PASS)"
    else
      ok "$(basename "$d"): INCOMPLETE 且无成功 COMPLETE"
    fi
  fi
done

echo ""
echo "===== PERF TOOL HARDENING FIXTURE: ${PASS} PASS / ${FAIL} FAIL ====="
[ "$FAIL" -eq 0 ] && echo "STATUS: ALL PASSED ✅" || echo "STATUS: FAILURES ❌"
exit "$FAIL"
