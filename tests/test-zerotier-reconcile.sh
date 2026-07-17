#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/zerotier-reconcile-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin" "$TMP/fw" "$TMP/nft-state"

cat > "$TMP/bin/lock" <<'EOF'
#!/bin/sh
[ "${LOCK_BUSY:-0}" = 1 ] && [ "${1:-}" != -u ] && exit 1
exit 0
EOF

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
    *zerotier.global.enabled*) printf '%s\n' "${ZT_ENABLED:-1}" ;;
    *zerotier.global.fw_allow_input*) printf '%s\n' "${FW_ALLOW_INPUT:-1}" ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
[ "${ZT_CLI_FAIL:-0}" = 1 ] && exit 1
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
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
input=$(cat)
case "$*" in
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
    '-c -f '*)
        cat "$3" >> "$NFT_CHECK_LOG"
        if [ "${NFT_FAIL:-0}" = 1 ]; then exit 1; fi
        exit 0
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
meta l4proto { udp, tcp } th dport 9993 counter accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)"
meta l4proto { udp } th dport 56064 counter accept comment "!fw4: Accept ZeroTier input 56064 (secondaryPort)"
meta l4proto { udp } th dport 63542 counter accept comment "!fw4: Accept ZeroTier input 63542 (tertiaryPort)"
EOF
cat > "$TMP/nft-state/input" <<'EOF'
meta l4proto { tcp, udp } th dport 9993 counter accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)" # handle 10
udp dport 56064 counter accept comment "!fw4: Accept ZeroTier input 56064 (secondaryPort)" # handle 11
udp dport 63542 counter accept comment "!fw4: Accept ZeroTier input 63542 (tertiaryPort)" # handle 12
EOF

run_reconcile() {
    PATH="$TMP/bin:$PATH" FW_PATH="$TMP/fw" INPUT_FILE="$TMP/fw/input.nft" \
        STATE_FILE="$TMP/state" LOCK_FILE="$TMP/lock" STABLE_DELAY=0 \
        BYPASS_HELPER="$TMP/bin/bypass" \
        sh ${TRACE_RECONCILE:+-x} \
        "$ROOT/AX6-IPQ/files/usr/sbin/ax6-zerotier-reconcile" --once
}

run_dry_run() {
    PATH="$TMP/bin:$PATH" FW_PATH="$TMP/fw" INPUT_FILE="$TMP/fw/input.nft" \
        STATE_FILE="$TMP/state" LOCK_FILE="$TMP/lock" STABLE_DELAY=0 \
        BYPASS_HELPER="$TMP/bin/bypass" \
        sh "$ROOT/AX6-IPQ/files/usr/sbin/ax6-zerotier-reconcile" --dry-run
}

before=$(cksum "$TMP/fw/input.nft")
: > "$NFT_APPLY_LOG"
: > "$BYPASS_LOG"
run_dry_run
[ "$before" = "$(cksum "$TMP/fw/input.nft")" ]
[ ! -s "$NFT_APPLY_LOG" ]
grep -Fqx -- '--dry-run --sync 9993 59120 63542' "$BYPASS_LOG"

run_reconcile
grep -Fq 'tcp dport 1234' "$TMP/fw/input.nft"
grep -Fq 'secondaryPort)' "$TMP/fw/input.nft"
grep -Fq 'dport 59120' "$TMP/fw/input.nft"
if grep -Fq 56064 "$TMP/fw/input.nft"; then exit 1; fi
grep -Fq 'delete rule inet fw4 input handle 11' "$NFT_APPLY_LOG"
grep -Fq 'udp dport 59120' "$NFT_APPLY_LOG"
grep -Fqx -- '--sync 9993 59120 63542' "$BYPASS_LOG"

# Exact include/live state must be a no-op.
cat > "$TMP/nft-state/input" <<'EOF'
meta l4proto { tcp, udp } th dport 9993 counter accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)" # handle 20
udp dport 59120 counter accept comment "!fw4: Accept ZeroTier input 59120 (secondaryPort)" # handle 21
udp dport 63542 counter accept comment "!fw4: Accept ZeroTier input 63542 (tertiaryPort)" # handle 22
EOF
: > "$NFT_APPLY_LOG"
run_reconcile
[ ! -s "$NFT_APPLY_LOG" ]

# A CLI failure retains the last valid include and does not touch nft.
before=$(cksum "$TMP/fw/input.nft")
: > "$NFT_APPLY_LOG"
if ZT_CLI_FAIL=1 run_reconcile; then
    echo 'reconciler unexpectedly accepted an unavailable CLI' >&2
    exit 1
fi
[ "$before" = "$(cksum "$TMP/fw/input.nft")" ]
[ ! -s "$NFT_APPLY_LOG" ]

# Disabling input permission removes only owned service-port rules.
ZT_CLI_FAIL=0 FW_ALLOW_INPUT=0 run_reconcile
grep -Fq 'tcp dport 1234' "$TMP/fw/input.nft"
if grep -Fq 'primaryPort' "$TMP/fw/input.nft"; then exit 1; fi
grep -Fq 'delete rule inet fw4 input handle 20' "$NFT_APPLY_LOG"

# A busy lock skips reconciliation without modifying state.
before=$(cksum "$TMP/fw/input.nft")
LOCK_BUSY=1 run_reconcile
[ "$before" = "$(cksum "$TMP/fw/input.nft")" ]

# A failed nft transaction must leave the include unchanged.
cat > "$TMP/fw/input.nft" <<'EOF'
tcp dport 1234 counter accept comment "user rule"
meta l4proto { udp, tcp } th dport 9993 counter accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)"
meta l4proto { udp } th dport 59120 counter accept comment "!fw4: Accept ZeroTier input 59120 (secondaryPort)"
meta l4proto { udp } th dport 63542 counter accept comment "!fw4: Accept ZeroTier input 63542 (tertiaryPort)"
EOF
before=$(cksum "$TMP/fw/input.nft")
if ZT_CLI_FAIL=0 FW_ALLOW_INPUT=1 LOCK_BUSY=0 NFT_FAIL=1 ZT_SECONDARY=60000 run_reconcile; then
    echo 'reconciler unexpectedly accepted a failed nft transaction' >&2
    exit 1
fi
[ "$before" = "$(cksum "$TMP/fw/input.nft")" ]

# Two different samples must be rejected without changing rules.
: > "$ZT_CLI_COUNT_FILE"
before=$(cksum "$TMP/fw/input.nft")
if NFT_FAIL=0 ZT_UNSTABLE=1 ZT_SECONDARY=60001 ZT_SECONDARY_ALT=60002 run_reconcile; then
    echo 'reconciler unexpectedly accepted unstable daemon ports' >&2
    exit 1
fi
[ "$before" = "$(cksum "$TMP/fw/input.nft")" ]

# Disabling ZeroTier cleans only owned input/bypass rules without reading the CLI.
: > "$BYPASS_LOG"
ZT_ENABLED=0 ZT_UNSTABLE=0 ZT_CLI_FAIL=1 NFT_FAIL=0 LOCK_BUSY=0 run_reconcile
grep -Fq 'tcp dport 1234' "$TMP/fw/input.nft"
if grep -Fq 'primaryPort' "$TMP/fw/input.nft"; then exit 1; fi
grep -Fqx -- '--cleanup' "$BYPASS_LOG"

echo 'test-zerotier-reconcile: PASS'
