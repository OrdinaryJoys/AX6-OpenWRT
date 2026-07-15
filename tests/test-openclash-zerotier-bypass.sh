#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/openclash-zerotier-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin"

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
    *zerotier.global.enabled*) echo 1 ;;
    *openclash.config.enable*) echo 1 ;;
    *openclash.config.router_self_proxy*) echo "${ROUTER_SELF_PROXY:-1}" ;;
esac
EOF

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
cat <<JSON
{"config":{"settings":{"primaryPort":9993,"secondaryPort":19993,"tertiaryPort":29993,"portMappingEnabled":${PORT_MAPPING_ENABLED:-true}}}}
JSON
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
case "$*" in
    *config.settings*) cat ;;
    *portMappingEnabled*) echo "${PORT_MAPPING_ENABLED:-true}" ;;
    *primaryPort*) echo 9993 ;;
    *secondaryPort*) echo 19993 ;;
    *tertiaryPort*) echo 29993 ;;
esac
EOF

cat > "$TMP/bin/nft" <<'EOF'
#!/bin/sh
case "$*" in
    "-a list chain"*) exit 0 ;;
    "list chain"*) exit 0 ;;
    "insert rule"*) printf '%s\n' "$*" >> "$NFT_LOG" ;;
    "delete rule"*) exit 0 ;;
esac
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$TMP/bin/"*

NFT_LOG="$TMP/nft.log"
export NFT_LOG
PATH="$TMP/bin:$PATH" \
    "$ROOT/AX6-IPQ/files/usr/bin/ax6-openclash-zerotier-bypass"

[ "$(wc -l < "$NFT_LOG" | tr -d ' ')" -eq 4 ]
grep -Fq 'openclash_output position 0' "$NFT_LOG"
grep -Fq 'openclash_mangle_output position 0' "$NFT_LOG"
grep -Fq 'openclash_output_v6 position 0' "$NFT_LOG"
grep -Fq 'openclash_mangle_output_v6 position 0' "$NFT_LOG"
grep -Fq '9993, 19993, 29993' "$NFT_LOG"
grep -Fq 'AX6 ZeroTier self bypass' "$NFT_LOG"

: > "$NFT_LOG"
ROUTER_SELF_PROXY=0 PATH="$TMP/bin:$PATH" \
    "$ROOT/AX6-IPQ/files/usr/bin/ax6-openclash-zerotier-bypass"
[ ! -s "$NFT_LOG" ]

: > "$NFT_LOG"
PORT_MAPPING_ENABLED=false PATH="$TMP/bin:$PATH" \
    "$ROOT/AX6-IPQ/files/usr/bin/ax6-openclash-zerotier-bypass"
grep -Fq '9993, 19993' "$NFT_LOG"
if grep -Fq '29993' "$NFT_LOG"; then
    echo "test-openclash-zerotier-bypass: tertiary port used while mapping is disabled" >&2
    exit 1
fi

cat > "$TMP/openclash.init" <<'EOF'
#!/bin/sh
if [ -f "/etc/openclash/custom/openclash_custom_firewall_rules.sh" ]; then
   chmod +x /etc/openclash/custom/openclash_custom_firewall_rules.sh
   /etc/openclash/custom/openclash_custom_firewall_rules.sh
fi
EOF
chmod 0755 "$TMP/openclash.init"
"$ROOT/.github/scripts/inject-openclash-zerotier-hook.sh" "$TMP/openclash.init"
[ -x "$TMP/openclash.init" ]
[ "$(grep -Fc '/usr/bin/ax6-openclash-zerotier-bypass' "$TMP/openclash.init")" -eq 2 ]
grep -Fq 'LOG_ERROR "Set ZeroTier self-proxy bypass failed"' "$TMP/openclash.init"
"$ROOT/.github/scripts/inject-openclash-zerotier-hook.sh" "$TMP/openclash.init"
[ "$(grep -Fc '/usr/bin/ax6-openclash-zerotier-bypass' "$TMP/openclash.init")" -eq 2 ]

echo "test-openclash-zerotier-bypass: PASS"
