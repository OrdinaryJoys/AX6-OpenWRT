# AX6 完整修复、验证与合并执行方案 (2026-08-12)

## 0. 目的和边界

本文是当前 AX6 候选分支的完整执行方案，不是“系统已经无故障”的声明。它把已经确认的
构建故障、75 项问题矩阵、核心驱动候选、性能异常、服务配置、上游移植、固件产物和实机
验收组织成可逐步执行、逐步回退的流程。

目标设备和产品边界固定为：

- Redmi AX6 stock layout，1 GiB SKU；
- IPQ807x、EDMA v1、NSS firmware 12.5；
- Linux 6.18.38 当前正确性候选；
- NSS/ECM/SSDK/ath11k 数据面；
- 不把 IPQ50xx、EDMA v2/v3、PPE-DS、MHT、QSDK 14 改动直接并入 AX6；
- 不自动刷写、重启、恢复配置、合并主线、tag 或发布 Release。

本文不包含私钥、密码、订阅、节点或 ZeroTier secret。实机写操作仍需用户单独确认。

## 1. 当前真实基线

| 层 | 当前状态 |
|---|---|
| 源码仓 | `codex/ax6-regmap-pbuf-hardening-20260812@956cf06b6c86c10de28670157a9c986a74a91454` |
| 构建仓 | `codex/ax6-regmap-pbuf-build-validation-20260812@5d95c33555ae9a6bdca9474b2a25fca63654f721` |
| 实机固件 | `r0-4e35043`，Linux 6.18.38；不是当前候选源码 |
| 云端运行 | Actions `31610278552` 已失败 |
| 已通过范围 | 源码获取、锁定提交、patchset SHA256/provenance |
| 未执行范围 | prepare、编译、DTB、rootfs、kmod、manifest、产物 SHA256 |
| 当前发布状态 | 阻塞，不能刷写或合并主线 |

### 1.1 当前确定失败根因

源码中的实际版本为：

- `qca-nss-drv PKG_RELEASE:=20`；
- `qca-nss-ecm PKG_RELEASE:=10`；
- `hostapd PKG_RELEASE:=2`。

构建 workflow 仍硬编码要求 ECM release 9，lint 又要求 workflow 保留这段旧字符串。K-05
修复把 ECM release 从 9 提升为 10 后，构建仓语义门禁没有同步，最终在
`Clone locked source code` 阶段 fail-fast。

这不是 ECM 源码编译失败，也不是 `956cf06` 不可达。不得通过把 ECM 降回 release 9 绕过。

### 1.2 当前状态统计

K-12 已由 D 转为 B，T-14 已由 D 转为 A。按现有逐项表首状态重新计数：

| 状态 | 数量 | 说明 |
|---|---:|---|
| A | 33 | 实现或既有基线已闭环，但不等于本轮候选已经完成发布验证 |
| B | 7 | K-01..K-06、K-12 已修，等待候选构建/产物/实机 |
| C | 3 | K-09、N-08、W-05 部分修复 |
| D | 12 | 3 个产品项和 9 个无法补救的旧证据项 |
| E | 16 | 缺端点、授权、构建、故障注入或长窗口 |
| N | 4 | 正常行为或不支持项，不应修改 |
| 合计 | 75 | 不含 V-01..V-15 验证与发布动作 |

由于 O-10 当前再次暴露“构建语义锁漂移”，在 P0 完成前应临时记为 C。此时执行状态为
`A=32/B=7/C=4/D=12/E=16/N=4`。P0 构建及 lint 门禁通过后，O-10 才可恢复 A。

## 2. 总体执行原则

1. 每次只解决一个可证明的问题，不用大规模上游合并掩盖局部故障。
2. 源码实现、构建语义、产物内容、实机运行四层分别验证，不能相互代替。
3. 每个候选必须有正向 fixture、至少一个负向 fixture、失败传播和回退点。
4. 性能调整必须单变量 A/B，不能同时改 IRQ、GRO、PAUSE、NSS 频率或内核。
5. 累计计数只看相同负载窗口的差分，不用单点总值宣称故障。
6. LAN-LAN 二层交换不能作为 WAN-LAN/NAT/NSS routed 证据。
7. 未经完整构建和产物审计的源码修复只能保持 B，不能进入实机。
8. 已归档原始证据保持只读；新测试使用独立目录、inventory 和 SHA256。

