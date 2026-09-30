#!/usr/bin/env python3
"""Constrain OpenClash's fw4 DNS redirects; reject upstream anchor drift.

This is a build-time transformer, never a router-side firewall executor.
Only the two prerouting DNS redirect modes are covered. Generic proxy/TProxy
rules and router-origin OUTPUT rules deliberately retain their own policy.
"""
import argparse
import re
from pathlib import Path

BEGIN = "# AX6 DNS ingress scope v1 begin"
END = "# AX6 DNS ingress scope v1 end"
HELPERS = r'''# AX6 DNS ingress scope v1 begin
ax6_dns_scope_prepare()
{
   local rules handles handle chain batch=""
   AX6_DNS_SCOPE=""
   if ! AX6_DNS_SCOPE="$("${DNS_REDIRECT_SCOPE_BIN:-/usr/libexec/dns-redirect-scope}")"; then
      AX6_DNS_SCOPE=""
   fi
   if [ -z "$AX6_DNS_SCOPE" ]; then
      LOG_WARN "AX6 DNS ingress scope unavailable; skip inbound DNS redirects (OUTPUT unchanged)"
   fi

   # Remove only our owned DNS rules, including pre-fix/unscoped rules and
   # stale allowlist members. The existing comment-only probe must not skip
   # rebuilding them. Do not touch OUTPUT or third-party redirects.
   for chain in dstnat openclash_dns_redirect; do
      if ! rules="$(nft -a list chain inet fw4 "$chain" 2>/dev/null)"; then
         [ "$chain" = openclash_dns_redirect ] && continue
         LOG_ERROR "AX6 cannot inspect dstnat for DNS scope reconciliation"
         return 1
      fi
      handles="$(printf '%s\n' "$rules" | awk '
         /dport 53([[:space:]]|$)/ &&
         (/comment "OpenClash DNS Hijack"/ || /jump openclash_dns_redirect([[:space:]]|$)/) {
            if ($0 !~ /# handle [0-9]+[[:space:]]*$/) exit 1
            sub(/^.*# handle /, ""); sub(/[[:space:]]*$/, ""); print
         }
      ')" || {
         LOG_ERROR "AX6 DNS rule handle format changed; refusing partial reconciliation"
         return 1
      }
      for handle in $handles; do
         case "$handle" in ''|*[!0-9]*) return 1 ;; esac
         batch="${batch}delete rule inet fw4 $chain handle $handle
"
      done
   done
   # The delete batch is atomic; the surrounding upstream set_firewall is
   # not. No claim of zero interruption is made for a real reload.
   if [ -n "$batch" ] && ! printf '%s' "$batch" | nft -f -; then
      LOG_ERROR "AX6 failed to reconcile owned DNS rules; abort firewall setup"
      return 1
   fi
   return 0
}
# AX6 DNS ingress scope v1 end

'''
ANCHOR = "fw4_has_dns_hijack_rule()\n"
START = '   LOG_TIP "Firewall4 was Detected, Use NFTABLE Rules..."\n'
CALL = '   ax6_dns_scope_prepare || return 1\n'
GUARD = '[ -n "$AX6_DNS_SCOPE" ] && '
SCOPE = '"$AX6_DNS_SCOPE" '
RULE = re.compile(r"^(?P<indent>\s*)(?P<guard>\[ -n \"\$AX6_DNS_SCOPE\" \] && )?nft (?P<body>.*)$")
PREFIX = re.compile(r"^((?:insert|add) rule inet fw4 (?:dstnat|openclash_dns_redirect)(?: position 0)? )")


def relevant(line):
    match = RULE.fullmatch(line)
    if not match:
        return None
    body = match['body']
    if body.startswith("'") and body.endswith("'"):
        body = body[1:-1]
    if not re.match(r'^(?:add|insert) rule ', body):
        return None
    owned = 'OpenClash DNS Hijack' in body or 'jump openclash_dns_redirect' in body
    # Recognize owned rules before accepting their exact grammar: a moving
    # upstream might add `udp dport 53`, a new chain, or accidentally use 5353.
    # None may silently escape a guard merely because it misses our old regex.
    if 'rule inet fw4 nat_output ' in body:
        return None
    if owned and not re.search(r'\bth dport 53(?:\s|$)', body):
        raise ValueError('Owned inbound DNS rule uses an unreviewed protocol/port grammar')
    if not owned and not re.search(r'\b(?:th|tcp|udp) dport 53(?:\s|$)', body):
        return None
    if not PREFIX.match(body):
        if owned:
            raise ValueError('Owned DNS rule moved to an unreviewed chain/table')
        return None
    if 'OpenClash DNS Hijack' not in body and 'jump openclash_dns_redirect' not in body:
        raise ValueError('Unrecognized inbound DNS rule ownership')
    return match, body


def counts(text):
    found = [result for line in text.splitlines() if (result := relevant(line))]
    direct = sum('redirect to' in b and 'rule inet fw4 dstnat ' in b for _, b in found)
    mode2 = sum('redirect to' in b and 'rule inet fw4 openclash_dns_redirect ' in b for _, b in found)
    jump = sum('jump openclash_dns_redirect' in b for _, b in found)
    if (direct, mode2, jump) != (6, 6, 2):
        raise ValueError(f'Expected 6 direct / 6 mode2 / 2 jump rules, got {(direct, mode2, jump)}')
    return found


def check(text):
    if text.count(HELPERS) != 1 or text.count(START + CALL) != 1:
        raise ValueError('DNS scope helper/setup anchor is absent or changed')
    for match, body in counts(text):
        if not match['guard'] or not PREFIX.sub('', body, count=1).startswith(SCOPE):
            raise ValueError('Inbound DNS rule lacks nonempty guard or exact ingress scope')
    output = [l for l in text.splitlines() if 'nft ' in l and 'rule inet fw4 nat_output ' in l and re.search(r'\bth dport 53(?:\s|$)', l)]
    if len(output) != 4 or any('AX6_DNS_SCOPE' in l or 'iifname' in l for l in output):
        raise ValueError('Router-origin DNS OUTPUT rules drifted')


def transform(text):
    if BEGIN in text or END in text:
        check(text)
        return text
    if text.count(ANCHOR) != 1 or text.count(START) != 1:
        raise ValueError('OpenClash fw4 anchors changed')
    counts(text)
    lines = []
    for line in text.splitlines(keepends=True):
        found = relevant(line.rstrip('\n'))
        if found:
            match, body = found
            body = PREFIX.sub(lambda m: m[0] + SCOPE, body, count=1)
            line = match['indent'] + GUARD + 'nft ' + body + '\n'
        lines.append(line)
    result = ''.join(lines).replace(ANCHOR, HELPERS + ANCHOR).replace(START, START + CALL)
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
        parser.exit(2, f'AX6 OpenClash DNS scope: {error}\n')
    print(f'AX6 OpenClash DNS scope {args.mode}: PASS (12 redirect + 2 jump; OUTPUT unchanged)')


if __name__ == '__main__':
    main()
