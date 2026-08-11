#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
HELPER="$ROOT/.github/scripts/inject-openclash-rom-core-guard.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/openclash-core-guard-test.XXXXXX")"
cleanup_test() {
	status=$?
	trap - EXIT HUP INT TERM
	rm -rf "$TMP"
	exit "$status"
}
trap cleanup_test EXIT HUP INT TERM

cat > "$TMP/openclash" <<'EOF'
do_run_file() {
   if [ ! -x "$CLASH" ]; then
      chmod 4755 "$CLASH"
      chown root:root "$CLASH"
   fi
}

start_run_core()
{
   meta_core_path="$(readlink -f "$CLASH")"
   chown root:root "$CLASH"
   "$CLASH" -d /etc/openclash
}

stop() {
   :
}
EOF

"$HELPER" apply "$TMP/openclash"
"$HELPER" check "$TMP/openclash" > "$TMP/check.log"
grep -Fq 'ROM core ownership guard: PASS' "$TMP/check.log"
[ "$(grep -Fc 'chown root:root "$CLASH"' "$TMP/openclash")" -eq 2 ]
[ "$(grep -Fxc '      chown root:root "$CLASH"' "$TMP/openclash")" -eq 2 ]
[ "$(grep -Fxc '   chown root:root "$CLASH"' "$TMP/openclash")" -eq 0 ]
grep -Fq '[ -e "$meta_core_path" ]' "$TMP/openclash"
grep -Fq 'ls -ln "$meta_core_path"' "$TMP/openclash"

before="$(sha256sum "$TMP/openclash" | awk '{ print $1 }')"
"$HELPER" apply "$TMP/openclash"
after="$(sha256sum "$TMP/openclash" | awk '{ print $1 }')"
[ "$before" = "$after" ] || {
	echo 'OpenClash core guard injection is not idempotent' >&2
	exit 1
}

sed '/^   if \[ -e .*meta_core_path/d' "$TMP/openclash" > "$TMP/malformed"
if "$HELPER" check "$TMP/malformed" >/dev/null 2>&1; then
	echo 'OpenClash core guard accepted a malformed guard' >&2
	exit 1
fi

sed '/^start_run_core()/,/^}/s/^      chown/   chown/' \
	"$TMP/openclash" > "$TMP/unconditional"
if "$HELPER" check "$TMP/unconditional" >/dev/null 2>&1; then
	echo 'OpenClash core guard accepted an unconditional start_run_core chown' >&2
	exit 1
fi

sed '/^start_run_core()/,/^}/d' "$TMP/openclash" > "$TMP/missing-function"
if "$HELPER" apply "$TMP/missing-function" >/dev/null 2>&1; then
	echo 'OpenClash core guard accepted a missing start_run_core function' >&2
	exit 1
fi

cat "$TMP/openclash" "$TMP/openclash" > "$TMP/duplicate"
if "$HELPER" check "$TMP/duplicate" >/dev/null 2>&1; then
	echo 'OpenClash core guard accepted duplicate start_run_core functions' >&2
	exit 1
fi

echo 'test-openclash-rom-core-guard: PASS'