## 3. P0：恢复可信构建链

### P0-1：建立 package release 单一事实来源

修改 `.github/ax6-nss-lock.env`，增加：

```text
SOURCE_HOSTAPD_PKG_RELEASE=2
SOURCE_QCA_NSS_DRV_PKG_RELEASE=20
SOURCE_QCA_NSS_ECM_PKG_RELEASE=10
```

约束：

- 值必须为正整数；
- 必须来自锁定源码提交，不允许人工猜测；
- source commit、patchset manifest 和 package release 必须在同一提交更新；
- 不把 release 写入多个 workflow 的硬编码字符串。

### P0-2：新增跨仓源码语义验证器

新增 `.github/scripts/verify-ax6-source-semantics.sh`，输入为源码目录和 lock 文件。脚本负责：

1. 精确读取三个 Makefile 的唯一有效 `PKG_RELEASE:=N`；
2. 比较 lock 期望值与源码实际值；
3. 缺失、重复、非数字或不一致均返回非零；
4. 错误信息输出组件、期望值和实际值；
5. 保留现有 hostapd 安全补丁、ECM VLAN、SSDK MAC sync、Wi-Fi ucode 和 ath11k
   recovery 语义检查；
6. 不执行源码修改，不自动“修正”版本。

建议把现有 `Clone locked source code` 中的大段语义检查逐步移入该脚本，workflow 仅调用
验证器，避免 build 与 lint 各维护一份规则。

### P0-3：修复 build workflow

修改 `.github/workflows/build-AX6-NSS.yml`：

- `Load and verify build lock` 必须加载三个 release 变量；
- 删除 ECM release 9 和 hostapd release 2 的散落硬编码；
- 在 source patchset provenance 通过后调用语义验证器；
- 保持 fail-fast；
- source 语义失败后禁止进入 feeds、prepare 和编译；
- provenance 报告记录三个实际 release。

### P0-4：修复 lint workflow

修改 `.github/workflows/lint.yml`：

- 校验三个 release 锁存在且为正整数；
- 校验 build workflow 调用统一语义验证器；
- 禁止 `PKG_RELEASE:=9`、`release must be 9` 等数字硬编码重新出现；
- 对语义验证器运行 shell 语法和 ShellCheck；
- 不再用“错误消息字符串存在”代替真实行为测试。

### P0-5：fixture 和负向测试

新增 `AX6-IPQ/tests/test-source-semantic-lock.sh`，至少覆盖：

| 场景 | 期望 |
|---|---|
| hostapd=2、drv=20、ecm=10 | PASS |
| ECM 源码为 10、lock 为 9 | FAIL |
| ECM release 缺失 | FAIL |
| ECM release 重复定义 | FAIL |
| release 为非数字或 0 | FAIL |
| 修改 source commit 但不刷新 release/manifest | FAIL |
| workflow 再次出现 ECM 9 硬编码 | FAIL |

### P0-6：本地通过标准

必须全部满足：

- `git diff --check`；
- YAML 可解析；
- `actionlint`；
- ShellCheck；
- 新 release fixture 正负场景全部通过；
- 现有顶层 fixtures 全通过，环境缺失项必须明确 SKIP；
- source commit `956cf06...` 可达；
- patchset manifest hash 等于 lock；
- patchset present/absent 清单无漂移；
- 现有 hwspinlock、APCS、PBUF、NSS、ECM、EDMA 门禁无回归。

### P0-7：文档治理

更新状态文件时执行以下规则：

