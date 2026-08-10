#!/usr/bin/env bash
# Temporary, reboot-safe NSS frequency A/B helper for IPQ8074.
# It never writes UCI and defaults to the read-only status command.

set -euo pipefail

ACTION="${1:-status}"
LEVEL="${2:-}"
CONFIRMED=0
for arg in "$@"; do
    [ "$arg" = "--confirm-runtime-write" ] && CONFIRMED=1
done

ROUTER_IP="${AX6_ROUTER_IP:-192.168.5.1}"
SSH_KEY="${AX6_SSH_KEY:-${HOME}/.ssh/ax6_check}"
EXPECTED_SOURCE_REVISION="${AX6_EXPECTED_SOURCE_REVISION:-}"
BUILD_COMMIT="${AX6_BUILD_COMMIT:-}"
STATE_FILE="${AX6_FREQ_STATE_FILE:-$PWD/.ax6-nss-frequency-ab.state}"
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10 -i "$SSH_KEY" "root@$ROUTER_IP")

die() {
    echo "ax6-nss-frequency-ab: $*" >&2
    exit 2
}

router_cmd() {
    "${SSH[@]}" "$@"
}

router_revision() {
    router_cmd ". /etc/openwrt_release; printf '%s\\n' \"\$DISTRIB_REVISION\""
}

status() {
    router_cmd '
        printf "compatible="
        tr "\000" " " < /proc/device-tree/compatible
        echo
        echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
        echo "auto_scale=$(cat /proc/sys/dev/nss/clock/auto_scale 2>/dev/null || echo unavailable)"
        echo "current_freq=$(cat /proc/sys/dev/nss/clock/current_freq 2>/dev/null || echo unavailable)"
    '
}

require_test_identity() {
    local revision
    [ -n "$EXPECTED_SOURCE_REVISION" ] ||
        die "set AX6_EXPECTED_SOURCE_REVISION before a runtime write"
    [ -n "$BUILD_COMMIT" ] ||
        die "set AX6_BUILD_COMMIT before a runtime write"
    [[ "$BUILD_COMMIT" =~ ^[0-9a-f]{7,40}$ ]] ||
        die "AX6_BUILD_COMMIT must be a Git commit ID"
    revision=$(router_revision)
    [ "$revision" = "$EXPECTED_SOURCE_REVISION" ] ||
        die "router revision $revision does not match $EXPECTED_SOURCE_REVISION"
    router_cmd "nss-check -q && ax6-config-audit -q" ||
        die "router health gates must pass before a frequency test"
}

set_level() {
    local target previous boot revision
    [ "$CONFIRMED" -eq 1 ] ||
        die "set requires --confirm-runtime-write"
    case "$LEVEL" in
        mid) target=748800000 ;;
        high) target=1689600000 ;;
        *) die "usage: $0 set {mid|high} --confirm-runtime-write" ;;
    esac
    require_test_identity

    boot=$(router_cmd "cat /proc/sys/kernel/random/boot_id")
    revision=$(router_revision)
    previous=$(router_cmd '
        grep -q "qcom,ipq8074" /proc/device-tree/compatible || exit 20
        [ "$(cat /proc/sys/dev/nss/clock/auto_scale)" = 0 ] || exit 21
        cat /proc/sys/dev/nss/clock/current_freq
    ') || die "router is not an IPQ8074 fixed-frequency NSS test baseline"

    umask 077
    {
        echo "boot_id=$boot"
        echo "source_revision=$revision"
        echo "build_repo_commit=$BUILD_COMMIT"
        echo "previous_freq=$previous"
        echo "target_freq=$target"
        echo "applied=0"
    } > "$STATE_FILE"

    if ! router_cmd "
        set -eu
        grep -q 'qcom,ipq8074' /proc/device-tree/compatible
        [ \"\$(cat /proc/sys/dev/nss/clock/auto_scale)\" = 0 ]
        printf '%s\\n' '$target' > /proc/sys/dev/nss/clock/current_freq
        [ \"\$(cat /proc/sys/dev/nss/clock/current_freq)\" = '$target' ]
        nss-check -q
        ax6-config-audit -q
    "; then
        router_cmd "printf '%s\\n' '$previous' > /proc/sys/dev/nss/clock/current_freq" || true
        die "temporary NSS frequency write or post-write health gate failed; restore attempted"
    fi
    echo "applied=1" >> "$STATE_FILE"
    echo "temporary_level=$LEVEL previous_freq=$previous target_freq=$target"
    status
}

state_value() {
    local key="$1"
    sed -n "s/^${key}=//p" "$STATE_FILE" | tail -n 1
}

restore() {
    local state_boot current_boot previous applied state_revision state_build
    [ "$CONFIRMED" -eq 1 ] ||
        die "restore requires --confirm-runtime-write"
    [ -r "$STATE_FILE" ] || die "state file is missing: $STATE_FILE"
    require_test_identity
    applied=$(state_value applied)
    [ "$applied" = 1 ] || die "state file does not record a completed write"
    state_boot=$(state_value boot_id)
    state_revision=$(state_value source_revision)
    state_build=$(state_value build_repo_commit)
    previous=$(state_value previous_freq)
    [ "$state_revision" = "$EXPECTED_SOURCE_REVISION" ] ||
        die "state source revision does not match the requested test identity"
    [ "$state_build" = "$BUILD_COMMIT" ] ||
        die "state build commit does not match the requested test identity"
    current_boot=$(router_cmd "cat /proc/sys/kernel/random/boot_id")
    [ "$state_boot" = "$current_boot" ] ||
        die "router rebooted; do not restore a value from the previous boot"
    [[ "$previous" =~ ^[0-9]+$ ]] || die "invalid previous frequency in state file"

    router_cmd "
        set -eu
        [ \"\$(cat /proc/sys/dev/nss/clock/auto_scale)\" = 0 ]
        printf '%s\\n' '$previous' > /proc/sys/dev/nss/clock/current_freq
        [ \"\$(cat /proc/sys/dev/nss/clock/current_freq)\" = '$previous' ]
        nss-check -q
        ax6-config-audit -q
    " || die "failed to restore the previous NSS frequency"
    echo "restored_freq=$previous"
    status
}

case "$ACTION" in
    status) status ;;
    set) set_level ;;
    restore) restore ;;
    *) die "usage: $0 {status|set mid|set high|restore} [--confirm-runtime-write]" ;;
esac
