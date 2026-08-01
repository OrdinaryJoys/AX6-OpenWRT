#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
PATCH="$ROOT/AX6-IPQ/package-patches/zerotier/100-openwrt-increase-udp-socket-buffer.patch"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/zerotier-buffer-patch-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/node"

line=1
while [ "$line" -le 740 ]; do
	printf 'line %s\n' "$line"
	line=$((line + 1))
done > "$TMP/node/Constants.hpp"
cat >> "$TMP/node/Constants.hpp" <<'EOF'
/**
 * Desired buffer size for UDP sockets (used in service and osdep but defined here)
 */
#define ZT_UDP_DESIRED_BUF_SIZE 1048576

/**
 * Desired / recommended min stack size for threads (used on some platforms to reset thread stack size)
EOF

(cd "$TMP" && patch -s -p1 < "$PATCH")
grep -Fqx '#define ZT_UDP_DESIRED_BUF_SIZE 4194304' "$TMP/node/Constants.hpp"
[ "$(grep -c 'ZT_UDP_DESIRED_BUF_SIZE' "$TMP/node/Constants.hpp")" -eq 1 ]
grep -Fq 'ZEROTIER_BUFFER_PATCH=' "$ROOT/AX6-IPQ/diy.sh"
if rg -n 'rmem_default.*=' "$ROOT/AX6-IPQ" >/dev/null 2>&1; then
	echo 'ZeroTier fix must not mutate global rmem_default' >&2
	exit 1
fi

echo 'test-zerotier-buffer-patch: PASS'
