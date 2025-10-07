#!/bin/bash
# 通用稀疏克隆函数 —— 自动建目录、防失败
git_sparse_clone(){
  local branch="$1" repourl="$2"; shift 2
  local repodir=$(basename "$repourl" .git)
  git clone --depth=1 -b "$branch" --single-branch --filter=blob:none --sparse "$repourl" || {
    echo "❌ 克隆 $repourl 失败"; return 1
  }
  mkdir -p ../package
  cd "$repodir" || exit 1
  git sparse-checkout set "$@"
  mv -f "$@" ../package/
  cd .. && rm -rf "$repodir"
}

# 0) 替换 LuCI 源 —— 兼容 src-git-full 写法
sed -Ei '/^src-git(-full)? luci/d' feeds.conf.default
echo "src-git luci https://github.com/OrdinaryJoys/luci.git" >> feeds.conf.default

# 1) 先更新 feeds 索引（避免后续 rm 后再拉取官方包）
./scripts/feeds update -a

# 2) 删除官方 argon 主题/应用（防止冲突）
rm -rf feeds/luci/themes/luci-theme-argon
rm -rf feeds/luci/applications/luci-app-argon-config

# 3) 克隆完整 argon 主题 + 配置
git clone --depth 1 https://github.com/jerrykuku/luci-theme-argon package/luci-theme-argon
git clone --depth 1 https://github.com/jerrykuku/luci-app-argon-config package/luci-app-argon-config

# 4) 安装 feed 软件包索引
./scripts/feeds install -a

# 5) 可选：改默认 IP / 主机名（当前注释）
# sed -i 's/192.168.1.1/192.168.123.1/g' package/base-files/files/bin/config_generate
# sed -i "s/hostname='ImmortalWrt'/hostname='Redmi-AX6'/g" package/base-files/files/bin/config_generate

# 6) 调试输出
echo ">>> package 目录结构"
find package -maxdepth 2 -type d | sort
