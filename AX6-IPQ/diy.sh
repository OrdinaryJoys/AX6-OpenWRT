#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

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

resolve_branch_commit() {
  repo="$1"
  branch="$2"
  commit=$(git ls-remote "$repo" "refs/heads/$branch" | awk 'NR == 1 { print $1 }')
  printf '%s\n' "$commit" | grep -Eq '^[0-9a-f]{40}$' || {
    echo "[diy.sh] Unable to resolve $repo branch $branch" >&2
    return 1
  }
  printf '%s\n' "$commit"
}

clone_locked "$ARGON_THEME_URL" "$ARGON_THEME_COMMIT" package/luci-theme-argon
clone_locked "$ARGON_CONFIG_URL" "$ARGON_CONFIG_COMMIT" package/luci-app-argon-config

# Verify the authenticated cgi-io security source lock. The helper is
# intentionally idempotent when the selected packages feed already contains
# the fixed source, and refuses mixed or unknown metadata.
CGI_IO_BACKPORT_HELPER="$REPO_ROOT/AX6-IPQ/scripts/apply-cgi-io-security-backport.sh"
CGI_IO_BACKPORT_PATCH="$REPO_ROOT/AX6-IPQ/package-patches/cgi-io/100-fix-malformed-post-use-after-free.patch"
[ -x "$CGI_IO_BACKPORT_HELPER" ] || {
  echo "[diy.sh] cgi-io security backport helper is missing or not executable" >&2
  exit 2
}
"$CGI_IO_BACKPORT_HELPER" feeds/packages "$CGI_IO_BACKPORT_PATCH"

# ZeroTier explicitly requests its UDP socket buffer, so changing the global
# rmem_default cannot fix receive-queue overflow. Install an AX6-scoped package
# patch whose hunk encodes the exact upstream 1 MiB constant. Patch application
# will stop the build if a future upstream revision changes this contract.
ZEROTIER_PACKAGE="feeds/packages/net/zerotier"
ZEROTIER_BUFFER_PATCH="$REPO_ROOT/AX6-IPQ/package-patches/zerotier/100-openwrt-increase-udp-socket-buffer.patch"
if grep -q '^CONFIG_PACKAGE_zerotier=y' .config 2>/dev/null; then
  [ -f "$ZEROTIER_PACKAGE/Makefile" ] || {
    echo "[diy.sh] ZeroTier package is selected but its locked feed source is missing" >&2
    exit 2
  }
  [ -s "$ZEROTIER_BUFFER_PATCH" ] || {
    echo "[diy.sh] ZeroTier UDP buffer patch is missing" >&2
    exit 2
  }
  mkdir -p "$ZEROTIER_PACKAGE/patches"
  cp "$ZEROTIER_BUFFER_PATCH" "$ZEROTIER_PACKAGE/patches/100-openwrt-increase-udp-socket-buffer.patch"
  grep -Fq '#define ZT_UDP_DESIRED_BUF_SIZE 1048576' "$ZEROTIER_BUFFER_PATCH" || {
    echo "[diy.sh] ZeroTier UDP patch no longer documents the expected upstream value" >&2
    exit 2
  }
  echo "[diy.sh] Installed AX6 ZeroTier 4 MiB UDP socket-buffer patch"
fi

# Argon: 侧边栏 brand 字号从 1.8rem 调整为 1.7rem
sed -i 's/font-size: 1.8rem/font-size: 1.7rem/' package/luci-theme-argon/htdocs/luci-static/argon/css/cascade.css 2>/dev/null || true

# OpenClash: 预置 Meta 核心到固件, 避免首次启动时的网络下载 (aarch64, ~10MB)
OPENCLASH_CORE_COMMIT=$(resolve_branch_commit "$OPENCLASH_URL" core)
CORE_URL="https://raw.githubusercontent.com/vernesong/OpenClash/${OPENCLASH_CORE_COMMIT}/master/meta/clash-linux-arm64.tar.gz"
CORE_DEST="files/etc/openclash/core"
mkdir -p "$CORE_DEST"
echo "[diy.sh] Downloading OpenClash Meta core..."
curl -fsSL --retry 3 --retry-delay 10 -o /tmp/clash_core.tar.gz "$CORE_URL"
tar tzf /tmp/clash_core.tar.gz | grep -Fqx 'clash' || {
  echo "[diy.sh] OpenClash Meta archive does not contain the expected clash binary" >&2
  exit 2
}
tar xzf /tmp/clash_core.tar.gz -C "$CORE_DEST/" clash
mv "$CORE_DEST/clash" "$CORE_DEST/clash_meta"
chmod +x "$CORE_DEST/clash_meta"
readelf -h "$CORE_DEST/clash_meta" 2>/dev/null | grep -Eq '^  Machine:[[:space:]]+AArch64$' || {
  echo "[diy.sh] OpenClash Meta core is not an AArch64 ELF binary" >&2
  exit 2
}
echo "[diy.sh] OpenClash Meta AArch64 core installed"
rm -f /tmp/clash_core.tar.gz

