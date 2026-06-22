#!/bin/sh
# AX6 router configuration backup. Run before manually flashing firmware.
# Usage: ./backup-router-config.sh [router_ip] [backup_directory]
set -eu

umask 077

ROUTER="${1:-192.168.5.1}"
BACKUP_DIR="${2:-./ax6-backup-$(date +%Y%m%d-%H%M%S)}"
TARGET="root@$ROUTER"
REMOTE_TMP="/tmp/ax6-sysupgrade-backup-$$.tar.gz"

say() {
    printf '%s\n' "$*"
}

capture() {
    name="$1"
    shift
    if ssh "$TARGET" "$*" > "$BACKUP_DIR/$name" 2> "$BACKUP_DIR/$name.stderr"; then
        rm -f "$BACKUP_DIR/$name.stderr"
        say "  [ok] $name"
    else
        say "  [warn] $name failed; see $name.stderr"
    fi
}

say "=== AX6 Router Configuration Backup ==="
say "Router: $ROUTER"
say "Backup: $BACKUP_DIR"
say ""

mkdir -p "$BACKUP_DIR"

say "[1/6] Verify SSH access"
ssh "$TARGET" 'uname -a; ubus call system board 2>/dev/null || true' \
    > "$BACKUP_DIR/router-system.txt"
say "  [ok] SSH connection"

say "[2/6] Create complete OpenWrt sysupgrade configuration archive"
ssh "$TARGET" "sysupgrade -b '$REMOTE_TMP' >/dev/null && cat '$REMOTE_TMP'; rc=\$?; rm -f '$REMOTE_TMP'; exit \$rc" \
    > "$BACKUP_DIR/sysupgrade-config-backup.tar.gz"
[ -s "$BACKUP_DIR/sysupgrade-config-backup.tar.gz" ] || {
    say "  [error] sysupgrade backup is empty"
    exit 2
}
say "  [ok] sysupgrade-config-backup.tar.gz"

say "[3/6] Archive OpenClash runtime configuration"
if ssh "$TARGET" '
    set --
    for path in \
        /etc/config/openclash \
        /etc/openclash/custom \
        /etc/openclash/config \
        /etc/openclash/proxy_provider \
        /etc/openclash/rule_provider \
        /usr/share/openclash/fix_dot.sh; do
        [ -e "$path" ] && set -- "$@" "$path"
    done
    [ "$#" -gt 0 ] || exit 3
    tar -czf - "$@"
' > "$BACKUP_DIR/openclash-runtime.tar.gz"; then
    [ -s "$BACKUP_DIR/openclash-runtime.tar.gz" ] || {
        say "  [error] OpenClash archive is empty"
        exit 3
    }
    say "  [ok] openclash-runtime.tar.gz"
else
    rm -f "$BACKUP_DIR/openclash-runtime.tar.gz"
    say "  [warn] OpenClash is absent or its runtime archive failed"
fi

say "[4/6] Export UCI configuration"
for config in network wireless firewall dhcp system zerotier upnpd openclash sqm; do
    capture "uci-$config.txt" "uci export '$config'"
done

say "[5/6] Capture runtime diagnostics"
capture "crontab.txt" "crontab -l"
capture "nss-check.txt" "nss-check -v 2>&1"
capture "ax6-config-audit.txt" "ax6-config-audit -v 2>&1"
capture "packages.txt" "apk list-installed"
capture "mtd.txt" "cat /proc/mtd"
capture "mounts.txt" "mount"
capture "network-status.json" "ubus call network status"

say "[6/6] Write manifest and checksums"
{
    echo "BACKUP_CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "ROUTER=$ROUTER"
    echo "CONTENTS=sysupgrade-config-backup.tar.gz openclash-runtime.tar.gz UCI exports diagnostics"
    echo "RESTORE_POLICY=Do not restore the whole sysupgrade archive automatically after changing firmware branches."
} > "$BACKUP_DIR/MANIFEST.txt"

rm -f "$BACKUP_DIR/SHA256SUMS.txt"
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$BACKUP_DIR" && sha256sum ./* > SHA256SUMS.txt)
elif command -v shasum >/dev/null 2>&1; then
    (cd "$BACKUP_DIR" && shasum -a 256 ./* > SHA256SUMS.txt)
else
    say "  [warn] no SHA-256 utility found; checksum file not created"
fi

say ""
say "=== Backup complete: $BACKUP_DIR ==="
say "Keep this directory private: it contains WiFi keys, VPN credentials and proxy subscriptions."
say "After manual firmware installation, restore only OpenClash runtime data with:"
say "  ./deploy-openclash-runtime.sh '$ROUTER' '$BACKUP_DIR'"
