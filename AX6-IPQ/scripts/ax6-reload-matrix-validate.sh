#!/bin/sh
# Validate reload-matrix evidence. This script never performs a reload.

set -eu

EXPECTED=20
case "${1:-}" in
    --expected)
        EXPECTED="${2:-}"
        shift 2
        ;;
esac
LOG="${1:-}"

case "$EXPECTED" in
    ''|*[!0-9]*) echo "invalid expected count: $EXPECTED" >&2; exit 2 ;;
esac
[ "$EXPECTED" -gt 0 ] || { echo "expected count must be positive" >&2; exit 2; }
[ -r "$LOG" ] || { echo "usage: $0 [--expected N] LOG" >&2; exit 2; }

awk -v expected="$EXPECTED" '
function value(key,    i, prefix) {
    prefix = key "="
    for (i = 3; i <= NF; i++) {
        if (index($i, prefix) == 1)
            return substr($i, length(prefix) + 1)
    }
    return ""
}
function require(type, key,    v) {
    v = value(key)
    if (v == "") {
        printf "FAIL line=%d scenario=%s missing=%s\n", NR, type, key > "/dev/stderr"
        failed = 1
    }
    return v
}
function common(type) {
    if (require(type, "result") != "PASS") {
        printf "FAIL line=%d scenario=%s result_must_be_PASS\n", NR, type > "/dev/stderr"
        failed = 1
    }
    if (require(type, "boot_same") != "1" ||
        require(type, "audit_rc") != "0" || require(type, "nss_rc") != "0") {
        printf "FAIL line=%d scenario=%s health_gate_failed\n", NR, type > "/dev/stderr"
        failed = 1
    }
}
$2 ~ /^NETWORK#[0-9]+$/ {
    count["NETWORK"]++
    require("NETWORK", "br"); require("NETWORK", "wanip")
    require("NETWORK", "dns"); require("NETWORK", "eca")
    require("NETWORK", "red"); require("NETWORK", "tproxy")
    require("NETWORK", "err"); common("NETWORK")
}
$2 ~ /^ECM#[0-9]+$/ {
    count["ECM"]++
    require("ECM", "do"); require("ECM", "dgl")
    require("ECM", "red"); require("ECM", "eca"); common("ECM")
}
$2 ~ /^WAN#[0-9]+$/ {
    count["WAN"]++
    require("WAN", "wanip"); require("WAN", "rt")
    require("WAN", "zt"); require("WAN", "clash"); common("WAN")
}
$2 ~ /^WIFI#[0-9]+$/ {
    count["WIFI"]++
    require("WIFI", "p0"); require("WIFI", "p1")
    require("WIFI", "fm"); require("WIFI", "no")
    require("WIFI", "queue"); require("WIFI", "sta5g"); common("WIFI")
}
$2 == "===" && $3 == "MATRIX_DONE" { done = 1 }
END {
    split("NETWORK ECM WAN WIFI", scenarios, " ")
    for (i = 1; i <= 4; i++) {
        type = scenarios[i]
        if (count[type] != expected) {
            printf "FAIL scenario=%s count=%d expected=%d\n", type, count[type], expected > "/dev/stderr"
            failed = 1
        }
    }
    if (!done) {
        print "FAIL missing MATRIX_DONE marker" > "/dev/stderr"
        failed = 1
    }
    if (failed)
        exit 1
    printf "PASS reload matrix: %d scenarios x %d iterations\n", 4, expected
}
' "$LOG"
