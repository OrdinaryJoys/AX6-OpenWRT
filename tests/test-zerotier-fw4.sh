#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/zerotier-fw4-test.XXXXXX")"
cleanup_test() {
	status=$?
	trap - EXIT HUP INT TERM
	rm -rf "$TMP"
	exit "$status"
}
trap cleanup_test EXIT HUP INT TERM
mkdir -p "$TMP/bin"

cat > "$TMP/bin/reconciler" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$RECONCILER_LOG"
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
exit 0
EOF

chmod +x "$TMP/bin/reconciler" "$TMP/bin/logger"
export RECONCILER_LOG="$TMP/reconciler.log"

PATH="$TMP/bin:$PATH" RECONCILER="$TMP/bin/reconciler" \
	sh "$ROOT/AX6-IPQ/files/usr/bin/zerotier-fw4" -i ztmock0
PATH="$TMP/bin:$PATH" RECONCILER="$TMP/bin/reconciler" \
	sh "$ROOT/AX6-IPQ/files/usr/bin/zerotier-fw4" -s

[ "$(grep -Fxc -- '--once' "$RECONCILER_LOG")" -eq 2 ]

if PATH="$TMP/bin:$PATH" RECONCILER="$TMP/bin/missing" \
	sh "$ROOT/AX6-IPQ/files/usr/bin/zerotier-fw4" -s; then
	echo 'zerotier-fw4 accepted a missing reconciler' >&2
	exit 1
fi

echo 'test-zerotier-fw4: PASS'
