#!/bin/sh
set -eu

[ "$#" -eq 2 ] || {
	echo "usage: $0 <apply|check> <openclash-init-script>" >&2
	exit 64
}

mode="$1"
target="$2"
marker='# AX6: avoid copying the immutable ROM core into overlayfs for metadata-only changes.'

[ "$mode" = apply ] || [ "$mode" = check ] || {
	echo "unknown mode: $mode" >&2
	exit 64
}
[ -f "$target" ] || {
	echo "OpenClash init script is missing: $target" >&2
	exit 2
}

check_contract() {
	check_target="${1:-$target}"
	awk -v marker="$marker" '
		/^[[:alnum:]_]+\(\)([[:space:]]*\{)?[[:space:]]*$/ {
			if ($0 ~ /^start_run_core\(\)([[:space:]]*\{)?[[:space:]]*$/) {
				in_start = 1
				start_count++
			} else if (in_start) {
				in_start = 0
			}
		}
		in_start {
			if ($0 == marker) marker_count++
			if ($0 == "   chown root:root \"$CLASH\"") unconditional_count++
			if ($0 == "      chown root:root \"$CLASH\"") guarded_chown_count++
			if ($0 == "   if [ -e \"$meta_core_path\" ] &&") exists_count++
			if (index($0, "ls -ln \"$meta_core_path\"") &&
			    index($0, "!= \"0:0\"")) owner_count++
		}
		END {
			if (start_count != 1 || marker_count != 1 ||
			    unconditional_count != 0 || guarded_chown_count != 1 ||
			    exists_count != 1 || owner_count != 1) {
				printf "start=%d marker=%d unconditional=%d guarded=%d exists=%d owner=%d\n",
				    start_count, marker_count, unconditional_count,
				    guarded_chown_count, exists_count, owner_count > "/dev/stderr"
				exit 1
			}
		}
	' "$check_target"
}

if [ "$mode" = check ]; then
	check_contract || {
		echo "OpenClash ROM core ownership guard contract is missing or malformed" >&2
		exit 2
	}
	echo "OpenClash ROM core ownership guard: PASS"
	exit 0
fi

if grep -Fq "$marker" "$target"; then
	check_contract || {
		echo "OpenClash ROM core ownership guard marker exists but the contract is malformed" >&2
		exit 2
	}
	exit 0
fi

tmp="${target}.ax6.$$"
trap 'rm -f "$tmp"' EXIT HUP INT TERM
cp -p "$target" "$tmp"

if ! awk -v marker="$marker" '
	/^[[:alnum:]_]+\(\)([[:space:]]*\{)?[[:space:]]*$/ {
		if ($0 ~ /^start_run_core\(\)([[:space:]]*\{)?[[:space:]]*$/) {
			in_start = 1
			start_count++
		} else if (in_start) {
			in_start = 0
		}
	}
	in_start && $0 == "   chown root:root \"$CLASH\"" {
		print marker
		print "   if [ -e \"$meta_core_path\" ] &&"
		print "      [ \"$(ls -ln \"$meta_core_path\" 2>/dev/null | awk '\''{ print $3 \":\" $4 }'\'')\" != \"0:0\" ]; then"
		print "      chown root:root \"$CLASH\""
		print "   fi"
		replaced++
		next
	}
	{ print }
	END {
		if (start_count != 1 || replaced != 1) exit 42
	}
' "$target" > "$tmp"; then
	echo "OpenClash start_run_core ownership hook changed upstream" >&2
	exit 2
fi

check_contract "$tmp" || {
	echo "OpenClash ROM core ownership guard injection failed" >&2
	exit 2
}
mv "$tmp" "$target"
trap - EXIT HUP INT TERM
