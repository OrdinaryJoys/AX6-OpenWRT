#!/usr/bin/env bash
# Build a self-contained offline package feed from an OpenWrt target index.

set -euo pipefail

SOURCE_DIR="${1:?usage: package-ax6-offline-feed.sh SOURCE_DIR OUTPUT_DIR}"
OUTPUT_DIR="${2:?usage: package-ax6-offline-feed.sh SOURCE_DIR OUTPUT_DIR}"
PACKAGES_DIR="$OUTPUT_DIR/packages"
PACKAGES_INDEX="$SOURCE_DIR/Packages"

[ -d "$SOURCE_DIR" ] || { echo "package source directory is missing: $SOURCE_DIR" >&2; exit 1; }
[ -s "$PACKAGES_INDEX" ] || { echo "target package index is missing" >&2; exit 1; }

mkdir -p "$OUTPUT_DIR"
if find "$OUTPUT_DIR" -mindepth 1 -print -quit | grep -q .; then
    echo "output directory must be empty: $OUTPUT_DIR" >&2
    exit 1
fi
mkdir -p "$PACKAGES_DIR"

find "$SOURCE_DIR" -maxdepth 1 -type f -name 'Packages*' \
    -exec cp -f {} "$PACKAGES_DIR/" \;

indexed_ipks=()
while IFS= read -r filename; do
    indexed_ipks[${#indexed_ipks[@]}]="$filename"
done < <(awk -F': ' '/^Filename: / { print $2 }' "$PACKAGES_INDEX")
[ "${#indexed_ipks[@]}" -gt 0 ] || {
    echo "target package index contains no Filename entries" >&2
    exit 1
}

for filename in "${indexed_ipks[@]}"; do
    case "$filename" in
        ''|*/*|.|..)
            echo "unsafe package filename: $filename" >&2
            exit 1
            ;;
    esac
    [ -f "$SOURCE_DIR/$filename" ] || {
        echo "package index references a missing IPK: $filename" >&2
        exit 1
    }
    cp -f "$SOURCE_DIR/$filename" "$PACKAGES_DIR/"
done

find "$PACKAGES_DIR" -maxdepth 1 -type f -name 'kmod-*.ipk' -print -quit |
    grep -q . || { echo "offline feed contains no kmod IPK" >&2; exit 1; }

staged_ipks=$(find "$PACKAGES_DIR" -maxdepth 1 -type f -name '*.ipk' | wc -l)
[ "$staged_ipks" -eq "${#indexed_ipks[@]}" ] || {
    echo "offline feed mismatch: staged=$staged_ipks indexed=${#indexed_ipks[@]}" >&2
    exit 1
}

while IFS= read -r filename; do
    [ -f "$PACKAGES_DIR/$filename" ] || {
        echo "staged package index references a missing IPK: $filename" >&2
        exit 1
    }
done < <(awk -F': ' '/^Filename: / { print $2 }' "$PACKAGES_DIR/Packages")

if [ -f "$PACKAGES_DIR/Packages.gz" ]; then
    gzip -dc "$PACKAGES_DIR/Packages.gz" | cmp - "$PACKAGES_DIR/Packages" || {
        echo "Packages.gz does not match Packages" >&2
        exit 1
    }
fi

find "$PACKAGES_DIR" -type f -exec sha256sum {} + |
    sed "s#$OUTPUT_DIR/##" > "$OUTPUT_DIR/KMOD-SHA256SUMS.txt"
tar -czf "$OUTPUT_DIR/kmod-packages.tar.gz" \
    -C "$OUTPUT_DIR" packages KMOD-SHA256SUMS.txt
(
    cd "$OUTPUT_DIR"
    sha256sum kmod-packages.tar.gz > KMOD-ARCHIVE-SHA256.txt
)

printf 'offline feed complete: indexed=%s staged=%s\n' \
    "${#indexed_ipks[@]}" "$staged_ipks"
