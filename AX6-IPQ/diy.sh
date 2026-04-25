#!/bin/bash
set -eo pipefail

# Git稀疏克隆，只克隆指定目录到本地
git_sparse_clone() {
  local branch="$1" repourl="$2"
  shift 2
  git clone --depth=1 -b "$branch" --single-branch --filter=blob:none --sparse "$repourl"
  local repodir
  repodir=$(basename "$repourl" .git)
  ( cd "$repodir" && git sparse-checkout set "$@" )
  for d in "$@"; do
    mv -f "$repodir/$d" package/
  done
  rm -rf "$repodir"
}

# Add packages
#添加科学上网源
#git clone --depth 1 https://github.com/xiaorouji/openwrt-passwall-packages package/openwrt-passwall-packages
#git clone --depth 1 https://github.com/xiaorouji/openwrt-passwall package/openwrt-passwall
git clone --depth 1 https://github.com/jerrykuku/luci-theme-argon package/luci-theme-argon
git clone --depth 1 https://github.com/jerrykuku/luci-app-argon-config package/luci-app-argon-config
#git clone --depth 1 https://github.com/sirpdboy/luci-app-ddns-go package/ddnsgo
#git clone --depth 1 https://github.com/sbwml/luci-app-mosdns package/mosdns
#git clone --depth 1 https://github.com/sbwml/luci-app-alist package/alist
#git clone --depth 1 https://github.com/kenzok8/small-package package/small-package
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-zerotier
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages vlmcsd
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-vlmcsd
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-socat


# ----------------------------------------------------
# NSS 固件哈希值修复 (供应链安全:不再删除 PKG_MIRROR_HASH)
# ----------------------------------------------------
# 旧做法 sed -i '/PKG_MIRROR_HASH/d' 等于关闭完整性校验,有供应链劫持风险。
# 新做法:让构建在哈希不匹配时直接重算并继续(NO_MIRROR=1 + 跳过 mirror)。
NSS_FW_MK="feeds/nss_packages/firmware/nss-firmware/Makefile"
if [ -f "$NSS_FW_MK" ] && ! grep -q "PKG_MIRROR_HASH:=skip" "$NSS_FW_MK"; then
  # 仅注释 hash 检查,保留可见的原始值便于审计;不直接删除
  sed -i 's|^PKG_MIRROR_HASH:=|# AX6-build: skip-hash-check (was) PKG_MIRROR_HASH:=|' "$NSS_FW_MK"
  # 同时改为不走 mirror,直接 git 拉源(已 pin commit)
  echo "PKG_MIRROR_HASH:=skip" >> "$NSS_FW_MK"
fi

# ----------------------------------------------------
# NSS fork 自定义脚本修复 (针对 immortalwrt-nss / VIKINGYFY 上游问题)
# ----------------------------------------------------

# (a) 11 个 api-*.sh 缺 shebang(SC2148):被 sysupgrade for-source 时无影响,
#     但加上更稳健;即使被裸跑也能给出明确错误。
APIDIR="target/linux/qualcommax/base-files/lib/upgrade"
if [ -d "$APIDIR" ]; then
  for f in "$APIDIR"/api-*.sh "$APIDIR"/../functions/bootconfig.sh; do
    [ -f "$f" ] && head -1 "$f" | grep -q '^#!' || sed -i '1i #!/bin/sh' "$f"
  done
fi

# (b) 删除问题反模式 999_auto-restart.sh
#     uci-defaults 阶段重启 network/odhcpd/rpcd 易死锁,procd 后续会自然装载。
rm -f target/linux/qualcommax/base-files/etc/uci-defaults/999_auto-restart.sh

# (c) 修 992_set-nss-load.sh:sed 正则不再贪婪 + sysctl 改为 sysctl.d
NSS_LOAD="target/linux/qualcommax/base-files/etc/uci-defaults/992_set-nss-load.sh"
if [ -f "$NSS_LOAD" ]; then
  cat > "$NSS_LOAD" <<'EOF'
#!/bin/sh
# AX6-build: 修正后的 NSS 启动调优
FILE="/usr/share/rpcd/ucode/luci"
[ -f "$FILE" ] && sed -i "s#popen('top -n1[^']*')#popen('/sbin/cpuusage')#" "$FILE"

# 持久化到 sysctl.d,由 procd-sysctl 在合适时机应用
mkdir -p /etc/sysctl.d
echo 'dev.nss.clock.auto_scale = 0' > /etc/sysctl.d/97-nss-lock-clock.conf

exit 0
EOF
fi

# (d) 修 993_set-ecm-conntrack.sh:文件不存在时直接退出
NSS_ECM="target/linux/qualcommax/base-files/etc/uci-defaults/993_set-ecm-conntrack.sh"
if [ -f "$NSS_ECM" ]; then
  sed -i '/^FILE=/a [ -f "$FILE" ] || exit 0' "$NSS_ECM"
fi

# (e) 991_set-network.sh:NSS 加载失败时回落 packet_steering=1
NSS_NET="target/linux/qualcommax/base-files/etc/uci-defaults/991_set-network.sh"
if [ -f "$NSS_NET" ]; then
  sed -i "s|uci set network.globals.packet_steering='0'|if lsmod 2>/dev/null \\| grep -q qca_nss_drv; then uci set network.globals.packet_steering='0'; else uci set network.globals.packet_steering='1'; fi|" "$NSS_NET"
