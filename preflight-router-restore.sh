#!/bin/sh
# Offline gate for AX6 clean-flash backup sets. This script never contacts the router.
# Usage: ./preflight-router-restore.sh backup_directory
set -eu

BACKUP_DIR="${1:-}"
FORENSIC_ARCHIVE="FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked"
WARNING_MARKER="DO-NOT-RESTORE-WHOLE-BACKUP.txt"

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 2
}

[ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ] || \
    fail "backup directory not found; pass it as the only argument"

for legacy in "$BACKUP_DIR"/sysupgrade-config*.tar.gz; do
    [ -e "$legacy" ] || continue
    fail "legacy whole-restore archive found: $(basename "$legacy"); quarantine it before flashing"
done

[ -s "$BACKUP_DIR/$WARNING_MARKER" ] || fail "missing $WARNING_MARKER"
grep -Fq 'Never upload FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked in LuCI.' \
    "$BACKUP_DIR/$WARNING_MARKER" || fail "whole-restore warning is incomplete"
grep -Fq 'never pass it to sysupgrade -r' "$BACKUP_DIR/$WARNING_MARKER" || \
    fail "sysupgrade restore prohibition is missing"

[ -s "$BACKUP_DIR/$FORENSIC_ARCHIVE" ] || fail "missing forensic snapshot"
gzip -t "$BACKUP_DIR/$FORENSIC_ARCHIVE" || fail "forensic snapshot is corrupt"

[ -s "$BACKUP_DIR/MANIFEST.txt" ] || fail "missing MANIFEST.txt"
grep -Fq 'forensic snapshot must never be restored whole' "$BACKUP_DIR/MANIFEST.txt" || \
    fail "manifest does not prohibit whole restore"

[ -s "$BACKUP_DIR/SHA256SUMS.txt" ] || fail "missing SHA256SUMS.txt"
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS.txt >/dev/null) || \
        fail "backup checksum verification failed"
elif command -v shasum >/dev/null 2>&1; then
    (cd "$BACKUP_DIR" && shasum -a 256 -c SHA256SUMS.txt >/dev/null) || \
        fail "backup checksum verification failed"
else
    fail "no SHA-256 utility is available"
fi

validate_archive() {
    archive="$1"
    policy="$2"

    [ -s "$archive" ] || fail "missing staged archive: $(basename "$archive")"
    gzip -t "$archive" || fail "corrupt archive: $(basename "$archive")"
    tar -tvzf "$archive" | awk '
        {
            type = substr($1, 1, 1)
            if (type != "-" && type != "d") {
                bad=1
                print "unsafe archive member type: " $0 > "/dev/stderr"
            }
        }
        END { exit bad }
    ' || fail "links or special files found in $(basename "$archive")"

    case "$policy" in
        openclash)
            tar -tzf "$archive" | awk '
                /^\.\// { sub(/^\.\//, "") }
                /^\// { sub(/^\/+/, "") }
                /(^|\/)\.\.(\/|$)/ { bad=1; next }
                /^etc\/config\/openclash$/ { next }
                /^etc\/openclash\/(custom|config|overwrite)(\/|$)/ { next }
                { bad=1 }
                END { exit bad }
            ' || fail "OpenClash archive crossed its restore allowlist"
            ;;
        ssh)
            tar -tzf "$archive" | awk '
                /^\.\// { sub(/^\.\//, "") }
                /^\// { sub(/^\/+/, "") }
                /^etc\/dropbear\/authorized_keys$/ { found=1; next }
                { bad=1 }
                END { exit bad || !found }
            ' || fail "SSH archive contains data other than authorized_keys"
            ;;
        zerotier)
            tar -tzf "$archive" | awk '
                /^\.\// { sub(/^\.\//, "") }
                /^\// { sub(/^\/+/, "") }
                /^etc\/zerotier\/identity\.public$/ { public=1; next }
                /^etc\/zerotier\/identity\.secret$/ { secret=1; next }
                { bad=1 }
                END { exit bad || !public || !secret }
            ' || fail "ZeroTier archive is not identity-only"
            ;;
        *)
            fail "internal archive policy error: $policy"
            ;;
    esac
}

validate_archive "$BACKUP_DIR/openclash-runtime.tar.gz" openclash
validate_archive "$BACKUP_DIR/ssh-authorized-keys.tar.gz" ssh
validate_archive "$BACKUP_DIR/zerotier-identity.tar.gz" zerotier

for reference in uci-network.txt uci-firewall.txt uci-dhcp.txt uci-wireless.txt; do
    [ -s "$BACKUP_DIR/$reference" ] || fail "missing reference export: $reference"
done

printf '%s\n' "AX6 restore preflight: PASS"
printf '%s\n' "The backup is structurally valid for staged recovery; the forensic snapshot remains NON-RESTORABLE."
printf '%s\n' "Network, firewall, DHCP and WiFi must be rebuilt against the new firmware defaults."
