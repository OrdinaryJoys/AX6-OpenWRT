#!/bin/bash
# Git稀疏克隆，只克隆指定目录到本地
function git_sparse_clone() {
  branch="$1" repourl="$2" && shift 2
  git clone --depth=1 -b $branch --single-branch --filter=blob:none --sparse $repourl
  repodir=$(echo $repourl | awk -F '/' '{print $(NF)}' | sed 's/.git$//')
  cd $repodir && git sparse-checkout set $@
  mkdir -p ../package
  # 逐个移动文件/目录，避免通配符问题
  for item in $@; do
    if [ -e "$item" ]; then
      mv -f "$item" ../package/
    fi
  done
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

#删除库中的插件，使用自定义源中的包。
rm -rf feeds/luci/themes/luci-theme-argon
rm -rf feeds/luci/applications/luci-app-argon-config
#rm -rf feeds/luci/applications/luci-app-ddns-go
#rm -rf feeds/packages/net/ddns-go
#rm -rf feeds/packages/net/alist
#rm -rf feeds/luci/applications/luci-app-alist
#rm -rf feeds/luci/applications/openwrt-passwall

# 移除 LuCI「路由/NAT 卸载」页面控件

# 创建patch目录
mkdir -p feeds/luci/patches

# 创建移除offloading的patch
cat > feeds/luci/patches/992-remove-offloading-tab.patch << 'EOF'
--- a/applications/luci-app-firewall/luasrc/model/cbi/firewall/zones.lua
+++ b/applications/luci-app-firewall/luasrc/model/cbi/firewall/zones.lua
@@ -XXX,XX +XXX,XX @@
 
- -- Routing/NAT Offloading
- s:tab("offloading", translate("Routing", "Routing / NAT Offloading"))
- 
- o = s:taboption("offloading", Flag, "offloading", translate("Software flow offloading"))
- o.default = o.disabled
- o.rmempty = false
- 
- o = s:taboption("offloading", Flag, "fullcone", translate("FullCone NAT"))
- o.default = o.disabled
- o.rmempty = false
- 
- o = s:taboption("offloading", Flag, "fullcone6", translate("FullCone NAT6"))
- o.default = o.disabled
- o.rmempty = false
- 
- o = s:taboption("offloading", Flag, "sfe", translate("Hardware flow offloading"))
- o.default = o.disabled
- o.rmempty = false
- 
- o = s:taboption("offloading", Flag, "sfe_loop", translate("HWNAT loopback traffic"))
- o.default = o.disabled
- o.rmempty = false
- o:depends("sfe", "1")
- 
- o = s:taboption("offloading", Flag, "sfe_bridge", translate("HWNAT bridge traffic"))
- o.default = o.disabled
- o.rmempty = false
- o:depends("sfe", "1")
 
 -- Custom Rules
EOF

echo "[DIY] offloading移除补丁已创建"


#修改默认IP
#sed -i 's/192.168.1.1/192.168.123.1/g' package/base-files/files/bin/config_generate

#修改主机名
#sed -i "s/hostname='ImmortalWrt'/hostname='Redmi-AX6'/g" package/base-files/files/bin/config_generate

# <<<<<<<<<<<<<<<<<<<< 新增内容：隐藏状态页的自动刷新按钮 >>>>>>>>>>>>>>>>>>>>
sed -i '/<\/head>/i <style>[data-indicator="poll-status"] { display: none !important; }</style>' package/luci-theme-argon/luasrc/view/themes/argon/header.htm


# ==============================================================================
# 专门移除状态概览页面 (/admin/status/overview) 的Hide按钮
# ==============================================================================

echo "开始移除状态概览页面的Hide按钮..."

# 方法1：直接修改状态概览页面的JavaScript文件
STATUS_JS_FILE="feeds/luci/modules/luci-mod-status/htdocs/luci-static/resources/view/status/include/10-system.js"

if [ -f "$STATUS_JS_FILE" ]; then
    echo "找到状态页面JavaScript文件，正在修改..."
    
    # 备份原文件
    cp "$STATUS_JS_FILE" "$STATUS_JS_FILE.bak"
    
    # 使用sed删除创建Hide按钮的代码段
    sed -i '/var hideButton = E(.button/,/hideButton\.outerHTML;/d' "$STATUS_JS_FILE"
    
    # 删除与Hide按钮相关的事件监听器
    sed -i '/hideButton\.addEventListener/d' "$STATUS_JS_FILE"
    
    # 删除对hideButton变量的引用
    sed -i '/hideButton/d' "$STATUS_JS_FILE"
    
    echo "[DIY] 状态概览页面Hide按钮代码已移除"
else
    echo "[DIY] 警告：未找到状态页面JS文件 $STATUS_JS_FILE"
fi

# 方法2：创建LuCI补丁确保修改持久化
PATCH_DIR="feeds/luci/patches"
mkdir -p "$PATCH_DIR"

cat > "$PATCH_DIR/991-remove-status-overview-hide-button.patch" << 'EOF'
--- a/modules/luci-mod-status/htdocs/luci-static/resources/view/status/include/10-system.js
+++ b/modules/luci-mod-status/htdocs/luci-static/resources/view/status/include/10-system.js
@@ -1,3 +1,4 @@
+// Modified: Hide button removed from status overview
 return baseclass.extend({
 	title: _('System'),
 
@@ -7,34 +8,6 @@
 	var poll_status = true;
 	var section;
 
-	var hideButton = E('button', {
-		'class': 'btn cbi-button',
-		'data-indicator': 'poll-status',
-		'data-clickable': true,
-		'data-style': 'inactive'
-	}, _('Hide'));
-
-	hideButton.addEventListener('click', function(ev) {
-		ev.target.classList.toggle('inactive');
-		ev.target.classList.toggle('spin');
-		ev.target.classList.toggle('success');
-		ev.target.disabled = !ev.target.disabled;
-		ev.target.firstChild.data = ev.target.disabled ? _('Show') : _('Hide');
-		poll_status = !poll_status;
-	});
-
-	o = s.option(form.DummyValue, '_hide_button', ' ');
-	o.rawhtml = true;
-	o.cfgvalue = function(section_id) {
-		return hideButton.outerHTML;
-	};
-
 	poll.add(function() {
 		return rpc.call('luci.getInit', { name: 'system' }).then(function(res) {
 			section = res;
EOF

echo "[DIY] LuCI状态页面补丁已创建"

# 方法3：创建自定义JavaScript在运行时移除按钮（备用方案）
mkdir -p files/www/luci-static/resources/view/status/

cat > files/www/luci-static/resources/view/status/overview-fix.js << 'EOF'
// 专门移除状态概览页面的Hide按钮
document.addEventListener('DOMContentLoaded', function() {
    // 只在状态概览页面执行
    if (window.location.pathname.indexOf('/admin/status/overview') !== -1) {
        function removeStatusHideButton() {
            var buttons = document.querySelectorAll('button, input');
            for (var i = 0; i < buttons.length; i++) {
                var element = buttons[i];
                if (element.getAttribute('data-indicator') === 'poll-status' && 
                    element.getAttribute('data-clickable') === 'true' &&
                    element.getAttribute('data-style') === 'inactive') {
                    
                    console.log('Removing status overview hide button');
                    element.style.display = 'none';
                    element.remove();
                    return true;
                }
            }
            return false;
        }
        
        // 立即尝试移除
        if (!removeStatusHideButton()) {
            // 如果没找到，等待一下再尝试（针对动态加载）
            setTimeout(removeStatusHideButton, 500);
        }
        
        // 监听DOM变化
        var observer = new MutationObserver(function(mutations) {
            removeStatusHideButton();
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }
});
EOF

# 方法4：确保自定义JS被加载
mkdir -p files/etc/uci-defaults

cat > files/etc/uci-defaults/99-status-overview-fix << 'EOF'
#!/bin/sh
# 修复状态概览页面：移除Hide按钮

# 在状态页面模板中注入我们的修复JS
OVERVIEW_HTML="/www/luci-static/resources/view/status/overview.htm"
CUSTOM_JS='<script src="/luci-static/resources/view/status/overview-fix.js"></script>'

if [ -f "$OVERVIEW_HTML" ]; then
    # 检查是否已经添加了我们的脚本
    if ! grep -q "overview-fix.js" "$OVERVIEW_HTML"; then
        # 在</body>标签前添加我们的脚本
        sed -i 's|</body>|'"$CUSTOM_JS"'</body>|' "$OVERVIEW_HTML"
        echo "状态概览页面修复脚本已注入"
    fi
fi

# 备用方案：直接修改LuCI的core.js包含我们的修复
LUCI_JS="/www/luci-static/resources/cbi.js"
if [ -f "$LUCI_JS" ] && [ -f "/www/luci-static/resources/view/status/overview-fix.js" ]; then
    # 在cbi.js加载后加载我们的修复
    (echo; echo '// Load status overview fix'; echo '(function(){var s=document.createElement("script");s.src="/luci-static/resources/view/status/overview-fix.js";document.head.appendChild(s);})();') >> "$LUCI_JS"
fi

exit 0
EOF

chmod +x files/etc/uci-defaults/99-status-overview-fix

echo "[DIY] 状态概览页面Hide按钮移除配置完成"


# 验证状态页面修改
echo "验证状态概览页面修改..."
if [ -f "$STATUS_JS_FILE" ]; then
    if grep -q "hideButton" "$STATUS_JS_FILE"; then
        echo "⚠️  警告：状态JS文件中仍可能存在hideButton代码"
    else
        echo "✓ 状态JS文件已清理hideButton代码"
    fi
fi

if [ -f "files/www/luci-static/resources/view/status/overview-fix.js" ]; then
    echo "✓ 运行时修复脚本已创建"
fi

if [ -f "files/etc/uci-defaults/99-status-overview-fix" ]; then
    echo "✓ 启动修复脚本已创建"
fi

if [ -f "feeds/luci/patches/991-remove-status-overview-hide-button.patch" ]; then
    echo "✓ LuCI状态页面补丁已创建"
fi

echo "[DIY] 状态概览页面Hide按钮移除配置全部完成"


