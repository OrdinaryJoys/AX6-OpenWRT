#!/bin/sh
# Sent over strict SSH by the host tool; never installed in the router rootfs.
set -eu
umask 077
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH LC_ALL=C

ACTION=$1
TOKEN=$2
PAYLOAD_SHA=$3
INIT_SHA=$4
CORE_SHA=$5
ENABLED=$6
PAYLOAD_KB=$7
WORK=/etc/.ax6-openclash-restore
ROOTS='etc/config/openclash etc/openclash/config etc/openclash/custom etc/openclash/overwrite'

fail() { printf 'restore remote: %s\n' "$*" >&2; exit 2; }
hash() {
    value=$(sha256sum "$1") || return 1
    printf '%s\n' "${value%% *}"
}
phase() {
    printf '%s\n' "$1" > "$WORK/phase.new" && mv "$WORK/phase.new" "$WORK/phase"
}
owned() {
    [ -d "$WORK" ] && [ ! -L "$WORK" ] || fail 'transaction is missing'
    [ "$(cat "$WORK/token")" = "$TOKEN" ] || fail 'transaction ownership mismatch'
    [ "$(cat /proc/sys/kernel/random/boot_id)" = "$(cat "$WORK/boot")" ] || fail 'boot changed; manual recovery required'
}
unrelated_cron() {
    # Only the upstream's explicit owned markers may be regenerated.
    sed '/#openclash-cron-task/d; /#openclash-overwrite-download/d' "$1"
}
check_paths() {
    for path in /etc /etc/config /etc/openclash; do
        [ -d "$path" ] && [ ! -L "$path" ] || return 1
    done
    [ -s /etc/config/openclash ] && [ ! -L /etc/config/openclash ] || return 1
    for relative in $ROOTS; do
        [ ! -L "/$relative" ] || return 1
        case "$relative" in
            etc/config/openclash) [ -f "/$relative" ] || return 1 ;;
            *) [ ! -e "/$relative" ] || [ -d "/$relative" ] || return 1 ;;
        esac
        if [ -e "/$relative" ]; then
            bad=$(find "/$relative" ! -type d ! -type f -print) || return 1
            [ -z "$bad" ] || return 1
        fi
    done
}
rom_contract() {
    for path in /etc/init.d/openclash /sbin/ax6-config-audit \
        /usr/sbin/ax6-openclash-dns-health /usr/sbin/ax6-openclash-fw-health \
        /usr/libexec/ax6-openclash-lan-scope /usr/libexec/ax6-openclash-fw-check.uc; do
        [ -f "$path" ] && [ ! -L "$path" ] && [ -r "/rom$path" ] && [ ! -L "/rom$path" ] || return 1
        cmp -s "$path" "/rom$path" || return 1
    done
    for path in /etc/init.d/openclash /sbin/ax6-config-audit \
        /usr/sbin/ax6-openclash-dns-health /usr/sbin/ax6-openclash-fw-health \
        /usr/libexec/ax6-openclash-lan-scope; do
        [ -x "$path" ] || return 1
    done
    [ "$(hash /etc/init.d/openclash)" = "$INIT_SHA" ] || return 1
    [ "$(hash /rom/etc/openclash/core/clash_meta)" = "$CORE_SHA" ] || return 1
    [ ! -e /overlay/upper/etc/openclash/core/clash_meta ] || return 1
    sh -n /etc/init.d/openclash || return 1
    for marker in 'AX6 proxy ingress scope v1 begin' 'AX6 DNS ingress scope v1 begin' \
        'AX6 R-11 v2' 'avoid copying the immutable ROM core' 'ax6-openclash-zerotier-bypass'; do
        grep -Fq "$marker" /etc/init.d/openclash || return 1
    done
    printf '%s\n' /etc/openclash/config/ /etc/openclash/custom/ /etc/openclash/overwrite/ \
        > "$WORK/expected-keep"
    cmp -s "$WORK/expected-keep" /lib/upgrade/keep.d/luci-app-openclash || return 1
}
contract() {
    rom_contract && check_paths || return 1
    changes=$(uci -q changes openclash) || return 1
    [ -z "$changes" ]
}
capture_tree() {
    output=$1
    set --
    for relative in $ROOTS; do
        [ ! -e "/$relative" ] || set -- "$@" "$relative"
    done
    [ "$#" -gt 0 ] || return 1
    tar -cf "$output" -C / "$@"
}
prepare() {
    [ ! -e "$WORK" ] && [ ! -L "$WORK" ] || fail 'unfinished transaction exists; do not overwrite it'
    # Atomic mkdir is also the transaction lock; an abandoned lock is never stolen.
    mkdir -m 0700 "$WORK" || fail 'cannot acquire transaction directory'
    printf '%s\n' "$TOKEN" > "$WORK/token" || return 1
    cat /proc/sys/kernel/random/boot_id > "$WORK/boot" || return 1
    phase PREPARING || return 1
    contract || fail 'ROM/init/keep/config contract not verified; no restore'
    [ -f /etc/crontabs/root ] && [ ! -L /etc/crontabs/root ] || return 1
    cp /etc/crontabs/root "$WORK/crontab.before" || return 1
    unrelated_cron "$WORK/crontab.before" > "$WORK/cron.unrelated" || return 1
    original=$(uci -q get openclash.config.enable) || return 1
    case "$original" in 0|1) ;; *) return 1 ;; esac
    printf '%s\n' "$original" > "$WORK/enabled.before" || return 1
    if [ "$original" = 1 ]; then
        pidof clash >/dev/null 2>&1 || return 1
    else
        if pidof clash >/dev/null 2>&1; then return 1; fi
    fi
    # Bound overlay consumption before receiving or creating archives.
    disk=$(df -Pk /etc) || return 1
    available=$(printf '%s\n' "$disk" | awk 'END {print $4}') || return 1
    case "$available" in ''|*[!0-9]*) return 1 ;; esac
    set --
    for relative in $ROOTS; do
        [ ! -e "/$relative" ] || set -- "$@" "/$relative"
    done
    sizes=$(du -sk "$@") || return 1
    old_kb=$(printf '%s\n' "$sizes" | awk '{sum += $1} END {print sum}') || return 1
    case "$old_kb" in ''|*[!0-9]*) return 1 ;; esac
    required=$((4096 + PAYLOAD_KB * 4 + old_kb * 3))
    [ "$available" -ge "$required" ] || fail 'insufficient space for staging and rollback; no restore'
    cat > "$WORK/payload.tar.gz" || return 1
    [ "$(hash "$WORK/payload.tar.gz")" = "$PAYLOAD_SHA" ] || return 1
    gzip -t "$WORK/payload.tar.gz" || return 1
    mkdir "$WORK/new" "$WORK/old" "$WORK/failed" || return 1
    tar -xzf "$WORK/payload.tar.gz" -C "$WORK/new" || return 1
    staged=$(uci -c "$WORK/new/etc/config" -q get openclash.config.enable) || return 1
    [ "$staged" = "$ENABLED" ] || return 1
    capture_tree "$WORK/before.tar" || return 1
    gzip -c "$WORK/before.tar" > "$WORK/rollback.tar.gz" || return 1
    gzip -t "$WORK/rollback.tar.gz" || return 1
    hash "$WORK/before.tar" > "$WORK/before.sha" || return 1
    hash "$WORK/rollback.tar.gz" > "$WORK/rollback.sha" || return 1
    for relative in $ROOTS; do
        tar -cf "$WORK/root.tar" -C "$WORK/new" "$relative" || return 1
        hash "$WORK/root.tar" > "$WORK/new-$(basename "$relative").sha" || return 1
    done
    phase PREPARED
}
same_tree() {
    capture_tree "$WORK/current.tar" || return 1
    [ "$(hash "$WORK/current.tar")" = "$(cat "$WORK/before.sha")" ]
}
same_unrelated_cron() {
    unrelated_cron /etc/crontabs/root > "$WORK/cron.current" || return 1
    cmp -s "$WORK/cron.current" "$WORK/cron.unrelated"
}
disabled_snapshots() {
    nft -j list table inet fw4 > "$WORK/disabled-nft.json" || return 1
    ip -j -4 rule show > "$WORK/disabled-rule4.json" || return 1
    ip -j -6 rule show > "$WORK/disabled-rule6.json" || return 1
    ip -j -4 route show table all > "$WORK/disabled-route4.json" || return 1
    ip -j -6 route show table all > "$WORK/disabled-route6.json"
}
commit() {
    [ "$(cat "$WORK/phase")" = PREPARED ] || return 1
    contract && same_tree && same_unrelated_cron || return 1
    [ "$(hash "$WORK/rollback.tar.gz")" = "$(cat "$WORK/rollback.sha")" ] || return 1
    phase STOPPING || return 1
    /etc/init.d/openclash stop || return 1
    if pidof clash >/dev/null 2>&1; then return 1; fi
    # A stop hook or another writer changing data invalidates the captured rollback.
    same_tree && same_unrelated_cron || return 1
    phase APPLYING || return 1
    for relative in $ROOTS; do
        mkdir -p "$WORK/old/$(dirname "$relative")" "$WORK/failed/$(dirname "$relative")" || return 1
        if [ -e "/$relative" ]; then
            mv "/$relative" "$WORK/old/$relative" || return 1
        fi
        mv "$WORK/new/$relative" "/$relative" || return 1
    done
    # Commit failure is never hidden by a later successful start command.
    uci -q commit openclash || return 1
    if [ "$ENABLED" = 1 ]; then
        /etc/init.d/openclash start || return 1
    fi
    phase APPLIED
}
verify() {
    [ "$(cat "$WORK/phase")" = APPLIED ] || return 1
    contract && same_unrelated_cron || return 1
    current=$(uci -q get openclash.config.enable) || return 1
    [ "$current" = "$ENABLED" ] || return 1
    if [ "$ENABLED" = 1 ]; then
        ready=0
        # shellcheck disable=SC2034 # A fixed attempt count, not an elapsed-time claim.
        for retry in 1 2 3 4 5; do
            if pidof clash >/dev/null 2>&1 &&
                timeout 10 /usr/sbin/ax6-openclash-dns-health --probe &&
                timeout 10 /usr/sbin/ax6-openclash-fw-health --probe; then
                ready=1
                break
            fi
            sleep 2
        done
        [ "$ready" = 1 ] || return 1
    else
        if pidof clash >/dev/null 2>&1; then return 1; fi
        # Host parses these complete JSON snapshots; rc=3 alone is insufficient.
        disabled_snapshots || return 1
    fi
    /sbin/ax6-config-audit -q || return 1
    phase VERIFIED
}
rollback() {
    current_phase=$(cat "$WORK/phase") || return 1
    case "$current_phase" in STOPPING|APPLYING|APPLIED|VERIFIED) ;; *) return 1 ;; esac
    rom_contract && same_unrelated_cron || return 1
    if pidof clash >/dev/null 2>&1; then
        /etc/init.d/openclash stop || return 1
    fi
    if pidof clash >/dev/null 2>&1; then return 1; fi
    # Refuse to overwrite another writer's replacement, retaining all evidence.
    for relative in $ROOTS; do
        if [ ! -e "$WORK/new/$relative" ] && [ -e "/$relative" ]; then
            tar -cf "$WORK/root.tar" -C / "$relative" || return 1
            [ "$(hash "$WORK/root.tar")" = "$(cat "$WORK/new-$(basename "$relative").sha")" ] || return 1
        elif [ -e "$WORK/old/$relative" ] && [ -e "/$relative" ]; then
            return 1
        fi
    done
    for relative in $ROOTS; do
        if [ ! -e "$WORK/new/$relative" ]; then
            if [ -e "/$relative" ]; then
                mv "/$relative" "$WORK/failed/$relative" || return 1
            fi
        fi
        if [ -e "$WORK/old/$relative" ]; then
            mv "$WORK/old/$relative" "/$relative" || return 1
        fi
    done
    same_tree || return 1
    # Only restore the original cron if unrelated rows have not changed.
    same_unrelated_cron || return 1
    crontab "$WORK/crontab.before" || return 1
    original=$(cat "$WORK/enabled.before") || return 1
    if [ "$original" = 1 ]; then
        /etc/init.d/openclash start || return 1
        timeout 10 /usr/sbin/ax6-openclash-dns-health --probe || return 1
        timeout 10 /usr/sbin/ax6-openclash-fw-health --probe || return 1
    else
        if pidof clash >/dev/null 2>&1; then return 1; fi
        disabled_snapshots || return 1
    fi
    /sbin/ax6-config-audit -q && same_unrelated_cron || return 1
    phase ROLLED_BACK
}

