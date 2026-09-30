#!/usr/bin/env python3
"""Scope the six reviewed OpenClash fw4 proxy entry sites to LAN/marked lo.

Build-time only. DNS scope remains a separate, pre-existing contract. Reject
upstream entry-point drift instead of silently emitting an unguarded rule.
"""
import argparse
from collections import Counter
from pathlib import Path
import re

BEGIN = '# AX6 proxy ingress scope v1 begin'
END = '# AX6 proxy ingress scope v1 end'
ANCHOR = 'fw4_has_dns_hijack_rule()\n'
START = '   ax6_dns_scope_prepare || return 1\n'
CALL = '   ax6_proxy_scope_prepare || return 1\n'
FIREWALL_CALL = '      set_firewall\n'
FIREWALL_GUARD = '      ax6_proxy_apply_firewall || return $?\n'
R11_OLD = ('         if nft list chain inet fw4 openclash 2>/dev/null | grep -q "counter" ||\n'
           '            nft list chain inet fw4 openclash_mangle 2>/dev/null | grep -q "counter"; then\n')
R11_PROBE = '"${AX6_FW_HEALTH_BIN:-/usr/sbin/ax6-openclash-fw-health}" --probe'
R11_NEW = f'         if {R11_PROBE} >/dev/null 2>&1; then\n'
HELPERS = r'''# AX6 proxy ingress scope v1 begin
ax6_proxy_apply_firewall()
{
   local status=0
   set_firewall || status=$?
   if [ "$status" -ne 0 ]; then
      LOG_ERROR "AX6 firewall installation failed ($status); no success recorded"
   fi
   return "$status"
}

ax6_proxy_scope_prepare()
{
   local rules handles handle chain batch=""
   AX6_PROXY_SCOPE=""
   if ! AX6_PROXY_SCOPE="$("${AX6_PROXY_SCOPE_BIN:-/usr/libexec/ax6-openclash-lan-scope}")"; then
      AX6_PROXY_SCOPE=""
   fi
   if [ -z "$AX6_PROXY_SCOPE" ]; then
      LOG_WARN "AX6 LAN scope unavailable; inbound proxy disabled (marked loopback/OUTPUT unchanged)"
   fi
   # Reconcile only the four owned generic targets. DNS has its own helper.
   for chain in dstnat mangle_prerouting; do
      rules="$(nft -a list chain inet fw4 "$chain" 2>/dev/null)" || {
         LOG_ERROR "AX6 cannot inspect $chain for proxy ingress reconciliation"
         return 1
      }
      handles="$(printf '%s\n' "$rules" | awk '
         {
            rule=$0
            sub(/[[:space:]]comment[[:space:]].*$/, "", rule)
            sub(/[[:space:]]*# handle .*$/, "", rule)
            if (rule !~ /[[:space:]]jump openclash(_v6|_mangle|_mangle_v6)?[[:space:]]*$/) next
            if ($0 !~ /# handle [0-9]+[[:space:]]*$/) exit 1
            sub(/^.*# handle /, ""); sub(/[[:space:]]*$/, ""); print
         }
      ')" || {
         LOG_ERROR "AX6 proxy rule handle format changed"
         return 1
      }
      for handle in $handles; do
         case "$handle" in ''|*[!0-9]*) return 1 ;; esac
         batch="${batch}delete rule inet fw4 $chain handle $handle
"
      done
   done
   if [ -n "$batch" ] && ! printf '%s' "$batch" | nft -f -; then
      LOG_ERROR "AX6 failed to reconcile owned proxy ingress rules"
      return 1
   fi
   return 0
}

ax6_proxy_scope_jump()
{
   local chain="$1" expression="$2"
   if [ -n "$AX6_PROXY_SCOPE" ]; then
      nft add rule inet fw4 "$chain" "$AX6_PROXY_SCOPE" "$expression" || return $?
   fi
   # OUTPUT marks router-origin traffic before policy routing through lo.
   # This exception is not an external ingress or a blanket lo allowlist.
   if [ "$chain" = mangle_prerouting ]; then
      nft add rule inet fw4 "$chain" iifname lo meta mark "$PROXY_FWMARK" "$expression" || return $?
   fi
   return 0
}
# AX6 proxy ingress scope v1 end

'''
ENTRIES = Counter({
    ('dstnat', 'meta nfproto {ipv4} ip protocol tcp counter jump openclash'): 1,
    ('dstnat', 'ip6 nexthdr {tcp} counter jump openclash_v6'): 1,
    ('mangle_prerouting', 'meta nfproto {ipv4} ip protocol udp counter jump openclash_mangle'): 2,
    ('mangle_prerouting', 'meta nfproto {ipv4} counter jump openclash_mangle'): 1,
    ('mangle_prerouting', 'meta nfproto {ipv6} counter jump openclash_mangle_v6'): 1,
})
RAW = re.compile(r"^(\s*)nft 'add rule inet fw4 (dstnat|mangle_prerouting) (.*)'$")
SCOPED = re.compile(r"^(\s*)ax6_proxy_scope_jump '(dstnat|mangle_prerouting)' '(.*)' \|\| return 1$")
TARGET = re.compile(r'\b(?:jump|goto) (openclash(?:_v6|_mangle|_mangle_v6)?)(?:\s|[\'\"]|$)')


