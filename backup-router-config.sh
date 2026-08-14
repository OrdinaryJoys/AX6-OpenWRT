#!/bin/sh
# AX6 router configuration backup. Run before manually flashing firmware.
# Usage: ./backup-router-config.sh [router_ip] [backup_directory]
set -eu

umask 077

# shellcheck disable=SC1007 # Keep cd output independent of a caller-provided CDPATH.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
ROUTER="${1:-192.168.5.1}"
BACKUP_DIR="${2:-./ax6-backup-$(date +%Y%m%d-%H%M%S)}"
TARGET="root@$ROUTER"
FORENSIC_CONFIG_ARCHIVE="$BACKUP_DIR/FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked"
RESTORE_WARNING="$BACKUP_DIR/DO-NOT-RESTORE-WHOLE-BACKUP.txt"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ax6_check}"
SSH_KNOWN_HOSTS="${SSH_KNOWN_HOSTS:-$HOME/.ssh/known_hosts}"

say() {
    printf '%s\n' "$*"
}

remote() {
    if [ -r "$SSH_KEY" ]; then
        ssh -i "$SSH_KEY" \
            -o IdentitiesOnly=yes \
            -o BatchMode=yes \
            -o StrictHostKeyChecking=yes \
            -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
            -o ConnectTimeout=8 \
            "$TARGET" "$@"
    else
        ssh -o BatchMode=yes \
            -o StrictHostKeyChecking=yes \
            -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
            -o ConnectTimeout=8 \
            "$TARGET" "$@"
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

say "[1/7] Verify SSH access"
remote 'uname -a; ubus call system board 2>/dev/null || true' \
    > "$BACKUP_DIR/router-system.txt"
say "  [ok] SSH connection"

say "[2/7] Create forensic-only configuration snapshot (NEVER RESTORE WHOLE)"
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
' > "$FORENSIC_CONFIG_ARCHIVE"
[ -s "$FORENSIC_CONFIG_ARCHIVE" ] || {
    say "  [error] forensic configuration snapshot is empty"
    exit 2
}
if ! tar -tzf "$FORENSIC_CONFIG_ARCHIVE" | awk '
    /^\.\// { sub(/^\.\//, "") }
    /^\// { sub(/^\/+/, "") }
    /(^|\/)etc\/shadow-?$/ { bad=1; print "login password leaked into archive: " $0 > "/dev/stderr"; next }
    /^etc\/openclash\// && $0 !~ /^etc\/openclash\/(config|custom|overwrite)(\/|$)/ {
        bad=1
        print "generated OpenClash data leaked into archive: " $0 > "/dev/stderr"
    }
    END { exit bad }
'; then
    say "  [error] forensic configuration snapshot crossed its capture allowlist"
    exit 2
fi
if ! tar -tvzf "$FORENSIC_CONFIG_ARCHIVE" | awk '
    {
        type = substr($1, 1, 1)
        if (type != "-" && type != "d") {
            bad=1
            print "unsafe forensic snapshot member type: " $0 > "/dev/stderr"
        }
    }
    END { exit bad }
'; then
    say "  [error] forensic configuration snapshot contains links or special files"
    exit 2
fi
{
    echo "DANGER: THIS DIRECTORY IS NOT A WHOLE-SYSTEM RESTORE BUNDLE."
    echo ""
    echo "Never upload FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked in LuCI."
    echo "Never rename it to .tar.gz and never pass it to sysupgrade -r."
    echo "It contains old network, firewall, system and core-driver configuration."
    echo "Restoring it can replace the new AX6 board topology and disconnect LAN, WAN and SSH."
    echo "Use only reviewed, allowlisted stage restore tools after validating the new firmware."
} > "$RESTORE_WARNING"
say "  [ok] FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked (capture only)"
say "  [ok] DO-NOT-RESTORE-WHOLE-BACKUP.txt"

say "[3/7] Archive narrow identity data for staged restoration"
# shellcheck disable=SC2016 # This single-quoted block is evaluated by the router shell.
if remote '
    test -f /etc/dropbear/authorized_keys
    test ! -L /etc/dropbear/authorized_keys
    tar -czf - /etc/dropbear/authorized_keys
