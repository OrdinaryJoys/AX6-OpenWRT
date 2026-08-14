#!/bin/sh
set -eu

# shellcheck disable=SC1007 # Keep cd output independent of a caller-provided CDPATH.
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/router-restore-preflight.XXXXXX")
cleanup_test() {
    status=$?
    trap - EXIT HUP INT TERM
    rm -rf "$TMP"
    exit "$status"
}
trap cleanup_test EXIT HUP INT TERM

make_valid_backup() {
    directory="$1"
    mkdir -p \
        "$directory/payload/etc/config" \
        "$directory/payload/etc/openclash/config" \
        "$directory/payload/etc/dropbear" \
        "$directory/payload/etc/zerotier"
    printf "config interface 'lan'\n" > "$directory/payload/etc/config/network"
    printf "config defaults 'defaults'\n" > "$directory/payload/etc/config/firewall"
    printf "config dnsmasq\n" > "$directory/payload/etc/config/dhcp"
    printf "config wifi-device 'radio0'\n" > "$directory/payload/etc/config/wireless"
    printf "config openclash 'config'\n" > "$directory/payload/etc/config/openclash"
    printf 'proxy config\n' > "$directory/payload/etc/openclash/config/main.yaml"
    printf 'ssh-ed25519 AAAATEST ax6-check\n' > "$directory/payload/etc/dropbear/authorized_keys"
    printf 'identity-public\n' > "$directory/payload/etc/zerotier/identity.public"
    printf 'identity-secret\n' > "$directory/payload/etc/zerotier/identity.secret"

    tar -czf "$directory/FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked" \
        -C "$directory/payload" etc/config/network etc/config/firewall
    tar -czf "$directory/openclash-runtime.tar.gz" \
        -C "$directory/payload" etc/config/openclash etc/openclash/config/main.yaml
    tar -czf "$directory/ssh-authorized-keys.tar.gz" \
        -C "$directory/payload" etc/dropbear/authorized_keys
    tar -czf "$directory/zerotier-identity.tar.gz" \
        -C "$directory/payload" etc/zerotier/identity.public etc/zerotier/identity.secret

    for config in network firewall dhcp wireless; do
        cp "$directory/payload/etc/config/$config" "$directory/uci-$config.txt"
    done
    printf '%s\n' \
        'RESTORE_POLICY=The forensic snapshot must never be restored whole.' \
        > "$directory/MANIFEST.txt"
    printf '%s\n' \
        'DANGER: THIS DIRECTORY IS NOT A WHOLE-SYSTEM RESTORE BUNDLE.' \
        'Never upload FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked in LuCI.' \
        'Never rename it to .tar.gz and never pass it to sysupgrade -r.' \
        > "$directory/DO-NOT-RESTORE-WHOLE-BACKUP.txt"
    rm -rf "$directory/payload"
    (cd "$directory" && sha256sum ./* > SHA256SUMS.txt)
}

make_valid_backup "$TMP/valid"
"$ROOT/preflight-router-restore.sh" "$TMP/valid" > "$TMP/valid-output"
grep -Fq 'AX6 restore preflight: PASS' "$TMP/valid-output"

cp -R "$TMP/valid" "$TMP/legacy"
cp "$TMP/legacy/FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked" \
    "$TMP/legacy/sysupgrade-config-restore-safe.tar.gz"
if "$ROOT/preflight-router-restore.sh" "$TMP/legacy" > "$TMP/legacy-output" 2>&1; then
    echo "test-router-restore-preflight: legacy whole archive was accepted" >&2
    exit 1
fi
grep -Fq 'legacy whole-restore archive found' "$TMP/legacy-output"

cp -R "$TMP/valid" "$TMP/no-warning"
rm "$TMP/no-warning/DO-NOT-RESTORE-WHOLE-BACKUP.txt"
if "$ROOT/preflight-router-restore.sh" "$TMP/no-warning" > "$TMP/warning-output" 2>&1; then
    echo "test-router-restore-preflight: backup without warning was accepted" >&2
    exit 1
fi
grep -Fq 'missing DO-NOT-RESTORE-WHOLE-BACKUP.txt' "$TMP/warning-output"

cp -R "$TMP/valid" "$TMP/unsafe"
mkdir -p "$TMP/unsafe-payload/etc"
printf 'not allowed\n' > "$TMP/unsafe-payload/etc/passwd"
tar -czf "$TMP/unsafe/openclash-runtime.tar.gz" -C "$TMP/unsafe-payload" etc/passwd
(cd "$TMP/unsafe" && rm SHA256SUMS.txt && sha256sum ./* > SHA256SUMS.txt)
if "$ROOT/preflight-router-restore.sh" "$TMP/unsafe" > "$TMP/unsafe-output" 2>&1; then
    echo "test-router-restore-preflight: unsafe OpenClash archive was accepted" >&2
    exit 1
fi
grep -Fq 'OpenClash archive crossed its restore allowlist' "$TMP/unsafe-output"

echo "test-router-restore-preflight: PASS"
