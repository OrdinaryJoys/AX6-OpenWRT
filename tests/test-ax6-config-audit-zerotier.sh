#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ax6-audit-zerotier-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin" "$TMP/fw"

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
    '-q show wireless') printf '%s\n' 'wireless.radio0=wifi-device' ;;
    '-q show network') exit 0 ;;
    '-q show zerotier') printf '%s\n' "zerotier.net=network" "zerotier.net.id='abc123'" ;;
    '-q get wireless.radio0.band') echo 2g ;;
    '-q get wireless.radio0.htmode') echo HE40 ;;
    '-q get wireless.radio0.ht_coex') echo 1 ;;
    '-q get wireless.radio0.noscan') exit 1 ;;
    '-q get zerotier.global') echo zerotier ;;
    '-q get zerotier.global.enabled') echo 1 ;;
    '-q get zerotier.global.fw_allow_input') echo "${FW_ALLOW_INPUT:-1}" ;;
    '-q get zerotier.net.id') echo abc123 ;;
    '-q get zerotier.net.enabled') echo 1 ;;
    '-q get zerotier.net.fw_allow_input') echo "${NETWORK_ALLOW_INPUT:-0}" ;;
    '-q get zerotier.net.fw_allow_forward'|'-q get zerotier.net.fw_allow_masq') echo 0 ;;
    '-q get zerotier.net.allow_default'|'-q get zerotier.net.allow_global'|'-q get zerotier.net.allow_dns') echo 0 ;;
    '-q get firewall.zerotier_input.type') echo nftables ;;
    '-q get firewall.zerotier_input.path') echo "$ZT_FW_PATH/input.nft" ;;
    '-q get firewall.zerotier_input.position') echo chain-pre ;;
    '-q get firewall.zerotier_input.chain') echo input ;;
    '-q get upnpd.config'|'-q get openclash.config') exit 1 ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
printf '%s\n' '{"config":{"settings":{"primaryPort":9993,"secondaryPort":59120,"tertiaryPort":63542,"portMappingEnabled":true}}}'
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
input=$(cat)
case "$*" in
    *primaryPort*) echo 9993 ;;
    *secondaryPort*) echo 59120 ;;
    *tertiaryPort*) echo 63542 ;;
    *portMappingEnabled*) echo true ;;
    *) printf '%s\n' "$input" >/dev/null; exit 1 ;;
esac
EOF

cat > "$TMP/bin/nft" <<'EOF'
#!/bin/sh
case "$*" in
    '-a list chain inet fw4 input') cat "$NFT_INPUT" ;;
    '-a list chain inet fw4 openclash_'*) exit 1 ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/pidof" <<'EOF'
#!/bin/sh
[ "$1" = zerotier-one ] && echo 100
EOF

cat > "$TMP/bin/find" <<'EOF'
#!/bin/sh
printf '%s\n' /sys/class/net/ztmock0
EOF
chmod +x "$TMP/bin/"*

export ZT_FW_PATH="$TMP/fw"
export NFT_INPUT="$TMP/nft-input"

write_exact_rules() {
    cat > "$ZT_FW_PATH/input.nft" <<'EOF'
meta l4proto { udp, tcp } th dport 9993 counter accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)"
meta l4proto { udp } th dport 59120 counter accept comment "!fw4: Accept ZeroTier input 59120 (secondaryPort)"
meta l4proto { udp } th dport 63542 counter accept comment "!fw4: Accept ZeroTier input 63542 (tertiaryPort)"
EOF
    cat > "$NFT_INPUT" <<'EOF'
meta l4proto { tcp, udp } th dport 9993 counter accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)" # handle 10
udp dport 59120 counter accept comment "!fw4: Accept ZeroTier input 59120 (secondaryPort)" # handle 11
udp dport 63542 counter accept comment "!fw4: Accept ZeroTier input 63542 (tertiaryPort)" # handle 12
EOF
}

run_audit() {
    PATH="$TMP/bin:$PATH" "$ROOT/AX6-IPQ/files/sbin/ax6-config-audit" -v
}

write_exact_rules
run_audit > "$TMP/pass.log"
grep -Fq 'nft input include exactly matches daemon ports and protocols' "$TMP/pass.log"
grep -Fq 'live nft input rules exactly match daemon ports and protocols' "$TMP/pass.log"
grep -Fq 'FAIL=0' "$TMP/pass.log"

sed 's/59120/56064/g' "$ZT_FW_PATH/input.nft" > "$TMP/stale"
mv "$TMP/stale" "$ZT_FW_PATH/input.nft"
if run_audit > "$TMP/stale.log"; then
    echo 'audit unexpectedly accepted a stale include port' >&2
    exit 1
fi
grep -Fq 'input include has missing, stale, or protocol-mismatched service ports' "$TMP/stale.log"

write_exact_rules
printf '%s\n' 'udp dport 56064 counter accept comment "!fw4: Accept ZeroTier input 56064 (secondaryPort)" # handle 13' >> "$NFT_INPUT"
if run_audit > "$TMP/extra.log"; then
    echo 'audit unexpectedly accepted an extra live port' >&2
    exit 1
fi
grep -Fq 'live nft input rules differ from daemon ports or include stale rules' "$TMP/extra.log"

printf '%s\n' 'tcp dport 1234 counter accept comment "user rule"' > "$ZT_FW_PATH/input.nft"
printf '%s\n' 'tcp dport 1234 counter accept comment "user rule" # handle 20' > "$NFT_INPUT"
FW_ALLOW_INPUT=0 run_audit > "$TMP/disabled.log"
grep -Fq 'service-port input permission disabled and no service-port rules remain' "$TMP/disabled.log"
grep -Fq 'FAIL=0' "$TMP/disabled.log"

# Per-network input permission needs the shared include but not daemon service ports.
cat > "$ZT_FW_PATH/input.nft" <<'EOF'
iifname ztmock0 counter accept comment "!fw4: Accept ZeroTier input ztmock0"
EOF
cat > "$NFT_INPUT" <<'EOF'
iifname ztmock0 counter accept comment "!fw4: Accept ZeroTier input ztmock0" # handle 30
EOF
FW_ALLOW_INPUT=0 NETWORK_ALLOW_INPUT=1 run_audit > "$TMP/network-input.log"
grep -Fq 'dynamic nftables input include installed' "$TMP/network-input.log"
grep -Fq 'service-port input permission disabled and no service-port rules remain' "$TMP/network-input.log"
grep -Fq 'FAIL=0' "$TMP/network-input.log"

echo 'test-ax6-config-audit-zerotier: PASS'
