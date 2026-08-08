#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
MONITOR="$ROOT/AX6-IPQ/files/etc/uci-defaults/96-ax6-nss-monitor"

fail() {
    echo "test-nss-monitor: FAIL: $*" >&2
    exit 1
}

[ -f "$MONITOR" ] || fail "monitor defaults script is missing"
sh -n "$MONITOR" || fail "monitor defaults script has invalid shell syntax"

grep -Fq '/sbin/nss-check -q; rc=$?' "$MONITOR" ||
    fail "normal cron probe must remain quiet"
grep -Fq 'nss-check failed (exit=$rc), collecting verbose snapshot' "$MONITOR" ||
    fail "failure marker must preserve the original exit code"
grep -Fq '/sbin/nss-check 2>&1 | logger -t nss-monitor' "$MONITOR" ||
    fail "failure path must capture a verbose nss-check snapshot"
grep -Fq "sed '\\|/sbin/nss-check -q.*logger -t nss-monitor|d'" "$MONITOR" ||
    fail "upgrade path must replace the previously managed cron line"
grep -Fq 'mv "$TMP_CRONTAB" "$CRONTAB_ROOT"' "$MONITOR" ||
    fail "managed crontab update must use an atomic replacement"

if grep -Fq "grep -qF '/sbin/nss-check'" "$MONITOR"; then
    fail "a generic nss-check match would block upgrades and user-defined probes"
fi

[ "$(grep -Fc "LINE='*/30 " "$MONITOR")" -eq 1 ] ||
    fail "exactly one 30-minute cron line is expected"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM HUP

cat > "$TMP/root" <<'EOF'
*/30 * * * * /sbin/nss-check -q; rc=$?; [ "$rc" -eq 0 ] || logger -t nss-monitor "nss-check failed (exit=$rc)"
7 * * * * /sbin/nss-check -v >/tmp/user-nss-check.log
EOF
cat > "$TMP/cron" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$TMP/cron"

CRONTAB_ROOT="$TMP/root" CRON_INIT="$TMP/cron" sh "$MONITOR"
CRONTAB_ROOT="$TMP/root" CRON_INIT="$TMP/cron" sh "$MONITOR"

[ "$(grep -Fc 'logger -t nss-monitor' "$TMP/root")" -eq 1 ] ||
    fail "managed monitor line must be idempotent"
grep -Fq 'collecting verbose snapshot' "$TMP/root" ||
    fail "fixture did not install the verbose failure snapshot"
grep -Fq '7 * * * * /sbin/nss-check -v >/tmp/user-nss-check.log' "$TMP/root" ||
    fail "fixture removed an unrelated user-defined nss-check probe"
if grep -Fq '|| logger -t nss-monitor "nss-check failed' "$TMP/root"; then
    fail "legacy managed monitor line was not replaced"
fi

echo "test-nss-monitor: PASS"
