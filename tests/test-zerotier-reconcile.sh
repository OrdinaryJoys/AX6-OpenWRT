#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/zerotier-reconcile-test.XXXXXX")"
cleanup_test() {
	status=$?
	trap - EXIT HUP INT TERM
	rm -rf "$TMP"
	exit "$status"
}
trap cleanup_test EXIT HUP INT TERM
mkdir -p "$TMP/bin" "$TMP/fw" "$TMP/nft-state"

cat > "$TMP/bin/lock" <<'EOF'
#!/bin/sh
[ "${LOCK_BUSY:-0}" = 1 ] && [ "${1:-}" != -u ] && exit 1
exit 0
EOF

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
	*'show zerotier'*)
		if [ "${UCI_SCHEMA:-current}" = legacy ]; then
			printf "%s\n" "zerotier.legacy=zerotier" \
				"zerotier.legacy.join='other123'" "zerotier.legacy.join='abc123'"
		else
			printf "%s\n" "zerotier.global=zerotier" "zerotier.net=network" \
				"zerotier.net.id='abc123'"
		fi
		;;
	*zerotier.global) [ "${UCI_SCHEMA:-current}" != legacy ] && printf '%s\n' zerotier ;;
	*zerotier.global.enabled*) printf '%s\n' "${ZT_ENABLED:-1}" ;;
	*zerotier.global.fw_allow_input*) printf '%s\n' "${FW_ALLOW_INPUT:-1}" ;;
	*zerotier.net.fw_allow_input*) printf '%s\n' "${NET_ALLOW_INPUT:-1}" ;;
	*zerotier.net.id*) exit 1 ;;
	*zerotier.net.join*) printf '%s\n' abc123 ;;
	*zerotier.net.enabled*) printf '%s\n' "${NET_ENABLED:-1}" ;;
	*zerotier.net.fw_allow_forward*) printf '%s\n' "${NET_ALLOW_FORWARD:-1}" ;;
	*zerotier.net.fw_allow_masq*) printf '%s\n' "${NET_ALLOW_MASQ:-1}" ;;
	*zerotier.net.fw_forward_ifaces*) printf '%s\n' "${FORWARD_IFACES:-lan1 br-lan}" ;;
	*zerotier.net.fw_masq_ifaces*) printf '%s\n' "${MASQ_IFACES:-br-lan}" ;;
	*zerotier.legacy.id*) exit 1 ;;
	*zerotier.legacy.join*) printf '%s\n' 'other123 abc123' ;;
	*zerotier.legacy.enabled*) printf '%s\n' "${ZT_ENABLED:-1}" ;;
	*zerotier.legacy.fw_allow_input*) printf '%s\n' "${NET_ALLOW_INPUT:-1}" ;;
	*zerotier.legacy.fw_allow_forward*) printf '%s\n' "${NET_ALLOW_FORWARD:-1}" ;;
	*zerotier.legacy.fw_allow_masq*) printf '%s\n' "${NET_ALLOW_MASQ:-1}" ;;
	*zerotier.legacy.fw_forward_ifaces*) printf '%s\n' "${FORWARD_IFACES:-lan1 br-lan}" ;;
	*zerotier.legacy.fw_masq_ifaces*) printf '%s\n' "${MASQ_IFACES:-br-lan}" ;;
	*) exit 1 ;;
esac
EOF

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
[ "${ZT_CLI_FAIL:-0}" = 1 ] && exit 1
case "$*" in
	'-j listnetworks')
		printf '%s\n' '[{"portDeviceName":"ztmock0","nwid":"abc123"}]'
		;;
	'-j info')
		secondary="${ZT_SECONDARY:-59120}"
		if [ "${ZT_UNSTABLE:-0}" = 1 ]; then
			count=$(cat "$ZT_CLI_COUNT_FILE" 2>/dev/null || echo 0)
			count=$((count + 1))
			printf '%s\n' "$count" > "$ZT_CLI_COUNT_FILE"
			[ $((count % 2)) -eq 1 ] || secondary="${ZT_SECONDARY_ALT:-59122}"
		fi
		printf '{"config":{"settings":{"primaryPort":%s,"secondaryPort":%s,"tertiaryPort":%s,"portMappingEnabled":%s}}}\n' \
			"${ZT_PRIMARY:-9993}" "$secondary" "${ZT_TERTIARY:-63542}" \
			"${ZT_MAPPING:-true}"
		;;
	*) exit 1 ;;
