#!/bin/sh
# AX6 router configuration backup. Run before manually flashing firmware.
# Usage: ./backup-router-config.sh [router_ip] [backup_directory]
set -eu

umask 077

ROUTER="${1:-192.168.5.1}"
BACKUP_DIR="${2:-./ax6-backup-$(date +%Y%m%d-%H%M%S)}"
TARGET="root@$ROUTER"
SAFE_SYSUPGRADE_ARCHIVE="$BACKUP_DIR/sysupgrade-config-restore-safe.tar.gz"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ax6_check}"

say() {
    printf '%s\n' "$*"
}

remote() {
    if [ -r "$SSH_KEY" ]; then
        ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=8 "$TARGET" "$@"
    else
        ssh -o BatchMode=yes -o ConnectTimeout=8 "$TARGET" "$@"
    fi
}

capture() {
    name="$1"
    shift
    if remote "$*" > "$BACKUP_DIR/$name" 2> "$BACKUP_DIR/$name.stderr"; then
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
remote 'uname -a; ubus call system board 2>/dev/null || true' \
    > "$BACKUP_DIR/router-system.txt"
say "  [ok] SSH connection"

say "[2/6] Create restore-safe OpenWrt configuration archive"
# shellcheck disable=SC2016 # This single-quoted block is evaluated by the router shell.
remote '
    list="/tmp/ax6-sysupgrade-list.$$"
    trap '\''rm -f "$list"'\'' EXIT HUP INT TERM
    sysupgrade -l 2>/dev/null | while IFS= read -r path; do
        case "$path" in
            /etc/shadow|/etc/shadow-)
                ;;
            /etc/openclash/*)
                case "$path" in
                    /etc/openclash/config|/etc/openclash/config/*|\
                    /etc/openclash/custom|/etc/openclash/custom/*|\
                    /etc/openclash/overwrite|/etc/openclash/overwrite/*)
                        printf "%s\n" "$path"
                        ;;
                esac
                ;;
            *)
                printf "%s\n" "$path"
                ;;
        esac
    done > "$list"
    test -s "$list"
    tar -czf - -T "$list"
' > "$SAFE_SYSUPGRADE_ARCHIVE"
[ -s "$SAFE_SYSUPGRADE_ARCHIVE" ] || {
    say "  [error] restore-safe sysupgrade backup is empty"
    exit 2
}
if ! tar -tzf "$SAFE_SYSUPGRADE_ARCHIVE" | awk '
    /^\.\// { sub(/^\.\//, "") }
    /^\// { sub(/^\/+/, "") }
    /(^|\/)etc\/shadow-?$/ { bad=1; print "login password leaked into archive: " $0 > "/dev/stderr"; next }
    /^etc\/openclash\// && $0 !~ /^etc\/openclash\/(config|custom|overwrite)(\/|$)/ {
        bad=1
        print "generated OpenClash data leaked into archive: " $0 > "/dev/stderr"
    }
    END { exit bad }
'; then
    say "  [error] restore-safe sysupgrade archive crossed its allowlist"
    exit 2
fi
if ! tar -tvzf "$SAFE_SYSUPGRADE_ARCHIVE" | awk '
    {
        type = substr($1, 1, 1)
        if (type != "-" && type != "d") {
            bad=1
            print "unsafe restore-safe member type: " $0 > "/dev/stderr"
        }
    }
    END { exit bad }
'; then
    say "  [error] restore-safe sysupgrade archive contains links or special files"
    exit 2
fi
say "  [ok] sysupgrade-config-restore-safe.tar.gz"

say "[3/6] Archive OpenClash persistent configuration"
# shellcheck disable=SC2016 # This single-quoted block is evaluated by the router shell.
if remote '
    set --
    for path in \
        /etc/config/openclash \
        /etc/openclash/custom \
        /etc/openclash/config \
        /etc/openclash/overwrite; do
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
capture "packages.txt" "opkg list-installed"
capture "mtd.txt" "cat /proc/mtd"
capture "mounts.txt" "mount"
capture "network-interface-dump.json" "ubus call network.interface dump"

say "[6/6] Write manifest and checksums"
{
    echo "BACKUP_CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "ROUTER=$ROUTER"
    echo "CONTENTS=sysupgrade-config-restore-safe.tar.gz openclash-runtime.tar.gz UCI exports diagnostics"
    echo "EXCLUDED=/etc/shadow OpenClash core Geo cache history proxy_provider rule_provider package scripts"
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
say "The router login password hash and generated OpenClash data were not archived."
say "After manual firmware installation, restore only OpenClash runtime data with:"
say "  ./deploy-openclash-runtime.sh '$ROUTER' '$BACKUP_DIR'"
