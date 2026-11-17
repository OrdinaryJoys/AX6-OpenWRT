#!/bin/sh

set -eu

if [ "$#" -ne 2 ]; then
	printf 'usage: %s DEVICE_MANIFEST OPKG_STATUS\n' "$0" >&2
	exit 2
fi

manifest=$1
status=$2

[ -s "$manifest" ] || {
	printf 'device manifest is missing or empty: %s\n' "$manifest" >&2
	exit 1
}
[ -s "$status" ] || {
	printf 'rootfs opkg status is missing or empty: %s\n' "$status" >&2
	exit 1
}

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT HUP INT TERM

LC_ALL=C sort "$manifest" > "$tmpdir/device-manifest"
awk '
	BEGIN { RS=""; FS="\n" }
	{
		package=""; version=""; state=""
		for (i = 1; i <= NF; i++) {
			if ($i ~ /^Package: /) package=substr($i, 10)
			if ($i ~ /^Version: /) version=substr($i, 10)
			if ($i ~ /^Status: /) state=substr($i, 9)
		}
		if (package != "" && version != "" && state ~ /^install [^ ]+ installed$/)
			print package " - " version
	}
' "$status" | LC_ALL=C sort > "$tmpdir/rootfs-manifest"

[ -s "$tmpdir/rootfs-manifest" ] || {
	printf 'no installed packages found in rootfs opkg status: %s\n' "$status" >&2
	exit 1
}

if ! cmp -s "$tmpdir/device-manifest" "$tmpdir/rootfs-manifest"; then
	printf 'device manifest does not match packages installed in the final rootfs\n' >&2
	diff -u "$tmpdir/device-manifest" "$tmpdir/rootfs-manifest" >&2 || true
	exit 1
fi

# The NSS workflow already sets its build lock path. The fallback build has
# a different source and must not be checked against these exact versions.
if [ "${BUILD_LOCK:-}" = '.github/ax6-nss-lock.env' ]; then
	manifest_dir=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
	expected_file="$manifest_dir/ax6-upstream-leaves-stock.manifest"
	[ "$(wc -l < "$expected_file")" -eq 7 ] || {
		printf 'expected seven upstream-leaf package pins\n' >&2
		exit 1
	}
	while IFS= read -r expected; do
		grep -Fxq -- "$expected" "$tmpdir/rootfs-manifest" || {
			printf 'missing exact upstream-leaf package in stock rootfs: %s\n' "$expected" >&2
			exit 1
		}
	done < "$expected_file"
fi

printf 'Device manifest/rootfs package inventory: PASS\n'
