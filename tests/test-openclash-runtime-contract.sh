#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
GATE="$ROOT/AX6-IPQ/scripts/check-openclash-runtime-contract.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/openclash-contract-test.XXXXXX")"
cleanup_test() {
	status=$?
	trap - EXIT HUP INT TERM
	rm -rf "$TMP"
	exit "$status"
}
trap cleanup_test EXIT HUP INT TERM

cat > "$TMP/openclash-good" <<'EOF'
change_dnsmasq() {
    uci -q add_list dhcp.@dnsmasq[0].server=127.0.0.1#"$dns_port"
    uci -q set dhcp.@dnsmasq[0].noresolv=1
    uci -q del_list dhcp.@dnsmasq[0].server="127.0.0.1#$dns_port"
}
revert_dnsmasq() {
    uci -q set dhcp.@dnsmasq[0].noresolv=0
}
fw4_has_dns_hijack_rule() {
    :
}
/usr/bin/ax6-openclash-zerotier-bypass --apply
EOF

"$GATE" "$TMP/openclash-good" > "$TMP/good.log"
grep -Fq 'runtime contract gate: PASS' "$TMP/good.log"

sed '/del_list dhcp.*dns_port/d' "$TMP/openclash-good" > "$TMP/no-cleanup"
if "$GATE" "$TMP/no-cleanup" > "$TMP/no-cleanup.log" 2>&1; then
    echo 'runtime contract gate accepted missing dnsmasq cleanup' >&2
    exit 1
fi
grep -Fq 'disabled-mode residual redirect cleanup' "$TMP/no-cleanup.log"

sed '/ax6-openclash-zerotier-bypass/d' "$TMP/openclash-good" > "$TMP/no-hook"
if "$GATE" "$TMP/no-hook" > "$TMP/no-hook.log" 2>&1; then
    echo 'runtime contract gate accepted missing ZeroTier bypass hook' >&2
    exit 1
fi
grep -Fq 'AX6 ZeroTier self-proxy bypass hook' "$TMP/no-hook.log"

echo 'test-openclash-runtime-contract: PASS'
