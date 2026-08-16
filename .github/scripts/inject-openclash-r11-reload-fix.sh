#!/bin/sh
# AX6 R-11 fix injector for the OpenClash init script (upstream-tracked).
#
# R-11: after any fw4/network reload the OpenClash nft rules were left wiped.
# Root causes in upstream reload_service():
#   1. The 10-per-300s rate limit SKIPPED the re-injection entirely when the
#      limit was reached, leaving the ruleset permanently broken.
#   2. The re-injection ran only through the backgrounded check_core_status
#      tail, which races the next fw4 reload; observed state: openclash chains
#      present with zero rules after the reload fired successfully.
#
# This injector makes the reload path self-healing:
#   - the rate-limit skip now only skips while the rules are actually present
#     (sentinel check on the openclash/openclash_mangle chains);
#   - set_firewall is called synchronously in the "firewall" and "manual"
#     reload branches before the background TUN/cfg check.
#
# Idempotent; fails hard when the upstream anchor text moved.
set -eu

[ "$#" -eq 1 ] || {
	echo "usage: $0 <openclash-init-script>" >&2
	exit 64
}

target="$1"
[ -f "$target" ] || {
	echo "OpenClash init script is missing: $target" >&2
	exit 2
}

grep -Fq "AX6 R-11 fix" "$target" && exit 0

tmp="${target}.ax6r11.$$"
trap 'rm -f "$tmp"' EXIT HUP INT TERM
cp -p "$target" "$tmp"

if ! awk '
	BEGIN { prev = ""; fw_branch = 0; swallow = 0 }

	{
		if (swallow > 0) {
			if (swallow == 2 && $0 !~ /^         LOG_OUT /) failed = 1
			if (swallow == 1 && $0 != "         exit 0") failed = 1
			swallow--
			next
		}

		# 1) Sentinel-guarded rate-limit skip.
		if ($0 == "      if [ \"$RELOAD_COUNT\" -ge \"$MAX_RELOAD\" ]; then") {
			print $0
			print "         # AX6 R-11 fix: a rate-limit skip must never leave the ruleset wiped."
			print "         # fw4 rebuilds the ruleset from scratch on every reload, so when the"
			print "         # OpenClash chains are missing the rules MUST be restored even if the"
			print "         # reload rate limit is reached. Only skip when rules are present."
			print "         if nft list chain inet fw4 openclash 2>/dev/null | grep -q \"counter\" ||"
			print "            nft list chain inet fw4 openclash_mangle 2>/dev/null | grep -q \"counter\"; then"
			print "            LOG_OUT \"【${CUR_RELOAD_NUM}/$MAX_RELOAD】Skip Reload OpenClash Firewall Rules Until 5 Minutes Later...\""
			print "            exit 0"
			print "         fi"
			print "         LOG_OUT \"【${CUR_RELOAD_NUM}/$MAX_RELOAD】OpenClash Rules Missing After fw4 Reload, Force Restore...\""
			swallow = 2
			saw_guard = 1
			next
		}

		# 2) Track the firewall-reload branch (its LOG_OUT is unique).
		if ($0 == "      LOG_OUT \"【${CUR_RELOAD_NUM}/$MAX_RELOAD】Reload OpenClash Firewall Rules...\"") {
			fw_branch = 1
		}

		# 3) Synchronous injection before the background TUN/cfg check.
		if ($0 == "      check_core_status &") {
			if (fw_branch) {
				print "      # AX6 R-11 fix: inject synchronously. The upstream path relied on the"
				print "      # background check_core_status tail, which races the next fw4 reload and"
				print "      # can leave the ruleset empty (observed: chains exist with zero rules)."
				print "      set_firewall"
				print $0
				fw_branch = 0
				saw_fw_sync = 1
				prev = $0
				next
			}
			if (prev == "      do_run_mode") {
				print "      set_firewall"
				print $0
				saw_manual_sync = 1
				prev = $0
				next
			}
		}

		print
		prev = $0
	}

	END {
		if (!saw_guard || !saw_fw_sync || !saw_manual_sync || failed) exit 42
	}
' "$target" > "$tmp"; then
	echo "OpenClash R-11 anchors changed upstream" >&2
	exit 2
fi

grep -Fq "AX6 R-11 fix" "$tmp" || {
	echo "OpenClash R-11 injection failed" >&2
	exit 2
}

mv "$tmp" "$target"
trap - EXIT HUP INT TERM
