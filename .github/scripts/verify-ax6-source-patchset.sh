#!/bin/sh
set -eu

if [ "$#" -ne 5 ]; then
    echo "usage: $0 <source-root> <sha256-manifest> <absent-list> <manifest-sha256> <base-commit>" >&2
    exit 64
fi

source_root="$1"
manifest="$2"
absent_list="$3"
expected_manifest_sha="$4"
source_base_commit="$5"

case "$expected_manifest_sha" in
    *[!0-9a-f]*|'')
        echo "invalid expected manifest SHA256" >&2
        exit 2
        ;;
esac
[ "${#expected_manifest_sha}" -eq 64 ] || {
    echo "expected manifest SHA256 must contain 64 lowercase hex characters" >&2
    exit 2
}

case "$source_base_commit" in
    *[!0-9a-f]*|'')
        echo "invalid source base commit" >&2
        exit 2
        ;;
esac
[ "${#source_base_commit}" -eq 40 ] || {
    echo "source base commit must contain 40 lowercase hex characters" >&2
    exit 2
}

git -C "$source_root" cat-file -e "$source_base_commit^{commit}" 2>/dev/null || {
    echo "source base commit is unavailable: $source_base_commit" >&2
    exit 2
}

if command -v sha256sum >/dev/null 2>&1; then
    manifest_sha="$(sha256sum "$manifest" | awk '{print $1}')"
    verify_cmd=sha256sum
elif command -v shasum >/dev/null 2>&1; then
    manifest_sha="$(shasum -a 256 "$manifest" | awk '{print $1}')"
    verify_cmd=shasum
else
    echo "no SHA256 implementation found" >&2
    exit 2
fi

[ "$manifest_sha" = "$expected_manifest_sha" ] || {
    echo "source patchset manifest hash mismatch: expected $expected_manifest_sha, got $manifest_sha" >&2
    exit 2
}

case "$verify_cmd" in
    sha256sum)
        (cd "$source_root" && sha256sum -c "$manifest")
        ;;
    shasum)
        (cd "$source_root" && shasum -a 256 -c "$manifest")
        ;;
esac

while IFS= read -r path || [ -n "$path" ]; do
    [ -n "$path" ] || continue
    case "$path" in
        /*|*'..'*)
            echo "unsafe path in absent list: $path" >&2
            exit 2
            ;;
    esac
    [ ! -e "$source_root/$path" ] || {
        echo "obsolete source patch must be absent: $path" >&2
        exit 2
    }
done < "$absent_list"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

awk '
    NF == 0 { next }
    NF != 2 || $1 !~ /^[0-9a-f]{64}$/ || $2 ~ /^\// || $2 ~ /\.\./ { exit 1 }
    { print $2 }
' "$manifest" > "$tmp_dir/listed-present-raw" || {
    echo "invalid source patchset manifest entry" >&2
    exit 2
}
LC_ALL=C sort -u "$tmp_dir/listed-present-raw" > "$tmp_dir/listed-present"
LC_ALL=C sort -u "$absent_list" > "$tmp_dir/listed-absent"

: > "$tmp_dir/diff-present-raw"
: > "$tmp_dir/diff-absent-raw"
git -C "$source_root" diff --name-status -M "$source_base_commit" HEAD |
awk -F '\t' -v present="$tmp_dir/diff-present-raw" -v absent="$tmp_dir/diff-absent-raw" '
    $1 == "D" { print $2 > absent; next }
    $1 ~ /^R/ { print $2 > absent; print $3 > present; next }
    $1 ~ /^C/ { print $3 > present; next }
    { print $2 > present }
'
LC_ALL=C sort -u "$tmp_dir/diff-present-raw" > "$tmp_dir/diff-present"
LC_ALL=C sort -u "$tmp_dir/diff-absent-raw" > "$tmp_dir/diff-absent"

diff -u "$tmp_dir/diff-present" "$tmp_dir/listed-present" || {
    echo "source patchset manifest does not cover the complete source diff" >&2
    exit 2
}
diff -u "$tmp_dir/diff-absent" "$tmp_dir/listed-absent" || {
    echo "source absent list does not cover every deleted or renamed path" >&2
    exit 2
}

echo "AX6 source patchset provenance: PASS"
