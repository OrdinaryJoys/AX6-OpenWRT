# AX6 上游 32b5f4898f9 进度审计

日期: 2026-07-10

## 当前结论

本轮检查已完成三个部分:

1. 刷新 `VIKINGYFY/immortalwrt`、`qosmio/openwrt-ipq`、`immortalwrt/immortalwrt`、`OrdinaryJoys/immortalwrt-nss` 和 `OrdinaryJoys/AX6-OpenWRT` 的远端引用。
2. 验证 `codex/ax6-hostapd-wifi-v2-clean-build-test` 云端构建产物内容。
3. 拆解 VIKINGYFY 最新 `0d3ee80549e..32b5f4898f9` 的新增上游差异。

本轮没有合并上游代码,没有刷写路由器,没有修改实机配置。

## 已验证的构建产物

| 项目 | 结果 |
| --- | --- |
| GitHub Actions run | `29024239911` 成功 |
| 构建仓库提交 | `3218b73d1a62e6a2cb3041f1ba9da3d45310221c` |
| 锁定源码提交 | `a706a46e462c9f22ce29dc4076d2913c9c1b6452` |
| sysupgrade SHA256 | `b0c8d422caafe26fd8bdde73f9885b126d551f8bb6350c93ea92be52e981b62d` |
| 目标设备 | `qualcommax/ipq807x` / `redmi_ax6-stock` |
| 内核 | `6.18.35` |
| rootfs | squashfs xz, 约 44 MiB |
| sysupgrade 包 | 约 50 MiB |

## 固件内容确认

| 区域 | 状态 | 说明 |
| --- | --- | --- |
| NSS/ECM | 已落地 | `ecm.disable_offloads=1`, `disable_gro_list=1`, `flow_offloading=0`, `flow_offloading_hw=0` |
| br-lan offload | 已落地 | `100-disable_offloads_br_lan` 调用 ECM 官方 helper |
| 软件 flow offload | 未启用 | `kmod-nf-flow`、`kmod-nft-offload` 未选中 |
| OpenClash | 已落地 | `luci-app-openclash 0.47.116`, `clash_meta` 内核进入固件 |
| OpenClash 自动更新 | 未关闭 | `release_branch=master`, 未触碰订阅/覆写文件 |
| ZeroTier | 已落地 | `zerotier 1.16.2-r1`, `zerotier-fw4` 与 include 骨架存在 |
| UPnP | 已落地 | `miniupnpd-nftables 2.3.9-r3`, 默认 `enabled=0` |
| ZRAM | 已落地 | `zram-swap`, `S15zram`, zstd backend 配置存在 |
| WiFi | 已落地 | 国家码默认 `US`; 2.4G `HE40 + ht_coex=1`; 5G `HE80 + noscan=1` |
| GCMP-256 修复 | 已落地 | 仅在 `gcmp256 && phy_features.cipher_gcmp256` 时写入 |
| sing-box/xray/v2ray | 未作为运行组件进入 | 只在 dashboard 静态资源名中出现 |
| WireGuard | 未进入当前固件 | `kmod-wireguard`、`wireguard-tools`、`luci-proto-wireguard` 均未选中 |

## 固件空间构成

| 路径/组件 | 未压缩大小 | 说明 |
| --- | ---: | --- |
| `/etc/openclash` | 约 20.6 MiB | OpenClash core、GeoSite、规则资源 |
| `/usr/share/openclash` | 约 18.3 MiB | metacubexd/zashboard 等 Web UI |
| `/usr/bin` | 约 17.7 MiB | `ddns-go` 等二进制是主要来源 |
| `/lib/modules` | 约 10.6 MiB | NSS、SSDK、ath11k、mac80211 等核心模块 |
| `/lib/firmware` | 约 7.8 MiB | Q6、NSS、ath11k 固件与 board data |

空间大头是 OpenClash 运行资源、Web UI 和 ddns-go,不是 NSS/WiFi/SSDK 核心驱动异常膨胀。

## 新上游 32b5f4898f9 拆解

| commit | 范围 | AX6 相关性 | 当前判断 |
| --- | --- | --- | --- |
| `f95dcd3672c` | generic fitblk | 低到中 | 主要是 FIT/block 适配,需确认是否影响 AX6 分区/恢复镜像路径 |
| `0be028e1591` | qca-nss | 高 | 含 qca-nss-drv 内存/fraglist 修复、qdisc/netlink 安全修复、ECM VLAN-over-bridge 修复 |
| `55eb00a233e` | qualcommbe | 低 | 主要是 BE/PPE/EDMA,不直接命中 AX6 ipq807x,暂不进入 AX6 候选 |
| `32b5f4898f9` | mac80211/ath11k | 高 | 含 ath11k crash recovery、EAPOL/status、per-CPU TX queue、pbuf 启动顺序变化 |

