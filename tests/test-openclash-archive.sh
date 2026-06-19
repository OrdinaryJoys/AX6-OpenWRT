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

echo "test-openclash-archive: PASS"
