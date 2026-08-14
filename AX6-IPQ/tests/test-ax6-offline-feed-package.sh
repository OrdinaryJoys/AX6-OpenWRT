#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGER="$ROOT/AX6-IPQ/scripts/package-ax6-offline-feed.sh"
WORK="$(mktemp -d /tmp/ax6-offline-feed.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

make_source() {
    local source="$1"
    mkdir -p "$source"
    printf 'kmod fixture\n' > "$source/kmod-fixture_1_aarch64.ipk"
    printf 'dependency fixture\n' > "$source/runtime-dependency_1_aarch64.ipk"
    cat > "$source/Packages" <<'EOF'
Package: kmod-fixture
Version: 1
Filename: kmod-fixture_1_aarch64.ipk

Package: runtime-dependency
Version: 1
Filename: runtime-dependency_1_aarch64.ipk
EOF
    gzip -c "$source/Packages" > "$source/Packages.gz"
    cp "$source/Packages" "$source/Packages.manifest"
    printf 'fixture signature\n' > "$source/Packages.sig"
}

source_ok="$WORK/source-ok"
output_ok="$WORK/output-ok"
make_source "$source_ok"
mkdir "$output_ok"
"$PACKAGER" "$source_ok" "$output_ok"

[ "$(find "$output_ok/packages" -name '*.ipk' | wc -l)" -eq 2 ]
gzip -dc "$output_ok/packages/Packages.gz" | cmp - "$output_ok/packages/Packages"
(
    cd "$output_ok"
    sha256sum -c KMOD-ARCHIVE-SHA256.txt
    sha256sum -c KMOD-SHA256SUMS.txt
    tar -tzf kmod-packages.tar.gz | grep -q '^packages/runtime-dependency_1_aarch64.ipk$'
)

source_missing="$WORK/source-missing"
output_missing="$WORK/output-missing"
make_source "$source_missing"
rm "$source_missing/runtime-dependency_1_aarch64.ipk"
mkdir "$output_missing"
if "$PACKAGER" "$source_missing" "$output_missing" >/dev/null 2>&1; then
    echo "missing indexed IPK was not rejected" >&2
    exit 1
fi

source_unsafe="$WORK/source-unsafe"
output_unsafe="$WORK/output-unsafe"
make_source "$source_unsafe"
sed -i.bak 's#Filename: runtime-dependency_1_aarch64.ipk#Filename: ../runtime-dependency_1_aarch64.ipk#' \
    "$source_unsafe/Packages"
mkdir "$output_unsafe"
if "$PACKAGER" "$source_unsafe" "$output_unsafe" >/dev/null 2>&1; then
    echo "unsafe indexed path was not rejected" >&2
    exit 1
fi

echo "offline feed packaging fixture: PASS"