新增 4 个 commit 本身 `git diff --check 0d3ee80549e..viking/main` 通过。

## 需要重点验证的候选项

| 优先级 | 项目 | 根因/价值 | 风险边界 |
| --- | --- | --- | --- |
| P0 | 保留现有 ECM offload 修复 | 解决 IPQ807x 本机终结流量 LuCI/SSH/DNS 慢加载和重传 | 不能接受上游把 helper 缩回只关 `rx-gro-list` 的版本 |
| P0 | `qca-nss-drv` fraglist truesize | 修复 WiFi/NSS path 下 skb truesize 欠账,可能关联局域网传输和内存压力 | 需编译验证补丁上下文和运行时无 WARN |
| P0 | `qca-nss-drv` empty buffer kmalloc | 降低固件持有 empty-buffer 时 page-frag 内存放大 | 需观察 512M/1G SKU 内存占用,避免吞吐回退 |
| P1 | `qca-nss-clients` 011/012/013 | IFB/qdisc/netlink 稳定性与权限修复 | 方向合理,需编译验证 |
| P1 | `ath11k` recovery 926-931 | 修复固件 crash recovery 中 CE/SRNG/TX 空指针和 IRQ 不平衡 | 高风险高价值,必须单独候选构建 |
| P1 | `mac80211` EAPOL/status 657/658 | 修复停止接口时 pending ack/status 泄露 | 和 WiFi 断流/重启路径相关,需单独验证 |
| P1 | `mac80211` per-CPU TX queue | 提升 NSS WiFi 本机发往无线客户端吞吐 | 需确认不会影响多队列队列管理和小包延迟 |
| P1 | ECM VLAN-over-bridge | 上游支持 bridge-vlan 场景下正确判断 on-wire tag | 与本仓当前“禁用 bridge-vlan,使用 802.1q 子接口”策略不同,只能作为兼容候选验证 |
| P2 | ath12k 新补丁组 | 非 AX6 主路径 | 暂不影响 AX6,可后置 |
| P2 | qualcommbe/PPE | 非 AX6 主路径 | 暂不进入 AX6 验证 |

## 已发现的遗留问题

| 问题 | 状态 | 影响 | 建议 |
| --- | --- | --- | --- |
| `nss-check` RAM 检查仍将 `<800MB` 判为 FAIL | 未修复 | 与多 SKU/官方配置版本兼容目标冲突 | 改为按 SKU/MTD/内存 profile 分级,512M/256M 不应硬失败 |
| `firewall.fullcone=1` 默认开启 | 未定 | 可能与 UPnP、OpenClash 透明代理、ZeroTier 同处 nftables 路径,需验证 | 单独测试 fullcone 开/关对 NAT 类型、游戏、OpenClash、ZT 的影响 |
| OpenClash UI 与资源占用大 | 已确认 | 空间压力主要来源之一 | 不做小空间配置;仅作为空间说明,不删除自动更新和订阅相关资源 |
| 上游 `qca-nss-pbuf.init` 回到 `START=27 + wifi up` | 未合并 | 可能与本仓 `S19`、`reload_wifi=0` 不扰动 WiFi 逻辑冲突 | 暂拒绝直接覆盖,拆出 pbuf 单独验证 |
| 上游 `disable_offloads.sh` 缩减为只关 `rx-gro-list` | 拒绝直接合并 | 会重新暴露 IPQ807x 本机终结流量 checksum/GRO/GSO 风险 | 必须保留当前完整 helper 与 br-lan 调用路径 |

## 下一步

1. 新建不合并主线的源码候选分支,仅挑选 qca-nss-drv 015/016 与 qca-nss-clients 011/012/013 做 P0/P1a 构建验证。
2. 单独建立 ath11k recovery 候选分支,验证 926-931 与现有 ath11k NSS patch stack 的上下文冲突。
3. 暂不合并 pbuf 启动顺序改动,先比较 `START=19/reload_wifi=0` 与上游 `START=27/wifi up` 的启动链差异。
4. 修正 `nss-check` 多 SKU RAM 判定逻辑,使 1G/512M/256M 与不同分区布局都能得到正确 WARN/FAIL。
5. 对 `firewall.fullcone=1` 做配置层审计和运行态测试方案,先不改默认。
6. 每个候选分支分别跑本地 lint/patch 检查,通过后再触发云端 stock 构建;不刷写实机。
