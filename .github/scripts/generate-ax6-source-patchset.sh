#!/bin/sh
set -eu
#
# Generate AX6 source patchset provenance manifest.
#
# Compares SOURCE_COMMIT against SOURCE_BASE_COMMIT and produces:
#   1. ax6-source-patchset.sha256 — SHA256 of every tracked NSS-critical file
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

# ---- File patterns that constitute the NSS-critical patchset ----
# These match the set curated in the existing manifest.
PATTERNS="
    package/kernel/mac80211/patches/
    package/kernel/mac80211/files/
    package/libs/libubox/
    package/network/config/netifd/
    package/network/config/wifi-scripts/
    package/network/services/hostapd/
    package/qca-nss/
    package/system/ubus/
    target/linux/airoha/patches-6.18/
    target/linux/armsr/
    target/linux/generic/
    target/linux/ipq40xx/patches-6.18/
    target/linux/mediatek/patches-6.18/
    target/linux/qualcommax/
    target/linux/rockchip/
    target/linux/starfive/patches-6.18/
"

# ---- Generate present manifest (SHA256 of each tracked file) ----
> "$manifest"
for pattern in $PATTERNS; do
    # List files under this pattern at the target commit
    git -C "$source_root" ls-tree -r --name-only "$target_commit" -- "$pattern" 2>/dev/null | while IFS= read -r f; do
        # Only regular files that exist
        [ -f "$source_root/$f" ] || continue
        sha256sum "$source_root/$f" | awk '{print $1 "  " $2}' >> "$manifest"
    done
done

# Sort for deterministic output
sort -t' ' -k3 "$manifest" -o "$manifest"

# ---- Generate absent list (deleted since base commit) ----
> "$absent"
for pattern in $PATTERNS; do
    # Find files that existed at base but not at target
    git -C "$source_root" diff --name-only --diff-filter=D "$base_commit".."$target_commit" -- "$pattern" 2>/dev/null >> "$absent"
done

sort "$absent" -o "$absent"

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