' > "$BACKUP_DIR/ssh-authorized-keys.tar.gz"; then
    [ -s "$BACKUP_DIR/ssh-authorized-keys.tar.gz" ] || {
        say "  [error] SSH authorized-keys archive is empty"
        exit 3
    }
    say "  [ok] ssh-authorized-keys.tar.gz (no host keys or password hashes)"
else
    rm -f "$BACKUP_DIR/ssh-authorized-keys.tar.gz"
    say "  [error] SSH authorized_keys is absent or its archive failed"
    exit 3
fi

# shellcheck disable=SC2016 # This single-quoted block is evaluated by the router shell.
if remote '
    test -f /etc/zerotier/identity.public
    test -f /etc/zerotier/identity.secret
    test ! -L /etc/zerotier/identity.public
    test ! -L /etc/zerotier/identity.secret
    tar -czf - /etc/zerotier/identity.public /etc/zerotier/identity.secret
' > "$BACKUP_DIR/zerotier-identity.tar.gz"; then
    [ -s "$BACKUP_DIR/zerotier-identity.tar.gz" ] || {
        say "  [error] ZeroTier identity archive is empty"
        exit 3
    }
    say "  [ok] zerotier-identity.tar.gz (identity only; no generated network state)"
else
    rm -f "$BACKUP_DIR/zerotier-identity.tar.gz"
    say "  [error] ZeroTier identity is absent or its archive failed"
    exit 3
fi

say "[4/7] Archive OpenClash persistent configuration"
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
    say "  [error] OpenClash is absent or its runtime archive failed"
    exit 3
fi

say "[5/7] Export UCI configuration for reference, not bulk import"
for config in network wireless firewall dhcp system zerotier upnpd openclash sqm; do
    capture "uci-$config.txt" "uci export '$config'"
done

say "[6/7] Capture runtime diagnostics"
capture "crontab.txt" "crontab -l"
capture "nss-check.txt" "nss-check -v 2>&1"
capture "ax6-config-audit.txt" "ax6-config-audit -v 2>&1"
capture "packages.txt" "opkg list-installed"
capture "mtd.txt" "cat /proc/mtd"
capture "mounts.txt" "mount"
capture "network-interface-dump.json" "ubus call network.interface dump"

say "[7/7] Write manifest and checksums"
{
    echo "BACKUP_CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "ROUTER=$ROUTER"
    echo "CONTENTS=FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked staged identity archives openclash-runtime.tar.gz UCI exports diagnostics"
    echo "EXCLUDED=/etc/shadow OpenClash core Geo cache history proxy_provider rule_provider package scripts"
    echo "RESTORE_POLICY=The forensic snapshot must never be restored whole. Use only reviewed allowlisted stage restore tools."
    echo "NETWORK_POLICY=Rebuild network, firewall, DHCP and WiFi semantically on the new firmware defaults; never bulk-import them."
} > "$BACKUP_DIR/MANIFEST.txt"

rm -f "$BACKUP_DIR/SHA256SUMS.txt"
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$BACKUP_DIR" && sha256sum ./* > SHA256SUMS.txt)
elif command -v shasum >/dev/null 2>&1; then
    (cd "$BACKUP_DIR" && shasum -a 256 ./* > SHA256SUMS.txt)
else
    say "  [warn] no SHA-256 utility found; checksum file not created"
fi

"$SCRIPT_DIR/preflight-router-restore.sh" "$BACKUP_DIR"

say ""
say "=== Backup complete: $BACKUP_DIR ==="
say "Keep this directory private: it contains WiFi keys, VPN credentials and proxy subscriptions."
say "The router login password hash and generated OpenClash data were not archived."
say "The forensic snapshot is deliberately blocked from whole-system restore."
say "Before flashing, validate this directory with:"
say "  ./preflight-router-restore.sh '$BACKUP_DIR'"
say "After a clean manual installation and base-network validation, restore OpenClash with:"
say "  ./deploy-openclash-runtime.sh '$ROUTER' '$BACKUP_DIR'"