- `AX6_ERRORS_AND_FIXES_MASTER_2026-08-12.md` 从“终版”改为“状态快照”；
- Run `31610278552` 标为失败，记录准确失败步骤；
- O-10 临时 A→C，O-11 记录 provenance 已通过但 build 未开始；
- V-02 标为失败/待新运行；
- K-12 表述为“3 个 handler、6 处 printk”；
- 当前逐项统计按脚本生成，不手工维护数字；
- 旧归档是证据基线，不覆盖新运行状态；
- 不修改既有 SHA256 归档，新增更正附录或新快照。

P0 完成条件：本地所有门禁通过，并形成一个只改构建语义、测试和文档的独立提交。

## 4. P1：候选源码完整构建与产物审计

### P1-1：只触发一次新的 stock 构建

在 P0 提交推送后，触发新 workflow_dispatch：

- variant=`stock`；
- SSH debug=`false`；
- 不使用 EXPAND；
- 不发布 Release；
- 不盲目 rerun `31610278552`。

失败处理：先读取准确步骤和日志，判断属于 source、feeds、prepare、compile、DTB、rootfs
还是 artifact；未经根因确认不重跑。

### P1-2：源码和 prepare 门禁

要求：

- source HEAD 精确等于 `956cf06...`；
- base commit、present、absent 和 manifest SHA256 一致；
- qca-nss-drv release 20；
- qca-nss-ecm release 10；
- 022、017、027、1001、1002 等补丁按顺序应用且无 fuzz；
- qca-nss-drv、qca-nss-ecm、mac80211 prepare 成功；
- K-01..K-06、K-12 fixture 在 CI 中执行。

### P1-3：核心编译门禁

必须确认：

- Linux 6.18.38 kernel；
- qca-nss-drv、qca-nss-dp、qca-ssdk、qca-nss-ecm；
- ath11k NSS 补丁栈和 Wi-Fi firmware 12.5；
- qca-nss-clients、vlan manager、bridge manager、qdisc 依赖；
- stock DTS/DTB 和分区布局；
- 无 unresolved symbol、modpost、section mismatch 或 patch reject。

### P1-4：离线产物审计

构建成功后下载到持久 `NOT-FLASHED` 目录，独立检查：

1. sysupgrade、factory/initramfs/recovery 镜像存在且命名明确；
2. kernel、rootfs、kmod、设备 manifest 恰好对应本轮 run；
3. 设备 manifest 与 rootfs `opkg` 已安装清单完全一致；
4. OpenClash 插件实际版本、resolved commit、AArch64 Meta core ELF 和 SHA256 一致；
5. BUILD-LOCK/PROVENANCE 包含 source、feeds、插件和 package release；
6. stock DTB 的 aliases、nvmem、MAC、rootfs/rootfs_1、stock layout 正确；
7. NSS/ECM/EDMA/SSDK/ath11k 模块和启动脚本存在；
8. OpenWrt flow offload、hardware flow offload 和通用 packet steering 默认关闭；
9. 不出现 DSA bridge-vlan、错误 IRQ overlay 或重复自定义 affinity 所有者；
10. 所有文件由顶层 SHA256 清单覆盖并逐项通过。

### P1-5：兼容性预检

只有 P1-4 全通过后，才把真实 sysupgrade 传到 `/tmp` 并执行 `sysupgrade -T`。此步骤：

- 只做兼容性预检；
- 不带 `-n` 或 `-c` 执行实际刷写；
- 不重启；
- 记录镜像 SHA256、设备 board_name、分区容量和返回码；
- 失败即隔离镜像，不尝试强制刷写。

P1 完成条件：完整 stock build 成功，产物独立审计和 `sysupgrade -T` 全通过。

## 5. P1：新候选核心驱动实机验收

本阶段必须在用户明确授权刷写后执行，并先验证备份、回退镜像和恢复清单。建议不保留配置
刷写，再按审计过的白名单恢复；`/etc/shadow` 和登录密码不得恢复。

### P1-6：K-01/K-02 regmap 边界

- 十轮物理冷启动；
- 每轮保存 boot ID、pstore、dmesg 受控日志和模块状态；
- 禁止递归读 debugfs；
- 禁止读取旧危险路径 `regmap/1905000.hwlock/registers`；
- 无 panic、SError、external abort、regmap 越界或 pstore 新记录。

