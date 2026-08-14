#!/bin/sh
#
# AX6 cross-repo source semantic verifier (P0-2).
#
# Compares the five package PKG_RELEASE values declared in the build
# lock against the single authoritative PKG_RELEASE in the locked
# source tree.  A drift here previously failed the CI gate only after
# the source clone step (ECM release 9 vs 10), so the expected values
# must come from the lock, not from hardcoded workflow strings.
#
# Usage: verify-ax6-source-semantics.sh <source-root> <lock-file>
#
# Behavior:
#   1. Reads SOURCE_HOSTAPD_PKG_RELEASE / SOURCE_QCA_NSS_DRV_PKG_RELEASE /
#      SOURCE_QCA_NSS_ECM_PKG_RELEASE / SOURCE_QCA_NSS_CLIENTS_PKG_RELEASE /
#      SOURCE_QCA_MCS_PKG_RELEASE
#      from the lock (must be positive ints).
#   2. Reads the single authoritative PKG_RELEASE:=N from each Makefile.
#   3. Missing, duplicated, non-numeric or mismatched values fail with a
#      per-component message.  Never modifies source or lock.
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: $0 <source-root> <lock-file>" >&2
    exit 64
fi

source_root="$1"
lock_file="$2"

# ---------------------------------------------------------------------------
# Lock values
# ---------------------------------------------------------------------------
lock_var() { # name
    name="$1"
    value=$(sed -n "s/^$name=//p" "$lock_file" | tail -1)
    if [ -z "$value" ]; then
        echo "FAIL: $name is missing from $(basename "$lock_file")" >&2
        exit 1
    fi
    case "$value" in
        ''|*[!0-9]*) echo "FAIL: $name must be a positive integer (got '$value')" >&2; exit 1 ;;
        0) echo "FAIL: $name must be a positive integer (got '0')" >&2; exit 1 ;;
    esac
    echo "$value"
}

# ---------------------------------------------------------------------------
# Source Makefile values
# ---------------------------------------------------------------------------
src_release() { # makefile label
    mk="$1"
    [ -f "$mk" ] || { echo "FAIL: source Makefile missing: $mk" >&2; exit 1; }
    count=$(grep -c '^PKG_RELEASE:=' "$mk")
    if [ "$count" -ne 1 ]; then
        echo "FAIL: $mk must define PKG_RELEASE exactly once (got $count)" >&2
        exit 1
    fi
    value=$(sed -n 's/^PKG_RELEASE:=//p' "$mk")
    case "$value" in
        ''|*[!0-9]*) echo "FAIL: $mk PKG_RELEASE must be numeric (got '$value')" >&2; exit 1 ;;
        0) echo "FAIL: $mk PKG_RELEASE must be positive (got '0')" >&2; exit 1 ;;
    esac
    echo "$value"
}

# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------
FAIL=0
compare() { # label lock_var src_mk
    label=$1; expected=$2; actual=$3
    if [ "$expected" != "$actual" ]; then
        echo "FAIL: $label mismatch: lock=$expected source=$actual" >&2
        FAIL=1
    else
        echo "OK: $label release=$actual"
    fi
}

exp_hostapd=$(lock_var SOURCE_HOSTAPD_PKG_RELEASE)
exp_drv=$(lock_var SOURCE_QCA_NSS_DRV_PKG_RELEASE)
exp_ecm=$(lock_var SOURCE_QCA_NSS_ECM_PKG_RELEASE)
exp_clients=$(lock_var SOURCE_QCA_NSS_CLIENTS_PKG_RELEASE)
exp_mcs=$(lock_var SOURCE_QCA_MCS_PKG_RELEASE)

compare hostapd "$exp_hostapd" \
    "$(src_release "$source_root/package/network/services/hostapd/Makefile")"
compare qca-nss-drv "$exp_drv" \
    "$(src_release "$source_root/package/qca-nss/qca-nss-drv/Makefile")"
compare qca-nss-ecm "$exp_ecm" \
    "$(src_release "$source_root/package/qca-nss/qca-nss-ecm/Makefile")"
compare qca-nss-clients "$exp_clients" \
    "$(src_release "$source_root/package/qca-nss/qca-nss-clients/Makefile")"
compare qca-mcs "$exp_mcs" \
    "$(src_release "$source_root/package/qca-nss/qca-mcs/Makefile")"

if [ "$FAIL" -ne 0 ]; then
    echo "AX6 source semantics: FAIL (see per-component messages above)" >&2
    exit 1
fi
echo "AX6 source semantics: PASS (hostapd=$exp_hostapd drv=$exp_drv ecm=$exp_ecm clients=$exp_clients mcs=$exp_mcs)"
