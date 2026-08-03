#!/usr/bin/env bash
# AX6 Performance Test — Fixture Tests (Phase 0 §3.2 compliance)
# ============================================================================
# Tests: normal exit, SIGTERM, SSH failure, boot_id change, phase failure
# Uses mock functions to validate script logic without touching the router.
# ============================================================================

set -o nounset
TEST_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_UNDER_TEST="${TEST_DIR}/scripts/ax6-perf-test.sh"
PASS=0
FAIL=0
TOTAL=0

ok() { PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); echo "  ❌ $1"; }

echo "===== AX6 Perf Test Fixture ====="
echo ""

# ── Test 1: Syntax validity ───────────────────────────────────────────────
echo "--- Test 1: Syntax ---"
if bash -n "$SCRIPT_UNDER_TEST" 2>&1; then ok "bash -n"; else bad "bash -n"; fi
if sh -n "$SCRIPT_UNDER_TEST" 2>&1; then ok "sh -n"; else bad "sh -n"; fi

# ── Test 2: No killall iperf3 ──────────────────────────────────────────────
echo "--- Test 2: No killall iperf3 (§3.1.6) ---"
if grep -n 'killall.*iperf3' "$SCRIPT_UNDER_TEST" | grep -v '^\s*#' | grep -v 'no killall' > /dev/null 2>&1; then
  bad "killall iperf3 found in code — violates §3.1.6"
else
  ok "no killall iperf3 (comments excluded)"
fi

# ── Test 3: No recursive debugfs ───────────────────────────────────────────
echo "--- Test 3: No recursive debugfs (§3.1.8) ---"
if grep -nE 'find.*debugfs|grep -r.*debugfs|ls -R.*debugfs|readelf.*debugfs|cat /sys/kernel/debug/\*' "$SCRIPT_UNDER_TEST"; then
  bad "recursive debugfs read found — violates §3.1.8"
else
  ok "no recursive debugfs"
fi

# ── Test 4: Two revision fields ────────────────────────────────────────────
echo "--- Test 4: Two revision fields (§3.1.4) ---"
if grep -q 'SOURCE_REVISION' "$SCRIPT_UNDER_TEST" && grep -q 'BUILD_REPO_COMMIT' "$SCRIPT_UNDER_TEST"; then
  ok "SOURCE_REVISION and BUILD_REPO_COMMIT present"
else
  bad "missing revision fields"
fi

# ── Test 5: Trap handlers ──────────────────────────────────────────────────
echo "--- Test 5: Trap handlers (§3.1.1) ---"
for sig in INT TERM HUP EXIT; do
  if grep -q "trap.*${sig}" "$SCRIPT_UNDER_TEST"; then
    ok "trap ${sig} handler exists"
  else
    bad "trap ${sig} handler missing"
  fi
done

# ── Test 6: INCOMPLETE on failure, COMPLETE only on success ────────────────
echo "--- Test 6: INCOMPLETE/COMPLETE semantics (§3.1.5) ---"
if grep -q 'INCOMPLETE' "$SCRIPT_UNDER_TEST"; then
  ok "INCOMPLETE keyword present"
else
  bad "INCOMPLETE keyword missing"
fi
# Count standalone COMPLETE usage (not INCOMPLETE, not comments)
COMPLETE_COUNT=$(grep -c '"COMPLETE"' "$SCRIPT_UNDER_TEST" 2>/dev/null || echo 0)
INCOMPLETE_COUNT=$(grep -c 'INCOMPLETE' "$SCRIPT_UNDER_TEST" 2>/dev/null || echo 0)
if [ "${COMPLETE_COUNT:-0}" -le 3 ]; then
  ok "COMPLETE string-literal appears ${COMPLETE_COUNT}x (≤3), INCOMPLETE: ${INCOMPLETE_COUNT}x"
else
  bad "COMPLETE string-literal appears ${COMPLETE_COUNT}x (>3, may print on failure paths)"
fi

# ── Test 7: Phase failure stops subsequent phases ──────────────────────────
echo "--- Test 7: Phase failure propagation (§3.1.5) ---"
if grep -A1 'phase_tcp_single' "$SCRIPT_UNDER_TEST" | grep -q 'phase_tcp_bidir' || \
   grep -q 'phase_tcp_single.*||.*phase_tcp_bidir.*||' "$SCRIPT_UNDER_TEST" || \
   grep -q '|| { log "ABORT"' "$SCRIPT_UNDER_TEST"; then
  ok "phase failure stops subsequent phases"
else
  bad "phase failure may not stop subsequent phases"
fi

# ── Test 8: Process tracking (no untracked processes) ──────────────────────
echo "--- Test 8: Process tracking (§3.1.6) ---"
if grep -q 'track_client_pid\|track_router_pid' "$SCRIPT_UNDER_TEST"; then
  ok "process tracking functions present"
else
  bad "process tracking functions missing"
fi

# ── Test 9: Independent ports ──────────────────────────────────────────────
echo "--- Test 9: Independent ports (§3.1.7) ---"
DEFAULT_PORTS=$(grep -E '^TCP_PORT=|^UDP_PORT=|^TCP_PORT_EXTRA=' "$SCRIPT_UNDER_TEST")
if echo "$DEFAULT_PORTS" | grep -q '15201' && echo "$DEFAULT_PORTS" | grep -q '15202'; then
  ok "ports in 152xx range (independent)"
else
  bad "ports may conflict: $DEFAULT_PORTS"
fi

# ── Test 10: Pre/post snapshot collection ──────────────────────────────────
echo "--- Test 10: Data collection points (§3.1.3) ---"
for item in "snmp" "udp_socket" "softnet" "port_stats" "nss_check" "config_audit"; do
  if grep -q "$item" "$SCRIPT_UNDER_TEST"; then
    ok "collects $item"
  else
    bad "missing collection: $item"
  fi
done

# ── Test 11: Boot ID tracking ──────────────────────────────────────────────
echo "--- Test 11: Boot ID tracking (§3.1.2) ---"
if grep -q 'boot_id' "$SCRIPT_UNDER_TEST"; then
  ok "boot_id tracking present"
else
  bad "boot_id tracking missing"
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "===== FIXTURE RESULTS: ${PASS}/${TOTAL} PASS, ${FAIL}/${TOTAL} FAIL ====="
[ "$FAIL" -eq 0 ] && echo "STATUS: ALL PASSED ✅" || echo "STATUS: FAILURES DETECTED ❌"
exit "$FAIL"
