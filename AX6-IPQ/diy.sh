#!/bin/bash
# Git稀疏克隆，只克隆指定目录到本地
function git_sparse_clone() {
  branch="$1" repourl="$2" && shift 2
  git clone --depth=1 -b $branch --single-branch --filter=blob:none --sparse $repourl
  repodir=$(echo $repourl | awk -F '/' '{print $(NF)}')
  cd $repodir && git sparse-checkout set $@
  mv -f $@ ../package
  cd .. && rm -rf $repodir
}

# >>> 【关键修改】替换 LuCI Feed 源 START <<<
echo "正在替换 LuCI feed 源为 OrdinaryJoys/luci.git..."
sed -i 's/src-git luci.*/src-git luci https:\/\/github.com\/OrdinaryJoys\/luci.git/g' feeds.conf.default
# >>> 【关键修改】替换 LuCI Feed 源 END <<<

# 添加主题+配置（Argon 完整）
git clone --depth 1 https://github.com/jerrykuku/luci-theme-argon package/luci-theme-argon || echo "❌ luci-theme-argon 克隆失败"
git clone --depth 1 https://github.com/jerrykuku/luci-app-argon-config package/luci-app-argon-config || echo "❌ luci-app-argon-config 克隆失败"

# 删除官方残留，防止冲突
rm -rf feeds/luci/themes/luci-theme-argon
rm -rf feeds/luci/applications/luci-app-argon-config

# 可选：修改默认IP & 主机名（当前注释掉）
# sed -i 's/192.168.1.1/192.168.123.1/g' package/base-files/files/bin/config_generate
# sed -i "s/hostname='ImmortalWrt'/hostname='Redmi-AX6'/g" package/base-files/files/bin/config_generate

# >>> 必须立即更新 feeds，否则新 LuCI 源不生效 <<<
echo ">>> 正在更新并安装 feeds..."
./scripts/feeds update -a
./scripts/feeds install -a

# 调试输出
echo ">>> package 目录结构"
find package -maxdepth 2 -type d | sort
echo ">>> 最终 feeds.conf.default"
cat feeds.conf.default