case "$TOKEN" in ''|*[!a-f0-9]*) fail 'invalid transaction token' ;; esac
[ "${#TOKEN}" = 32 ] || fail 'invalid transaction token length'
for checksum in "$PAYLOAD_SHA" "$INIT_SHA" "$CORE_SHA"; do
    case "$checksum" in ''|*[!a-f0-9]*) fail 'invalid digest' ;; esac
    [ "${#checksum}" = 64 ] || fail 'invalid digest length'
done
case "$ENABLED" in 0|1) ;; *) fail 'invalid enable state' ;; esac
case "$PAYLOAD_KB" in ''|*[!0-9]*) fail 'invalid payload size' ;; esac
[ "$PAYLOAD_KB" -le 131072 ] || fail 'payload size exceeds bound'
case "$ACTION" in
    prepare) prepare || fail 'prepare failed; target data not replaced; retain evidence' ;;
    fetch-rollback) owned; cat "$WORK/rollback.tar.gz" ;;
    fetch-cron) owned; cat "$WORK/crontab.before" ;;
    state) owned; cat "$WORK/phase" "$WORK/enabled.before" ;;
    commit) owned; commit || fail 'apply failed; do not report success' ;;
    verify) owned; verify || fail 'post-restore verification failed' ;;
    disabled-nft|disabled-rule4|disabled-rule6|disabled-route4|disabled-route6)
        owned
        [ "$(uci -q get openclash.config.enable)" = 0 ] || fail 'target not disabled'
        case "$(cat "$WORK/phase")" in VERIFIED|ROLLED_BACK) ;; *) fail 'disabled snapshot unavailable' ;; esac
        cat "$WORK/$ACTION.json" ;;
    rollback) owned; rollback || fail 'rollback NOT VERIFIED; manual recovery required' ;;
    finish)
        owned
        [ "$(cat "$WORK/phase")" = VERIFIED ] || fail 'transaction not verified'
        contract && same_unrelated_cron || fail 'final state changed'
        # Only our token-owned staging tree is removed, never the user roots.
        rm -rf "$WORK" || fail 'staging cleanup failed'
        ;;
    *) fail 'unknown action' ;;
esac
