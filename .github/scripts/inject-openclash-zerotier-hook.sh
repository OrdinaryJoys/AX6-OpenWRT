#!/bin/sh
set -eu

[ "$#" -eq 1 ] || {
	echo "usage: $0 <openclash-init-script>" >&2
	exit 64
}

target="$1"
helper=/usr/bin/ax6-openclash-zerotier-bypass
[ -f "$target" ] || {
	echo "OpenClash init script is missing: $target" >&2
	exit 2
}

grep -Fq "$helper" "$target" && exit 0

tmp="${target}.ax6.$$"
trap 'rm -f "$tmp"' EXIT HUP INT TERM
cp -p "$target" "$tmp"

if ! awk '
	{
		print
		if ($0 == "   /etc/openclash/custom/openclash_custom_firewall_rules.sh") {
			marker = 1
		} else if (marker && $0 == "fi") {
			print ""
			print "if [ -x /usr/bin/ax6-openclash-zerotier-bypass ]; then"
			print "   /usr/bin/ax6-openclash-zerotier-bypass || LOG_ERROR \"Set ZeroTier self-proxy bypass failed\""
			print "fi"
			inserted = 1
			marker = 0
		}
	}
	END { if (!inserted) exit 42 }
' "$target" > "$tmp"; then
	echo "OpenClash custom-firewall hook point changed upstream" >&2
	exit 2
fi

grep -Fq "$helper" "$tmp" || {
	echo "OpenClash ZeroTier hook injection failed" >&2
	exit 2
}
mv "$tmp" "$target"
trap - EXIT HUP INT TERM
