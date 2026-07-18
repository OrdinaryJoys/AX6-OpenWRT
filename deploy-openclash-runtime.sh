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
PRE_RESTORE=
PRE_CRONTAB=
RESTORE_STARTED=0
RESTORE_COMPLETE=0

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

if ! tar -tvzf "$ARCHIVE" | awk '
    {
        type = substr($1, 1, 1)
        if (type != "-" && type != "d") {
            bad=1
            print "unsafe archive member type: " $0 > "/dev/stderr"
        }
    }
    END { exit bad }
'; then
    echo "error: OpenClash archive contains links or special files" >&2
    exit 2
fi

say() {
    printf '%s\n' "$*"
}

rollback_on_error() {
    rc=$?
    trap - EXIT HUP INT TERM

    if [ "$RESTORE_STARTED" -eq 1 ] &&
       [ "$RESTORE_COMPLETE" -ne 1 ] &&
       [ -s "$PRE_RESTORE" ]; then
        say ""
        say "[rollback] Restore failed; reverting OpenClash files and crontab"
        if ssh "$TARGET" '
            /etc/init.d/openclash stop >/dev/null 2>&1 || true
            rm -rf \
                /etc/config/openclash \
                /etc/openclash/custom \
                /etc/openclash/config \
                /etc/openclash/proxy_provider \
                /etc/openclash/rule_provider \
                /usr/share/openclash/fix_dot.sh
            tar -xzf - -C /
        ' < "$PRE_RESTORE" &&
           ssh "$TARGET" '
               crontab -
               /etc/init.d/cron restart
               /etc/init.d/openclash restart
           ' < "$PRE_CRONTAB"; then
            say "  [ok] previous OpenClash state restored"
        else
            say "  [error] automatic rollback failed; use $PRE_RESTORE manually" >&2
        fi
    fi

    exit "$rc"
}

abort_restore() {
    exit 130
}

say "=== AX6 OpenClash Runtime Restore ==="
say "Router: $ROUTER"
say "Backup: $BACKUP_DIR"
say ""

say "[1/5] Verify target and OpenClash installation"
ssh "$TARGET" '
    test -x /etc/init.d/openclash
    test -d /etc/openclash
    test ! -L /etc/openclash
    for path in \
        /etc/config/openclash \
        /etc/openclash/custom \
        /etc/openclash/config \
        /etc/openclash/proxy_provider \
        /etc/openclash/rule_provider \
        /usr/share/openclash/fix_dot.sh; do
        test ! -L "$path"
    done
'
say "  [ok] OpenClash is installed"

say "[2/5] Save current target state for rollback"
PRE_RESTORE="$BACKUP_DIR/openclash-pre-restore-$(date +%Y%m%d-%H%M%S).tar.gz"
PRE_CRONTAB="${PRE_RESTORE%.tar.gz}.crontab"
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
ssh "$TARGET" 'crontab -l 2>/dev/null || true' > "$PRE_CRONTAB"
say "  [ok] $(basename "$PRE_RESTORE")"

say "[3/5] Restore archived OpenClash runtime files"
trap rollback_on_error EXIT
trap abort_restore HUP INT TERM
RESTORE_STARTED=1
ssh "$TARGET" '
    /etc/init.d/openclash stop >/dev/null 2>&1 || true
    tar -xzf - -C /
    if [ -f /etc/openclash/custom/openclash_custom_overwrite.sh ]; then
        chmod 0755 /etc/openclash/custom/openclash_custom_overwrite.sh
    fi
    if [ -f /etc/openclash/custom/openclash_custom_firewall_rules.sh ]; then
        chmod 0755 /etc/openclash/custom/openclash_custom_firewall_rules.sh
    fi
    if [ -f /usr/share/openclash/fix_dot.sh ]; then
        chmod 0755 /usr/share/openclash/fix_dot.sh
    fi
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

RESTORE_COMPLETE=1
trap - EXIT HUP INT TERM
say ""
say "=== OpenClash runtime restore complete ==="
say "The complete sysupgrade archive was not restored automatically."
say "Rollback archive: $PRE_RESTORE"
