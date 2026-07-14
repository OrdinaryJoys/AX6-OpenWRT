#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
    echo "usage: $0 <source-root> <sha256-manifest> <absent-list> <manifest-sha256>" >&2
    exit 64
fi

source_root="$1"
manifest="$2"
absent_list="$3"
expected_manifest_sha="$4"

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

echo "AX6 source patchset provenance: PASS"
