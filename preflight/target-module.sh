#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
evidence="$GITHUB_WORKSPACE/module-preflight-evidence"
mkdir -p "$evidence"
trap 'rc=$?; printf "%s\n" "$rc" > "$evidence/exit-code.txt"' EXIT
cp "$GITHUB_WORKSPACE/.github/ax6-nss-lock.env" "$evidence/SOURCE-LOCK.env"
cd "$GITHUB_WORKSPACE/openwrt"
jobs=$(nproc)
[[ "$jobs" =~ ^[1-9][0-9]*$ ]]
grep -Fx 'CONFIG_TARGET_qualcommax_ipq807x_DEVICE_redmi_ax6-stock=y' .config
grep -Fx '# CONFIG_KERNEL_DYNAMIC_DEBUG is not set' .config
cp .config "$evidence/stock.config"
make -j"$jobs" target/linux/prepare V=s 2>&1 | tee "$evidence/kernel-prepare.log"
make -j1 package/qca-nss/qca-nss-drv/prepare V=s 2>&1 | tee "$evidence/driver-prepare.log"
target=build_dir/target-aarch64_cortex-a53_musl/linux-qualcommax_ipq807x
mapfile -t drivers < <(find "$target" -maxdepth 1 -type d -name 'qca-nss-drv-*')
test "${#drivers[@]}" = 1
driver=${drivers[0]}
kernel=$target/linux-6.18.38
base="$GITHUB_WORKSPACE"
python3 -B "$base/.github/scripts/verify-nss-drv29.py" --source-root . --driver "$driver" \
  --drv27-source-root "$base/core-drv27-source" --kernel "$kernel" --cc clang \
  --output "$RUNNER_TEMP/ax6-module-drv29-gate" 2>&1 | tee "$evidence/drv29-gate.log"
cp "$RUNNER_TEMP/ax6-module-drv29-gate/RESULTS.json" "$evidence/DRV29-HOST.json"
cp "$RUNNER_TEMP/ax6-module-drv29-gate/PREPARED-driver.json" "$evidence/PREPARED-driver.json"
toolchain=staging_dir/toolchain-aarch64_cortex-a53_gcc-14.3.0_musl
export PATH="$PWD/$toolchain/bin:$PATH"
compiler="$PWD/$toolchain/bin/aarch64-openwrt-linux-musl-gcc"
test "$("$compiler" -dumpfullversion)" = 14.3.0
"$compiler" --version > "$evidence/target-gcc.txt"
python3 -B "$base/preflight/gcc-canary.py" "$driver" "$compiler" "$evidence" \
  2>&1 | tee "$evidence/gcc-canary.log"

make -j"$jobs" target/linux/compile V=s 2>&1 | tee "$evidence/kernel-compile.log"
cp "$kernel/.config" "$evidence/kernel.config"
if grep -Eq '^CONFIG_DYNAMIC_DEBUG=(y|m)$' "$kernel/.config"; then
    echo 'Stock kernel must not enable dynamic debug'
    exit 1
fi
# These are the package's real Kbuild dependencies and staging recipes.
for package in qca-nss-phy qca-ssdk qca-nss-dp qca-nss-drv; do
    make -j"$jobs" "package/qca-nss/$package/compile" V=s 2>&1 |
      tee "$evidence/$package-compile.log"
done
module=$driver/qca-nss-drv.ko
test -s "$module"
test -s "$driver/nss_conn_table.o"
test -s "$driver/nss_core.o"
grep -F -- '-DNSS_DEBUG_LEVEL=0' "$driver/.nss_core.o.cmd" | grep -F -- '-Werror' > "$evidence/nss_core.o.cmd"
cp "$module" "$evidence/"
"$toolchain/bin/aarch64-openwrt-linux-musl-readelf" -h "$module" > "$evidence/module-elf.txt"
grep -Eq 'Machine:[[:space:]]+AArch64$' "$evidence/module-elf.txt"
grep -Eq 'Type:[[:space:]]+REL ' "$evidence/module-elf.txt"
test "$(sha256sum "$driver/nss_core.c" | cut -d' ' -f1)" = 2ffd9f7c12cf21a77b5413b85ffccb0669dab35bd9122c07c5580b0c011f2680
test -z "$(find bin -type f \( -name '*sysupgrade*' -o -name '*factory.ubi' -o -name '*initramfs*.itb' \) -print)"
(cd "$evidence"; sha256sum qca-nss-drv.ko stock.config kernel.config nss_core.o.cmd > SHA256SUMS)
printf '%s\n' 'PASS_REAL_STOCK_TARGET_MODULE_NO_FIRMWARE' | tee "$evidence/result.txt"
