#!/bin/sh

set -eu

GENERATOR=${GENERATOR:-.github/scripts/generate-ax6-source-patchset.sh}
VERIFIER=${VERIFIER:-.github/scripts/verify-ax6-source-patchset.sh}
GENERATOR=$(cd "$(dirname "$GENERATOR")" && pwd)/$(basename "$GENERATOR")
VERIFIER=$(cd "$(dirname "$VERIFIER")" && pwd)/$(basename "$VERIFIER")

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
source_repo="$tmp/source"
workspace="$tmp/workspace"
mkdir -p "$source_repo" "$workspace/.github"

git -C "$source_repo" init -q
git -C "$source_repo" config user.name fixture
git -C "$source_repo" config user.email fixture@example.invalid

printf 'base\n' > "$source_repo/modified"
printf 'delete\n' > "$source_repo/deleted"
printf 'rename\n' > "$source_repo/rename-old"
printf 'unchanged\n' > "$source_repo/unchanged"
git -C "$source_repo" add .
git -C "$source_repo" commit -qm base
base=$(git -C "$source_repo" rev-parse HEAD)

printf 'changed\n' > "$source_repo/modified"
printf 'new\n' > "$source_repo/added"
git -C "$source_repo" rm -q deleted
git -C "$source_repo" mv rename-old rename-new
git -C "$source_repo" add .
git -C "$source_repo" commit -qm target
target=$(git -C "$source_repo" rev-parse HEAD)

cat > "$workspace/.github/ax6-nss-lock.env" <<'EOF'
SOURCE_PATCHSET_MANIFEST_SHA256=placeholder
EOF

GITHUB_WORKSPACE="$workspace" \
    "$GENERATOR" "$source_repo" "$base" "$target" >/dev/null

manifest="$workspace/.github/ax6-source-patchset.sha256"
absent="$workspace/.github/ax6-source-patchset.absent"
manifest_sha=$(sed -n 's/^SOURCE_PATCHSET_MANIFEST_SHA256=//p' \
    "$workspace/.github/ax6-nss-lock.env")

expected_present='added
modified
rename-new'
actual_present=$(awk '{print $2}' "$manifest")
[ "$actual_present" = "$expected_present" ] || {
    echo "FAIL: generated present set is incorrect" >&2
    printf '%s\n' "$actual_present" >&2
    exit 1
}

expected_absent='deleted
rename-old'
actual_absent=$(cat "$absent")
[ "$actual_absent" = "$expected_absent" ] || {
    echo "FAIL: generated absent set is incorrect" >&2
    printf '%s\n' "$actual_absent" >&2
    exit 1
}

# Deliberately use relative manifest paths to verify path normalization.
(
    cd "$workspace"
    "$VERIFIER" "$source_repo" \
        .github/ax6-source-patchset.sha256 \
        .github/ax6-source-patchset.absent \
        "$manifest_sha" "$base" >/dev/null
)

# An unavailable lock commit must fail before replacing a valid manifest.
before=$(sha256sum \
    "$manifest" "$absent" "$workspace/.github/ax6-nss-lock.env")
if GITHUB_WORKSPACE="$workspace" \
    "$GENERATOR" "$source_repo" "$base" deadbeef >/dev/null 2>&1; then
    echo "FAIL: generator accepted an unavailable target commit" >&2
    exit 1
fi
after=$(sha256sum \
    "$manifest" "$absent" "$workspace/.github/ax6-nss-lock.env")
[ "$before" = "$after" ] || {
    echo "FAIL: failed generation replaced a valid manifest or lock" >&2
    exit 1
}

echo "test-source-patchset-generator: PASS"
