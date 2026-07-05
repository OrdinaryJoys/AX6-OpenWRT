#!/bin/bash
set -eo pipefail

# Add packages from the verified build lock exported by the workflow.
clone_locked() {
  url="$1"
  commit="$2"
  destination="$3"
  [ -n "$url" ] && [ -n "$commit" ] || {
    echo "[diy.sh] missing locked source for $destination" >&2
    exit 2
  }
  rm -rf "$destination"
  git init -q "$destination"
  git -C "$destination" remote add origin "$url"
  git -C "$destination" fetch -q --depth 1 origin "$commit"
  git -C "$destination" checkout -q --detach FETCH_HEAD
  [ "$(git -C "$destination" rev-parse HEAD)" = "$commit" ] || {
    echo "[diy.sh] locked source mismatch for $destination" >&2
    exit 2
  }
}

clone_tracking() {
  url="$1"
  ref="$2"
  destination="$3"
  [ -n "$url" ] && [ -n "$ref" ] || {
    echo "[diy.sh] missing tracked source for $destination" >&2
    exit 2
  }
  rm -rf "$destination"
  git init -q "$destination"
  git -C "$destination" remote add origin "$url"
  git -C "$destination" fetch -q --depth 1 origin "$ref"
  git -C "$destination" checkout -q --detach FETCH_HEAD
}

clone_locked "$ARGON_THEME_URL" "$ARGON_THEME_COMMIT" package/luci-theme-argon
clone_locked "$ARGON_CONFIG_URL" "$ARGON_CONFIG_COMMIT" package/luci-app-argon-config

# Argon: 侧边栏 brand 字号从 1.8rem 调整为 1.7rem
sed -i 's/font-size: 1.8rem/font-size: 1.7rem/' package/luci-theme-argon/htdocs/luci-static/argon/css/cascade.css 2>/dev/null || true

# OpenClash: 预置 Meta 核心到固件, 避免首次启动时的网络下载 (aarch64, ~10MB)
CORE_URL="https://raw.githubusercontent.com/vernesong/OpenClash/core/master/meta/clash-linux-arm64.tar.gz"
CORE_DEST="files/etc/openclash/core"
mkdir -p "$CORE_DEST"
echo "[diy.sh] Downloading OpenClash Meta core..."
curl -sL --retry 3 --retry-delay 10 -o /tmp/clash_core.tar.gz "$CORE_URL" || {
  echo "[diy.sh] WARNING: OpenClash core download failed; router will download on first boot"
}
if [ -s /tmp/clash_core.tar.gz ]; then
  tar xzf /tmp/clash_core.tar.gz -C "$CORE_DEST/"
  mv "$CORE_DEST/clash" "$CORE_DEST/clash_meta"
  chmod +x "$CORE_DEST/clash_meta"
  echo "[diy.sh] OpenClash Meta core installed: $($CORE_DEST/clash_meta -v 2>&1 | head -1)"
  rm -f /tmp/clash_core.tar.gz
fi

# OpenClash: 预置最新 Metacubexd + Zashboard 到固件
DASH_DIR="files/usr/share/openclash/ui"
mkdir -p "$DASH_DIR"
for dash in \
  "metacubexd:https://codeload.github.com/MetaCubeX/metacubexd/zip/refs/heads/gh-pages:metacubexd-gh-pages" \
  "zashboard:https://codeload.github.com/Zephyruso/zashboard/zip/refs/heads/gh-pages-cdn-fonts:zashboard-gh-pages-cdn-fonts"; do
	name="${dash%%:*}"
	rest="${dash#*:}"
	url="${rest%:*}"
	dir="${rest##*:}"
	echo "[diy.sh] Downloading $name dashboard..."
	if curl -sL --retry 2 --retry-delay 10 -o "/tmp/${name}.zip" "$url"; then
		rm -rf "$DASH_DIR/${name}" "$DASH_DIR/${name}_backup"
		unzip -qo "/tmp/${name}.zip" -d "/tmp/${name}_extract/"
		mv "/tmp/${name}_extract/${dir}" "$DASH_DIR/${name}"
		rm -rf "/tmp/${name}_extract" "/tmp/${name}.zip"
		echo "[diy.sh] $name dashboard installed"
	else
		echo "[diy.sh] WARNING: $name dashboard download failed; keeping plugin default"
	fi
done

