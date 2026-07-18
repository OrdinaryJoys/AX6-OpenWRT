#!/bin/sh

set -eu

source_root="${1:-}"

if [ -z "$source_root" ] || [ ! -d "$source_root" ]; then
	echo "usage: $0 <openwrt source root>" >&2
	exit 64
fi

stock="$source_root/target/linux/qualcommax/dts/ipq8071-ax6-stock.dts"
parent="$source_root/target/linux/qualcommax/dts/ipq8071-xiaomi.dtsi"

for file in "$stock" "$parent"; do
	[ -r "$file" ] || {
		echo "required AX6 DTS is missing: $file" >&2
		exit 1
	}
done

[ "$(grep -Ec 'ethernet[1-4][[:space:]]*=[[:space:]]*&dp[2-5];' "$stock")" -eq 4 ] || {
	echo "AX6 stock DTS must retain all four U-Boot ethernet aliases" >&2
	exit 1
}

grep -Fq 'compatible = "qcom,smem-part";' "$stock" || {
	echo "AX6 stock DTS must continue to use the runtime SMEM partition table" >&2
	exit 1
}

if grep -Eq 'partition-0-art|nvmem-layout|macaddr_dp[2-5]' "$stock"; then
	echo "AX6 stock DTS must not place nvmem cells under bootloader-rewritten SMEM partitions" >&2
	exit 1
fi

[ "$(grep -Fc '/delete-property/ nvmem-cells;' "$stock")" -eq 4 ] || {
	echo "AX6 stock DTS must delete all four inherited nvmem-cells references" >&2
	exit 1
}
[ "$(grep -Fc '/delete-property/ nvmem-cell-names;' "$stock")" -eq 4 ] || {
	echo "AX6 stock DTS must delete all four inherited nvmem-cell-names references" >&2
	exit 1
}

for port in 2 3 4 5; do
	grep -Fq "&dp$port {" "$stock" || {
		echo "AX6 stock DTS is missing the dp$port override" >&2
		exit 1
	}
done

grep -Fq 'macaddr_dp2: macaddr@6' "$parent" || {
	echo "parent Xiaomi DTS unexpectedly lost the non-stock nvmem layout" >&2
	exit 1
}

echo "AX6 stock SMEM/nvmem compatibility gate: PASS"
