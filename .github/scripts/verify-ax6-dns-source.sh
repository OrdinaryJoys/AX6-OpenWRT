#!/bin/sh
# Shared DIY must never install a scoped OpenClash without its source contract.
# Read files only; do not source init scripts or run network commands.
set -eu

[ "$#" -eq 1 ] || { echo "usage: $0 <source-root>" >&2; exit 64; }
source_root=$1
package="$source_root/package/network/services/dnsmasq"
fail()
{
    echo "AX6 DNS source contract: $1; use a reviewed source candidate" >&2
    exit 1
}

for path in \
    package/network/services/dnsmasq/files/dns-redirect-scope.sh \
    package/network/services/dnsmasq/files/dnsmasq.init \
    tests/test-dns-redirect-scope.sh \
    tests/fixtures/dns-redirect-scope/uci.sh \
    tests/fixtures/dns-redirect-scope/logger.sh; do
    file="$source_root/$path"
    [ -f "$file" ] && [ ! -L "$file" ] && [ -x "$file" ] ||
        fail "missing regular executable $path"
    sh -n "$file" || fail "invalid shell syntax in $path"
done
network_fixture="$source_root/tests/fixtures/dns-redirect-scope/network.sh"
[ -f "$network_fixture" ] && [ ! -L "$network_fixture" ] ||
    fail 'missing network resolver fixture'
sh -n "$network_fixture" || fail 'invalid network resolver fixture'

# shellcheck disable=SC2016 # Literal source contracts, not runtime expansion.
grep -Fq '$(INSTALL_BIN) ./files/dns-redirect-scope.sh $(1)/usr/libexec/dns-redirect-scope' \
    "$package/Makefile" || fail 'dnsmasq package does not install its scope helper'
# shellcheck disable=SC2016
grep -Fq 'DNS_REDIRECT_SCOPE="${DNS_REDIRECT_SCOPE:-/usr/libexec/dns-redirect-scope}"' \
    "$package/files/dnsmasq.init" || fail 'dnsmasq uses an unknown helper path'
# shellcheck disable=SC2016
grep -Fq 'dnsmasq_dns_redirect "$cfg"' "$package/files/dnsmasq.init" ||
    fail 'dnsmasq does not call its scoped redirect producer'
echo 'AX6 DNS source contract: PASS (packaging prerequisites, not runtime validation)'