esac
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
input=$(cat)
case "$*" in
	*'@[*].portDeviceName'*) printf '%s\n' ztmock0 ;;
	*'portDeviceName="ztmock0"'*) printf '%s\n' abc123 ;;
	*config.settings*) printf '%s\n' "$input" | sed -e 's/^{"config":{"settings"://' -e 's/}}$//' ;;
	*primaryPort*) printf '%s\n' "$input" | sed -n 's/.*"primaryPort":\([0-9][0-9]*\).*/\1/p' ;;
	*secondaryPort*) printf '%s\n' "$input" | sed -n 's/.*"secondaryPort":\([0-9][0-9]*\).*/\1/p' ;;
	*tertiaryPort*) printf '%s\n' "$input" | sed -n 's/.*"tertiaryPort":\([0-9][0-9]*\).*/\1/p' ;;
	*portMappingEnabled*)
		case "$input" in
			*'"portMappingEnabled":true'*) printf '%s\n' true ;;
			*) printf '%s\n' false ;;
		esac
		;;
	*) exit 1 ;;
esac
EOF

cat > "$TMP/bin/nft" <<'EOF'
#!/bin/sh
case "$*" in
	'-a list chain inet fw4 input') cat "$NFT_STATE/input" ;;
	'-a list chain inet fw4 forward') cat "$NFT_STATE/forward" ;;
	'-a list chain inet fw4 srcnat') cat "$NFT_STATE/srcnat" ;;
	'-c -f '*)
		cat "$3" >> "$NFT_CHECK_LOG"
		[ "${NFT_FAIL:-0}" != 1 ]
		;;
	'-f '*) cat "$2" >> "$NFT_APPLY_LOG" ;;
	*) exit 1 ;;
esac
EOF

cat > "$TMP/bin/bypass" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$BYPASS_LOG"
exit "${BYPASS_STATUS:-0}"
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$TMP/bin/"*

export NFT_STATE="$TMP/nft-state"
export NFT_CHECK_LOG="$TMP/nft-check.log"
export NFT_APPLY_LOG="$TMP/nft-apply.log"
export BYPASS_LOG="$TMP/bypass.log"
export ZT_CLI_COUNT_FILE="$TMP/zt-cli-count"

cat > "$TMP/fw/input.nft" <<'EOF'
tcp dport 1234 counter accept comment "user rule"
udp dport 9993 counter accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)"
udp dport 56064 counter accept comment "!fw4: Accept ZeroTier input 56064 (secondaryPort)"
iifname "ztold0" counter accept comment "!fw4: Accept ZeroTier input ztold0"
EOF
cat > "$TMP/fw/forward.nft" <<'EOF'
iifname "ztold0" counter accept comment "!fw4: Accept ZeroTier input forward ztold0"
oifname "ztold0" counter accept comment "!fw4: Accept ZeroTier output forward ztold0"
EOF
cat > "$TMP/fw/srcnat.nft" <<'EOF'
oifname "ztold0" counter masquerade comment "!fw4: Masquerade ZeroTier traffic ztold0"
EOF

