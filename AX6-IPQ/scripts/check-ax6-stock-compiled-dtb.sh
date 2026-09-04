#!/bin/sh

set -eu

if [ "$#" -lt 1 ]; then
	echo "usage: $0 <compiled AX6 stock DTB> [...]" >&2
	exit 64
fi

command -v fdtget >/dev/null 2>&1 || {
	echo "fdtget is required to inspect compiled device trees" >&2
	exit 69
}

for dtb in "$@"; do
	[ -r "$dtb" ] || {
		echo "compiled AX6 stock DTB is unreadable: $dtb" >&2
		exit 1
	}

	wifi_node=/soc@0/wifi@c0000000
	tx_desc_count=$(fdtget -t u "$dtb" "$wifi_node" \
		qcom,nss-wifili-tx-desc-count 2>/dev/null) || {
		echo "$dtb is missing the AX6 NSS WiFi TX descriptor override" >&2
		exit 1
	}
	[ "$tx_desc_count" = 16384 ] || {
		echo "$dtb has unexpected AX6 NSS WiFi TX descriptor count: $tx_desc_count" >&2
		exit 1
	}

	for port in 2 3 4 5; do
		case "$port" in
			2) address=3a001200 ;;
			3) address=3a001400 ;;
			4) address=3a001600 ;;
			5) address=3a001800 ;;
		esac
		node="/soc@0/dp$port@$address"
		alias="ethernet$((port - 1))"
		expected="$node"
		actual=$(fdtget -t s "$dtb" /aliases "$alias" 2>/dev/null) || {
			echo "$dtb is missing the $alias U-Boot MAC alias" >&2
			exit 1
		}
		[ "$actual" = "$expected" ] || {
			echo "$dtb has an unexpected $alias target: $actual" >&2
			exit 1
		}

		for property in nvmem-cells nvmem-cell-names; do
			if fdtget "$dtb" "$node" "$property" >/dev/null 2>&1; then
				echo "$dtb retains forbidden $property on $node" >&2
				exit 1
			fi
		done
	done
done

echo "AX6 stock compiled DTB compatibility gate: PASS"