# The locked LuCI feed may lag OpenClash. Track the official upstream package
# ref so rebuilds receive the latest plugin while driver/kernel inputs remain
# fixed and reviewable.
rm -rf package/feeds/luci/luci-app-openclash
clone_tracking "$OPENCLASH_URL" "${OPENCLASH_REF:-master}" package/luci-app-openclash-source
mv package/luci-app-openclash-source/luci-app-openclash package/luci-app-openclash
rm -rf package/luci-app-openclash-source
OPENCLASH_ACTUAL_VERSION=$(sed -n 's/^PKG_VERSION:=//p' package/luci-app-openclash/Makefile | head -1)
OPENCLASH_ACTUAL_COMMIT=$(git -C package/luci-app-openclash rev-parse HEAD)
printf '%s\n' "$OPENCLASH_ACTUAL_VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || {
  echo "[diy.sh] OpenClash PKG_VERSION is missing or non-numeric" >&2
  exit 2
}
echo "[diy.sh] OpenClash ${OPENCLASH_ACTUAL_VERSION} from ${OPENCLASH_ACTUAL_COMMIT}"

# ----------------------------------------------------
# 切断 firewall4→kmod-nft-offload→kmod-nf-flow 依赖链
# NSS ECM owns connection acceleration. firewall4's kmod-nft-offload dependency
# pulls in the generic nf_flow_table path, which conflicts with that ownership.
# Remove the dependency before defconfig so it cannot be selected again.
# ----------------------------------------------------
FW4_MK="package/network/config/firewall4/Makefile"
if [ -f "$FW4_MK" ] && grep -q '^CONFIG_PACKAGE_kmod-qca-nss-drv=y' .config 2>/dev/null; then
  sed -i 's/+kmod-nft-offload //' "$FW4_MK"
  echo "[diy.sh] Removed +kmod-nft-offload from firewall4 DEPENDS (NSS provides offload)"
fi

# ----------------------------------------------------
# NSS fork 自定义脚本修复 (针对 immortalwrt-nss / VIKINGYFY 上游问题)
# ----------------------------------------------------

# (a) 11 个 api-*.sh 缺 shebang(SC2148):被 sysupgrade for-source 时无影响,
#     但加上更稳健;即使被裸跑也能给出明确错误。
APIDIR="target/linux/qualcommax/base-files/lib/upgrade"
if [ -d "$APIDIR" ]; then
  for f in "$APIDIR"/api-*.sh "$APIDIR"/../functions/bootconfig.sh; do
    [ -f "$f" ] || continue
    if ! head -n 1 "$f" | grep -q '^#!'; then
      sed -i '1i #!/bin/sh' "$f"
    fi
  done
fi

# (b) 删除问题反模式 999_auto-restart.sh
#     uci-defaults 阶段重启 network/odhcpd/rpcd 易死锁,procd 后续会自然装载。
rm -f target/linux/qualcommax/base-files/etc/uci-defaults/999_auto-restart.sh

# (c) 992_set-nss-load.sh: 非贪婪 sed 修复已推送至 nss-fork,此处不再覆盖

# (d) 防御 993_set-ecm-conntrack.sh: 旧版 nss-fork 还有此文件时加防御
# 幂等:已修复的源文件不再重复追加 guard
NSS_ECM="target/linux/qualcommax/base-files/etc/uci-defaults/993_set-ecm-conntrack.sh"
# shellcheck disable=SC2016
# 双单引号故意的:grep 模式与 sed 写入内容都需要字面 $FILE,而非 shell 展开
if [ -f "$NSS_ECM" ] && ! grep -q '\[ -f "\$FILE" \] || exit 0' "$NSS_ECM" 2>/dev/null; then
  sed -i '/^FILE=/a [ -f "$FILE" ] || exit 0' "$NSS_ECM"
fi

# (e) 991_set-network.sh: global packet_steering policy is supplied by nss-fork;
# Boot Guard removes obsolete per-device copies left by older source revisions.

# (f) qca-nss-pbuf fix now lives in the locked source commit; no build-time
#     patch is needed here.

# (g) [removed] 235-003 skip — NSS/mac80211 patches are maintained in the
#     locked source tree; no external NSS feed or runtime patch skipping is used.

