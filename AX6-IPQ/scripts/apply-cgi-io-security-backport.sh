#!/bin/sh
set -eu

PACKAGE_ROOT=${1:?usage: apply-cgi-io-security-backport.sh PACKAGE_ROOT PATCH}
PATCH_FILE=${2:?usage: apply-cgi-io-security-backport.sh PACKAGE_ROOT PATCH}
MAKEFILE="$PACKAGE_ROOT/net/cgi-io/Makefile"

old_date='PKG_SOURCE_DATE:=2026-06-28'
old_version='PKG_SOURCE_VERSION:=7314451cb99692c0862a70c3307ee08bd2fbd9c0'
old_hash='PKG_MIRROR_HASH:=dbee2e121906bf93631f288c94ebee61f812929a03bc948c84ccea6fc4c8e333'
new_date='PKG_SOURCE_DATE:=2026-07-21'
new_version='PKG_SOURCE_VERSION:=31cb3c89f02d918d7f17bf62a80c852fc38a1ca1'
new_hash='PKG_MIRROR_HASH:=ecb2ce93b5f62d9fa35ca2b514faa5ef14e462d782bc1dd0de0e4b2ecabcec71'

fail() {
	echo "[cgi-io-backport] $*" >&2
	exit 2
}

has_all() {
	file=$1
	shift
	for line in "$@"; do
		grep -Fqx "$line" "$file" || return 1
	done
}

[ -f "$MAKEFILE" ] || fail "missing locked package Makefile: $MAKEFILE"
[ -s "$PATCH_FILE" ] || fail "missing security backport: $PATCH_FILE"

if has_all "$MAKEFILE" "$new_date" "$new_version" "$new_hash"; then
	if grep -Fq '7314451cb99692c0862a70c3307ee08bd2fbd9c0' "$MAKEFILE"; then
		fail "mixed old and fixed cgi-io source metadata"
	fi
	echo '[cgi-io-backport] official fixed source is already selected'
	exit 0
fi

has_all "$MAKEFILE" "$old_date" "$old_version" "$old_hash" ||
	fail "unknown or partially updated cgi-io source metadata"

(cd "$PACKAGE_ROOT" && patch -s -p1 < "$PATCH_FILE") ||
	fail "official security backport did not apply cleanly"

has_all "$MAKEFILE" "$new_date" "$new_version" "$new_hash" ||
	fail "security backport applied without producing the locked fixed source"

if grep -Fq '7314451cb99692c0862a70c3307ee08bd2fbd9c0' "$MAKEFILE"; then
	fail "old cgi-io source revision remains after backport"
fi

echo '[cgi-io-backport] selected official fixed source 31cb3c89f02d918d7f17bf62a80c852fc38a1ca1'
