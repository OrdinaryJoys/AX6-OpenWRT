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
#git clone --depth 1 https://github.com/jerrykuku/luci-theme-argon package/luci-theme-argon
#git clone --depth 1 https://github.com/jerrykuku/luci-app-argon-config package/luci-app-argon-config
#git clone --depth 1 https://github.com/sirpdboy/luci-app-ddns-go package/ddnsgo
#git clone --depth 1 https://github.com/sbwml/luci-app-mosdns package/mosdns
#git clone --depth 1 https://github.com/sbwml/luci-app-alist package/alist
#git clone --depth=1  https://github.com/kenzok8/small-package package/small-package
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-zerotier
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages vlmcsd
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-vlmcsd
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-socat
#git_sparse_clone main https://github.com/kiddin9/kwrt-packages luci-app-openvpn-server

# Remove packages
#删除lean库中的插件，使用自定义源中的包。
#rm -rf feeds/packages/net/alist
#rm -rf feeds/luci/applications/luci-app-alist
#rm -rf feeds/packages/net/mosdns
#rm -rf feeds/luci/applications/luci-app-mosdns


# Default IP
#sed -i 's/192.168.1.1/192.168.2.2/g' package/base-files/files/bin/config_generate