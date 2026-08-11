#!/bin/sh
set -eu

# shellcheck disable=SC1007 # Keep cd output independent of CDPATH.
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
HELPER="$ROOT/.github/scripts/enforce-openclash-keep-policy.sh"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/openclash-keep-policy.XXXXXX")
cleanup_test() {
    status=$?
    trap - EXIT HUP INT TERM
    rm -rf "$TMP"
    exit "$status"
}
trap cleanup_test EXIT HUP INT TERM

cat > "$TMP/luci-openclash" <<'FIXTURE'
#!/bin/sh
mkdir -p /lib/upgrade/keep.d
cat > "/lib/upgrade/keep.d/luci-app-openclash" <<-EOF
/etc/openclash/
EOF
echo after-policy
FIXTURE

"$HELPER" apply "$TMP/luci-openclash"
"$HELPER" check "$TMP/luci-openclash"
grep -Fqx 'echo after-policy' "$TMP/luci-openclash"
test "$(grep -Fc '/etc/openclash/config/' "$TMP/luci-openclash")" -eq 1
test "$(grep -Fc '/etc/openclash/custom/' "$TMP/luci-openclash")" -eq 1
test "$(grep -Fc '/etc/openclash/overwrite/' "$TMP/luci-openclash")" -eq 1
if grep -Fqx '/etc/openclash/' "$TMP/luci-openclash"; then
    echo "test-openclash-keep-policy: broad keep path survived" >&2
    exit 1
fi

printf '%s\n' '#!/bin/sh' 'echo no-policy' > "$TMP/missing"
if "$HELPER" apply "$TMP/missing" >/dev/null 2>&1; then
    echo "test-openclash-keep-policy: missing policy unexpectedly accepted" >&2
    exit 1
fi
grep -Fqx 'echo no-policy' "$TMP/missing"

cat "$TMP/luci-openclash" "$TMP/luci-openclash" > "$TMP/duplicate"
if "$HELPER" check "$TMP/duplicate" >/dev/null 2>&1; then
    echo "test-openclash-keep-policy: duplicate policy unexpectedly accepted" >&2
    exit 1
fi

echo "test-openclash-keep-policy: PASS"
