#!/bin/sh
# AX6 UDP 空闲基线 + socket inode 采集 — AX6_NEXT_PROGRESS_AND_TEST_PLAN_2026-08-03.md §5.1
# 只读检查: 不修改任何持久配置、不重启服务
# 方法: 60 秒 × 10 秒采样 (7 点), 记录 UDP InErrors/RcvbufErrors 差分、
#       ZeroTier/Clash 端口 socket inode 与 drops、softnet、端口错误
# 通过门槛: 无主动压力时所有计数器差分 = 0

FW="r0-0ea8486"        # source revision (immortalwrt-nss 0ea84864 构建)
BUILD="84fc0f2"        # build repo commit
ZTPORTS="2709|5f95|c3e6|1ec2|1ecf"   # hex: 9993|24469|50150|7874|7895

echo "=== AX6 UDP IDLE BASELINE $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "firmware=$FW build=$BUILD"
echo "boot_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)"
echo "uptime=$(cut -d' ' -f1 /proc/uptime)"
echo ""

# ── 起始快照 ───────────────────────────────────────────────────────────────
U0=$(grep '^Udp:' /proc/net/snmp | tail -1)
I0=$(echo "$U0" | awk '{print $4}')
R0=$(echo "$U0" | awk '{print $6}')
S0=$(awk '{d+=$2} END{print d}' /proc/net/softnet_stat 2>/dev/null)
P0=$(awk 'NR>2 {printf "%s:%s,%s,%s,%s ", $1, $4, $5, $12, $13}' /proc/net/dev)
ZT0=$(awk -v p="$ZTPORTS" 'NR>1 {split($2,a,":"); if (a[2] ~ "("p")") s+=$13} END{print s+0}' /proc/net/udp)
ZT6_0=$(awk -v p="$ZTPORTS" 'NR>1 {split($2,a,":"); if (a[2] ~ "("p")") s+=$13} END{print s+0}' /proc/net/udp6)
echo "起始: InErrors=$I0 RcvbufErrors=$R0 softnet=$S0 ZT_drops4=$ZT0 ZT_drops6=$ZT6_0"

# ── 7 次采样 ───────────────────────────────────────────────────────────────
SAMP=0
while [ $SAMP -lt 7 ]; do
  SAMP=$((SAMP+1))
  TS=$(date +%H:%M:%S)
  U=$(grep '^Udp:' /proc/net/snmp | tail -1)
  INERR=$(echo "$U" | awk '{print $4}')
  RCVBUF=$(echo "$U" | awk '{print $6}')
  SOFT=$(awk '{d+=$2} END{print d}' /proc/net/softnet_stat 2>/dev/null)
  echo "== #$SAMP $TS InErrors=$INERR RcvbufErrors=$RCVBUF softnet=$SOFT =="
  echo "  [非零 drops 的 UDP socket: proto local rxq drops inode]"
  awk 'NR>1 && $13+0>0 {print "  "$1, $2, "rxq="$5, "drops="$13, "inode="$11}' /proc/net/udp
  awk 'NR>1 && $13+0>0 {print "  "$1, $2, "rxq="$5, "drops="$13, "inode="$11}' /proc/net/udp6
  echo "  [关键端口 9993/24469/50150/7874/7895: local rxq drops inode]"
  awk -v p="$ZTPORTS" 'NR>1 {split($2,a,":"); if (a[2] ~ "("p")") print "  "$1, $2, "rxq="$5, "drops="$13, "inode="$11}' /proc/net/udp
  awk -v p="$ZTPORTS" 'NR>1 {split($2,a,":"); if (a[2] ~ "("p")") print "  "$1, $2, "rxq="$5, "drops="$13, "inode="$11}' /proc/net/udp6
  [ $SAMP -lt 7 ] && sleep 10
done

# ── 进程→socket inode 映射 (ZeroTier/Clash) ───────────────────────────────
echo "== 进程 socket inode 映射 =="
for p in $(pgrep -f "zerotier" 2>/dev/null) $(pgrep -f "clash" 2>/dev/null); do
  CMD=$(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | cut -c1-60)
  for fd in /proc/$p/fd/*; do
    ino=$(readlink "$fd" 2>/dev/null | sed -n 's/socket:\[\([0-9]*\)\]/\1/p')
    [ -n "$ino" ] && echo "  pid=$p inode=$ino fd=${fd##*/} $CMD"
  done
done

# ── 结束快照与差分 ─────────────────────────────────────────────────────────
U1=$(grep '^Udp:' /proc/net/snmp | tail -1)
I1=$(echo "$U1" | awk '{print $4}')
R1=$(echo "$U1" | awk '{print $6}')
S1=$(awk '{d+=$2} END{print d}' /proc/net/softnet_stat 2>/dev/null)
P1=$(awk 'NR>2 {printf "%s:%s,%s,%s,%s ", $1, $4, $5, $12, $13}' /proc/net/dev)
ZT1=$(awk -v p="$ZTPORTS" 'NR>1 {split($2,a,":"); if (a[2] ~ "("p")") s+=$13} END{print s+0}' /proc/net/udp)
ZT6_1=$(awk -v p="$ZTPORTS" 'NR>1 {split($2,a,":"); if (a[2] ~ "("p")") s+=$13} END{print s+0}' /proc/net/udp6)
echo ""
echo "== 差分 (60s 窗口) =="
echo "UDP InErrors:      $I0 -> $I1  (Δ=$((I1-I0)))"
echo "UDP RcvbufErrors:  $R0 -> $R1  (Δ=$((R1-R0)))"
echo "softnet drops:     $S0 -> $S1  (Δ=$((S1-S0)))"
echo "ZT 端口 drops(v4): $ZT0 -> $ZT1  (Δ=$((ZT1-ZT0)))"
echo "ZT 端口 drops(v6): $ZT6_0 -> $ZT6_1  (Δ=$((ZT6_1-ZT6_0)))"
echo "端口错误:"
echo "  起始: $P0"
echo "  结束: $P1"
echo ""
echo "== 服务状态 =="
zerotier-cli info 2>/dev/null | head -1
zerotier-cli listnetworks 2>/dev/null | tail -n +2 | head -2
echo "== nss-check -q (EDMA alloc-fail 增长检查) =="
nss-check -q 2>/dev/null
echo "rc=$?"
echo "=== BASELINE COMPLETE ==="