### P1-7：K-03/K-06 PBUF 和 NSS 启动参数

- 每轮核对 `extra_pbuf_core0`、high-water、Wi-Fi pool、queue limit 和 RPS bitmap；
- 验证写入失败能传播，不出现“日志成功但读回不一致”；
- 不在运行中反复写一次性 PBUF 分配参数；
- 十轮冷启动全部一致才由 B 转 A。

### P1-8：K-04/K-12 NSS 频率和日志

- `current_freq`/`auto_scale` 在 core 未初始化时不得触发空指针或 workqueue 异常；
- 运行中只读 sysctl 不再产生 warn/alert 级日志污染；
- 当前 qualcommax 未启用 `CONFIG_DYNAMIC_DEBUG`，因此 `pr_debug` 通常不会输出；
- 不宣称可通过 dynamic debug 查看，除非未来候选显式启用该配置并另行验证；
- 不同时调整固定频率策略。

### P1-9：K-05 ECM multicast

- IPv4 IGMP、IPv6 MLD、bridge MDB 和 ECM multicast 分别验证；
- NSS 和 SFE 四路径的负返回码不得变为大循环边界；
- 无 WARN、越界、refcount、classifier 或连接残留；
- 单播 OpenClash、ZeroTier 和普通 LAN/WAN 流量不能回归。

### P1-10：K-13/K-14/K-15 加速所有权

- UCI 和运行态 software/hardware flow offload 均为 0；
- `packet_steering=0`，但 Linux RPS/RFS/XPS 的 AX6 专用策略必须存在；
- NSS internal RPS 保持启用；
- ECM `disable_offloads=1`，`disable_gro_list=1`；
- `disable_flow_control=0`，不擅自改物理 PAUSE/autoneg；
- IRQ affinity 只由 qualcommax 上游脚本所有；
- 重启后上述状态不能漂移。

## 6. P1：网络和服务回归

### P1-11：VLAN、Firewall、DHCP

- 禁止 DSA `bridge-vlan`/`vlan_filtering=1`；
- 使用 802.1q 端口子接口和独立 bridge；
- `vlan-add` 创建、重复执行、非法输入和失败回滚分别验证；
- firewall zone、forwarding、DHCP 和接口设备完整；
- 不在未经确认时创建新实机 VLAN。

### P1-12：OpenClash DNS

- 7874 直探、dnsmasq redirect、健康守护、失败计数和冷却窗口；
- SIGSTOP 故障注入后能够恢复；
- 不修改订阅、覆写和当前配置文件；
- 保留 GeoIP/GeoSite/GeoASN/CHNR 自动更新；
- ZeroTier bypass、局域网 DNS、互联网域名和本地域名均回归；
- LuCI 页面慢不能仅凭总加载时间归因 DNS，需逐 XHR/ubus 计时。

### P1-13：ZeroTier

- daemon ONLINE、network membership、managed address 和 interface 一致；
- secondaryPort/实际监听端口与 fw4 include 一致；
- restart 返回非零但新 daemon ONLINE 时不误判失败；
- LAN→ZT、ZT→LAN、远端 Mac→LuCI/SSH、反向访问分别测试；
- 4 MiB socket buffer 的实际每 socket 值和高速 UDP receive drops 做差分；
- N-08 在新固件高速压测归零前保持 C。

### P1-14：UPnP、OpenVPN、ZRAM

- UPnP 默认关闭、无活动映射；启用测试需要独立授权和受控端口；
- OpenVPN 关闭/未安装时无 zone、forwarding、DNAT、socket 和接口残留；
- ZRAM 设备、算法、容量和启动链正确；
- 做受控内存压力，记录 CPU、压缩比、OOM、swap in/out，不以“已使用 100%”单点判错。

## 7. P2：性能、丢包和端点专项

### P2-1：关闭 W-05 LAN-LAN 双向不公平

