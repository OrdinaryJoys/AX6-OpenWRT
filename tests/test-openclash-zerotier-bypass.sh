#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/openclash-zerotier-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin" "$TMP/nft-state"

cat > "$TMP/bin/lock" <<'EOF'
#!/bin/sh
exit 0
EOF

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
    *zerotier.global.enabled*) echo "${ZT_ENABLED:-1}" ;;
    *openclash.config.enable*) echo "${OPENCLASH_ENABLED:-1}" ;;
    *openclash.config.router_self_proxy*) echo "${ROUTER_SELF_PROXY:-1}" ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
[ "${ZT_CLI_FAIL:-0}" = 1 ] && exit 1
printf '%s\n' '{"config":{"settings":{"primaryPort":9993,"secondaryPort":19993,"tertiaryPort":29993,"portMappingEnabled":true}}}'
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
case "$*" in
    *config.settings*) cat ;;
    *portMappingEnabled*) cat >/dev/null; echo true ;;
    *primaryPort*) cat >/dev/null; echo 9993 ;;
    *secondaryPort*) cat >/dev/null; echo 19993 ;;
    *tertiaryPort*) cat >/dev/null; echo 29993 ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/nft" <<'EOF'
#!/bin/sh
case "$*" in
    '-a list chain inet fw4 '*)
        chain=${6}
        [ -f "$NFT_STATE/$chain" ] || exit 1
        cat "$NFT_STATE/$chain"
        ;;
    '-c -f '*) cat "$3" >> "$NFT_CHECK_LOG" ;;
    '-f '*) cat "$2" >> "$NFT_APPLY_LOG" ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$TMP/bin/"*

export NFT_STATE="$TMP/nft-state"
export NFT_CHECK_LOG="$TMP/nft-check.log"
export NFT_APPLY_LOG="$TMP/nft-apply.log"
for chain in openclash_output openclash_mangle_output openclash_output_v6 openclash_mangle_output_v6; do
    : > "$TMP/nft-state/$chain"
done

run_helper() {
    PATH="$TMP/bin:$PATH" LOCK_FILE="$TMP/lock" TMPDIR="$TMP" \
        "$ROOT/AX6-IPQ/files/usr/bin/ax6-openclash-zerotier-bypass" "$@"
}

: > "$NFT_APPLY_LOG"
run_helper --dry-run --sync 9993 19993 29993
[ ! -s "$NFT_APPLY_LOG" ]

run_helper --sync 9993 19993 29993
[ "$(grep -Fc 'AX6 ZeroTier primary self bypass' "$NFT_APPLY_LOG")" -eq 4 ]
[ "$(grep -Fc 'AX6 ZeroTier UDP self bypass' "$NFT_APPLY_LOG")" -eq 4 ]
grep -Fq 'meta l4proto { tcp, udp } th sport 9993' "$NFT_APPLY_LOG"
grep -Fq 'udp sport { 19993, 29993 }' "$NFT_APPLY_LOG"
if grep -E 'meta l4proto \{ tcp, udp \}.*(19993|29993)' "$NFT_APPLY_LOG"; then
    echo 'secondary/tertiary ports must not receive TCP bypass' >&2
    exit 1
fi

# Exact protocol-specific state must be idempotent.
for chain in openclash_output openclash_mangle_output openclash_output_v6 openclash_mangle_output_v6; do
    cat > "$TMP/nft-state/$chain" <<'EOF'
meta l4proto { tcp, udp } th sport 9993 counter return comment "AX6 ZeroTier primary self bypass" # handle 10
udp sport { 19993, 29993 } counter return comment "AX6 ZeroTier UDP self bypass" # handle 11
EOF
done
: > "$NFT_APPLY_LOG"
run_helper --sync 9993 19993 29993
[ ! -s "$NFT_APPLY_LOG" ]

# Mapping disabled removes tertiary from the generated UDP set.
for chain in openclash_output openclash_mangle_output openclash_output_v6 openclash_mangle_output_v6; do
    : > "$TMP/nft-state/$chain"
done
run_helper --sync 9993 19993 0
grep -Fq 'udp sport { 19993 }' "$NFT_APPLY_LOG"
if grep -Fq 29993 "$NFT_APPLY_LOG"; then
    echo 'tertiary port used while mapping is disabled' >&2
    exit 1
fi

# Disabling router self proxy cleans owned rules without inserting replacements.
cat > "$TMP/nft-state/openclash_output" <<'EOF'
meta l4proto { tcp, udp } th sport { 9993, 19993, 29993 } counter return comment "AX6 ZeroTier self bypass" # handle 42
EOF
: > "$NFT_APPLY_LOG"
ROUTER_SELF_PROXY=0 run_helper
grep -Fq 'delete rule inet fw4 openclash_output handle 42' "$NFT_APPLY_LOG"
if grep -Fq 'insert rule' "$NFT_APPLY_LOG"; then exit 1; fi

# An unavailable CLI must retain existing rules rather than deleting them.
: > "$NFT_APPLY_LOG"
if ROUTER_SELF_PROXY=1 ZT_CLI_FAIL=1 run_helper; then
    echo 'bypass helper unexpectedly accepted an unavailable CLI' >&2
    exit 1
fi
[ ! -s "$NFT_APPLY_LOG" ]

cat > "$TMP/openclash.init" <<'EOF'
#!/bin/sh
if [ -f "/etc/openclash/custom/openclash_custom_firewall_rules.sh" ]; then
   chmod +x /etc/openclash/custom/openclash_custom_firewall_rules.sh
   /etc/openclash/custom/openclash_custom_firewall_rules.sh
fi
EOF
chmod 0755 "$TMP/openclash.init"
"$ROOT/.github/scripts/inject-openclash-zerotier-hook.sh" "$TMP/openclash.init"
[ "$(grep -Fc '/usr/bin/ax6-openclash-zerotier-bypass' "$TMP/openclash.init")" -eq 2 ]
"$ROOT/.github/scripts/inject-openclash-zerotier-hook.sh" "$TMP/openclash.init"
[ "$(grep -Fc '/usr/bin/ax6-openclash-zerotier-bypass' "$TMP/openclash.init")" -eq 2 ]

echo 'test-openclash-zerotier-bypass: PASS'
