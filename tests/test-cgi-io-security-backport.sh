#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
HELPER="$ROOT/AX6-IPQ/scripts/apply-cgi-io-security-backport.sh"
PATCH="$ROOT/AX6-IPQ/package-patches/cgi-io/100-fix-malformed-post-use-after-free.patch"
FIXTURE="$ROOT/tests/fixtures/cgi-io/Makefile.old"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/cgi-io-backport-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

fail() {
	echo "test-cgi-io-security-backport: FAIL: $*" >&2
	exit 1
}

[ -x "$HELPER" ] || fail "helper is missing or not executable"
[ -s "$PATCH" ] || fail "official backport patch is missing"
grep -Fq '50dec501ab1bc86f844de2e40d4e4d0aaa613d20' "$PATCH" ||
	fail "package backport provenance is missing"
grep -Fq '31cb3c89f02d918d7f17bf62a80c852fc38a1ca1' "$PATCH" ||
	fail "fixed cgi-io source revision is missing"

mkdir -p "$TMP/packages/net/cgi-io"
cp "$FIXTURE" "$TMP/packages/net/cgi-io/Makefile"

"$HELPER" "$TMP/packages" "$PATCH"
"$HELPER" "$TMP/packages" "$PATCH"
grep -Fqx 'PKG_SOURCE_DATE:=2026-07-21' "$TMP/packages/net/cgi-io/Makefile"
grep -Fqx 'PKG_SOURCE_VERSION:=31cb3c89f02d918d7f17bf62a80c852fc38a1ca1' "$TMP/packages/net/cgi-io/Makefile"
grep -Fqx 'PKG_MIRROR_HASH:=ecb2ce93b5f62d9fa35ca2b514faa5ef14e462d782bc1dd0de0e4b2ecabcec71' "$TMP/packages/net/cgi-io/Makefile"

cp "$FIXTURE" "$TMP/packages/net/cgi-io/Makefile"
sed 's/PKG_SOURCE_DATE:=2026-06-28/PKG_SOURCE_DATE:=2026-07-21/' \
	"$FIXTURE" > "$TMP/packages/net/cgi-io/Makefile"
if "$HELPER" "$TMP/packages" "$PATCH" >/dev/null 2>&1; then
	fail "mixed source metadata was accepted"
fi

cp "$FIXTURE" "$TMP/packages/net/cgi-io/Makefile"
sed 's/7314451cb99692c0862a70c3307ee08bd2fbd9c0/unknown/' \
	"$FIXTURE" > "$TMP/packages/net/cgi-io/Makefile"
if "$HELPER" "$TMP/packages" "$PATCH" >/dev/null 2>&1; then
	fail "unknown source metadata was accepted"
fi

grep -Fq 'CGI_IO_BACKPORT_HELPER=' "$ROOT/AX6-IPQ/diy.sh" ||
	fail "diy.sh does not invoke the guarded backport helper"

echo 'test-cgi-io-security-backport: PASS'
