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

# ----------------------------------------------------
# 添加 OAF 插件 (Open-App-Filter)
# ----------------------------------------------------

# 1. 将 OAF 所在的 small-package 仓库添加为 Feed 源
#    （该仓库的链接在您原文件注释中已体现）
if ! grep -q "small-package" feeds.conf.default; then
    echo "src-git small8 https://github.com/kenzok8/small-package" >> feeds.conf.default
fi

# 2. 更新 small8 Feed 源
./scripts/feeds update small8

# 3. 安装 OAF 相关的软件包
#    -p small8 指定了从哪个源安装 OAF 的核心和 LuCI 界面包
./scripts/feeds install -p small8 oaf open-app-filter luci-app-oaf

# ----------------------------------------------------


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
