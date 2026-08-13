#!/usr/bin/env bash
# AX6 吞吐测试独立分析器 (R2 P0-8) — 只读, 不产生测试数据
# ============================================================================
# 输入: LAN-LAN runner 生成的 run 目录 (env.txt + *.json + 快照 + SHA256SUMS.txt)
# 输出: 逐场景判定 + JSON verdict; 退出码 0=PASS 1=FAIL 2=INCOMPLETE 3=ENV-BLOCKED
# 原则: 执行完成 ≠ 通过; 阈值判定与原始 JSON 分离; 端点先饱和 → ENV-BLOCKED
#       不得判 AX6 FAIL (R2 §6)。
# 用法: ax6-perf-analyzer.sh RUN_DIR [--assume-qualified-endpoint]
# ============================================================================

set -uo pipefail

RUN_DIR="${1:?usage: ax6-perf-analyzer.sh RUN_DIR [--assume-qualified-endpoint]}"
QUALIFIED=0
[ "${2:-}" = "--assume-qualified-endpoint" ] && QUALIFIED=1

[ -d "$RUN_DIR" ] || { echo "INCOMPLETE: run dir not found: $RUN_DIR"; exit 2; }

python3 - "$RUN_DIR" "$QUALIFIED" <<'PYEOF'
import json, sys, os, glob, re, collections

run, qualified = sys.argv[1], bool(int(sys.argv[2]))
issues = []
verdicts = []          # (scenario, status, detail)
status_rank = {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2, "ENV-BLOCKED": 3}

# ── 0. 完整性 ──────────────────────────────────────────────────────────────
env_file = os.path.join(run, "env.txt")
if not os.path.exists(env_file):
    print(json.dumps({"overall": "INCOMPLETE", "reason": "env.txt missing"}, indent=2))
    sys.exit(2)
env = {}
for ln in open(env_file):
    ln = ln.strip()
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1); env[k.strip()] = v.strip()

json_files = sorted(glob.glob(os.path.join(run, "*.json")))
if not json_files:
    print(json.dumps({"overall": "INCOMPLETE", "reason": "no iperf3 JSON found"}, indent=2))
    sys.exit(2)

# SHA 归档校验 (R2 P0-7)
sha_file = os.path.join(run, "SHA256SUMS.txt")
if not os.path.exists(sha_file):
    issues.append(("SHA256SUMS.txt missing", "INCOMPLETE"))