# OpenClash: resolve each dashboard branch once, then download by immutable
# commit so the final rootfs can be traced and reproduced.
DASH_DIR="files/usr/share/openclash/ui"
METACUBEXD_REPO="https://github.com/MetaCubeX/metacubexd.git"
METACUBEXD_REF="gh-pages"
ZASHBOARD_REPO="https://github.com/Zephyruso/zashboard.git"
ZASHBOARD_REF="gh-pages-cdn-fonts"
mkdir -p "$DASH_DIR"
for dash in \
  "metacubexd:${METACUBEXD_REPO}:${METACUBEXD_REF}" \
  "zashboard:${ZASHBOARD_REPO}:${ZASHBOARD_REF}"; do
	name="${dash%%:*}"
	rest="${dash#*:}"
	repo="${rest%:*}"
	branch="${rest##*:}"
	commit=$(resolve_branch_commit "$repo" "$branch")
	owner_repo="${repo#https://github.com/}"
	owner_repo="${owner_repo%.git}"
	url="https://codeload.github.com/${owner_repo}/zip/${commit}"
	archive="/tmp/${name}.zip"
	extract_dir="/tmp/${name}_extract"
	echo "[diy.sh] Downloading $name dashboard at $commit..."
	curl -fsSL --retry 3 --retry-delay 10 -o "$archive" "$url"
	if unzip -Z1 "$archive" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
		echo "[diy.sh] Unsafe path in $name dashboard archive" >&2
		exit 2
	fi
	rm -rf "$extract_dir" "${DASH_DIR:?}/${name}" "${DASH_DIR:?}/${name}_backup"
	mkdir -p "$extract_dir"
	unzip -qo "$archive" -d "$extract_dir"
	set -- "$extract_dir"/*
	[ "$#" -eq 1 ] && [ -d "$1" ] || {
		echo "[diy.sh] $name dashboard archive has an unexpected layout" >&2
		exit 2
	}
	mv "$1" "$DASH_DIR/${name}"
	[ -f "$DASH_DIR/${name}/index.html" ] || {
		echo "[diy.sh] $name dashboard index.html is missing" >&2
		exit 2
	}
	archive_sha=$(sha256sum "$archive" | awk '{print $1}')
	case "$name" in
		metacubexd)
			METACUBEXD_COMMIT="$commit"
			METACUBEXD_ARCHIVE_SHA256="$archive_sha"
			;;
		zashboard)
			ZASHBOARD_COMMIT="$commit"
			ZASHBOARD_ARCHIVE_SHA256="$archive_sha"
			;;
	esac
	rm -rf "$extract_dir" "$archive"
	echo "[diy.sh] $name dashboard installed"
done

# Track the official OpenClash branch without pinning a plugin version in the
# repository. Resolve it once per build, then fetch that immutable commit so a
# moving branch cannot mix two plugin revisions within one artifact.
rm -rf package/feeds/luci/luci-app-openclash
OPENCLASH_RESOLVED_COMMIT=$(resolve_branch_commit "$OPENCLASH_URL" "${OPENCLASH_REF:-master}")
clone_locked "$OPENCLASH_URL" "$OPENCLASH_RESOLVED_COMMIT" package/luci-app-openclash-source
OPENCLASH_ACTUAL_COMMIT=$(git -C package/luci-app-openclash-source rev-parse HEAD)
[ "$OPENCLASH_ACTUAL_COMMIT" = "$OPENCLASH_RESOLVED_COMMIT" ] || {
  echo "[diy.sh] OpenClash resolved/checked-out commit mismatch" >&2
  exit 2
}
OPENCLASH_ACTUAL_VERSION=$(sed -n 's/^PKG_VERSION:=//p' \
  package/luci-app-openclash-source/luci-app-openclash/Makefile | head -1)
mv package/luci-app-openclash-source/luci-app-openclash package/luci-app-openclash
rm -rf package/luci-app-openclash-source
"$REPO_ROOT/.github/scripts/enforce-openclash-keep-policy.sh" apply \
  package/luci-app-openclash/root/etc/uci-defaults/luci-openclash
"$REPO_ROOT/.github/scripts/inject-openclash-zerotier-hook.sh" \
  package/luci-app-openclash/root/etc/init.d/openclash
"$REPO_ROOT/.github/scripts/inject-openclash-rom-core-guard.sh" apply \
  package/luci-app-openclash/root/etc/init.d/openclash
"$REPO_ROOT/.github/scripts/inject-openclash-r11-reload-fix.sh" \
  package/luci-app-openclash/root/etc/init.d/openclash
"$REPO_ROOT/AX6-IPQ/scripts/check-openclash-runtime-contract.sh" \
  package/luci-app-openclash/root/etc/init.d/openclash
printf '%s\n' "$OPENCLASH_ACTUAL_VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || {
  echo "[diy.sh] OpenClash PKG_VERSION is missing or non-numeric" >&2
  exit 2
}
printf '%s\n' "$OPENCLASH_ACTUAL_COMMIT" | grep -Eq '^[0-9a-f]{40}$' || {
  echo "[diy.sh] OpenClash commit is not a full SHA" >&2
  exit 2
}
{
  echo "OPENCLASH_ACTUAL_VERSION=$OPENCLASH_ACTUAL_VERSION"
  echo "OPENCLASH_RESOLVED_COMMIT=$OPENCLASH_RESOLVED_COMMIT"
  echo "OPENCLASH_ACTUAL_COMMIT=$OPENCLASH_ACTUAL_COMMIT"
  echo "OPENCLASH_CORE_COMMIT=$OPENCLASH_CORE_COMMIT"
  echo "OPENCLASH_CORE_URL=$CORE_URL"
  echo "OPENCLASH_CORE_SHA256=$(sha256sum "$CORE_DEST/clash_meta" | awk '{print $1}')"
  echo "METACUBEXD_REPO=$METACUBEXD_REPO"
  echo "METACUBEXD_REF=$METACUBEXD_REF"
  echo "METACUBEXD_COMMIT=$METACUBEXD_COMMIT"
  echo "METACUBEXD_ARCHIVE_SHA256=$METACUBEXD_ARCHIVE_SHA256"
  echo "ZASHBOARD_REPO=$ZASHBOARD_REPO"
  echo "ZASHBOARD_REF=$ZASHBOARD_REF"
  echo "ZASHBOARD_COMMIT=$ZASHBOARD_COMMIT"
  echo "ZASHBOARD_ARCHIVE_SHA256=$ZASHBOARD_ARCHIVE_SHA256"
} > .openclash-build.env
echo "[diy.sh] OpenClash ${OPENCLASH_ACTUAL_VERSION} from ${OPENCLASH_ACTUAL_COMMIT}"

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

# (f) qca-nss-pbuf fix now lives in the locked source commit; no build-time
#     patch is needed here.

# (g) [removed] 235-003 skip — NSS/mac80211 patches are maintained in the
#     locked source tree; no external NSS feed or runtime patch skipping is used.

# ----------------------------------------------------
# AX6 硬件适配(变体感知)
# ----------------------------------------------------
# 两种 SKU 通过 .config 选择,DT 这里只补扩容版分区。
#
# (1) SMEM/custom U-Boot (redmi,ax6-stock):
#       DTS 从 MIBIB/SMEM 读取实际分区。本仓主构建面向 rootfs=0x06640000
#       的 128MiB NAND 合并布局。源码升级预检会拒绝装不进当前分区的镜像。
#       原厂双 0x023c0000 槽也使用相同 compatible,但不能使用本仓完整镜像。
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
    if grep -q '<0x0*2dc0000 0x0*5220000>' "$AX6_DTS"; then
      echo "[diy.sh] ERROR: DTS still contains old rootfs reg" >&2; exit 1
    fi
    if ! grep -q '<0x02dc0000 0x0C000000>' "$AX6_DTS"; then
      echo "[diy.sh] ERROR: DTS missing new EXPAND rootfs reg" >&2; exit 1
    fi
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

# 修改版本标识为 Redmi AX6
# openwrt_release 模板使用 %D 占位符, 被 VERSION_SED_SCRIPT 替换
# 必须在模板层面修改 %D, 这样 build 系统填充时保持我们的值
TEMPLATE="package/base-files/files/etc/openwrt_release"
if [ -f "$TEMPLATE" ]; then
  sed -i "s/DISTRIB_ID='%D'/DISTRIB_ID='Redmi AX6'/g" "$TEMPLATE"
  sed -i "s/DISTRIB_DESCRIPTION='%D/DISTRIB_DESCRIPTION='Redmi AX6/g" "$TEMPLATE"
  sed -i "s/DISTRIB_DESCRIPTION='%d/DISTRIB_DESCRIPTION='Redmi AX6/g" "$TEMPLATE"
  echo "[diy.sh] Branding changed to Redmi AX6 in release template"
fi

for dir in ./files/etc/uci-defaults ./files/etc/init.d ./files/sbin ./files/usr/sbin ./files/etc/hotplug.d; do
  [ -d "$dir" ] || continue
  find "$dir" -type f -exec chmod +x {} +
done

# 启用仅负责 NSS 数据路径冲突项的 Boot Guard、静态国家码服务和 ZeroTier 规则协调器。
# IRQ/RPS 自动策略由上游 qualcommax 脚本统一管理;
# /usr/sbin/ax6-irq-affinity 保留为手动基准测试工具,不在启动或 WiFi hotplug 时覆盖上游。
mkdir -p ./files/etc/rc.d
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-boot-guard S12ax6-boot-guard 2>/dev/null )
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-wifi-regdom S10ax6-wifi-regdom 2>/dev/null )
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-zerotier-reconcile S91ax6-zerotier-reconcile 2>/dev/null )
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-openclash-dns-health S92ax6-openclash-dns-health 2>/dev/null )
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-zerotier-health S93ax6-zerotier-health 2>/dev/null )
( cd ./files/etc/rc.d && ln -sf ../init.d/ax6-network-invariants S95ax6-network-invariants 2>/dev/null )

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
