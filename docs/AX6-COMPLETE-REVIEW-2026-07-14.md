# AX6 完整修复审查与统一构建准入（2026-07-14）

## 1. 审查边界

- 主源码基线：`OrdinaryJoys/immortalwrt-nss@56807d9661dbe7df421d1fd31feba76677b5703d`
- 源码候选：`codex/ax6-core-integration-review@da2a771963c01baf0b8350a4126b8533ea23ac45`
- 构建仓主线：`OrdinaryJoys/AX6-OpenWRT@099556aae4c0449a23e157fd95d061fc7537f59a`
- 构建候选：`codex/ax6-openclash-manifest-guard`（本文档提交前仍为本地候选）
- 交叉上游：VIKINGYFY/immortalwrt、qosmio/openwrt-ipq、ImmortalWrt、Linux 6.18、锁定 feeds 与各插件官方仓库。
- 本轮未刷写、未改动路由器，也未把候选合并到主分支或发布固件。

## 2. 已确认并修复

| 范围 | 问题/根因 | 完整修复 | 验证 |
|---|---|---|---|
| qca-nss-dp | 广泛的 netdev/PHY 顺序改写偏离上游，失败回滚不完整 | 删除广泛改写，只保留 `phy_connect_direct()` 失败时清空 `phydev` 的窄修复 | 5 个 DP 补丁顺序重放，无 fuzz/reject/offset |
| qca-nss-drv | fraglist `truesize` 少计；空 buffer payload 缺后备分配 | 引入隔离补丁 015/016 | 16 个 drv 补丁顺序重放和内容哈希通过 |
| qca-nss-clients | mirred 释放链表损坏、noop qdisc 统计、netlink 规则注入权限 | 分别加入 011/012/013 | 13 个 clients 补丁顺序重放；netlink 使用全局管理权限 |
| ath11k NSS | Q6 恢复期间 CE/IRQ/ring 访问次序风险 | 以 999-927/928/932 有序组修复 | 149 个 backports/mac80211 补丁顺序重放 |
| IRQ/RPS | `set-irq-affinity` 硬编码 4 CPU 掩码且无可写检查 | 读取 online CPU 生成掩码，仅写存在且可写的 RPS/XPS 节点 | ShellCheck；与 NSS queue、EDMA IRQ 所有权逐项核对 |
| NSS 自检 | 用 `qca_nss* >= 10` 可被可选模块凑数，也会误伤精简配置 | 精确要求 `qca_nss_drv/qca_nss_dp/qca_ssdk/ecm` | 与已验证 rootfs 模块和 autoload 清单交叉检查 |
| 多内存版本 | 自检错误地只接受 1 GiB | 同时接受 512 MiB STOCK 与 1 GiB SKU，均使用 ath11k MID profile | pbuf 512M/1G 阈值与上游脚本一致 |
| ZRAM | 旧符号和运行态检查曾不匹配 | 256 MiB、ZSTD、有效 UCI 字段和运行态算法/大小检查 | 内核 `CONFIG_CRYPTO_ZSTD/ZSTD_COMPRESS` 与两套 config 依赖闭环 |
| ECM/offload | firewall flow path 与 NSS 重复；本机终结流量存在完整性风险 | blacklist + UCI + Boot Guard；使用打包的 ECM helper，br-lan hotplug 补齐 | 冲突模块、UCI、helper 和最终 rootfs 路径门禁 |
| 网络调度 | 20 ms NAPI budget 和 65536 packet budget 会放大 CPU 慢路径占用 | 删除激进 `netdev_budget*`/backlog 覆盖，交回内核和 qualcommax | Linux sysctl 语义、NSS 快/慢路径交叉审查 |
| WiFi | 5 GHz 固定信道仍强制 `noscan=1` | 删除 `noscan`；2.4 GHz 保持 HE40 + auto + `ht_coex=1`，国家码默认 US | WiFi 门禁和脚本审查 |
| ZeroTier | 自建 zone/双向 LAN/默认 masquerade 越过官方策略；端口集合曾被错误简化 | 恢复官方三 include 模型，策略由 `fw_allow_*` 所有；跟踪 primary + secondary，不推断 tertiary | 独立端口/idempotence 测试；与锁定 packages 源码对照 |
| OpenClash DNS | 可能形成错误重定向或单 DNS 依赖，但不能改订阅/覆写 | 保持插件所有权，只做只读模式、dnsmasq/nft、DNS 组和 IPv6 冲突审计 | 不写订阅、覆写和自动更新配置；CHNR 纳入空间/更新审计 |
| OpenClash 供应链 | core/dashboard 使用移动 URL；dashboard 下载失败可静默生成残缺固件 | 构建时解析官方分支提交，按不可变提交下载；记录 commit/URL/archive 或 ELF 哈希，缺失硬失败 | Meta arm64 ELF、两个 dashboard 归档结构/index 实下载通过 |
| 构建溯源 | 只锁源码提交，无法证明关键补丁集合未被替换 | 新增 9 个候选补丁 SHA256 清单、清单自身哈希和废弃补丁缺席门禁 | 正向通过；篡改内容/恢复废弃补丁的反向测试均失败 |
| manifest | 设备 manifest 曾与 kmod `Packages.manifest` 混淆 | 只选 sysupgrade 同目录唯一设备 manifest，并与最终 opkg 状态逐项一致 | 独立 manifest 测试和既有成功 artifact 验证 |

