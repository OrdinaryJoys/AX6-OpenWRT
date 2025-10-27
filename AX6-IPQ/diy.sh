#!/bin/bash
# Git稀疏克隆，只克隆指定目录到本地
function git_sparse_clone() {
  branch="$1" repourl="$2" && shift 2
  git clone --depth=1 -b $branch --single-branch --filter=blob:none --sparse $repourl
  # 提取目录名并去除.git后缀（如将yyy.git转为yyy）
  repodir=$(basename "$repourl" .git)
  cd $repodir && git sparse-checkout set $@
  mv -f $@ ../package
  cd .. && rm -rf $repodir
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
#git clone --depth=1  https://github.com/kenzok8/small-package package/small-package
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-zerotier
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages vlmcsd
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-vlmcsd
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-socat

# ====================================================
# [修复] open-app-filter 编译失败 (Werror/missing-prototypes)
# ----------------------------------------------------

# 1. 移除 OpenWrt 默认源中与 small8 源冲突的 open-app-filter 包
echo "Removing conflicting open-app-filter from default feeds/packages."
rm -rf feeds/packages/net/open-app-filter

echo "Removing conflicting luci-app-appfilter from default feeds/luci."
rm -rf feeds/luci/applications/luci-app-appfilter

# 2. 对 small8 源的 open-app-filter (kmod) Makefile 进行强力补丁
# 禁用所有将警告升级为错误的行为 (-Werror)
OAF_MAKEFILE="package/feeds/small8/open-app-filter/Makefile"

if [ -f "$OAF_MAKEFILE" ]; then
    echo "Patching: $OAF_MAKEFILE to disable Werror for kmod compilation."
    
    # a. 移除 Makefile 中所有明确的 -Werror 标志
    sed -i 's/-Werror//g' "$OAF_MAKEFILE"
    
    # b. 在 Makefile 中插入 -Wno-error 到内核编译标志中，覆盖其他地方可能注入的 -Werror
    sed -i '/include \.\.\/\.\.\/make\/pkg\.mk/i\KBUILD_CFLAGS += -Wno-error' "$OAF_MAKEFILE"
    sed -i '/include \.\.\/\.\.\/make\/pkg\.mk/i\KERNEL_CFLAGS += -Wno-error' "$OAF_MAKEFILE"
    
    # c. 尝试修补源代码目录下的 Makefile (如果有)
    OAF_KMOD_SRC_MAKEFILE="package/feeds/small8/open-app-filter/oaf/src/Makefile"
    if [ -f "$OAF_KMOD_SRC_MAKEFILE" ]; then
        echo "Patching internal oaf/src/Makefile."
        sed -i 's/-Werror//g' "$OAF_KMOD_SRC_MAKEFILE"
        sed -i 's/CFLAGS += -Wall/CFLAGS += -Wall -Wno-error/g' "$OAF_KMOD_SRC_MAKEFILE"
    fi
fi

echo "Open-App-Filter patch completed."

# ====================================================

# ----------------------------------------------------
# NSS 固件哈希值不匹配修复 (解决 PKG_MIRROR_HASH 错误)
# ----------------------------------------------------

# 目标文件路径：feeds/nss_packages/firmware/nss-firmware/Makefile
# 作用：删除 Makefile 中包含 PKG_MIRROR_HASH 的那一行。
# 这样构建系统会接受 Git 克隆的内容，即使其哈希值与 Makefile 中预期的不符。
sed -i '/PKG_MIRROR_HASH/d' feeds/nss_packages/firmware/nss-firmware/Makefile

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
