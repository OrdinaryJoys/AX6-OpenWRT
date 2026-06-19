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

clone_locked "$ARGON_THEME_URL" "$ARGON_THEME_COMMIT" package/luci-theme-argon
clone_locked "$ARGON_CONFIG_URL" "$ARGON_CONFIG_COMMIT" package/luci-app-argon-config

# The locked LuCI feed contains an older OpenClash. Use the independently
# locked upstream package so factory reset and rebuilds install the audited
# 0.47.097 implementation.
rm -rf package/feeds/luci/luci-app-openclash
clone_locked "$OPENCLASH_URL" "$OPENCLASH_COMMIT" package/luci-app-openclash-source
mv package/luci-app-openclash-source/luci-app-openclash package/luci-app-openclash
rm -rf package/luci-app-openclash-source
grep -qx "PKG_VERSION:=${OPENCLASH_VERSION}" package/luci-app-openclash/Makefile || {
  echo "[diy.sh] OpenClash version does not match build lock" >&2
  exit 2
}

# The stock SMEM slot is only 35.75 MiB for kernel + squashfs. OpenClash can
# download dashboards, GeoSite/MMDB and rule data together with its runtime
# core, so do not embed those replaceable assets in the compact STOCK image.
if [ -f .config ] &&
   grep -q '^CONFIG_TARGET_PROFILE="DEVICE_redmi_ax6-stock"$' .config; then
  rm -f \
    package/luci-app-openclash/root/etc/openclash/GeoSite.dat \
    package/luci-app-openclash/root/etc/openclash/Country.mmdb \
    package/luci-app-openclash/root/etc/openclash/rule_provider/oc-cn-domain.mrs
  rm -rf \
    package/luci-app-openclash/root/usr/share/openclash/ui/metacubexd \
    package/luci-app-openclash/root/usr/share/openclash/ui/zashboard
  echo "[diy.sh] STOCK: removed downloadable OpenClash data and dashboards"
fi


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

# (f) [removed] 235-003 skip — 使用 VIKINGYFY 6.18 基线 + nss-packages-618
#     NSS mac80211 patches 已由上游维护,不再需要运行时跳过任何 patch。

# ----------------------------------------------------
# AX6 硬件适配(变体感知)
# ----------------------------------------------------
# 两种 SKU 通过 .config 选择,DT 这里只补扩容版分区。
#
# (1) Stock (redmi,ax6-stock):
#       Xiaomi 原始 SMEM 双槽,rootfs/rootfs_1 各 0x023c0000 (35.75 MiB)
#       内核与 squashfs 共用当前 UBI 槽,源码 profile 负责执行容量门禁
#       — DT 不动 partition 节点(ax6-stock.dts 已 /delete-node/)
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
