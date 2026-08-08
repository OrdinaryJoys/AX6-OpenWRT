#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
SCRIPT="$ROOT/scripts/ax6-udp-baseline.sh"

fail() {
    echo "test-ax6-udp-baseline-fixture: FAIL: $*" >&2
    exit 1
}

sh -n "$SCRIPT" || fail "invalid shell syntax"
if grep -Eq 'r0-0ea8486|84fc0f2|2709\|5f95\|c3e6' "$SCRIPT"; then
    fail "stale firmware, build, or dynamic port constants remain"
fi
grep -Fq 'socket_inodes' "$SCRIPT" || fail "PID-to-inode ownership is missing"
grep -Fq 'AX6_BUILD_COMMIT' "$SCRIPT" || fail "exact build provenance is not required"
grep -Fq 'result=$RESULT reason=$REASON' "$SCRIPT" || fail "explicit result is missing"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM HUP
PROC="$TMP/proc"
NET="$TMP/net"
mkdir -p "$PROC/net" "$PROC/sys/kernel/random" "$PROC/101/fd" "$PROC/202/fd"
mkdir -p "$NET/wan/statistics" "$NET/lan1/statistics"

cat > "$PROC/net/snmp" <<'EOF'
Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors SndbufErrors InCsumErrors IgnoredMulti MemErrors
Udp: 100 0 4 90 4 0 0 0 0
EOF
cat > "$PROC/net/softnet_stat" <<'EOF'
00000010 0000000a 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000
EOF
cat > "$PROC/net/udp" <<'EOF'
  sl  local_address rem_address   st tx_queue:rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
   0: 00000000:2709 00000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 111 2 0 0
   1: 0100007F:1ECF 00000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 222 2 0 0
EOF
cp "$PROC/net/udp" "$PROC/net/udp6"
echo fixture-boot-id > "$PROC/sys/kernel/random/boot_id"
ln -s 'socket:[111]' "$PROC/101/fd/3"
ln -s 'socket:[222]' "$PROC/202/fd/4"

for iface in wan lan1; do
    for counter in rx_errors tx_errors rx_dropped tx_dropped; do
        echo 0 > "$NET/$iface/statistics/$counter"
    done
done
cat > "$TMP/health" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$TMP/health"

OUTPUT=$(AX6_PROC_ROOT="$PROC" AX6_NET_CLASS="$NET" \
    AX6_BASELINE_INTERVAL=0 AX6_BASELINE_SAMPLES=2 \
    AX6_BUILD_COMMIT=fixture-build AX6_SOURCE_REVISION=fixture-source \
    AX6_ZT_PIDS=101 AX6_CLASH_PIDS=202 \
    AX6_NSS_CHECK="$TMP/health" AX6_CONFIG_AUDIT="$TMP/health" \
    sh "$SCRIPT") || fail "stable fixture did not pass"

echo "$OUTPUT" | grep -Fq 'owner=zerotier' || fail "ZeroTier ownership was not reported"
echo "$OUTPUT" | grep -Fq 'inode=111' || fail "ZeroTier inode was not attributed"
echo "$OUTPUT" | grep -Fq 'owner=clash' || fail "Clash ownership was not reported"
echo "$OUTPUT" | grep -Fq 'inode=222' || fail "Clash inode was not attributed"
echo "$OUTPUT" | grep -Fq 'softnet=10' || fail "hexadecimal softnet counter was misparsed"
echo "$OUTPUT" | grep -Fq 'result=PASS reason=none' || fail "stable fixture result is not PASS"

echo "test-ax6-udp-baseline-fixture: PASS"
