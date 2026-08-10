#!/bin/sh
set -eu

SCRIPT="${1:-AX6-IPQ/scripts/ax6-routed-perf-test.sh}"
[ -f "$SCRIPT" ]
bash -n "$SCRIPT"
grep -Fq -- '--confirm-load-test' "$SCRIPT"
grep -Fq 'AX6_IPERF_TARGET' "$SCRIPT"
grep -Fq 'AX6_BUILD_COMMIT' "$SCRIPT"
grep -Fq 'ip route get' "$SCRIPT"
grep -Fq 'lan_to_wan' "$SCRIPT"
grep -Fq 'wan_to_lan' "$SCRIPT"
grep -Fq 'bidirectional' "$SCRIPT"
grep -Fq 'args+=(-R)' "$SCRIPT"
grep -Fq 'args+=(--bidir)' "$SCRIPT"
grep -Fq 'nss-check -q' "$SCRIPT"
grep -Fq 'ax6-config-audit -q' "$SCRIPT"
grep -Fq 'connection_count_simple' "$SCRIPT"
grep -Fq 'qca-nss-drv/stats/edma/err_stats' "$SCRIPT"
grep -Fq 'boot_start' "$SCRIPT"
if grep -Eq 'router_cmd .*iperf3|killall[[:space:]]+iperf3' "$SCRIPT"; then
    echo "routed performance test must not terminate flow on the router or use killall" >&2
    exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin" "$TMP/results"
: > "$TMP/key"

cat > "$TMP/bin/ssh" <<'EOF'
#!/bin/sh
for arg in "$@"; do command=$arg; done
case "$command" in
    *'/etc/openwrt_release'*) echo 'r0-test' ;;
    *'ip route get'*) echo '203.0.113.2 via 198.51.100.1 dev wan src 198.51.100.2' ;;
    *'/proc/sys/kernel/random/boot_id'*) echo 'fixture-boot-id' ;;
    *) echo 'fixture_snapshot=ok' ;;
esac
EOF
cat > "$TMP/bin/iperf3" <<'EOF'
#!/bin/sh
case " ${*} " in
    *' --help '*) echo '  --bidir test in both directions'; exit 0 ;;
    *' --version '*) echo 'iperf 3.fixture'; exit 0 ;;
esac
cat <<'JSON'
{"start":{"version":"iperf 3.fixture"},"end":{"sum_sent":{"bits_per_second":900000000,"retransmits":0},"sum_received":{"bits_per_second":895000000},"sum_sent_bidir_reverse":{"bits_per_second":880000000,"retransmits":1},"sum_received_bidir_reverse":{"bits_per_second":875000000}}}
JSON
EOF
cat > "$TMP/bin/ping" <<'EOF'
#!/bin/sh
trap 'exit 0' INT TERM HUP
while :; do sleep 1; done
EOF
cat > "$TMP/bin/nc" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$TMP/bin/ssh" "$TMP/bin/iperf3" "$TMP/bin/ping" "$TMP/bin/nc"

PATH="$TMP/bin:$PATH" \
AX6_IPERF_TARGET=203.0.113.2 \
AX6_BUILD_COMMIT=193e5fbc276e \
AX6_EXPECTED_SOURCE_REVISION=r0-test \
AX6_EXPECT_WAN_DEVICE=wan \
AX6_SSH_KEY="$TMP/key" \
AX6_RUNS=1 AX6_DURATION=10 AX6_RESULT_DIR="$TMP/results" \
bash "$SCRIPT" preflight > "$TMP/preflight"
grep -Fq 'iperf_server=reachable' "$TMP/preflight"

PATH="$TMP/bin:$PATH" \
AX6_IPERF_TARGET=203.0.113.2 \
AX6_BUILD_COMMIT=193e5fbc276e \
AX6_EXPECTED_SOURCE_REVISION=r0-test \
AX6_EXPECT_WAN_DEVICE=wan \
AX6_SSH_KEY="$TMP/key" \
AX6_RUNS=1 AX6_DURATION=10 AX6_RESULT_DIR="$TMP/results" \
bash "$SCRIPT" run --confirm-load-test > "$TMP/run"

SUMMARY=$(find "$TMP/results" -name summary.tsv -type f | head -n 1)
RESULT=$(find "$TMP/results" -name result.txt -type f | head -n 1)
[ "$(wc -l < "$SUMMARY" | tr -d ' ')" -eq 4 ]
awk -F '\t' '$1 == "bidirectional" && $6 == "880.000" && $7 == "875.000" && $8 == "1" && $9 == "iperf 3.fixture" { found=1 } END { exit !found }' "$SUMMARY"
grep -Fq 'result=COMPLETE boot_id=fixture-boot-id' "$RESULT"
echo "test-ax6-routed-perf-fixture: PASS"
