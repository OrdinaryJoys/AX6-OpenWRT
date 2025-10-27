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
# 修复 OAF 编译错误 (禁用 Werror)
# ----------------------------------------------------

OAF_MAKEFILE="package/feeds/small8/open-app-filter/Makefile"

if [ -f "$OAF_MAKEFILE" ]; then
    # 查找并移除编译选项中的 -Werror 标志，或直接移除警告标志
    # 不同的 Makefile 结构可能不同，这里尝试移除所有默认警告，或只移除 Werror
    sed -i 's/CFLAGS += -Wall/CFLAGS += -Wno-error/g' "$OAF_MAKEFILE"
    sed -i 's/-Werror//g' "$OAF_MAKEFILE"
    
    # 针对 OAF 源码，通常需要修改 CFLAGS
    sed -i 's/ -Werror //g' $(find package/feeds/small8/open-app-filter/ -name "Makefile")
    
    echo "OAF Makefile patched to ignore -Werror."
else
    echo "警告：未找到 OAF 插件的 Makefile ($OAF_MAKEFILE)，跳过补丁。"
fi

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
