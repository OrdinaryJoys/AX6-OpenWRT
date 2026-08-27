#!/bin/sh
set -eu
#
# Generate AX6 source patchset provenance manifest.
#
# Compares SOURCE_COMMIT against SOURCE_BASE_COMMIT and produces:
#   1. ax6-source-patchset.sha256 — SHA256 of every present file in the diff
#   2. ax6-source-patchset.absent  — files deleted/renamed since the base commit
#   3. SOURCE_PATCHSET_MANIFEST_SHA256 (stdout) — SHA256 of the manifest itself
#
# Usage:
#   .github/scripts/generate-ax6-source-patchset.sh <source-root> <base-commit> <target-commit>
#
# Replaces manual manifest editing (P0-D.1 from corrective plan 2026-07-26).

if [ "$#" -ne 3 ]; then
    echo "usage: $0 <source-root> <base-commit> <target-commit>" >&2
    exit 64
fi

source_root="$1"
base_commit="$2"
target_commit="$3"

manifest="${GITHUB_WORKSPACE:-.}/.github/ax6-source-patchset.sha256"
absent="${GITHUB_WORKSPACE:-.}/.github/ax6-source-patchset.absent"

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

# Keep this in lockstep with verify-ax6-source-patchset.sh: provenance covers
# the complete base-to-target source diff, not every file below broad package
# directories. Rename sources are absent and rename destinations are present.
: > "$tmp_dir/present"
: > "$tmp_dir/absent"
for commit in "$base_commit" "$target_commit"; do
    git -C "$source_root" cat-file -e "$commit^{commit}" || {
        echo "ERROR: source commit is unavailable: $commit" >&2
        exit 2
    }
done
git -C "$source_root" diff --name-status -M "$base_commit" "$target_commit" \
    > "$tmp_dir/name-status"
awk -F '\t' -v present="$tmp_dir/present" -v absent_out="$tmp_dir/absent" '
    $1 == "D" { print $2 > absent_out; next }
    $1 ~ /^R/ { print $2 > absent_out; print $3 > present; next }
    $1 ~ /^C/ { print $3 > present; next }
    { print $2 > present }
' "$tmp_dir/name-status"

LC_ALL=C sort -u "$tmp_dir/present" > "$tmp_dir/present.sorted"
LC_ALL=C sort -u "$tmp_dir/absent" > "$absent"

: > "$manifest"
while IFS= read -r f || [ -n "$f" ]; do
    [ -n "$f" ] || continue
    case "$f" in
        *[[:space:]]*)
            echo "ERROR: whitespace in source paths is unsupported by SHA256 manifests: $f" >&2
            exit 2
            ;;
    esac
    [ -f "$source_root/$f" ] || {
        echo "ERROR: diff path is not a regular target file: $f" >&2
        exit 2
    }
    if command -v sha256sum >/dev/null 2>&1; then
        file_sha=$(sha256sum "$source_root/$f" | awk '{print $1}')
    elif command -v shasum >/dev/null 2>&1; then
        file_sha=$(shasum -a 256 "$source_root/$f" | awk '{print $1}')
    else
        echo "ERROR: no SHA256 implementation found" >&2
        exit 2
    fi
    printf '%s  %s\n' "$file_sha" "$f" >> "$manifest"
done < "$tmp_dir/present.sorted"

# ---- Compute manifest SHA256 ----
if command -v sha256sum >/dev/null 2>&1; then
    manifest_sha=$(sha256sum "$manifest" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
    manifest_sha=$(shasum -a 256 "$manifest" | awk '{print $1}')
else
    echo "ERROR: no SHA256 implementation found" >&2
    exit 2
fi

echo "SOURCE_PATCHSET_MANIFEST_SHA256=$manifest_sha"
echo "Present files: $(wc -l < "$manifest")"
echo "Absent files:  $(wc -l < "$absent")"

# Update the build lock with the new SHA256 if the lock file exists
lock="${GITHUB_WORKSPACE:-.}/.github/ax6-nss-lock.env"
if [ -f "$lock" ]; then
    if grep -q '^SOURCE_PATCHSET_MANIFEST_SHA256=' "$lock"; then
        sed -i.bak "s/^SOURCE_PATCHSET_MANIFEST_SHA256=.*/SOURCE_PATCHSET_MANIFEST_SHA256=${manifest_sha}/" "$lock"
        rm -f "${lock}.bak"
    else
        echo "SOURCE_PATCHSET_MANIFEST_SHA256=${manifest_sha}" >> "$lock"
    fi
    echo "Updated $lock"
fi
