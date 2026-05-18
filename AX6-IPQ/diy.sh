#!/bin/bash
set -eo pipefail

# Add packages
git clone --depth 1 https://github.com/jerrykuku/luci-theme-argon package/luci-theme-argon
git clone --depth 1 https://github.com/jerrykuku/luci-app-argon-config package/luci-app-argon-config


# ----------------------------------------------------
# 切断 firewall4→kmod-nft-offload→kmod-nf-flow 依赖链
# NSS 通过 kmod-qca-nss-nft 提供硬件卸载,kmod-nft-offload 多余且其
# 依赖的 kmod-nf-flow 与 NSS ECM 互斥。make defconfig 会通过 Kconfig
# +select 强制拉回 =y,唯有从源头上移除 DEPENDS 才能彻底阻断。
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

# (e) 991_set-network.sh: packet_steering 回退已推送至 nss-fork,此处不再修补

# (f) [removed] 235-003 skip — 使用 VIKINGYFY 6.18 基线 + nss-packages-618
#     NSS mac80211 patches 已由上游维护,不再需要运行时跳过任何 patch。

# ----------------------------------------------------
# AX6 硬件适配(变体感知)
# ----------------------------------------------------
# 两种 SKU 通过 .config 选择,DT 这里只补扩容版分区。
#
# (1) Stock (redmi,ax6-stock):
#       Xiaomi 原始 SMEM 分区,rootfs ≈ 102 MiB,**零变砖风险**
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
    sed -i 's|reg[ \t]*=[ \t]*<0x02dc0000 0x05220000>;|reg = <0x02dc0000 0x0C000000>;  /* AX6-build: expanded 256MiB NAND, rootfs 192 MiB, 18 MiB UBI reserve */|' "$AX6_DTS"
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

chmod +x ./files/etc/uci-defaults/* 2>/dev/null
chmod +x ./files/etc/init.d/* 2>/dev/null
chmod +x ./files/sbin/* 2>/dev/null
chmod +x ./files/etc/hotplug.d/*/* 2>/dev/null

# 启用 IRQ 亲和性 + Boot Guard (每次启动自动纠正 NSS 配置)
mkdir -p ./files/etc/rc.d
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-irq-affinity S95ax6-irq-affinity 2>/dev/null )
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-boot-guard S12ax6-boot-guard 2>/dev/null )