# ----------------------------------------------------
# AX6 硬件适配(变体感知)
# ----------------------------------------------------
# 两种 SKU 通过 .config 选择,DT 这里只补扩容版分区。
#
# (1) SMEM/custom U-Boot (redmi,ax6-stock):
#       DTS 从 MIBIB/SMEM 读取实际分区。本仓主构建面向 rootfs=0x06640000
#       的 128MiB NAND 合并布局。源码升级预检会拒绝装不进当前分区的镜像。
#       原厂双 0x023c0000 槽也使用相同 compatible,但不能使用本仓完整镜像。
#
# (2) Expanded (redmi,ax6):
#       NAND 必须已硬件改装到 ≥256MiB,否则刷下去会变砖!
#       — kernel-DT 写死 rootfs 大小,需匹配实际 NAND
#
# 共用: ath11k fw_mem_mode=1 (MID, ~32MB, DTS 已指定 qcom,ath11k-fw-memory-mode=<1>)
AX6_DTS="target/linux/qualcommax/dts/ipq8071-ax6.dts"
if [ -f "$AX6_DTS" ]; then
  # ath11k 保持 MID 模式 (<1>=16MB/radio, ~32MB total)
  # 不改为 FULL (<0>) — FULL 需要 ~100MB DMA 连续内存,
  # CMA 不足时固件加载失败会导致内核 panic + 看门狗重启
  # 如需启用 FULL 模式,先确认 CMA 池 >= 128MB

  # Expanded 变体:256MiB NAND 才能用,扩 rootfs 到 ~210 MiB
  # 通过 .config 中的 CONFIG_TARGET_PROFILE 检测构建变体
  if [ -f .config ] && grep -q '^CONFIG_TARGET_PROFILE="DEVICE_redmi_ax6"$' .config; then
    echo "[diy.sh] Expanded variant detected (256MB NAND assumed) — patching rootfs reg"
    sed -i 's|reg[ \t]*=[ \t]*<0x0*2dc0000 0x0*5220000>;|reg = <0x02dc0000 0x0C000000>;  /* AX6-build: expanded 256MiB NAND, rootfs 192 MiB, 18 MiB UBI reserve */|' "$AX6_DTS"
    if grep -q '<0x0*2dc0000 0x0*5220000>' "$AX6_DTS"; then
      echo "[diy.sh] ERROR: DTS still contains old rootfs reg" >&2; exit 1
    fi
    if ! grep -q '<0x02dc0000 0x0C000000>' "$AX6_DTS"; then
      echo "[diy.sh] ERROR: DTS missing new EXPAND rootfs reg" >&2; exit 1
    fi
  else
    echo "[diy.sh] Stock variant — DT partition layout untouched (Xiaomi SMEM)"
  fi
fi

# ----------------------------------------------------

# Argon theme conflict resolution
[ -d "feeds/luci/themes/luci-theme-argon" ] && rm -rf feeds/luci/themes/luci-theme-argon
[ -d "feeds/luci/applications/luci-app-argon-config" ] && rm -rf feeds/luci/applications/luci-app-argon-config

# 修改默认IP
sed -i 's/192.168.1.1/192.168.5.1/g' package/base-files/files/bin/config_generate

# 修改版本标识为 Redmi AX6
# openwrt_release 模板使用 %D 占位符, 被 VERSION_SED_SCRIPT 替换
# 必须在模板层面修改 %D, 这样 build 系统填充时保持我们的值
TEMPLATE="package/base-files/files/etc/openwrt_release"
if [ -f "$TEMPLATE" ]; then
  sed -i "s/DISTRIB_ID='%D'/DISTRIB_ID='Redmi AX6'/g" "$TEMPLATE"
  sed -i "s/DISTRIB_DESCRIPTION='%D/DISTRIB_DESCRIPTION='Redmi AX6/g" "$TEMPLATE"
  sed -i "s/DISTRIB_DESCRIPTION='%d/DISTRIB_DESCRIPTION='Redmi AX6/g" "$TEMPLATE"
  echo "[diy.sh] Branding changed to Redmi AX6 in release template"
fi

for dir in ./files/etc/uci-defaults ./files/etc/init.d ./files/sbin ./files/usr/sbin ./files/etc/hotplug.d; do
  [ -d "$dir" ] || continue
  find "$dir" -type f -exec chmod +x {} +
done

# 启用仅负责 NSS 数据路径冲突项的 Boot Guard，以及静态国家码服务。
# IRQ/RPS 自动策略由上游 qualcommax 脚本统一管理;
# /usr/sbin/ax6-irq-affinity 保留为手动基准测试工具,不在启动或 WiFi hotplug 时覆盖上游。
mkdir -p ./files/etc/rc.d
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-boot-guard S12ax6-boot-guard 2>/dev/null )
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-wifi-regdom S10ax6-wifi-regdom 2>/dev/null )

# ----------------------------------------------------
# 移除空的 Plugins 菜单页（无实际插件, 仅显示空白开关）
# ----------------------------------------------------
PLUGINS_JSON=$(find . -path "*/menu.d/luci-mod-system.json" -not -path "./files/*" 2>/dev/null | head -1)
if [ -f "$PLUGINS_JSON" ]; then
    start=$(grep -n '"admin/system/plugins"' "$PLUGINS_JSON" | cut -d: -f1)
    next=$(grep -n '"admin/system/startup"' "$PLUGINS_JSON" | cut -d: -f1)
    if [ -n "$start" ] && [ -n "$next" ] && [ "$start" -lt "$next" ]; then
        sed -i "${start},$((next - 1))d" "$PLUGINS_JSON"
        echo "[diy.sh] Removed empty Plugins menu entry"
    fi
fi
