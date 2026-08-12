# AX6 上游驱动交叉审查与针对性合并方案（2026-08-12）

## 1. 审查边界

本轮以 Redmi AX6 stock layout、IPQ807x、Linux 6.18、NSS firmware 12.5 为唯一主线目标。
任何只适用于 IPQ50xx、IPQ60xx、IPQ95xx/IPQ96xx、PPE、EDMA v2/v3、PPE-DS、MHT/MP、
QSDK 14 或 NSS firmware 11.4 的改动，均不得因“提交较新”直接进入 AX6 主线。

审查分为四层：

1. Qualcomm/CodeLinaro QSDK 官方驱动源码。
2. qosmio/OpenWrt/VIKINGYFY/ImmortalWrt 的 OpenWrt 适配层。
3. OrdinaryJoys/immortalwrt-nss 与 AX6-OpenWRT 的补丁、配置和构建门禁。
4. 使用 `ax6-check` 的实机只读运行映射；不刷写、不重启、不修改配置。

参考仓库：

- [qosmio/openwrt-ipq](https://github.com/qosmio/openwrt-ipq)
- [qosmio/nss-packages](https://github.com/qosmio/nss-packages/tree/NSS-12.5-K6.x)
- [VIKINGYFY/immortalwrt](https://github.com/VIKINGYFY/immortalwrt)
- [ImmortalWrt](https://github.com/immortalwrt/immortalwrt)
- [OpenWrt qca-nss-dp](https://github.com/openwrt/qca-nss-dp)
- [OpenWrt qca-ssdk](https://github.com/openwrt/qca-ssdk)
- CodeLinaro `nss-drv`、`qca-nss-ecm`、`nss-dp`、`qca-ssdk`、`nss-clients`、
  `nss-crypto`、`qca-mcs`、`qca-nss-phy`

## 2. 当前可复现基线

| 层 | 当前状态 |
| --- | --- |
| 源码仓 | `codex/ax6-regmap-pbuf-hardening-20260812@3854ea2aa18e977240b194d0fb35c5007e2e9f3b` |
| 构建仓 | `codex/ax6-regmap-pbuf-build-validation-20260812@dec2de5...` |
| 构建锁 | `.github/ax6-nss-lock.env` 与源码 HEAD 一致 |
| 内核 | Linux `6.18.38` |
| mac80211 backports | `6.18.26` |
| NSS firmware | `12.5`，公开包标签 `v2025.05.01` |
| qosmio 最新观察点 | `25.12-nss@d6848fa2`，`main-nss@92a2d104` |
| VIKINGYFY 最新观察点 | `main@de810bc8` |
| ImmortalWrt 最新观察点 | `master@eaff2b0b`，`openwrt-25.12@3dacd2fb` |
| 最近完整构建 | GitHub Actions `31504561114` 成功；这只证明编译和产物门禁，不证明实机运行 |

工作区在审查开始时均干净。`test-pbuf-fixture.sh`、`test-ax6-boot-guard.sh`、
`test-vlan-add.sh` 已通过。

## 3. Qualcomm 官方驱动锁定状态

| 组件 | 当前提交 | 官方同世代结论 | 处理 |
| --- | --- | --- | --- |
| nss-drv | `6aa14c78...` | 等于 QSDK 13.1/r2 最新公开标签目标 | 保持 |
| qca-nss-ecm | `8c7355bf...` | 等于 QSDK 13.1/r2；13.1.5/r2 是分叉产品线 | 保持基线，逐补丁筛选 |
| nss-dp | `d8f802f0...` | 等于 QSDK 13.1/r2；13.1.5/r2 主要增加 EDMA v2/v3/PPE | 保持基线 |
| qca-ssdk | `d9a19649...` | 等于 QSDK 13.1/r2；13.1.5/r2 大量面向新 PPE/PHY | 保持基线 |
| nss-clients | `51be82d4...` | `12.5.5.r1@aa145559` 是其祖先，当前提交更新 | 禁止降级 |
| nss-crypto | `60e27b91...` | 等于 QSDK 13.1/r2 标签目标 | 保持 |
| qca-mcs | `da120b15...` | 等于 QSDK 13.1/r2 标签目标 | 保持 |
| qca-nss-phy | `85cb19ff...` | 等于 QSDK 13.1/r2 标签目标 | 保持 |

QSDK 14、13.1.5 或编号更大的标签不等于 AX6 的线性升级。它们可能使用不同 PPE、
EDMA、SDX、WiFi classifier、SFE 或平台接口。必须从共同基点审查单个补丁，不能替换源码树。

## 4. qosmio 适配基线约束

qosmio 是 IPQ807x NSS OpenWrt 适配的重要基线，但不是所有组件的最新驱动来源。
当前仓库必须持续满足以下约束：

- `network.globals.packet_steering=0`。
- firewall 软件与硬件 flow offload 均为 `0`。
- 不使用 `config bridge-vlan`、`option vlan_filtering 1`、`lan1:u*` 等 DSA bridge
  VLAN filtering 语法；NSS WiFi offload 下使用 802.1q 端口子接口和独立 bridge。
- NSS firmware 12.5 只按 AP/STA 基线验证；WDS/Mesh 需要 11.4。
- AP_VLAN 仍被 qosmio 标记为 ath11k 已知故障，不得因局部补丁存在就宣称已支持。

当前 boot guard、`nss-check`、`ax6-config-audit`、`vlan-add` 和测试已覆盖上述约束。

qosmio `25.12-nss` 当前锁定 OpenWrt `qca-nss-dp@19c51af0` 与
`qca-ssdk@446db12b`；二者不是当前 Qualcomm 13.1/r2 源码的直接替代品。

## 5. 已确认的新增候选

### P0-A：qcom_hwspinlock 与 APCS regmap 资源边界修复

实机 pstore、运行设备树和 Linux v6.18 源码已经交叉确认：08-10 panic 的直接根因是
`qcom_hwspinlock` 将包含式 `max_register=0x20000` 用于长度同为 `0x20000` 的 MMIO
资源，debugfs 读到 offset `0x20000` 时越过映射末端。APCS 是独立的同类边界风险。

当前源码提交已经完成：

- hwspinlock 使用 `min(驱动原上限, resource_size - reg_stride)`，并拒绝小于一个
  register stride 的资源；
- APCS 使用相同 clamp 语义，避免扩大 SDX55 等平台的原始驱动范围；
- 两个补丁均以 Linux v6.18 fixture 验证可应用性和资源边界。

状态：源码和本地门禁已通过；尚待云端完整构建、新固件离线审计和授权后的实机验证。

### P1-A：ECM multicast 目的接口计数有符号类型修复

CodeLinaro 13.1.5/r2 提交 `5ff84400` 将 NSS IPv4/IPv6 multicast 路径的
`dst_if_cnt` 从 `uint32_t` 改为 `int`。当前 13.1/r2 源码仍使用 `uint32_t`，随后却检查
`dst_if_cnt < 0`，该错误分支永远不能成立。

影响：`ipmr_find_mfc_entry()`/`ip6mr_find_mfc_entry()` 返回负错误码时可能被当作巨大正数，
导致错误循环边界或异常 multicast 更新路径。

方案：精确移植官方提交的四个声明变化，不带入 13.1.5 的其他 PPE/SDX 结构。四条路径为
NSS IPv4、NSS IPv6、SFE IPv4 和 SFE IPv6。

门禁：

- 补丁只允许修改四个 multicast frontend 文件，不得附带接口或结构重构。
- qca-nss-ecm 单包编译、完整 stock 编译、IPv4/IPv6 multicast 配置编译门禁通过。
- 实机观察 ECM multicast、IGMP/MLD、bridge MDB 和内核日志；无越界、WARN、refcount 异常。

状态：官方补丁已移植为 `027-fix-multicast-destination-count-signedness.patch`，四路径
静态门禁 13/13 通过；尚待 qca-nss-ecm prepare、完整构建和实机 multicast 回归。

### P1-B：qca-nss-pbuf 写入结果读回验证

当前 `apply_sysctl()` 吞掉 `sysctl -w` 返回码，并用第二次写入
`n2h_high_water_core0` 作为“确认”，没有读回 `extra/high/wifi_pool`。冷启动时可能出现日志成功但
实际参数未应用。

方案：保留现有 1 GB/512 MB/256 MB 数值和 `START=19`，仅增加：

- 写入返回码检查；
- 三项参数读回比较；
- 有界重试和明确失败日志；
- `extra_pbuf_core0` 已分配时只读验证，不强制运行时改写；
- 不自动重载 WiFi。

该修复不得改变 AX6 当前 1 GB profile，也不得在运行中试改危险 pbuf 数值。

状态：已实现 CodeLinaro PAGE_SIZE 对齐语义的精确回读、零值有限重试、一次性分配
不重复写和失败传播；故障注入门禁 8/8 通过。尚待完整构建和十轮物理冷启动。

### P1-C：Linux 6.18.40 与 mac80211 6.18.39 独立升级验证

ImmortalWrt master 已到 Linux `6.18.40`、mac80211 `6.18.39`；当前分别为 `6.18.38` 和
`6.18.26`。这不是可直接 cherry-pick 的普通版本号更新：mac80211 目录叠加了 100 余个
ath11k NSS 补丁，内核 target 也保留 NSS-DP 而上游已转向 PPE。

方案：拆成两个候选分支，先内核、后 mac80211，不在同一提交升级。每层都要求补丁零 fuzz、
ath11k NSS patch 顺序审计、完整 stock 构建和实机 WiFi/NSS 恢复测试。

## 6. P2 候选

| 候选 | 来源 | AX6 影响 | 处理 |
| --- | --- | --- | --- |
| `ethtool_puts()` 替代固定长度复制 | OpenWrt qca-nss-dp `6a5c471` | 共享 ethtool 清理，无吞吐功能变化 | 小补丁候选，编译矩阵后再考虑 |
| `SOURCE_DATE_EPOCH` 构建日期 | OpenWrt qca-ssdk `c3bf07a` | 提高可复现性，不改运行逻辑 | 低风险独立候选 |
| netdev 注册先于 `phy_connect()` | CodeLinaro NSS-DP `0e633ea` | AX6 DTS 不启用 `qcom,link-poll`，不走该 PHY 路径 | 多设备正确性候选，不作为 AX6 P0/P1 |
| EDMA v2 flexible array 修复 | OpenWrt qca-nss-dp `22fb706` | 只修改 EDMA v2/PPE-DS | 仅多平台/IPQ50xx 构建候选 |
| SSDK MP uniphy reset 回退 | OpenWrt qca-ssdk `bb4f3f0` | MP/MHT/phy-to-phy，不是 AX6 QCA8075 主路径 | 不进入 AX6 stock |

## 7. EXP-only 性能候选

OpenWrt qca-nss-dp 提交 `e3dd38a` 为 EDMA v1 增加 GRO。其提交说明同时指出：由于 EDMA v1
没有 checksum offload，GRO 可能提高 RX，也可能降低性能。VIKINGYFY 的 split-NAPI/GRO 补丁还会
改变 NAPI 拓扑，并替换当前已经验证的 DMA、索引、headroom 和错误回滚修复。

因此：

- 不进入主线候选；
- 不和内核/mac80211/ECM 修复混合；
- 只能在 EXP 分支进行 build-only，然后经明确授权做实机 A/B；
- A/B 必须区分 NSS forwarded flow 与 router-local/host-terminated flow；
- 对比吞吐、CPU softirq、softnet drops、EDMA ring drops、TCP retransmit、LuCI/ubus 延迟；
- 任一 checksum、GRO、fraglist、refcount 或稳定性异常立即回退。

## 8. 明确拒绝整合的改动

1. 不整合 VIKINGYFY 的完整 split-NAPI/GRO 栈来覆盖当前 EDMA correctness 补丁。
2. 不整合 qosmio 的大型 ath11k peer 重构；静态检查发现循环中锁释放后继续访问、退出路径重复
   解锁以及 kickout 局部变量未初始化风险。
3. 不把 ImmortalWrt 新 `target/linux/qualcommax` 整体合并；上游 IPQ807x 已转换为 PPE，
   会替换 NSS-DP DTSI 和当前 NSS 数据面。
4. 不把 ECM 13.1.5/r2 的 97 文件差异整套替换；其中大量内容属于 PPE/SFE/SDX 和新平台。
5. 不降级 nss-clients 到 `12.5.5.r1`。
6. 不启用 DSA bridge VLAN filtering、OpenWrt flow offload、通用 packet steering、Mesh/WDS 或
   AP_VLAN 来“验证新补丁”。
7. 不更新与 AX6 无关的 QCN9074 firmware 或 QCA4019 BDF；当前 ath11k/IPQ WiFi 锁保持。

## 9. 针对性合并顺序

1. 已完成独立源码提交 `3854ea2`：P0-A、P1-A、P1-B 和 NSS 频率初始化保护形成一个
   可追溯正确性候选，各项仍由独立测试门禁隔离。
2. 已完成构建候选 `97b4781`：锁定源码提交和 202 项 patchset SHA256，并在 workflow
   加入 hwspinlock、PBUF、NSS backport 与 qca-nss-ecm prepare 门禁。
3. 推送两个独立分支后只运行一次 stock 完整构建；失败时读取准确日志，不盲目重跑。
4. 对生成的 kernel、DTB、rootfs、kmod、manifest、OpenClash provenance 和 SHA256 做
   独立离线检查；编译后 DTB 门禁也必须通过。
5. 取得授权后再做新固件实机验证：危险 debugfs 路径禁止读取，使用 pstore、固定 sysfs
   计数和冷启动日志确认修复。
6. 本轮候选闭环后，再建立 kernel 6.18.40 独立候选；mac80211 更新不得与内核更新混合。
7. P2 每项一个提交、一个可回退边界；EXP-only GRO/split-NAPI 不与主线候选共用结果。

## 10. 实机只读映射

客户端密钥固定为：

- 文件：`~/.ssh/ax6_check`
- 类型：ED25519
- 公钥指纹：`SHA256:yFtq2ICMaCTj08Ule8NYf9/Uiq6LHhUYYrpa1UXjLbk`

客户端登录密钥不能替代服务器主机身份校验。刷机后观测到的路由器 ED25519 主机指纹为
`SHA256:CwFnr3PlOkNqEZ9BepAaURHnWmlRAm6irI5Tdw5Dmok`，必须由用户确认后才能建立 SSH 会话。

确认后只读采集：

- board/kernel/package/module 版本与仓库锁匹配；
- NSS cores、ECM frontend、EDMA v1、SSDK/QCA8075、ath11k NSS offload；
- IRQ affinity、irqbalance、RPS/RFS/XPS 所有权；
- pbuf/N2H 实际值和启动日志；
- packet steering、flow offload、SQM、VLAN 拓扑；
- 端口/bridge/EDMA/softnet/drop/error/retransmit 计数斜率；
- WiFi station、恢复、固件崩溃和 ring/peer 统计。

本轮不修改实机配置、不执行吞吐流量、不刷写、不重启。运行数据通过后才决定哪些候选值得构建
或实机 A/B。

## 11. 当前结论

当前主驱动锁不是简单“落后”：八个 Qualcomm 组件均位于正确的 QSDK/NSS 兼容世代，且多数
已经是该世代的最新公开标签目标。主要风险不是缺少整仓更新，而是跨产品线误合并。

当前确定的正确性候选已经从“方案”进入本地已验证提交：

1. qcom_hwspinlock/APCS regmap 资源边界修复；
2. ECM multicast 四路径 `dst_if_cnt` 有符号类型修复；
3. pbuf sysctl 写入后的真实读回与失败处理；
4. NSS `current_freq`/`auto_scale` 入口和消费端初始化保护。

上述项目尚不能标记为固件或实机已闭环。内核/mac80211 更新需要后续独立候选分支和构建
验证；EDMA GRO/split-NAPI 仍仅是实验性能路径。云端构建、产物审计和实机授权验证完成前，
不得合并主线或发布。