def firewall_callers(text, scoped):
    expected = FIREWALL_GUARD if scoped else FIREWALL_CALL
    calls = [line for line in text.replace(HELPERS, '').splitlines(keepends=True)
             if re.match(r'^\s*(?:set_firewall|ax6_proxy_apply_firewall)(?:\s|$)', line)]
    if calls != [expected] * 4:
        raise ValueError('Firewall caller contract changed or lost failure propagation')


def entries(text, scoped=False):
    found = Counter()
    # Do not mistake the reconciliation awk pattern for a generated rule.
    without_helper = text.replace(HELPERS, '')
    for line in without_helper.splitlines():
        if line.lstrip().startswith('#'):
            continue
        base_rule = 'nft ' in line and re.search(r'rule inet fw4 (dstnat|mangle_prerouting)\b', line)
        dns_rule = 'OpenClash DNS Hijack' in line or 'jump openclash_dns_redirect' in line
        if not TARGET.search(line) and not (base_rule and not dns_rule):
            continue
        match = (SCOPED if scoped else RAW).fullmatch(line)
        if match is None:
            raise ValueError(f'Unreviewed proxy ingress site: {line.strip()}')
        found[(match[2], match[3])] += 1
    if found != ENTRIES:
        raise ValueError(f'Proxy ingress contract changed: {found!r}')


def check(text):
    if text.count(HELPERS) != 1 or text.count(START + CALL) != 1:
        raise ValueError('Proxy scope helper or ordering changed')
    firewall_callers(text, scoped=True)
    entries(text, scoped=True)
    if 'AX6 R-11 v2' in text and (text.count(R11_NEW) != 1 or R11_OLD in text):
        raise ValueError('R-11 must share the exact read-only ingress health probe')


def transform(text):
    if 'AX6 R-11 v2' in text and R11_NEW not in text:
        if text.count(R11_OLD) != 1:
            raise ValueError('R-11 rate-limit sentinel drifted')
        text = text.replace(R11_OLD, R11_NEW)
    if BEGIN in text or END in text:
        check(text)
        return text
    if text.count(ANCHOR) != 1 or text.count(START) != 1:
        raise ValueError('DNS scope must be installed first; upstream anchor drifted')
    firewall_callers(text, scoped=False)
    entries(text)
    lines = []
    for line in text.splitlines(keepends=True):
        match = RAW.fullmatch(line.rstrip('\n'))
        if match and (match[2], match[3]) in ENTRIES:
            line = (f"{match[1]}ax6_proxy_scope_jump '{match[2]}' '{match[3]}'"
                    ' || return 1\n')
        lines.append(line)
    result = ''.join(lines).replace(ANCHOR, HELPERS + ANCHOR).replace(START, START + CALL)
    result = result.replace(FIREWALL_CALL, FIREWALL_GUARD)
    check(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('apply', 'check'))
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    original = args.target.read_text()
    try:
        if args.mode == 'check':
            check(original)
        else:
            result = transform(original)
            if result != original:
                args.target.write_text(result)
    except ValueError as error:
        parser.exit(2, f'AX6 OpenClash proxy scope: {error}\n')
    print(f'AX6 OpenClash proxy scope {args.mode}: PASS (6 entry sites)')


if __name__ == '__main__':
    main()