cat > "$TMP/nft-state/input" <<'EOF'
udp dport 9993 counter packets 1 bytes 10 accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)" # handle 10
udp dport 56064 counter packets 0 bytes 0 accept comment "!fw4: Accept ZeroTier input 56064 (secondaryPort)" # handle 11
iifname "ztold0" counter packets 0 bytes 0 accept comment "!fw4: Accept ZeroTier input ztold0" # handle 12
EOF
cat > "$TMP/nft-state/forward" <<'EOF'
iifname "ztold0" counter packets 0 bytes 0 accept comment "!fw4: Accept ZeroTier input forward ztold0" # handle 20
oifname "ztold0" counter packets 0 bytes 0 accept comment "!fw4: Accept ZeroTier output forward ztold0" # handle 21
EOF
cat > "$TMP/nft-state/srcnat" <<'EOF'
oifname "ztold0" counter packets 0 bytes 0 masquerade comment "!fw4: Masquerade ZeroTier traffic ztold0" # handle 30
EOF

run_reconcile() {
	PATH="$TMP/bin:$PATH" FW_PATH="$TMP/fw" INPUT_FILE="$TMP/fw/input.nft" \
		FORWARD_FILE="$TMP/fw/forward.nft" SRCNAT_FILE="$TMP/fw/srcnat.nft" \
		STATE_FILE="$TMP/state" LOCK_FILE="$TMP/lock" STABLE_DELAY=0 \
		BYPASS_HELPER="$TMP/bin/bypass" \
		sh "$ROOT/AX6-IPQ/files/usr/sbin/ax6-zerotier-reconcile" --once
}

run_dry_run() {
	PATH="$TMP/bin:$PATH" FW_PATH="$TMP/fw" INPUT_FILE="$TMP/fw/input.nft" \
		FORWARD_FILE="$TMP/fw/forward.nft" SRCNAT_FILE="$TMP/fw/srcnat.nft" \
		STATE_FILE="$TMP/state" LOCK_FILE="$TMP/lock" STABLE_DELAY=0 \
		BYPASS_HELPER="$TMP/bin/bypass" \
		sh "$ROOT/AX6-IPQ/files/usr/sbin/ax6-zerotier-reconcile" --dry-run
}

before_input=$(cksum "$TMP/fw/input.nft")
before_forward=$(cksum "$TMP/fw/forward.nft")
before_srcnat=$(cksum "$TMP/fw/srcnat.nft")
: > "$NFT_APPLY_LOG"
: > "$BYPASS_LOG"
run_dry_run
[ "$before_input" = "$(cksum "$TMP/fw/input.nft")" ]
[ "$before_forward" = "$(cksum "$TMP/fw/forward.nft")" ]
[ "$before_srcnat" = "$(cksum "$TMP/fw/srcnat.nft")" ]
[ ! -s "$NFT_APPLY_LOG" ]
grep -Fqx -- '--dry-run --sync 9993 59120 63542' "$BYPASS_LOG"

run_reconcile
grep -Fq 'tcp dport 1234' "$TMP/fw/input.nft"
grep -Fq 'dport 59120' "$TMP/fw/input.nft"
if grep -F 'primaryPort' "$TMP/fw/input.nft" | grep -q tcp; then
	echo 'ZeroTier primary WAN input rule must remain UDP-only' >&2
	exit 1
fi
grep -Fq 'Accept ZeroTier input ztmock0' "$TMP/fw/input.nft"
grep -Fq 'Accept ZeroTier input forward ztmock0' "$TMP/fw/forward.nft"
grep -Fq 'Accept ZeroTier output forward ztmock0' "$TMP/fw/forward.nft"
grep -Fq 'Masquerade ZeroTier traffic ztmock0' "$TMP/fw/srcnat.nft"
if grep -Fq ztold0 "$TMP/fw/input.nft" "$TMP/fw/forward.nft" "$TMP/fw/srcnat.nft"; then
	echo 'stale ZeroTier interface rules were retained' >&2
	exit 1
fi
grep -Fq 'delete rule inet fw4 input handle 11' "$NFT_APPLY_LOG"
grep -Fq 'delete rule inet fw4 forward handle 20' "$NFT_APPLY_LOG"
grep -Fq 'delete rule inet fw4 srcnat handle 30' "$NFT_APPLY_LOG"
grep -Fq 'insert rule inet fw4 srcnat ' "$NFT_APPLY_LOG"
if grep -Fq ' position 0 ' "$NFT_APPLY_LOG"; then
	echo 'nft transaction used position 0 instead of a valid handle' >&2
	exit 1
