#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/zerotier-fw4-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin" "$TMP/fw"

cat > "$TMP/bin/lock" <<'EOF'
#!/bin/sh
exit 0
EOF

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
case "$*" in
    '-j listnetworks') printf '%s\n' '[{"portDeviceName":"ztmock0","nwid":"abc123"}]' ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
cat >/dev/null
printf '%s\n' abc123
EOF

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
    'show zerotier') printf '%s\n' "zerotier.net=network" "zerotier.net.id='abc123'" ;;
    *zerotier.net.fw_allow_input*) printf '%s\n' 1 ;;
    *zerotier.net.fw_allow_forward*) printf '%s\n' 1 ;;
    *zerotier.net.fw_allow_masq*) printf '%s\n' 1 ;;
    *zerotier.net.fw_forward_ifaces*|*zerotier.net.fw_masq_ifaces*) exit 1 ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/nft" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$NFT_LOG"
exit 0
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
exit 0
EOF

cat > "$TMP/bin/reconciler" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" > "$RECONCILER_LOG"
EOF

chmod +x "$TMP/bin/"*
export NFT_LOG="$TMP/nft.log"
export RECONCILER_LOG="$TMP/reconciler.log"

PATH="$TMP/bin:$PATH" FW_PATH="$TMP/fw" LOCK_FILE="$TMP/lock" \
    sh "$ROOT/AX6-IPQ/files/usr/bin/zerotier-fw4" -i ztmock0

grep -Fq 'Accept ZeroTier input ztmock0' "$TMP/fw/input.nft"
[ "$(grep -Fc 'forward ztmock0' "$TMP/fw/forward.nft")" -eq 2 ]
grep -Fq 'Masquerade ZeroTier traffic ztmock0' "$TMP/fw/srcnat.nft"

# An existing input rule must not prevent missing forward/srcnat files from rebuilding.
rm -f "$TMP/fw/forward.nft" "$TMP/fw/srcnat.nft"
PATH="$TMP/bin:$PATH" FW_PATH="$TMP/fw" LOCK_FILE="$TMP/lock" \
    sh "$ROOT/AX6-IPQ/files/usr/bin/zerotier-fw4" -i ztmock0
[ "$(grep -Fc 'forward ztmock0' "$TMP/fw/forward.nft")" -eq 2 ]
grep -Fq 'Masquerade ZeroTier traffic ztmock0' "$TMP/fw/srcnat.nft"

PATH="$TMP/bin:$PATH" FW_PATH="$TMP/fw" RECONCILER="$TMP/bin/reconciler" \
    sh "$ROOT/AX6-IPQ/files/usr/bin/zerotier-fw4" -s
grep -Fqx -- '--once' "$RECONCILER_LOG"

echo 'test-zerotier-fw4: PASS'
