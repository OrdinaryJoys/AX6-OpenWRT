#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/openclash-archive-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

mkdir -p "$TMP/payload/etc"
printf 'not allowed\n' > "$TMP/payload/etc/passwd"
mkdir -p "$TMP/backup"
tar -czf "$TMP/backup/openclash-runtime.tar.gz" -C "$TMP/payload" etc/passwd

if "$ROOT/deploy-openclash-runtime.sh" 192.0.2.1 "$TMP/backup" \
    > "$TMP/output" 2>&1; then
    echo "test-openclash-archive: unsafe archive unexpectedly accepted" >&2
    exit 1
fi

grep -q 'archive contains paths outside the restore allowlist' "$TMP/output" || {
    echo "test-openclash-archive: expected rejection was not reported" >&2
    exit 1
}

mkdir -p "$TMP/link-payload/etc/openclash/custom"
ln -s /etc/passwd "$TMP/link-payload/etc/openclash/custom/escape"
tar -czf "$TMP/backup/openclash-runtime.tar.gz" \
    -C "$TMP/link-payload" etc/openclash/custom

if "$ROOT/deploy-openclash-runtime.sh" 192.0.2.1 "$TMP/backup" \
    > "$TMP/link-output" 2>&1; then
    echo "test-openclash-archive: symlink archive unexpectedly accepted" >&2
    exit 1
fi

grep -q 'archive contains links or special files' "$TMP/link-output" || {
    echo "test-openclash-archive: expected symlink rejection was not reported" >&2
    exit 1
}

mkdir -p "$TMP/valid-payload/etc/config" "$TMP/pre-payload/etc/config" "$TMP/bin"
printf "config openclash 'config'\n\toption enable '0'\n" \
    > "$TMP/valid-payload/etc/config/openclash"
printf "config openclash 'config'\n\toption enable '1'\n" \
    > "$TMP/pre-payload/etc/config/openclash"
tar -czf "$TMP/backup/openclash-runtime.tar.gz" \
    -C "$TMP/valid-payload" etc/config/openclash
tar -czf "$TMP/pre-restore.tar.gz" \
    -C "$TMP/pre-payload" etc/config/openclash

cat > "$TMP/bin/ssh" <<'EOF'
#!/bin/sh
count=0
[ ! -r "$MOCK_CALLS" ] || count=$(cat "$MOCK_CALLS")
count=$((count + 1))
printf '%s\n' "$count" > "$MOCK_CALLS"
printf 'call=%s command=%s\n' "$count" "${2:-}" >> "$MOCK_LOG"

case "$count" in
    2)
        cat "$MOCK_PRE_ARCHIVE"
        ;;
    3)
        printf '0 4 * * * /usr/bin/original-job\n'
        ;;
    4|6|7)
        cat >/dev/null
        ;;
    5)
        exit 9
        ;;
esac
EOF
chmod +x "$TMP/bin/ssh"
: > "$TMP/mock-calls"
: > "$TMP/mock-log"

if PATH="$TMP/bin:$PATH" \
   MOCK_CALLS="$TMP/mock-calls" \
   MOCK_LOG="$TMP/mock-log" \
   MOCK_PRE_ARCHIVE="$TMP/pre-restore.tar.gz" \
   "$ROOT/deploy-openclash-runtime.sh" 192.0.2.1 "$TMP/backup" \
   > "$TMP/rollback-output" 2>&1; then
    echo "test-openclash-archive: failed restart unexpectedly succeeded" >&2
    exit 1
fi

grep -q 'previous OpenClash state restored' "$TMP/rollback-output" || {
    echo "test-openclash-archive: automatic rollback was not completed" >&2
    exit 1
}
[ "$(cat "$TMP/mock-calls")" -eq 7 ] || {
    echo "test-openclash-archive: unexpected SSH call count during rollback" >&2
    exit 1
}

echo "test-openclash-archive: PASS"