fi
grep -Fqx -- '--sync 9993 59120 63542' "$BYPASS_LOG"

# Exact include/live state must be a no-op even when nft reports packet counters.
sed 's/counter /counter packets 0 bytes 0 /; s/$/ # handle 40/' "$TMP/fw/input.nft" > "$TMP/nft-state/input"
sed 's/counter /counter packets 0 bytes 0 /; s/$/ # handle 50/' "$TMP/fw/forward.nft" > "$TMP/nft-state/forward"
sed 's/counter /counter packets 0 bytes 0 /; s/$/ # handle 60/' "$TMP/fw/srcnat.nft" > "$TMP/nft-state/srcnat"
: > "$NFT_APPLY_LOG"
run_reconcile
[ ! -s "$NFT_APPLY_LOG" ]

# Historical package configs use a zerotier section with a multi-value join list.
# The matching network may not be the first list item.
: > "$NFT_APPLY_LOG"
export UCI_SCHEMA=legacy
run_reconcile
[ ! -s "$NFT_APPLY_LOG" ]
grep -Fq 'Accept ZeroTier input ztmock0' "$TMP/fw/input.nft"
grep -Fq 'Accept ZeroTier input forward ztmock0' "$TMP/fw/forward.nft"
grep -Fq 'Masquerade ZeroTier traffic ztmock0' "$TMP/fw/srcnat.nft"
export UCI_SCHEMA=current

# Turning per-network permissions off must leave readable, empty includes.
: > "$NFT_APPLY_LOG"
NET_ALLOW_INPUT=0 NET_ALLOW_FORWARD=0 NET_ALLOW_MASQ=0 run_reconcile
grep -Fq 'primaryPort' "$TMP/fw/input.nft"
if grep -Fq 'input ztmock0' "$TMP/fw/input.nft"; then exit 1; fi
[ -f "$TMP/fw/forward.nft" ] && [ ! -s "$TMP/fw/forward.nft" ]
[ -f "$TMP/fw/srcnat.nft" ] && [ ! -s "$TMP/fw/srcnat.nft" ]
grep -Fq 'delete rule inet fw4 forward handle 50' "$NFT_APPLY_LOG"
grep -Fq 'delete rule inet fw4 srcnat handle 60' "$NFT_APPLY_LOG"

# A joined daemon network whose matching UCI section is disabled owns no rules.
sed 's/counter /counter packets 0 bytes 0 /; s/$/ # handle 70/' "$TMP/fw/input.nft" > "$TMP/nft-state/input"
: > "$TMP/nft-state/forward"
: > "$TMP/nft-state/srcnat"
NET_ENABLED=0 NET_ALLOW_INPUT=1 NET_ALLOW_FORWARD=1 NET_ALLOW_MASQ=1 run_reconcile
if grep -Fq 'ztmock0' "$TMP/fw/input.nft" "$TMP/fw/forward.nft" "$TMP/fw/srcnat.nft"; then
	echo 'disabled ZeroTier network still generated firewall rules' >&2
	exit 1
fi

# A CLI failure retains all three last valid include files.
before_input=$(cksum "$TMP/fw/input.nft")
before_forward=$(cksum "$TMP/fw/forward.nft")
before_srcnat=$(cksum "$TMP/fw/srcnat.nft")
if ZT_CLI_FAIL=1 run_reconcile; then
	echo 'reconciler unexpectedly accepted an unavailable CLI' >&2
	exit 1
fi
[ "$before_input" = "$(cksum "$TMP/fw/input.nft")" ]
[ "$before_forward" = "$(cksum "$TMP/fw/forward.nft")" ]
[ "$before_srcnat" = "$(cksum "$TMP/fw/srcnat.nft")" ]

