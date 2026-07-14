#!/bin/sh
set -eu

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

mkdir -p "$TMP/bin" "$TMP/fw"

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
    *zerotier.global.fw_allow_input*) printf '%s\n' 1 ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
case "$*" in
    info) exit 0 ;;
    '-j info') printf '%s\n' '{"config":{"settings":{"primaryPort":9993,"secondaryPort":45678,"tertiaryPort":56789}}}' ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
input=$(cat)
case "$*" in
    *'@.config.settings') printf '%s\n' '{"primaryPort":9993,"secondaryPort":45678,"tertiaryPort":56789}' ;;
    *'@.primaryPort') printf '%s\n' 9993 ;;
    *'@.secondaryPort') printf '%s\n' 45678 ;;
    *) printf '%s\n' "$input" >/dev/null; exit 1 ;;
esac
EOF

for command in nft fw4 logger; do
    cat > "$TMP/bin/$command" <<'EOF'
#!/bin/sh
exit 0
EOF
done
chmod +x "$TMP/bin/"*

run_helper() {
    PATH="$TMP/bin:$PATH" FW_PATH="$TMP/fw" \
        sh "$ROOT/AX6-IPQ/files/usr/bin/zerotier-fw4" -s
}

run_helper
grep -Fq 'meta l4proto { udp, tcp } th dport 9993' "$TMP/fw/input.nft"
grep -Fq 'meta l4proto { udp } th dport 45678' "$TMP/fw/input.nft"
if grep -Fq '56789' "$TMP/fw/input.nft"; then
    echo 'tertiaryPort must not be added to the fw4 include' >&2
    exit 1
fi

run_helper
[ "$(grep -Fc 'th dport 9993' "$TMP/fw/input.nft")" -eq 1 ]
[ "$(grep -Fc 'th dport 45678' "$TMP/fw/input.nft")" -eq 1 ]

echo 'zerotier fw4 service-port tests: PASS'
