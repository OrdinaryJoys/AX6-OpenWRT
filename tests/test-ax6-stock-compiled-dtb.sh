#!/bin/sh

set -eu

repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
gate="$repo_root/AX6-IPQ/scripts/check-ax6-stock-compiled-dtb.sh"
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

command -v dtc >/dev/null 2>&1 || {
	echo "dtc is required for the compiled DTB gate test" >&2
	exit 69
}

cat > "$tmp_dir/good.dts" <<'EOF'
/dts-v1/;

/ {
	aliases {
		ethernet1 = &dp2;
		ethernet2 = &dp3;
		ethernet3 = &dp4;
		ethernet4 = &dp5;
	};

	soc@0 {
		wifi@c0000000 {
			qcom,nss-wifili-tx-desc-count = <16384>;
		};
		dp2: dp2@3a001200 {};
		dp3: dp3@3a001400 {};
		dp4: dp4@3a001600 {};
		dp5: dp5@3a001800 {};
	};
};
EOF

cat > "$tmp_dir/bad.dts" <<'EOF'
/dts-v1/;

/ {
	aliases {
		ethernet1 = &dp2;
		ethernet2 = &dp3;
		ethernet3 = &dp4;
		ethernet4 = &dp5;
	};

	macaddr_dp2: macaddr-dp2 {};

	soc@0 {
		wifi@c0000000 {
			qcom,nss-wifili-tx-desc-count = <16384>;
		};
		dp2: dp2@3a001200 {
			nvmem-cells = <&macaddr_dp2>;
			nvmem-cell-names = "mac-address";
		};
		dp3: dp3@3a001400 {};
		dp4: dp4@3a001600 {};
		dp5: dp5@3a001800 {};
	};
};
EOF

sed 's/qcom,nss-wifili-tx-desc-count = <16384>/qcom,nss-wifili-tx-desc-count = <8192>/' \
	"$tmp_dir/good.dts" > "$tmp_dir/bad-desc.dts"

dtc -q -I dts -O dtb -o "$tmp_dir/good.dtb" "$tmp_dir/good.dts"
dtc -q -I dts -O dtb -o "$tmp_dir/bad.dtb" "$tmp_dir/bad.dts"
dtc -q -I dts -O dtb -o "$tmp_dir/bad-desc.dtb" "$tmp_dir/bad-desc.dts"

"$gate" "$tmp_dir/good.dtb" >/dev/null

if "$gate" "$tmp_dir/bad.dtb" >"$tmp_dir/bad.out" 2>"$tmp_dir/bad.err"; then
	echo "compiled DTB gate accepted a dangling nvmem reference" >&2
	exit 1
fi
grep -Fq 'retains forbidden nvmem-cells' "$tmp_dir/bad.err"

if "$gate" "$tmp_dir/bad-desc.dtb" >"$tmp_dir/bad-desc.out" 2>"$tmp_dir/bad-desc.err"; then
	echo "compiled DTB gate accepted the upstream-default descriptor count" >&2
	exit 1
fi
grep -Fq 'unexpected AX6 NSS WiFi TX descriptor count: 8192' "$tmp_dir/bad-desc.err"

echo "test-ax6-stock-compiled-dtb: PASS"