当前证据是：单向两边 946-949 Mbps；双向时低速始终跟随 Windows 接收方向，AX6 的
接口、softnet、qdisc 和 EDMA 活动错误增量为 0。因此先验证端点，不先改路由驱动。

单变量顺序：

1. 导出 Windows NIC 型号、硬件 ID、驱动/固件、PCIe link、RSS 队列和高级属性；
2. EEE/Green Ethernet A/B；
3. Flow Control Auto/Disabled A/B；
4. RSS、RSC、LSO、checksum offload、interrupt moderation 分别 A/B；
5. 交换 lan1/lan2 端口和两根网线；
6. 第二台 Linux/macOS 有线端点；
7. 同一 Windows 硬件临时 Linux 对照。

每个变量三轮，测试后恢复。通过条件：单向每边 >=930 Mbps；双向每方向 >=850 Mbps；
三轮差异 <=10%；无集中 TCP retransmit；路由接口/softnet/qdisc/EDMA 活动错误增量为 0。

### P2-2：物理 PAUSE 条件测试

只有 P2-1 排除端点后才执行：

- 保存 ethtool advertisement、PAUSE 和 SSDK MIB；
- 临时改变单一端口组合，不改 UCI，不重启 ECM；
- 确认重新协商为 1 Gbps full；
- 无稳定三轮收益或出现 overflow/drop 时立即恢复并否决；
- 不把 requested/negotiated 不同直接判为故障。

### P2-3：真实 WAN-LAN NSS/ECM routed 测试

- 在 WAN 上游网络增加独立 iperf3 端点；
- preflight 证明流量经过 AX6 wan，拒绝同 LAN 或 router-local 路径；
- TCP P1/P4 forward、reverse、bidir 各三轮；
- UDP 300/600/900 Mbps 随机顺序各三轮；
- 同步记录 ECM connection delta、wan/lan MIB、EDMA、softnet、CPU、温度和 NSS 频率；
- 只有 egress=wan 且 ECM/NSS 计数匹配才写为 NSS routed 结果。

### P2-4：NSS 频率 A/B

只在 P2-3 的真实 routed 瓶颈存在时执行：

- 固定中频/高频各三轮；
- 非持久调整，重启恢复；
- 不与 IRQ、GRO、PAUSE、内核或 split-NAPI 同时修改；
- 吞吐无稳定收益或温度/功耗明显恶化即否决。

### P2-5：Wi-Fi 和 IoT

- 国家码 US；2.4G HE40 + `ht_coex=1`，允许运行时 HE20；禁止 `noscan=1`；
- legacy/HT/HE 客户端分别做关联、DHCP、DNS、空闲、持续流和重连；
- 按设备 MAC、芯片、RSSI、重试、deauth/disassoc 原因记录；
- 5G `wifili_wbm_src_reo_code_inv` 只做时间关联差分；未关联用户可见丢包前不改驱动；
- AP_VLAN、WDS/Mesh 继续标记不支持，不通过局部补丁强开。

## 8. P2/P3：核心驱动未修项和重构

### P2-6：K-07 EDMA portable DMA

独立 Track B，不与当前正确性候选合并：

- 梳理 RX descriptor、DMA map/unmap、skb/data ownership；
- 移除对 identity-DMA 和 `phys_to_virt(dma_addr)` 的隐式依赖；
- 对 map error、refill failure、teardown 和 non-coherent 平台建模；
- AX6 identity-DMA 与至少一个非 identity-DMA fixture；
- 必须通过 KASAN/DEBUG_DMA_API 可用环境或等价故障注入；
- 未完成前保持 AX6 ring/store 约束，不阻塞当前 stock 发布，但不得宣称通用可移植。

### P2-7：K-08/K-09 EDMA store 模型

- invalid store index 必须计数、ratelimit warning 并完成 descriptor/skb/DMA 清理；
- 定义 ring 到 store 的唯一映射和所有权；
- 覆盖 1/1/1/1 当前 AX6 和多 ring 负向 fixture；
- 故障注入检查无 double free、leak、stale descriptor 或 silent skip；
- 重构完成前发布门禁继续固定 1/1/1/1。

