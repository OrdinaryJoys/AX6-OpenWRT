#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
VALIDATOR="$ROOT/scripts/ax6-reload-matrix-validate.sh"

fail() {
    echo "test-ax6-reload-matrix-validate: FAIL: $*" >&2
    exit 1
}

sh -n "$VALIDATOR" || fail "invalid validator syntax"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM HUP

cat > "$TMP/good.log" <<'EOF'
[00:00:01] NETWORK#1 br=1 wanip=1 dns=1 eca=10 red=1 tproxy=2 err=0 result=PASS boot_same=1 audit_rc=0 nss_rc=0
[00:00:02] ECM#1 do=1 dgl=1 red=1 eca=12 result=PASS boot_same=1 audit_rc=0 nss_rc=0
[00:00:03] WAN#1 wanip=1 rt=1 zt=1 clash=1 result=PASS boot_same=1 audit_rc=0 nss_rc=0
[00:00:04] WIFI#1 p0=1 p1=1 fm=2 no=1 queue=2048 sta5g=4 result=PASS boot_same=1 audit_rc=0 nss_rc=0
[00:00:05] === MATRIX_DONE ===
EOF
sh "$VALIDATOR" --expected 1 "$TMP/good.log" >/dev/null ||
    fail "complete fixture did not pass"

cat > "$TMP/bad.log" <<'EOF'
[00:00:01] NETWORK#1 br=1 wanip=0 dns=1 eca=0 red=1 tproxy=0 err=0
[00:00:02] ECM#1 do= dgl= red=1 eca=0
[00:00:03] WAN#1 wanip=1 rt=1 zt=0 clash=1
[00:00:04] WIFI#1 p0=1 p1=1 fm=2 no=1 queue= sta5g=4
[00:00:05] === MATRIX_DONE ===
EOF
if sh "$VALIDATOR" --expected 1 "$TMP/bad.log" >/dev/null 2>&1; then
    fail "incomplete legacy evidence was accepted"
fi

echo "test-ax6-reload-matrix-validate: PASS"
