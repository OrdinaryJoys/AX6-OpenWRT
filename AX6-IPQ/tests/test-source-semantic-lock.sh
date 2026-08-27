#!/bin/sh
#
# P0-5: cross-repo source semantic lock fixture.
#
# Verifies verify-ax6-source-semantics.sh against positive and negative
# scenarios using a scratch source tree, and that neither workflow
# hardcodes package release values.
set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/../.." && pwd)
VERIFY=$REPO_ROOT/.github/scripts/verify-ax6-source-semantics.sh

PASS=0
FAIL=0

ok() { PASS=$((PASS + 1)); echo "PASS: $1"; }
bad() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

# ---------------------------------------------------------------------------
# Scratch source tree with six Makefiles and the ath11k backport markers
# ---------------------------------------------------------------------------
mk_tree() { # hostapd_release drv_release ecm_release clients_release mcs_release [mac80211_release] [dup_flag]
    tree="$tmp/tree"
    rm -rf "$tree"
    mkdir -p "$tree/package/kernel/mac80211/patches/ath11k" \
             "$tree/package/network/services/hostapd" \
             "$tree/package/qca-nss/qca-nss-drv" \
             "$tree/package/qca-nss/qca-nss-ecm" \
             "$tree/package/qca-nss/qca-nss-clients" \
             "$tree/package/qca-nss/qca-mcs"
    echo "PKG_RELEASE:=${6:-4}" > "$tree/package/kernel/mac80211/Makefile"
    printf '%s\n' \
        'From 7a246c72132eb943b5844ba79dad597b47429dba Mon Sep 17 00:00:00 2001' \
        'kcalloc(svc_rdy_ext->tot_phy_id,' \
        'sizeof(*svc_rdy_ext->mac_phy_caps), GFP_ATOMIC)' \
        > "$tree/package/kernel/mac80211/patches/ath11k/102-wifi-ath11k-fix-stride-mismatch-in-mac_phy_caps_parse.patch"
    [ -n "$1" ] && echo "PKG_RELEASE:=$1" > "$tree/package/network/services/hostapd/Makefile"
    [ -n "$2" ] && echo "PKG_RELEASE:=$2" > "$tree/package/qca-nss/qca-nss-drv/Makefile"
    [ -n "$3" ] && echo "PKG_RELEASE:=$3" > "$tree/package/qca-nss/qca-nss-ecm/Makefile"
    [ -n "$4" ] && echo "PKG_RELEASE:=$4" > "$tree/package/qca-nss/qca-nss-clients/Makefile"
    [ -n "$5" ] && echo "PKG_RELEASE:=$5" > "$tree/package/qca-nss/qca-mcs/Makefile"
    if [ "${7:-}" = dup ]; then
        echo "PKG_RELEASE:=99" >> "$tree/package/qca-nss/qca-nss-ecm/Makefile"
    fi
}