### P2-8：K-10 PHY teardown

- 对 `phy_connect()` NULL、ERR_PTR 和部分初始化分别注入；
- 验证 netdev 注册顺序、IRQ/NAPI、PHY、DMA 和 workqueue 释放；
- 不因 qosmio/OpenWrt 有类似提交就整包移植；
- AX6 DTS 未命中路径时记录为多设备正确性，不假装实机覆盖。

### P2-9：K-11 NSS netlink 权限

- 定位具体 generic netlink family、operation 和 policy；
- 核对 `GENL_ADMIN_PERM`/capability 检查及 namespace 行为；
- 未授权请求必须拒绝，合法管理员路径必须工作；
- 不只凭一次 userspace EPERM 宣称 handler 已安全。

### P3-1：OpenClash overlay 重复 core

- 不在线删除 upperdir；
- 比较 ROM 和 overlay core 的 inode、SHA256、版本和使用路径；
- 干净刷写后验证不产生重复 copy-up；
- 只有离线维护或明确确认 ROM-identical 时清理；
- 保留 Geo 自动更新和正常空间预算。

### P3-2：内核与 mac80211 更新

- Linux 6.18.40/后续版本单独候选；
- mac80211 更新另一个候选，不能与内核同提交；
- 每层要求补丁零 fuzz、ath11k NSS 顺序审计、完整 stock build；
- 通过冷启动、Wi-Fi recovery、NSS offload、IoT、吞吐和 24/72 小时后才评估合并。

### P3-3：EXP-only split-NAPI/GRO

- 只允许独立实验分支；
- 默认不启用 GRO；
- 必须区分 forwarded 与 host-terminated；
- 检查 checksum、fraglist、truesize、softnet、NAPI 和 LuCI/SSH 延迟；
- 任一数据完整性或稳定性异常立即回退；
- 不用于修复当前 Windows 接收方向异常，除非 P2-1/P2-3 证明路由端根因。

## 9. 上游移植规则

审查顺序固定为：Qualcomm CodeLinaro → qosmio/openwrt-ipq 和 nss-packages →
OpenWrt qca-nss-dp/qca-ssdk → VIKINGYFY → ImmortalWrt → 当前两仓实现。

每个候选必须记录：

- 上游仓库、精确提交、分支/标签和共同基点；
- 修改文件、适用 SoC、EDMA/PPE/NSS firmware 世代；
- 当前仓是否已有等价、超集或冲突补丁；
- 最小回移内容和拒绝带入的相邻改动；
- 编译、fixture、实机路径和回退提交。

允许优先评估的低风险独立候选：

- qca-nss-dp `ethtool_puts()` API 清理；
- qca-ssdk `SOURCE_DATE_EPOCH` 可复现构建日期。

明确拒绝：整分支替换 qosmio/VIKINGYFY/ImmortalWrt/CodeLinaro 新产品线、QSDK 14、
EDMA v2/v3、PPE-DS、MHT/MP、未验证 AP_VLAN/WDS/Mesh，以及以版本号更大为理由降级或替换
当前 QSDK 13.1/r2 驱动锁。

## 10. 长稳、备份与回退

### 10.1 24 小时压力

- 有线双向、Wi-Fi、OpenClash DNS、ZeroTier、文件共享交替负载；
- 每阶段保存接口、EDMA、softnet、qdisc、ECM、NSS、内存、温度和日志差分；
- 观察 ath11k recovery、invalid REO、alloc_fail、DNS watchdog 和 ZT drops。

### 10.2 72 小时正常业务

- 不持续压满链路；
- 每小时采样同一组计数器；
- K-16、N-13、W-03、W-04 按斜率而非累计值判断；
- 任一 crash、pstore、服务活锁或持续丢包必须重新打开对应问题。

### 10.3 recovery 和回退

