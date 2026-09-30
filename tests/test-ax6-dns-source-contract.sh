#!/bin/sh
# shellcheck disable=SC2016
set -eu
ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
GATE="$ROOT/.github/scripts/verify-ax6-dns-source.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ax6-dns-source-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
SOURCE="$TMP/source"
PACKAGE="$SOURCE/package/network/services/dnsmasq"
mkdir -p "$PACKAGE/files" "$SOURCE/tests/fixtures/dns-redirect-scope"

for path in \
    package/network/services/dnsmasq/files/dns-redirect-scope.sh \
    package/network/services/dnsmasq/files/dnsmasq.init \
    tests/test-dns-redirect-scope.sh \
    tests/fixtures/dns-redirect-scope/uci.sh \
    tests/fixtures/dns-redirect-scope/logger.sh \
    tests/fixtures/dns-redirect-scope/network.sh; do
    printf '#!/bin/sh\nexit 0\n' > "$SOURCE/$path"
    chmod 755 "$SOURCE/$path"
done
printf '%s\n' \
    'DNS_REDIRECT_SCOPE="${DNS_REDIRECT_SCOPE:-/usr/libexec/dns-redirect-scope}"' \
    'dnsmasq_dns_redirect "$cfg"' >> "$PACKAGE/files/dnsmasq.init"
printf '%s\n' \
    '$(INSTALL_BIN) ./files/dns-redirect-scope.sh $(1)/usr/libexec/dns-redirect-scope' > "$PACKAGE/Makefile"

reject()
{
    if sh "$GATE" "$SOURCE" > "$TMP/reject.log" 2>&1; then
        echo "DNS source contract accepted $1" >&2
        exit 1
    fi
    grep -Fq 'AX6 DNS source contract:' "$TMP/reject.log"
}

sh "$GATE" "$SOURCE"
for path in \
    package/network/services/dnsmasq/files/dns-redirect-scope.sh \
    package/network/services/dnsmasq/files/dnsmasq.init \
    tests/test-dns-redirect-scope.sh \
    tests/fixtures/dns-redirect-scope/uci.sh \
    tests/fixtures/dns-redirect-scope/logger.sh \
    tests/fixtures/dns-redirect-scope/network.sh; do
    mv "$SOURCE/$path" "$TMP/saved"
    reject "missing $path"
    mv "$TMP/saved" "$SOURCE/$path"
done
chmod 644 "$PACKAGE/files/dns-redirect-scope.sh"
reject 'non-executable helper'
chmod 755 "$PACKAGE/files/dns-redirect-scope.sh"
mv "$PACKAGE/files/dns-redirect-scope.sh" "$TMP/saved"
ln -s "$TMP/saved" "$PACKAGE/files/dns-redirect-scope.sh"
reject 'symlink helper'
rm "$PACKAGE/files/dns-redirect-scope.sh"
mv "$TMP/saved" "$PACKAGE/files/dns-redirect-scope.sh"
printf 'if\n' >> "$PACKAGE/files/dns-redirect-scope.sh"
reject 'invalid helper syntax'
printf '#!/bin/sh\nexit 0\n' > "$PACKAGE/files/dns-redirect-scope.sh"
mv "$PACKAGE/Makefile" "$TMP/makefile"
printf '# helper installation omitted\n' > "$PACKAGE/Makefile"
reject 'uninstalled helper'
mv "$TMP/makefile" "$PACKAGE/Makefile"
cp "$PACKAGE/files/dnsmasq.init" "$TMP/init"
sed '/^DNS_REDIRECT_SCOPE=/d' "$TMP/init" > "$PACKAGE/files/dnsmasq.init"
reject 'wrong runtime helper path'
sed '/^dnsmasq_dns_redirect /d' "$TMP/init" > "$PACKAGE/files/dnsmasq.init"
reject 'unwired producer'
cp "$TMP/init" "$PACKAGE/files/dnsmasq.init"
sh "$GATE" "$SOURCE"
echo 'test-ax6-dns-source-contract: PASS (positive and 12 negative cases)'