## 3. 上游与插件状态

| 仓库 | 2026-07-14 状态 | 处理 |
|---|---|---|
| OrdinaryJoys/immortalwrt-nss | main 仍为 `56807d9661d...` | 候选修复保持独立分支 |
| VIKINGYFY/immortalwrt | main 仍为 `30e28764598d...` | 只移植已验证的 RPS 可写/online CPU 思路 |
| qosmio/openwrt-ipq | main-nss 仍为 `92a2d104145c...` | 作为 NSS/VLAN/驱动结构参照，不整仓合并 |
| ImmortalWrt | master 仍为 `4cafb73e88b6...` | 无新增 AX6 必合并项 |
| packages | 新增 1 个未选中的 rtp2httpd 更新 | feed 锁前移，固件包集合不变 |
| routing / telephony | 各 1 个 CI-only 更新 | feed 锁前移，无目标包代码变化 |
| Argon | tooltip CSS 一行修复 | 锁前移到 `8344bc932f3c...` |
| OpenClash | master `1c8e8cb8eaad...`，版本 0.47.116 | 继续跟踪 master，单次构建记录实际提交 |

## 4. 非构建验证结果

- 全仓库 ShellCheck（error 级）：PASS
- Actionlint：PASS
- Yamllint relaxed：PASS
- `lint.yml` 除工具安装外的全部 run 步骤本地逐项执行：PASS
- STOCK/EXPAND 配置差异 allowlist：PASS
- NSS/SSDK/ECM/ath11k/SQM/ZRAM 依赖与互斥矩阵：PASS
- device manifest、OpenClash archive、VLAN transaction、ZeroTier fw4 测试：PASS
- 源码补丁内容门禁：PASS
- Meta core 不可变提交 URL、arm64 ELF：PASS
- Metacubexd/Zashboard 不可变提交 URL、归档安全、唯一目录、index：PASS

## 5. 仍需保留的边界

1. `act_nssmirred` 的 release 链表损坏已经修复，但其 create/replace/IDR/NSS/IFB 全事务重构仍是上游级工作。当前 `nss-zk.qos` 只走 create-only 路径；本轮不以未经实机故障注入验证的大改替换它。
2. 编译通过只能证明补丁应用、ABI/依赖、rootfs 和产物门禁；不能证明无线恢复、长时 ECM、ZeroTier NAT 穿透和多客户端压力下完全无运行态问题。
3. 原厂双 `0x023c0000` rootfs 槽与 `0x06640000` 合并布局不能共用同一大镜像。STOCK profile 使用 SMEM 读真实布局并在升级前按 MTD 几何拒绝过大镜像；不得绕过该检查或 raw-write。
4. 不修改实机、不刷写、不发布。最终构建成功后仍需用户确认才进入实机验证。

## 6. 唯一统一构建的准入与验收

构建前必须满足：源码/构建候选工作区干净、候选提交已推送、远端 SHA 与锁一致、所有非构建门禁再次通过。随后只触发一次 AX6 STOCK NSS 构建，并检查：

- 锁定源码和 9 个补丁内容门禁；
- SSDK、qca-nss-dp、qca-nss-drv/clients、ath11k NSS 编译；
- 唯一 sysupgrade、recovery、kmod、设备 manifest；
- manifest 与最终 rootfs opkg 状态完全一致；
- OpenClash 0.47.116（或构建时 master 的实际版本）、AArch64 Meta core、两个 dashboard 的提交/哈希；
- NSS/ECM/WiFi/ZRAM/ZeroTier/审计脚本的最终 rootfs 内容；
- 全部 artifact SHA256 和 BUILD-LOCK/PROVENANCE。

任何门禁失败都先读取准确日志并回到独立候选分支修复，不盲目重跑、不合并主分支、不发布或刷写。