- 验证 stock recovery/initramfs 和上一已知正常 sysupgrade 的 SHA256；
- 保存分区表、boot slot、board identity 和恢复步骤；
- 恢复配置采用白名单，不恢复 `/etc/shadow`；
- recovery 演练需要独立维护窗口和明确授权；
- 未完成回退验证前不发布给普通用户。

## 11. 合并和发布门禁

### 11.1 当前 P0/P1 候选允许合并主线的必要条件

- release 单一事实来源和负向 fixture 完成；
- 新 stock Actions 完整成功；
- DTB、rootfs、kmod、manifest、OpenClash provenance 和 SHA256 独立通过；
- `sysupgrade -T` 通过；
- K-01..K-06、K-12 新固件实机验收通过；
- 十轮物理冷启动无 panic/pstore/NSS/ath11k 启动错误；
- ECM multicast、RPS/RFS/XPS、VLAN、OpenClash、ZeroTier 回归通过；
- 回退镜像和恢复清单可用。

### 11.2 不阻塞正确性候选、但必须明确保留的问题

- K-07/K-08/K-09 通用 EDMA 重构；
- W-05 Windows 接收方向异常，若第二 Linux 端点证明为端点问题；
- W-06 真实 WAN routed 性能，若产品发布说明明确未完成；
- N-08 ZeroTier 极限 UDP drops；
- W-03/W-04 特定客户端和统计项长稳；
- O-07 overlay 重复 core；
- P3 内核/mac80211/EXP 候选。

这些项目必须出现在 Release notes 的已知限制中，不能被“构建成功”自动关闭。

## 12. 失败分流和回退矩阵

| 失败层 | 动作 | 禁止动作 |
|---|---|---|
| lock/semantic | 修锁或验证器，重新本地 fixture | 改源码 release 迎合旧门禁 |
| source prepare | 定位具体补丁和上游基点 | 整分支覆盖或跳过 patch failure |
| compile/modpost | 定位组件和符号依赖 | 删除模块或关闭功能掩盖错误 |
| DTB/layout | 阻断镜像并核对 stock 分区 | 强制 `sysupgrade -F` |
| rootfs/manifest | 阻断产物并修构建逻辑 | 手工向镜像补文件后发布 |
| 实机启动 | 回退已知正常镜像，保存 pstore | 连续盲刷或清空证据 |
| 性能回归 | 恢复唯一 A/B 变量 | 同时调整多个加速参数 |
| 服务回归 | 回退对应单独提交 | 修改订阅、secret 或用户密码 |

## 13. 推荐执行顺序

1. P0-1 至 P0-7：修构建语义和文档，不碰驱动实现。
2. P1-1 至 P1-5：新 stock 构建、产物审计、`sysupgrade -T`。
3. 用户授权后 P1-6 至 P1-14：新固件核心驱动和服务验收。
4. P2-1：先关闭 Windows 接收方向端点变量。
5. P2-3：补真实 WAN-LAN/NSS routed 基线。
6. P2-2/P2-4：只有前两步提供证据时才测 PAUSE 或 NSS 频率。
7. P2-5：IoT/5G 受控客户端矩阵。
8. P2-6 至 P2-9：未修核心驱动项各自独立分支。
9. 24/72 小时长稳和 recovery。
10. 当前正确性候选满足门禁后再决定主线合并；P3 始终独立。

## 14. 当前结论

当前第一优先级不是继续修改 NSS/ECM 驱动，而是修复构建仓 release 语义门禁漂移，并重新
取得可信的完整构建与产物。`956cf06` 中 K-01..K-06、K-12 目前只在源码和 fixture 层成立，
不能标为固件或实机闭环。

双向吞吐现象仍以 Windows 接收方向高疑，现有数据没有证明 NSS/EDMA/SSDK 是根因；真实
WAN-LAN/NAT/NSS routed 性能仍未验证。EDMA portable DMA/store 模型属于后续独立重构，
不能混入当前 P0/P1 正确性构建。

只有完成“构建语义 → 完整 stock build → 离线产物 → `sysupgrade -T` → 授权实机 →
冷启动/服务/性能/长稳 → 回退”整条链路后，当前候选才具备主线合并资格。
