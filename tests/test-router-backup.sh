#!/bin/sh
set -eu

# shellcheck disable=SC1007 # Keep cd output independent of a caller-provided CDPATH.
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/router-backup-test.XXXXXX")
cleanup_test() {
    status=$?
    trap - EXIT HUP INT TERM
    rm -rf "$TMP"
    exit "$status"
}
trap cleanup_test EXIT HUP INT TERM

mkdir -p \
    "$TMP/bin" \
    "$TMP/safe/etc/config" \
    "$TMP/safe/etc/openclash/config" \
    "$TMP/safe/etc/openclash/custom" \
    "$TMP/safe/etc/openclash/overwrite" \
    "$TMP/openclash/etc/config" \
    "$TMP/openclash/etc/openclash/config" \
    "$TMP/shadow/etc" \
    "$TMP/link/etc/config"

printf "config system 'system'\n" > "$TMP/safe/etc/config/system"
printf "config openclash 'config'\n" > "$TMP/safe/etc/config/openclash"
printf 'proxy config\n' > "$TMP/safe/etc/openclash/config/main.yaml"
printf 'custom config\n' > "$TMP/safe/etc/openclash/custom/custom.sh"
printf 'overwrite config\n' > "$TMP/safe/etc/openclash/overwrite/settings.yml"
cp "$TMP/safe/etc/config/openclash" "$TMP/openclash/etc/config/openclash"
cp "$TMP/safe/etc/openclash/config/main.yaml" "$TMP/openclash/etc/openclash/config/main.yaml"
printf 'password hash\n' > "$TMP/shadow/etc/shadow"
ln -s /etc/shadow "$TMP/link/etc/config/unsafe-link"

tar -czf "$TMP/safe.tar.gz" -C "$TMP/safe" \
    etc/config/system \
    etc/config/openclash \
    etc/openclash/config/main.yaml \
    etc/openclash/custom/custom.sh \
    etc/openclash/overwrite/settings.yml
tar -czf "$TMP/openclash.tar.gz" -C "$TMP/openclash" etc/config/openclash etc/openclash/config
tar -czf "$TMP/shadow.tar.gz" -C "$TMP/shadow" etc/shadow
tar -czf "$TMP/link.tar.gz" -C "$TMP/link" etc/config/unsafe-link

cat > "$TMP/bin/ssh" <<'EOF'
#!/bin/sh
command=
for arg in "$@"; do
    command=$arg
done
case "$command" in
    *'uname -a'*)
        printf 'Linux mock-router\n{}\n'
        ;;
    *'sysupgrade -l'*)
        cat "$MOCK_SAFE_ARCHIVE"
        ;;
    *'/etc/openclash/overwrite'*'tar -czf -'*)
        cat "$MOCK_OPENCLASH_ARCHIVE"
        ;;
    *)
        printf 'mock output\n'
        ;;
esac
EOF
chmod +x "$TMP/bin/ssh"

if ! PATH="$TMP/bin:$PATH" \
   SSH_KEY="$TMP/nonexistent-key" \
   SSH_KNOWN_HOSTS="$TMP/known_hosts" \
   MOCK_SAFE_ARCHIVE="$TMP/safe.tar.gz" \
   MOCK_OPENCLASH_ARCHIVE="$TMP/openclash.tar.gz" \
   "$ROOT/backup-router-config.sh" 192.0.2.1 "$TMP/backup" \
   > "$TMP/backup-output" 2>&1; then
    cat "$TMP/backup-output" >&2
    echo "test-router-backup: valid backup failed" >&2
    exit 1
fi

gzip -t "$TMP/backup/sysupgrade-config-restore-safe.tar.gz"
gzip -t "$TMP/backup/openclash-runtime.tar.gz"
if tar -tzf "$TMP/backup/sysupgrade-config-restore-safe.tar.gz" |
   grep -Eq '(^|/)(shadow-?|core|Geo(IP|Site|ASN)|proxy_provider|rule_provider)(/|$)'; then
    echo "test-router-backup: forbidden data entered the restore-safe archive" >&2
    exit 1
fi
(cd "$TMP/backup" && sha256sum -c SHA256SUMS.txt >/dev/null)

if PATH="$TMP/bin:$PATH" \
   SSH_KEY="$TMP/nonexistent-key" \
   SSH_KNOWN_HOSTS="$TMP/known_hosts" \
   MOCK_SAFE_ARCHIVE="$TMP/shadow.tar.gz" \
   MOCK_OPENCLASH_ARCHIVE="$TMP/openclash.tar.gz" \
   "$ROOT/backup-router-config.sh" 192.0.2.1 "$TMP/shadow-backup" \
   > "$TMP/shadow-output" 2>&1; then
    echo "test-router-backup: password archive unexpectedly accepted" >&2
    exit 1
fi
grep -q 'login password leaked into archive' "$TMP/shadow-output" || {
    echo "test-router-backup: password rejection was not reported" >&2
    exit 1
}

if PATH="$TMP/bin:$PATH" \
   SSH_KEY="$TMP/nonexistent-key" \
   SSH_KNOWN_HOSTS="$TMP/known_hosts" \
   MOCK_SAFE_ARCHIVE="$TMP/link.tar.gz" \
   MOCK_OPENCLASH_ARCHIVE="$TMP/openclash.tar.gz" \
   "$ROOT/backup-router-config.sh" 192.0.2.1 "$TMP/link-backup" \
   > "$TMP/link-output" 2>&1; then
    echo "test-router-backup: symlink archive unexpectedly accepted" >&2
    exit 1
fi
grep -q 'restore-safe sysupgrade archive contains links or special files' \
    "$TMP/link-output" || {
    echo "test-router-backup: symlink rejection was not reported" >&2
    exit 1
}

grep -Fq -- '-o IdentitiesOnly=yes' "$ROOT/backup-router-config.sh" || {
    echo "test-router-backup: explicit identity isolation is missing" >&2
    exit 1
}
grep -Fq -- '-o StrictHostKeyChecking=yes' "$ROOT/backup-router-config.sh" || {
    echo "test-router-backup: strict host-key checking is missing" >&2
    exit 1
}
grep -Fq -- '-o UserKnownHostsFile="$SSH_KNOWN_HOSTS"' \
    "$ROOT/backup-router-config.sh" || {
    echo "test-router-backup: fixed known_hosts ownership is missing" >&2
    exit 1
}

echo "test-router-backup: PASS"
