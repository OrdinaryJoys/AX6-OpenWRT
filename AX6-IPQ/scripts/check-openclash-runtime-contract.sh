#!/bin/sh
set -eu

init_script="${1:-}"
[ -n "$init_script" ] && [ -r "$init_script" ] || {
    echo "usage: $0 <OpenClash init script>" >&2
    exit 64
}

require_fixed() {
    description="$1"
    pattern="$2"
    grep -Fq "$pattern" "$init_script" || {
        echo "OpenClash runtime contract missing: $description" >&2
        exit 1
    }
}

require_fixed "dnsmasq redirect function" 'change_dnsmasq()'
require_fixed "dnsmasq revert function" 'revert_dnsmasq()'
# shellcheck disable=SC2016 # Match upstream's literal shell expression.
require_fixed "local DNS upstream" 'uci -q add_list dhcp.@dnsmasq[0].server=127.0.0.1#"$dns_port"'
require_fixed "redirect noresolv ownership" 'uci -q set dhcp.@dnsmasq[0].noresolv=1'
# shellcheck disable=SC2016 # Match upstream's literal shell expression.
require_fixed "disabled-mode residual redirect cleanup" 'uci -q del_list dhcp.@dnsmasq[0].server="127.0.0.1#$dns_port"'
require_fixed "dnsmasq noresolv restoration" 'uci -q set dhcp.@dnsmasq[0].noresolv=0'
require_fixed "fw4 DNS hijack family check" 'fw4_has_dns_hijack_rule()'
require_fixed "AX6 ZeroTier self-proxy bypass hook" '/usr/bin/ax6-openclash-zerotier-bypass'
require_fixed "AX6 ROM core copy-up guard" '# AX6: avoid copying the immutable ROM core into overlayfs for metadata-only changes.'
require_fixed "resolved core ownership probe" 'ls -ln "$meta_core_path"'

# shellcheck disable=SC2016 # Match upstream's literal shell expression.
local_upstream_count="$(grep -Fc 'uci -q add_list dhcp.@dnsmasq[0].server=127.0.0.1#"$dns_port"' "$init_script")"
[ "$local_upstream_count" -eq 1 ] || {
    echo "OpenClash runtime contract has $local_upstream_count local DNS upstream writers; expected exactly one" >&2
    exit 1
}

if awk '
    /^[[:alnum:]_]+\(\)([[:space:]]*\{)?[[:space:]]*$/ {
        if ($0 ~ /^start_run_core\(\)([[:space:]]*\{)?[[:space:]]*$/) in_start = 1
        else if (in_start) in_start = 0
    }
    in_start && $0 == "   chown root:root \"$CLASH\"" { bad++ }
    END { exit bad ? 0 : 1 }
' "$init_script"; then
    echo "OpenClash runtime contract still has an unconditional start_run_core chown" >&2
    exit 1
fi

echo "OpenClash runtime contract gate: PASS"
