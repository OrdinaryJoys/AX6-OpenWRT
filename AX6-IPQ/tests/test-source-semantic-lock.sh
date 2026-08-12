#!/bin/sh
#
# P0-5: cross-repo source semantic lock fixture.
#
# Verifies verify-ax6-source-semantics.sh against positive and negative
# scenarios using a scratch source tree, and that neither workflow
# hardcodes package release values.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
VERIFY=$REPO_ROOT/.github/scripts/verify-ax6-source-semantics.sh

PASS=0
FAIL=0

ok() { PASS=$((PASS + 1)); echo "PASS: $1"; }
bad() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

# ---------------------------------------------------------------------------
# Scratch source tree with three Makefiles
# ---------------------------------------------------------------------------
mk_tree() { # hostapd_release drv_release ecm_release [dup_flag]
    tree="$tmp/tree"
    rm -rf "$tree"
    mkdir -p "$tree/package/network/services/hostapd" \
             "$tree/package/qca-nss/qca-nss-drv" \
             "$tree/package/qca-nss/qca-nss-ecm"
    [ -n "$1" ] && echo "PKG_RELEASE:=$1" > "$tree/package/network/services/hostapd/Makefile"
    [ -n "$2" ] && echo "PKG_RELEASE:=$2" > "$tree/package/qca-nss/qca-nss-drv/Makefile"
    [ -n "$3" ] && echo "PKG_RELEASE:=$3" > "$tree/package/qca-nss/qca-nss-ecm/Makefile"
    if [ "${4:-}" = dup ]; then
        echo "PKG_RELEASE:=99" >> "$tree/package/qca-nss/qca-nss-ecm/Makefile"
    fi
}

mk_lock() { # hostapd drv ecm
    lock="$tmp/lock.env"
    {
        echo "SOURCE_HOSTAPD_PKG_RELEASE=$1"
        echo "SOURCE_QCA_NSS_DRV_PKG_RELEASE=$2"
        echo "SOURCE_QCA_NSS_ECM_PKG_RELEASE=$3"
    } > "$lock"
}

run_expect_fail() { # label
    label=$1; shift
    if "$@" > /dev/null 2>&1; then
        bad "$label (expected FAIL, got PASS)"
    else
        ok "$label"
    fi
}

# ---------------------------------------------------------------------------
# 1. 正场景: hostapd=2 drv=20 ecm=10 → PASS
# ---------------------------------------------------------------------------
mk_tree 2 20 10
mk_lock 2 20 10
"$VERIFY" "$tmp/tree" "$lock" > /dev/null 2>&1 \
    && ok "positive: hostapd=2 drv=20 ecm=10 matches lock" \
    || bad "positive: hostapd=2 drv=20 ecm=10 matches lock"

# ---------------------------------------------------------------------------
# 2. ECM 源码 10、lock 9 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 20 10
mk_lock 2 20 9
run_expect_fail "negative: ecm source=10 lock=9 fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 3. ECM release 缺失 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 20 ""
mk_lock 2 20 10
run_expect_fail "negative: missing ecm release fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 4. ECM release 重复定义 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 20 10 dup
mk_lock 2 20 10
run_expect_fail "negative: duplicated ecm release fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 5. release 非数字 / 0 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 abc 10
mk_lock 2 20 10
run_expect_fail "negative: non-numeric drv release fails" "$VERIFY" "$tmp/tree" "$lock"

mk_tree 2 0 10
mk_lock 2 20 10
run_expect_fail "negative: zero drv release fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 6. lock 缺失 release 变量 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 20 10
printf 'SOURCE_HOSTAPD_PKG_RELEASE=2\nSOURCE_QCA_NSS_DRV_PKG_RELEASE=20\n' > "$lock"
run_expect_fail "negative: lock missing ecm release fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 7. workflow 不再出现 release 硬编码 → 真实文件检查
# ---------------------------------------------------------------------------
for wf in build-AX6-NSS.yml lint.yml; do
    if grep -Eq "PKG_RELEASE:=[0-9]+|release must be [0-9]+" "$REPO_ROOT/.github/workflows/$wf"; then
        bad "$wf still hardcodes a package release"
    else
        ok "$wf has no hardcoded package release"
    fi
done
grep -Fq 'verify-ax6-source-semantics.sh' "$REPO_ROOT/.github/workflows/build-AX6-NSS.yml" \
    && ok "build workflow calls the shared semantic verifier" \
    || bad "build workflow calls the shared semantic verifier"

# ---------------------------------------------------------------------------
# 8. 验证器自身语法
# ---------------------------------------------------------------------------
sh -n "$VERIFY" && ok "verifier shell syntax" || bad "verifier shell syntax"

echo "=== summary: PASS=$PASS FAIL=$FAIL ==="
[ "$FAIL" -eq 0 ]
