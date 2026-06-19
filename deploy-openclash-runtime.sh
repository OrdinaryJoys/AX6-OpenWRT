#!/bin/sh
# Restore OpenClash runtime configuration after a manual firmware upgrade.
# Usage: ./deploy-openclash-runtime.sh [router_ip] [backup_directory]
#
# This script deliberately does not restore the complete sysupgrade backup.
# Restoring old network/firewall files across source migrations can reintroduce
# the faults that the new firmware was built to remove.
set -eu

umask 077

ROUTER="${1:-192.168.5.1}"
TARGET="root@$ROUTER"

if [ "$#" -ge 2 ]; then
    BACKUP_DIR="$2"
else
    BACKUP_DIR="$(ls -dt ./ax6-backup-* 2>/dev/null | head -n 1 || true)"
fi

[ -n "${BACKUP_DIR:-}" ] && [ -d "$BACKUP_DIR" ] || {
    echo "error: backup directory not found; pass it as the second argument" >&2
    exit 2
}

ARCHIVE="$BACKUP_DIR/openclash-runtime.tar.gz"
[ -s "$ARCHIVE" ] || {
    echo "error: missing or empty $ARCHIVE" >&2
    exit 2
}

if ! tar -tzf "$ARCHIVE" | awk '
    /^\.\// { sub(/^\.\//, "") }
    /(^|\/)\.\.(\/|$)/ { bad=1; print "unsafe archive path: " $0 > "/dev/stderr"; next }
    /^etc\/config\/openclash$/ { next }
    /^etc\/openclash\/(custom|config|proxy_provider|rule_provider)(\/|$)/ { next }
    /^usr\/share\/openclash\/fix_dot\.sh$/ { next }
    { bad=1; print "unexpected archive path: " $0 > "/dev/stderr" }
    END { exit bad }
'; then
    echo "error: OpenClash archive contains paths outside the restore allowlist" >&2
    exit 2
fi

say() {
    printf '%s\n' "$*"
}

say "=== AX6 OpenClash Runtime Restore ==="
say "Router: $ROUTER"
say "Backup: $BACKUP_DIR"
say ""

say "[1/5] Verify target and OpenClash installation"
ssh "$TARGET" '
    test -x /etc/init.d/openclash
    test -d /etc/openclash
'
say "  [ok] OpenClash is installed"

say "[2/5] Save current target state for rollback"
PRE_RESTORE="$BACKUP_DIR/openclash-pre-restore-$(date +%Y%m%d-%H%M%S).tar.gz"
ssh "$TARGET" '
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
' > "$PRE_RESTORE"
[ -s "$PRE_RESTORE" ] || {
    say "  [error] pre-restore archive is empty"
    exit 3
}
say "  [ok] $(basename "$PRE_RESTORE")"

say "[3/5] Restore archived OpenClash runtime files"
ssh "$TARGET" '
    /etc/init.d/openclash stop >/dev/null 2>&1 || true
    tar -xzf - -C /
    [ -f /etc/openclash/custom/openclash_custom_overwrite.sh ] &&
        chmod 0755 /etc/openclash/custom/openclash_custom_overwrite.sh
    [ -f /etc/openclash/custom/openclash_custom_firewall_rules.sh ] &&
        chmod 0755 /etc/openclash/custom/openclash_custom_firewall_rules.sh
    [ -f /usr/share/openclash/fix_dot.sh ] &&
        chmod 0755 /usr/share/openclash/fix_dot.sh
' < "$ARCHIVE"
say "  [ok] runtime files restored"

if [ -s "$BACKUP_DIR/crontab.txt" ]; then
    awk '/openclash|fix_dot/' "$BACKUP_DIR/crontab.txt" |
        ssh "$TARGET" '
            tmp=/tmp/openclash-cron.restore
            cat > "$tmp"
            if [ -s "$tmp" ]; then
                (
                    crontab -l 2>/dev/null | grep -v -E "openclash|fix_dot" || true
                    cat "$tmp"
                ) | awk "!seen[\$0]++" | crontab -
            fi
            rm -f "$tmp"
        '
    say "  [ok] OpenClash cron entries merged"
fi

say "[4/5] Restart OpenClash"
ssh "$TARGET" '
    uci -q commit openclash
    /etc/init.d/cron restart
    /etc/init.d/openclash restart
'
say "  [ok] restart command completed"

say "[5/5] Verify restored state"
ssh "$TARGET" '
    set -e
    test -s /etc/config/openclash
    config_count=$(find /etc/openclash/config -maxdepth 1 -type f -name "*.yaml" 2>/dev/null | wc -l)
    custom_count=$(find /etc/openclash/custom -maxdepth 1 -type f 2>/dev/null | wc -l)
    printf "OpenClash YAML configs: %s\n" "$config_count"
    printf "OpenClash custom files: %s\n" "$custom_count"
    enabled=$(uci -q get openclash.config.enable || echo 0)
    printf "OpenClash enabled: %s\n" "$enabled"
    if [ "$enabled" = "1" ]; then
        retries=30
        while ! pidof clash >/dev/null 2>&1 && [ "$retries" -gt 0 ]; do
            sleep 1
            retries=$((retries - 1))
        done
        if pidof clash >/dev/null 2>&1; then
            echo "OpenClash core: running"
        else
            echo "OpenClash core: not running after 30 seconds; inspect /tmp/openclash.log" >&2
            exit 4
        fi
    else
        echo "OpenClash core: disabled by restored configuration"
    fi
    [ ! -x /sbin/ax6-config-audit ] || ax6-config-audit -v || true
'

say ""
say "=== OpenClash runtime restore complete ==="
say "The complete sysupgrade archive was not restored automatically."
say "Rollback archive: $PRE_RESTORE"