mk_lock() { # hostapd drv ecm clients mcs [mac80211]
    lock="$tmp/lock.env"
    {
        echo "SOURCE_MAC80211_PKG_RELEASE=${6:-4}"
        echo "SOURCE_HOSTAPD_PKG_RELEASE=$1"
        echo "SOURCE_QCA_NSS_DRV_PKG_RELEASE=$2"
        echo "SOURCE_QCA_NSS_ECM_PKG_RELEASE=$3"
        echo "SOURCE_QCA_NSS_CLIENTS_PKG_RELEASE=$4"
        echo "SOURCE_QCA_MCS_PKG_RELEASE=$5"
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
# 1. 正场景: hostapd=2 drv=20 ecm=10 clients=14 mcs=3 → PASS
# ---------------------------------------------------------------------------
mk_tree 2 20 10 14 3
mk_lock 2 20 10 14 3
if "$VERIFY" "$tmp/tree" "$lock" > /dev/null 2>&1; then
    ok "positive: hostapd=2 drv=20 ecm=10 clients=14 mcs=3 matches lock"
else
    bad "positive: hostapd=2 drv=20 ecm=10 clients=14 mcs=3 matches lock"
fi

# ---------------------------------------------------------------------------
# 2. ECM 源码 10、lock 9 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 20 10 14 3
mk_lock 2 20 9 14 3
run_expect_fail "negative: ecm source=10 lock=9 fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 3. ECM release 缺失 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 20 "" 14 3
mk_lock 2 20 10 14 3
run_expect_fail "negative: missing ecm release fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 4. ECM release 重复定义 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 20 10 14 3 4 dup
mk_lock 2 20 10 14 3
run_expect_fail "negative: duplicated ecm release fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 5. release 非数字 / 0 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 abc 10 14 3
mk_lock 2 20 10 14 3
run_expect_fail "negative: non-numeric drv release fails" "$VERIFY" "$tmp/tree" "$lock"

mk_tree 2 0 10 14 3
mk_lock 2 20 10 14 3
run_expect_fail "negative: zero drv release fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 6. lock 缺失 release 变量 → FAIL
# ---------------------------------------------------------------------------
mk_tree 2 20 10 14 3
printf '%s\n' \
    'SOURCE_MAC80211_PKG_RELEASE=4' \
    'SOURCE_HOSTAPD_PKG_RELEASE=2' \
    'SOURCE_QCA_NSS_DRV_PKG_RELEASE=20' > "$lock"
run_expect_fail "negative: lock missing ecm release fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 7. clients 版本倒退或 lock 缺失必须失败
# ---------------------------------------------------------------------------
mk_tree 2 20 10 14 3
mk_lock 2 20 10 13 3
run_expect_fail "negative: clients source=14 lock=13 fails" "$VERIFY" "$tmp/tree" "$lock"

mk_tree 2 20 10 14 3
mk_lock 2 20 10 "" 3
run_expect_fail "negative: lock missing clients release fails" "$VERIFY" "$tmp/tree" "$lock"

mk_tree 2 20 10 14 3
mk_lock 2 20 10 14 2
run_expect_fail "negative: mcs source=3 lock=2 fails" "$VERIFY" "$tmp/tree" "$lock"

mk_tree 2 20 10 14 3
mk_lock 2 20 10 14 ""
run_expect_fail "negative: lock missing mcs release fails" "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 8. mac80211 release and Linux 6.18 API compatibility must match
# ---------------------------------------------------------------------------
mk_tree 2 20 10 14 3 4
mk_lock 2 20 10 14 3 3
run_expect_fail "negative: mac80211 source=4 lock=3 fails" "$VERIFY" "$tmp/tree" "$lock"

mk_tree 2 20 10 14 3
mk_lock 2 20 10 14 3
echo '+ kzalloc_objs(*svc_rdy_ext->mac_phy_caps, count, GFP_ATOMIC)' \
    >> "$tmp/tree/package/kernel/mac80211/patches/ath11k/102-wifi-ath11k-fix-stride-mismatch-in-mac_phy_caps_parse.patch"
run_expect_fail "negative: Linux 6.18-incompatible kzalloc_objs backport fails" \
    "$VERIFY" "$tmp/tree" "$lock"

# ---------------------------------------------------------------------------
# 9. workflow 不再出现 release 硬编码 → 真实文件检查
# ---------------------------------------------------------------------------
for wf in build-AX6-NSS.yml lint.yml; do
    if grep -Eq "PKG_RELEASE:=[0-9]+|release must be [0-9]+" "$REPO_ROOT/.github/workflows/$wf"; then
        bad "$wf still hardcodes a package release"
    else
        ok "$wf has no hardcoded package release"
    fi
done
if grep -Fq 'verify-ax6-source-semantics.sh' \
    "$REPO_ROOT/.github/workflows/build-AX6-NSS.yml"; then
    ok "build workflow calls the shared semantic verifier"
else
    bad "build workflow calls the shared semantic verifier"
fi
if grep -Fq 'tests/test-qca-mcs-log-level.sh' \
    "$REPO_ROOT/.github/workflows/build-AX6-NSS.yml"; then
    ok "build workflow runs the qca-mcs source gate"
else
    bad "build workflow runs the qca-mcs source gate"
fi
for name in \
    SOURCE_MAC80211_PKG_RELEASE SOURCE_HOSTAPD_PKG_RELEASE SOURCE_QCA_NSS_DRV_PKG_RELEASE \
    SOURCE_QCA_NSS_ECM_PKG_RELEASE SOURCE_QCA_NSS_CLIENTS_PKG_RELEASE \
    SOURCE_QCA_MCS_PKG_RELEASE; do
    if grep -Fq "echo \"$name=\$$name\"" \
        "$REPO_ROOT/.github/workflows/build-AX6-NSS.yml"; then
        ok "artifact BUILD-LOCK records $name"
    else
        bad "artifact BUILD-LOCK records $name"
    fi
done

# ---------------------------------------------------------------------------
# 10. 验证器自身语法
# ---------------------------------------------------------------------------
if sh -n "$VERIFY"; then
    ok "verifier shell syntax"
else
    bad "verifier shell syntax"
fi

echo "=== summary: PASS=$PASS FAIL=$FAIL ==="
[ "$FAIL" -eq 0 ]