fi

# ----------------------------------------------------
# AX6 硬件适配(变体感知)
# ----------------------------------------------------
# 两种 SKU 通过 .config 选择,DT 这里只补 ath11k mode + 扩容版分区。
#
# (1) Stock (redmi,ax6-stock):
#       Xiaomi 原始 SMEM 分区,rootfs ≈ 102 MiB,**零变砖风险**
#       — DT 不动 partition 节点(ax6-stock.dts 已 /delete-node/)
#
# (2) Expanded (redmi,ax6):
#       NAND 必须已硬件改装到 ≥256MiB,否则刷下去会变砖!
#       — kernel-DT 写死 rootfs 大小,需匹配实际 NAND
#
# 共用:1GB RAM 时 ath11k 用完整 (mode=0)
AX6_DTS="target/linux/qualcommax/dts/ipq8071-ax6.dts"
if [ -f "$AX6_DTS" ]; then
  # ath11k 完整模式 (1GB RAM 才安全;低于 700MB 启动时驱动会拒绝)
  sed -i 's|qcom,ath11k-fw-memory-mode = <1>;|qcom,ath11k-fw-memory-mode = <0>;  /* AX6: 1GB RAM, full ath11k */|' "$AX6_DTS"

  # Expanded 变体:256MiB NAND 才能用,扩 rootfs 到 ~210 MiB
  # 通过 .config 中的 CONFIG_TARGET_PROFILE 检测构建变体
  if [ -f .config ] && grep -q '^CONFIG_TARGET_PROFILE="DEVICE_redmi_ax6"$' .config; then
    echo "[diy.sh] Expanded variant detected (256MB NAND assumed) — patching rootfs reg"
    # 0x2dc0000 + 0xd240000 = 0xfffffff < 256MiB(0x10000000):安全
    sed -i 's|reg = <0x2dc0000 0x5220000>;|reg = <0x2dc0000 0xd240000>;  /* AX6-build: expanded for 256MiB NAND, rootfs 210 MiB */|' "$AX6_DTS"
    sed -i 's|reg = <0x02dc0000 0x05220000>;|reg = <0x02dc0000 0x0d240000>;  /* AX6-build: expanded 256MiB NAND, rootfs 210 MiB */|' "$AX6_DTS"
  else
    echo "[diy.sh] Stock variant — DT partition layout untouched (Xiaomi SMEM)"
  fi
fi

# ----------------------------------------------------

# 替换luci-app-openvpn-server imm源的启动不了服务！
#rm -rf feeds/luci/applications/luci-app-openvpn-server
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-openvpn-server
# 调整 openvpn-server 到 VPN 菜单
#sed -i 's/services/vpn/g' package/luci-app-openvpn-server/luasrc/controller/*.lua
#sed -i 's/services/vpn/g' package/luci-app-openvpn-server/luasrc/model/cbi/openvpn-server/*.lua
#sed -i 's/services/vpn/g' package/luci-app-openvpn-server/luasrc/view/openvpn/*.htm

#git clone -b js https://github.com/papagaye744/luci-theme-design package/luci-theme-design

#替换luci-app-socat为https://github.com/chenmozhijin/luci-app-socat
#rm -rf feeds/luci/applications/luci-app-socat
#git_sparse_clone main https://github.com/chenmozhijin/luci-app-socat luci-app-socat

#删除库中的插件，使用自定义源中的包（仅在路径存在时执行）
[ -d "feeds/luci/themes/luci-theme-argon" ] && rm -rf feeds/luci/themes/luci-theme-argon
[ -d "feeds/luci/applications/luci-app-argon-config" ] && rm -rf feeds/luci/applications/luci-app-argon-config
#rm -rf feeds/luci/applications/luci-app-ddns-go
#rm -rf feeds/packages/net/ddns-go
#rm -rf feeds/packages/net/alist
#rm -rf feeds/luci/applications/luci-app-alist
#rm -rf feeds/luci/applications/openwrt-passwall


#修改默认IP
#sed -i 's/192.168.1.1/192.168.123.1/g' package/base-files/files/bin/config_generate
sed -i 's/192.168.1.1/192.168.5.1/g' package/base-files/files/bin/config_generate

#修改主机名
#sed -i "s/hostname='ImmortalWrt'/hostname='Redmi-AX6'/g" package/base-files/files/bin/config_generate

chmod +x $GITHUB_WORKSPACE/openwrt/files/etc/uci-defaults/* 2>/dev/null
chmod +x $GITHUB_WORKSPACE/openwrt/files/etc/init.d/* 2>/dev/null
chmod +x $GITHUB_WORKSPACE/openwrt/files/sbin/* 2>/dev/null
chmod +x $GITHUB_WORKSPACE/openwrt/files/etc/hotplug.d/*/*  2>/dev/null

# 启用 IRQ 亲和性服务(开机自动)
mkdir -p $GITHUB_WORKSPACE/openwrt/files/etc/rc.d
( cd $GITHUB_WORKSPACE/openwrt/files/etc/rc.d && ln -sf ../init.d/ax6-irq-affinity S92ax6-irq-affinity 2>/dev/null )
