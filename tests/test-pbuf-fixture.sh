#!/bin/sh
# PBUF validation fixture — verify nss-check PBUF logic (P1, 2026-07-28).
# Tests structural correctness of PBUF handling in nss-check.
# Full behavioral tests require a running router; this fixture
# validates the source logic and documents expected behavior.

set -eu

PASS=0
FAIL=0

NSS_CHECK="${NSS_CHECK:-./AX6-IPQ/files/sbin/nss-check}"

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== PBUF Fixture Tests ==="

# -- Structural checks (run without router) --

# 1. Firmware split budget fallback
if grep -q 'pbuf_high + pbuf_wifi' "$NSS_CHECK"; then
    pass "firmware split arithmetic present"
else
    fail "firmware split arithmetic missing"
fi

# 2. Non-numeric guard
if grep -q '\*\[!0-9\]\*' "$NSS_CHECK"; then
    pass "non-numeric sysctl guard present"
else
    fail "non-numeric sysctl guard missing"
fi

# 3. PBUF profile labels
for label in 1GB 512MB 256MB; do
    if grep -q "pbuf_label=$label" "$NSS_CHECK"; then
        pass "profile label: $label"
    else
        fail "profile label missing: $label"
    fi
done

# 4. Expected values for 1GB profile
if grep -q 'pbuf_expected_extra=10000000' "$NSS_CHECK" && \
   grep -q 'pbuf_expected_high=65536' "$NSS_CHECK" && \
   grep -q 'pbuf_expected_wifi=32768' "$NSS_CHECK"; then
    pass "1GB profile expected values correct"
else
    fail "1GB profile expected values incorrect"
fi

# 5. Three-tier result: ok / warn / fail
if grep -q 'ok.*NSS pbuf.*profile applied' "$NSS_CHECK" && \
   grep -q 'warn.*firmware split budget' "$NSS_CHECK" && \
   grep -q 'fail.*NSS pbuf.*profile not applied' "$NSS_CHECK"; then
    pass "three-tier result (ok/warn/fail) present"
else
    fail "three-tier result missing"
fi

echo ""
echo "=== Behavioral spec (requires router) ==="
echo "These scenarios are documented for manual verification:"
echo ""
echo "  [1] Valid 1GB: extra>=10M, high>=65536, wifi>=32768 -> ok, exit 0"
echo "  [2] Firmware split: extra>=10M, wifi>=32768, high+wifi>=65536 -> warn, exit 0"
echo "  [3] Insufficient: extra<10M or (high<65536 and high+wifi<65536) -> fail, exit N"
echo "  [4] Non-numeric: any sysctl non-numeric -> fail, exit N"
echo "  [5] Missing: any sysctl empty -> fail, exit N"
echo ""

echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
