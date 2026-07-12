#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
SCRIPT="$ROOT/AX6-IPQ/files/usr/bin/zerotier-fw4"
ZONE_SCRIPT="$ROOT/AX6-IPQ/files/etc/uci-defaults/94-ax6-zerotier-zone"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/zerotier-fw4-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/fw"

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
case "$*" in
    *listnetworks*) printf '%s\n' '[{"portDeviceName":"ztabc","nwid":"8056c2e21c000001"}]' ;;
    *info*) printf '%s\n' '{"config":{"settings":{"primaryPort":9993}}}' ;;
esac
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
case "$*" in
    *portDeviceName*) printf '%s\n' '8056c2e21c000001' ;;
    *primaryPort*) printf '%s\n' '9993' ;;
esac
EOF

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
key=
for arg in "$@"; do
    key="$arg"
done
case "$key" in
    zerotier.global.fw_allow_input|zerotier.test.fw_allow_input|zerotier.test.fw_allow_forward|zerotier.test.fw_allow_masq) printf '%s\n' 1 ;;
    zerotier.test.fw_forward_ifaces|zerotier.test.fw_masq_ifaces) printf '%s\n' lan ;;
esac
case "$*" in
    *'show zerotier'*) printf "%s\n" "zerotier.test=network" "zerotier.test.id='8056c2e21c000001'" ;;
esac
EOF

cat > "$TMP/bin/nft" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$NFT_LOG"
EOF

cat > "$TMP/bin/fw4" <<'EOF'
#!/bin/sh
exit 0
EOF

chmod +x "$TMP/bin/"*
export PATH="$TMP/bin:$PATH"
export NFT_LOG="$TMP/nft.log"
export ZEROTIER_FW_PATH="$TMP/fw"

# Reproduce the old failure: an existing input rule must not suppress the
# forward and srcnat rules for the same ZeroTier interface.
printf '%s\n' 'iifname ztabc counter accept comment "!fw4: Accept ZeroTier input ztabc"' > "$TMP/fw/input.nft"
"$SCRIPT" -i ztabc

[ "$(wc -l < "$TMP/fw/input.nft" | tr -d ' ')" -eq 1 ]
[ "$(wc -l < "$TMP/fw/forward.nft" | tr -d ' ')" -eq 2 ]
[ "$(wc -l < "$TMP/fw/srcnat.nft" | tr -d ' ')" -eq 1 ]

# A second hotplug event must not duplicate any rule.
"$SCRIPT" -i ztabc
[ "$(wc -l < "$TMP/fw/input.nft" | tr -d ' ')" -eq 1 ]
[ "$(wc -l < "$TMP/fw/forward.nft" | tr -d ' ')" -eq 2 ]
[ "$(wc -l < "$TMP/fw/srcnat.nft" | tr -d ' ')" -eq 1 ]

# Service-port refresh shares the same idempotent writer and must retain the
# interface rule while adding exactly one primary-port rule.
"$SCRIPT" -s
"$SCRIPT" -s
[ "$(wc -l < "$TMP/fw/input.nft" | tr -d ' ')" -eq 2 ]
grep -Fq 'th dport 9993' "$TMP/fw/input.nft"

# The persistent fw4 configuration must load every generated rule file.
grep -q "firewall.zerotier_srcnat.path='/var/run/zerotier-one/_fw4/srcnat.nft'" "$ZONE_SCRIPT"
grep -q "firewall.zerotier_srcnat.chain='srcnat'" "$ZONE_SCRIPT"

echo "test-zerotier-fw4: PASS"