# Invalid UCI interface tokens must not reach nft or replace the last valid files.
if ZT_CLI_FAIL=0 NET_ENABLED=1 NET_ALLOW_FORWARD=1 \
	FORWARD_IFACES='br-lan;reject' run_reconcile; then
	echo 'reconciler unexpectedly accepted an invalid forward interface token' >&2
	exit 1
fi
[ "$before_input" = "$(cksum "$TMP/fw/input.nft")" ]
[ "$before_forward" = "$(cksum "$TMP/fw/forward.nft")" ]
[ "$before_srcnat" = "$(cksum "$TMP/fw/srcnat.nft")" ]

# Invalid daemon ports must be rejected before rendering any firewall state.
if ZT_SECONDARY=70000 run_reconcile; then
	echo 'reconciler unexpectedly accepted an invalid daemon port' >&2
	exit 1
fi
[ "$before_input" = "$(cksum "$TMP/fw/input.nft")" ]

# A failed nft transaction must not install newly rendered include files.
if ZT_CLI_FAIL=0 NFT_FAIL=1 ZT_SECONDARY=60000 run_reconcile; then
	echo 'reconciler unexpectedly accepted a failed nft transaction' >&2
	exit 1
fi
[ "$before_input" = "$(cksum "$TMP/fw/input.nft")" ]

# Two different daemon port samples must be rejected.
: > "$ZT_CLI_COUNT_FILE"
if NFT_FAIL=0 ZT_UNSTABLE=1 ZT_SECONDARY=60001 ZT_SECONDARY_ALT=60002 run_reconcile; then
	echo 'reconciler unexpectedly accepted unstable daemon ports' >&2
	exit 1
fi
[ "$before_input" = "$(cksum "$TMP/fw/input.nft")" ]

# A busy lock skips reconciliation without changing state.
ZT_UNSTABLE=0 ZT_CLI_FAIL=0 NFT_FAIL=0 LOCK_BUSY=1 run_reconcile
[ "$before_input" = "$(cksum "$TMP/fw/input.nft")" ]

# Disabling ZeroTier cleans every owned include and the OpenClash bypass.
: > "$BYPASS_LOG"
ZT_ENABLED=0 ZT_UNSTABLE=0 ZT_CLI_FAIL=1 NFT_FAIL=0 LOCK_BUSY=0 run_reconcile
grep -Fq 'tcp dport 1234' "$TMP/fw/input.nft"
if grep -Fq 'ZeroTier' "$TMP/fw/input.nft"; then exit 1; fi
[ ! -s "$TMP/fw/forward.nft" ]
[ ! -s "$TMP/fw/srcnat.nft" ]
grep -Fqx -- '--cleanup' "$BYPASS_LOG"

# nft canonicalizes a singleton interface set to a scalar predicate. Render the
# scalar form directly and prove that a second reconciliation is a true no-op.
export ZT_ENABLED=1 ZT_CLI_FAIL=0 FORWARD_IFACES=br-lan
run_reconcile
grep -Fq 'oifname "br-lan" iifname "ztmock0"' "$TMP/fw/forward.nft"
if grep -Fq 'oifname { "br-lan" }' "$TMP/fw/forward.nft"; then
	echo 'singleton forward interface was rendered as a non-canonical nft set' >&2
	exit 1
fi
sed 's/counter /counter packets 0 bytes 0 /; s/$/ # handle 80/' "$TMP/fw/input.nft" > "$TMP/nft-state/input"
sed 's/counter /counter packets 0 bytes 0 /; s/$/ # handle 81/' "$TMP/fw/forward.nft" > "$TMP/nft-state/forward"
sed 's/counter /counter packets 0 bytes 0 /; s/$/ # handle 82/' "$TMP/fw/srcnat.nft" > "$TMP/nft-state/srcnat"
: > "$NFT_APPLY_LOG"
run_reconcile
[ ! -s "$NFT_APPLY_LOG" ]

echo 'test-zerotier-reconcile: PASS'