else:
    import subprocess
    try:
        subprocess.check_output(["shasum", "-a", "256", "-c", "SHA256SUMS.txt"],
                                cwd=run, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        issues.append(("SHA256SUMS verification failed: " + e.output.decode().strip()[:200], "INCOMPLETE"))

def add_issue(scn, detail, status="FAIL"):
    issues.append((f"{scn}: {detail}", status))
    verdicts.append((scn, status, detail))

# ── 1. 逐 JSON 解析 (与 runner 独立) ──────────────────────────────────────
scenarios = collections.defaultdict(lambda: collections.defaultdict(list))
incomplete_any = False
for jp in json_files:
    name = os.path.basename(jp)[:-5]
    try:
        j = json.load(open(jp))
    except Exception:
        incomplete_any = True
        add_issue(name, "JSON parse failed", "INCOMPLETE")
        continue
    if j.get("error"):
        incomplete_any = True
        add_issue(name, f"iperf3 .error={j['error']}", "INCOMPLETE")
        continue
    e = j.get("end", {}) or {}
    streams = e.get("streams", [])
    if not streams:
        incomplete_any = True
        add_issue(name, "no streams", "INCOMPLETE")
        continue
    if name.startswith("udp-"):
        m = re.match(r"udp-(\d+)-(fwd|rev)-r(\d+)", name)
        if not m:
            continue
        rate, direction, rnd = m.group(1), m.group(2), m.group(3)
        for s in streams:
            # iperf3 3.21 UDP: 数据在 stream.udp (seconds/lost_percent), sender 为 None
            udp = s.get("udp", {}) or {}
            secs = udp.get("seconds")
            if not secs:
                incomplete_any = True
                add_issue(name, "no udp.seconds", "INCOMPLETE")
                break
            scenarios[("udp", rate, direction)].setdefault("runs", []).append(
                {"loss": udp.get("lost_percent", 0.0), "jitter": udp.get("jitter_ms", 0.0),
                 "bps": udp.get("bytes", 0) * 8 / secs / 1e6})
    elif name.startswith("long-bidir"):
        for s in streams:
            send = s.get("sender", {}) or {}
            secs = send.get("seconds")
            if not secs:
                incomplete_any = True
                add_issue(name, "no sender.seconds", "INCOMPLETE")
                break
            k = "MAC->WIN" if send.get("sender") else "WIN->MAC"
            scenarios[("long", k)].setdefault("runs", []).append(
                {"bps": send.get("bytes", 0) * 8 / secs / 1e6,
                 "retx": send.get("retransmits", 0)})
    else:
        m = re.match(r"(P[14])-(fwd|rev|bidir)-r(\d+)", name)
        if not m:
            continue
        phase, mode, rnd = m.group(1), m.group(2), m.group(3)
        dirs = collections.defaultdict(lambda: [0, 0])
        for s in streams:
            send = s.get("sender", {}) or {}
            secs = send.get("seconds")
            if not secs:
                incomplete_any = True
                add_issue(name, "no sender.seconds", "INCOMPLETE")
                break
            k = "MAC->WIN" if send.get("sender") else "WIN->MAC"
            dirs[k][0] += send.get("bytes", 0) * 8 / secs / 1e6
            dirs[k][1] += send.get("retransmits", 0)
        for k, (bps, rt) in dirs.items():
            scenarios[(phase, mode, k)].setdefault("runs", []).append({"bps": bps, "retx": rt})

endpoint = env.get("endpoint_info", "")
ax88179 = "AX88179" in endpoint or "ax88179" in endpoint.lower()

# ── 2. 阈值判定 (R2 §5.3) ─────────────────────────────────────────────────
def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

def judge_tcp_unidir(key, label):
    v = scenarios.get(key)
    if not v or not v.get("runs"):
        return
    runs = v["runs"]
    if any(not r or "bps" not in r for r in runs):
        add_issue(label, "incomplete runs", "INCOMPLETE"); return
    med = median([r["bps"] for r in runs])
    mn = min(r["bps"] for r in runs)
    retx = sum(r.get("retx", 0) for r in runs)
    if med >= 930 and mn >= 900:
        verdicts.append((label, "PASS", f"median={med:.1f} min={mn:.1f} Mbps retx={retx}"))
    elif ax88179 and not qualified:
        verdicts.append((label, "ENV-BLOCKED",
            f"AX88179 endpoint, {med:.0f}/{mn:.0f} Mbps (retx={retx}) < 阈值 — 兼容性样本, "
            "端点 CPU/USB/驱动无法排除 (R2 §6), 不得判 AX6 FAIL"))
    else:
        verdicts.append((label, "FAIL", f"median={med:.1f} (<930) or min={mn:.1f} (<900) Mbps retx={retx}"))

def judge_tcp_bidir(key, label):
    v = scenarios.get(key)
    if not v or not v.get("runs"):
        return
    runs = v["runs"]
    med = median([r["bps"] for r in runs])
    mn = min(r["bps"] for r in runs)
    if ax88179 and not qualified:
        # R2 §5.1: AX88179 兼容性样本不能单独给 AX6 双向下结论 — 无论数值高低
        verdicts.append((label, "ENV-BLOCKED",
            f"AX88179 endpoint bidir {med:.0f}/{mn:.0f} Mbps — 双向结论需合格端点 (R2 §5.1)"))
    elif med >= 850 and mn >= 750:
        verdicts.append((label, "PASS", f"median={med:.1f} min={mn:.1f} Mbps"))
    else:
        verdicts.append((label, "FAIL", f"median={med:.1f} (<850) or min={mn:.1f} (<750) Mbps"))

def judge_udp(rate, label):
    for direction in ("fwd", "rev"):
        v = scenarios.get(("udp", rate, direction))
        if not v or not v.get("runs"):
            add_issue(f"{label} {direction}", "no runs", "INCOMPLETE"); continue
        losses = [r["loss"] for r in v["runs"]]
        worst = max(losses)
        limits = {"300": 0.05, "600": 0.1, "900": 1.0}
        if worst <= limits[rate]:
            verdicts.append((f"{label} {direction}", "PASS", f"max_loss={worst:.3f}%"))
        elif ax88179 and not qualified:
            verdicts.append((f"{label} {direction}", "ENV-BLOCKED",
                f"max_loss={worst:.3f}% > {limits[rate]}% — AX88179 端点无法排除丢包源 (R2 §6)"))
        else:
            verdicts.append((f"{label} {direction}", "FAIL", f"max_loss={worst:.3f}% > {limits[rate]}%"))

for phase in ("P1", "P4"):
    judge_tcp_unidir((phase, "fwd", "MAC->WIN"), f"TCP-{phase}-fwd MAC->WIN")
    judge_tcp_unidir((phase, "rev", "WIN->MAC"), f"TCP-{phase}-rev WIN->MAC")
    judge_tcp_bidir((phase, "bidir", "MAC->WIN"), f"TCP-{phase}-bidir MAC->WIN")
    judge_tcp_bidir((phase, "bidir", "WIN->MAC"), f"TCP-{phase}-bidir WIN->MAC")
for rate in ("300", "600", "900"):
    judge_udp(rate, f"UDP-{rate}")

# ── 3. 计数器差分 (pre-all vs 最后快照) ────────────────────────────────────
def parse_snapshot(f):
    d = {}; cur = None; in_soft = False
    if not os.path.exists(f):
        return None
    for ln in open(f):
        ln = ln.strip()
        m = re.match(r"=== (\w+) ===", ln)
        if m:
            cur = m.group(1); in_soft = (m.group(1) == "softnet_stat_dec"); continue
        if in_soft and ln.strip():
            d.setdefault("softnet", []).append([int(x) for x in ln.split()]); continue
        m = re.match(r"([\w_]+)=(\d+)", ln)
        if m: d.setdefault(cur or "?", {})[m.group(1)] = int(m.group(2)); continue
        m = re.match(r"(edma_err_[\w]+)\s*=\s*(\d+)", ln)
        if m: d.setdefault("edma", {})[m.group(1)] = int(m.group(2))
    return d

pre = parse_snapshot(os.path.join(run, "pre-all.txt"))
posts = sorted(glob.glob(os.path.join(run, "*post*.txt")))
post = parse_snapshot(posts[-1]) if posts else None

if pre is None or post is None:
    add_issue("counters", "pre/post snapshot missing", "INCOMPLETE")
else:
    for dev in ("lan1", "lan2"):
        for c in ("rx_errors", "rx_dropped", "tx_errors", "tx_dropped"):
            a = pre.get(dev, {}).get(c, 0); b = post.get(dev, {}).get(c, 0)
            if b != a:
                add_issue(f"counter {dev}.{c}", f"{a} -> {b} (Δ{b-a})", "FAIL")
    for k in pre.get("edma", {}):
        a = pre["edma"][k]; b = post.get("edma", {}).get(k, a)
        if b != a:
            add_issue(f"counter edma.{k}", f"{a} -> {b} (Δ{b-a})", "FAIL")
    sp, so = pre.get("softnet", []), post.get("softnet", [])
    if sp and so and len(sp) == len(so):
        for i, (r0, r1) in enumerate(zip(sp, so)):
            if r1[1] != r0[1]:
                add_issue(f"softnet cpu{i} dropped", f"{r0[1]} -> {r1[1]}", "FAIL")

# ── 4. 汇总 ─────────────────────────────────────────────────────────────────
worst = "PASS"
for scn, st, detail in verdicts:
    if status_rank[st] > status_rank[worst]:
        worst = st
for _, st in issues:
    if status_rank[st] > status_rank[worst]:
        worst = st
if incomplete_any and worst in ("PASS",):
    worst = "INCOMPLETE"

result = {
    "overall": worst,
    "run_dir": run,
    "firmware_revision": env.get("firmware_revision", ""),
    "endpoint_info": endpoint,
    "ax88179_endpoint": ax88179,
    "scenarios": [{"scenario": s, "status": st, "detail": d} for s, st, d in verdicts],
    "issues": [{"issue": s, "status": st} for s, st in issues],
}
print(json.dumps(result, indent=2, ensure_ascii=False))
sys.exit({"PASS": 0, "FAIL": 1, "INCOMPLETE": 2, "ENV-BLOCKED": 3}[worst])
PYEOF
