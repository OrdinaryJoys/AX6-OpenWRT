# AX6 合并、修复与实机验证主方案（2026-08-10）

## 1. 结论摘要

当前工作应分成三条互不混合的链：

1. **基线合并链**：合并已经通过完整构建、产物和实机运行验证的正确性修复。
2. **性能候选链**：NSS 固定高频与 qca-nss-dp split-NAPI 分开测试，不能同时改
   GRO、IRQ、内核或 Wi-Fi。
3. **上游升级链**：Linux 6.18.41、hostapd/wifi-scripts 和 VIKING patch refresh
   另建候选，不覆盖当前已验证的 AX6 stock DTS、ECM host path 和 NSS patch stack。

截至本文更新：

- `OrdinaryJoys/immortalwrt-nss` 的 `main@56807d9` 是候选源码的祖先；候选在其上
  前进 70 个提交，涉及 202 个文件；驱动代码头为 `be691ad`，测试头为 `4e350435`。
- `OrdinaryJoys/AX6-OpenWRT` 的 `main@099556a` 是集成分支的祖先；固件构建验证头
  `d8d9bd9` 前进 66 个提交，测试工具头 `e66dd45` 前进 68 个提交。
- GitHub Actions `31315718824` 已在构建提交 `193e5fb`、源码 `be691ad` 上完整
  成功，现只作为旧锁历史对照；新锁证据由 `31351445144` 取代。
- 当前未发现应立即修改实机配置的新 P0 故障。本轮不刷写、不重载服务、不修改
  UCI、OpenClash 订阅或覆写。
- 源码分支 `4e350435` 与构建分支 `d8d9bd9` 已推送；lint
  [31351390852](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/31351390852)
  完整通过。STOCK build
  [31351445144](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/31351445144)
  已完整成功，产物也已独立下载复核通过。
- 后续测试工具提交 `e66dd45` 的 lint
  [31352053415](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/31352053415)
  也已通过；它不改变 `d8d9bd9` 正在编译的固件目标内容。

因此 `4e350435 + d8d9bd9` 已满足 AX6 stock 候选的静态、编译和产物门禁，可以进入
用户确认后的实机测试；它仍不满足源码全局主线合并门禁，也不能把性能候选作为默认
配置发布。

## 2. 已独立验证的构建证据

### 2.1 Actions 运行

当前成功运行：[31351445144](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/31351445144)

以下步骤全部成功：源码锁、feed 锁、NSS patch prepare、回归断言、完整固件编译、
stock DTB、最终 rootfs、sysupgrade/recovery/kmod、manifest 和 SHA256。Release 步骤
在候选分支正确跳过。构建头为 `d8d9bd9`，源码锁为 `4e350435`；前一成功运行
`31315718824` 仅保留为 `be691ad` 旧锁历史证据。

### 2.2 独立下载后的结果

| 项目 | 结果 |
|---|---|
| sysupgrade | 53,187,362 字节；SHA256 `a78cf65a9668...bf585fa` |
| initramfs ITB | 52,666,180 字节；SHA256 `db582bf4d851...93de24b8` |
| factory UBI | 55,181,312 字节；SHA256 `e9660ca3b686...b5112045` |
| sysupgrade 内 rootfs | SquashFS/XZ，47,341,568 字节；SHA256 `158469ef7405...b6b0461` |
| 设备 manifest | 恰好 391 项 |
| rootfs opkg status | 恰好 391 项，与 manifest 排序后逐项一致 |
| OpenClash | 插件 `0.47.133`，Meta core SHA256 与 BUILD-LOCK 完全一致 |
| AX6 运行文件 | 从 SquashFS 单独读取 36 个文件，SHA256 与仓库源文件全部一致 |
| recovery/sysupgrade | BUILD-LOCK 与设备 manifest 分别字节一致 |
| kmod | 143 个 ipk、Packages 元数据、归档和全部 SHA256 均通过 |
| source patchset | 193 个存在项、15 个缺席项；manifest SHA256 `a161d445...10a031` |

macOS `unsquashfs` 全量解包会因内核模块硬链接重复和 `/dev/console` 创建设备节点
失败；使用 `unsquashfs -cat/-ll` 的逐文件验证通过，Linux CI 的完整 rootfs 门禁也
通过。因此该现象是宿主工具/权限边界，不是固件文件系统损坏证据。

### 2.3 最终 rootfs 的关键状态

- Linux `6.18.38`；NSS-DP `d8f802f0`；NSS-DRV `6aa14c7-r18`；
  ECM `8c7355b-r9`；SSDK `d9a19649`。
- `disable_offloads=1`、`disable_gro_list=1`，host path 为 `br-lan`，物理口为
  `report`，没有把物理 NSS 数据面端口强制关 offload。
- OpenWrt software/hardware flow offload 关闭；SQM 默认关闭；Linux RPS/XPS 默认
  不启用；NSS internal RPS 保留。
- ZeroTier、UPnP、OpenVPN 默认关闭；服务存在不等于开机运行。
- 未安装 `sing-box`、`xray-core`；OpenClash 使用内置 AArch64 Meta core。
- 不生成默认 `bridge-vlan`，VLAN 只由用户显式配置创建。

## 3. 新检出的验证缺口及修复

### P0-M0：AX6 构建成功不能证明源码分支可直接合并主线

`4e350435` 相对源码 `main@56807d9` 不是一个只改 AX6 的小补丁集。完整差异为 70 个
提交、202 个文件、约 5,591 行新增和 1,218 行删除，其中包括：

- Linux 6.18.35→6.18.38 及 generic patch refresh；
- airoha、armsr、ipq40xx、mediatek、rockchip、starfive 等非 AX6 路径；
- hostapd、wifi-scripts、ubus、libubox、netifd 的全局更新；
- AX6 的 NSS-DP/NSS-DRV/ECM/SSDK、ath11k、DTS 和 APCS 修复。

因此，当前 stock build 只能证明“精确锁定 `4e350435` 的 AX6 候选可构建并可进入
产物/实机验证”，不能证明上述非 AX6 目标没有回归。此前计划中“构建通过后直接将
70 个提交合入源码 main”的方向不成立，现已阻断。

处理边界：

1. 实机候选继续锁定 `4e350435`，不因主线尚未合并而改变测试对象。
2. 源码 main 合并必须另选一条路径：要么先完成 6.18.38 全局同步和受影响目标的
   编译矩阵，再叠加 AX6 修复；要么把 AX6 修复重放到 main 的 6.18.35 上。
3. 任一重放都会产生新源码 SHA，必须更新 193 项 manifest、重新完整构建和独立审查
   产物，不能沿用 `4e350435` 的构建证据。
4. 当前阶段不创建“可直接合并”的源码 PR；只允许审查型 draft/tracking PR，且必须
   明确标注非 AX6 目标尚未验证。

### P0-M1：APCS 测试未进入远端锁和云端门禁

驱动补丁 `be691ad` 已构建成功，但覆盖 IPQ8074/IPQ6018/SDX55 的 20 项静态测试
只存在于本地提交 `4e350435`。若直接合并，补丁和测试会处于不同证据链。

修复：

- 源码锁前移至 `4e350435cd9e38d8d0d1fbae2d6ad523a45e622e`；
- 全量 source patchset manifest 从 191 增至 193 个存在文件；
- 新 manifest SHA256 为
  `a161d445e36f1427e34f756e5a0152bc8342653cd38b71fee5fbaf482810a031`；
- build fast gate 增加 `tests/test-apcs-regmap-boundary.sh`；
- 本地 APCS 测试 20/20、EDMA correctness、Xiaomi stock upgrade 均通过。

该变更只增加测试和溯源，不改驱动目标代码；但因锁定提交和 BUILD-LOCK 变化，
仍必须重新跑 lint 和完整 stock build。

### P0-M2：旧性能脚本测错数据面

`ax6-perf-test.sh` 把路由器本机作为 iperf3 server，测到的是 AX6 host-terminated
path。它适合复核 LuCI/SSH/本机 socket 路径，却不能证明 WAN-LAN 转发吞吐、ECM
加速、split-NAPI 或 NSS 频率是否有效。

修复：新增 `AX6-IPQ/scripts/ax6-routed-perf-test.sh`：

- 必须在 LAN 客户端运行，目标必须是 WAN 侧独立 iperf3 server；
- preflight 从路由器执行 `ip route get`，拒绝目标经 `br-lan/lan1/lan2/lan3`；
- run 模式必须显式提供源码版本、构建提交和 `--confirm-load-test`；
- 每轮执行 LAN→WAN、WAN→LAN、双向三种测试，默认三轮；
- 双向 JSON 同时记录 `sum_sent/sum_received` 和 iperf3 官方的
  `sum_sent_bidir_reverse/sum_received_bidir_reverse`；缺少反向并发通道时将整轮标为
  `INCOMPLETE`，不能拿半份结果作结论；
- 保存原始 JSON、ping、boot ID、TCP/UDP/softnet、ECM connection、EDMA error、
  接口 error/drop、NSS/config audit 和中断分布；
- 不在路由器启动 iperf3，不修改路由器配置，不使用 `killall`。

### P1-M3：NSS 频率工具不能直接持久化用于归因

VIKING 的 `nss_freq` 会写 UCI 并在启动时恢复。若与 split-NAPI、IRQ 或新内核同轮
使用，会污染单变量归因。

修复：新增 `AX6-IPQ/scripts/ax6-nss-frequency-ab.sh`：

- 默认命令是只读 `status`；
- 只支持 IPQ8074 固定中频 `748800000` 与固定高频 `1689600000`；
- runtime write 必须同时匹配期望源码版本、构建提交、健康门禁和
  `--confirm-runtime-write`；
- 只写 `/proc/sys/dev/nss/clock/current_freq`，从不写 UCI；
- 保存 boot ID 和原频率；失败时尝试立即恢复；跨重启拒绝使用旧状态恢复。
- restore 前重新检查运行固件身份，并要求状态文件中的源码/构建身份完全一致。

这只是测试工具，不是默认高频配置，也不授权当前实机写入。

## 4. 上游更新逐组处理

上游引用于 2026-08-10 刷新：

| 上游 | 当前提交 | AX6 处理 |
|---|---|---|
| VIKINGYFY/immortalwrt | `5cc85e6c534d` | 逐组比较，不做 branch merge |
| ImmortalWrt master | `950703747550`，Linux `6.18.41` | 独立内核候选 |
| qosmio/openwrt-ipq main-nss | `92a2d104145c`，Linux 6.12.92 线 | 仅作 vendor NSS 语义参考 |
| OrdinaryJoys 源码 main | `56807d9661db` | 当前候选的祖先 |

### 4.1 可吸收但必须独立验证

| 更新组 | 原因 | 合并方式 |
|---|---|---|
| Linux 6.18.41 + patch refresh | 包含稳定内核更新，但会改变 6.18.38 patch offset 和 ABI | 单独源码/构建分支，全量 kmod/DTB/rootfs 回归 |
| hostapd/wifi-scripts | 包含 MLD、CSA、STA、rate 等修复 | 单独 Wi-Fi 分支，IoT 2.4G 与 5G 回归 |
| split Rx/Tx NAPI | 可能改善双向吞吐调度 | 只移植“无 GRO 默认”的 `009` 候选到新基线 |
| `nss_freq` status | 可改善可观测性 | 先用非持久 A/B 工具；不引入启动持久化 |
| qcomsmem 多 flash 设备 | 对新 DTS 重构有价值 | 仅随 6.18.41 分支评估，不单独覆盖 stock DTS |

### 4.2 当前明确拒绝直接合并

| 上游项 | 拒绝原因 |
|---|---|
| VIKING 整体 `main` 或整个 qualcommax 目录 | 与本地 NSS/ECM/EDMA/stock DTS patch stack 大面积重叠 |
| `007-edma-v1-split-napi-gro.patch` | 同时改变 NAPI 和默认 GRO，无法单变量归因 |
| VIKING `smp_affinity` | 同时固定 EDMA IRQ 并打开 GRO/checksum，与 host-path 策略冲突 |
| VIKING AX6 stock ART/nvmem 恢复 | 当前 custom U-Boot/SMEM live FDT 会造成悬空 phandle 风险 |
| `auto_scale=1` | 与固定频率 A/B 是另一变量，当前不测试 |
| QCA8084/QCA81xx PHY 修复 | AX6 使用 QCA8075 千兆 PHY，不命中目标硬件 |
| qca_edma/DSA conduit 修复 | 当前 AX6 stock 数据面是 vendor qca-nss-dp EDMA |
| packages feed HEAD | 已确认 trafficshaper/freeradius3 全局 Kconfig 递归依赖 |

Argon Theme 上游已从锁定 `e2935dc` 前进到 `86c3156`，仅包含两个模板向
`head_meta` 显式传入页面变量的浏览器标签修复。它不影响 NSS、ECM、Wi-Fi 或固件
分区，但当前构建继续冻结旧锁以保持证据单一；新提交列为基线闭环后的 P2 插件候选，
需单独做 LuCI 登录页、标签标题和完整构建回归，不夹入本次运行中的构建。

VIKING 最新 patch refresh 主要是 Linux 6.18.41 上的上下文刷新，不等于当前本地补丁
已经失效。Linux master 的 APCS 驱动仍把 `max_register` 固定为 `0x1008`；本仓按
MMIO resource size 限界的补丁在内核升级分支仍需重新判断，而不能仅因上游删除本地
文件名就删除修复。

## 5. 主线合并顺序

### M0：冻结候选

1. 源码候选固定为 `4e350435`。
2. 构建候选固定 OpenClash/feed/core 哈希，不同步新的移动 HEAD。
3. 门禁/方案头固定为 `d8d9bd9`，后续测试工具固定为 `e66dd45`；二者均已推送。
4. `git diff --check`、ShellCheck、全部 fixture 和源 manifest 必须通过。

### M1：固定源码候选的可达性和审查边界

1. 推送 `codex/ax6-apcs-regmap-boundary-20260803@4e350435`。
2. 保持远端分支，保证构建锁定 SHA 可达；不得删除或强推该分支。
3. 如建立 PR，只能是 draft/tracking PR，不标记 ready，不直接合并 `main`。
4. 不夹带 split-NAPI、6.18.41、GRO、IRQ、Wi-Fi 或新 stock nvmem 更新。

### M2：构建仓库 PR

1. 锁定 `SOURCE_COMMIT=4e350435` 并校验 193 个 source diff 文件。
2. 云端 lint 全通过后执行一次完整 STOCK 构建，不做 EXPAND、不发布。
3. 下载 artifact，重复第 2 节的独立核对。
4. 新 BUILD-LOCK、rootfs 版本、设备 manifest、OpenClash core 和 kmod 必须闭环。

### M3：候选实机入口

完整 build 和独立 artifact 复核通过后，`4e350435 + d8d9bd9` 才成为可请求用户确认的
实机候选。测试工具使用 `e66dd45` 或后续已通过 lint 的头，不要求重编固件。任何刷写、
频率写入和满载压测仍需用户单独确认。

### M4：最终主线合并顺序

当前禁止直接执行最终合并。应在以下两条路线中选择一条：

1. **全局同步路线**：先把 6.18.35→6.18.38 及 generic/非 AX6 更新形成独立 PR，
   对受影响目标执行编译矩阵；再在其上提交 AX6 NSS/Wi-Fi/DTS/APCS 修复。
2. **AX6 回移植路线**：从 `main@56807d9` 建新分支，只重放 AX6 所需修复，并逐项
   解决 6.18.35 上的上下文/API 差异；重新构建和实机验证。

只有选定路线的最终源码提交进入 main 且保持可达后，构建仓库 PR 才能更新到该精确
SHA 并重新构建。禁止 squash 已被构建锁定的提交；若发生 squash，必须重锁、重建，
不得沿用旧产物。

由于 `4e350435` 相对 `be691ad` 只增加测试，M2 构建通过后无需仅为该测试提交重新
刷机；现有 `r0-be691ad` 实机证据仍能代表相同驱动目标代码。任何后续驱动源码变更
则必须重新刷写候选并测试。

## 6. 性能候选分支

### F1：固定频率 A/B（不换固件）

保持当前 6.18.38、单 NAPI、GRO/IRQ/ECM/Wi-Fi/SQM 全部不变：

1. `status` 和 routed preflight；
2. 固定中频三轮单流、三轮四流；
3. 临时固定高频，重复完全相同矩阵；
4. 立即 restore，并验证 NSS/config audit；
5. 不 reboot、不 reload、不写 UCI。

只有高频在两个方向和双向均稳定改善，且无温度、重传、drop 或服务回归，才值得
讨论持久化频率策略。一次峰值提高不能作为合并证据。

### F2：split-NAPI（需要独立固件）

旧 split-NAPI 候选与当前 `4e350435` 已分叉：共同祖先 `34c20bca`，当前基线独有
5 个提交，旧候选独有 4 个提交。因此不能直接把旧分支当作当前可刷测试固件。

正确做法：

1. 从 `4e350435` 新建源码分支；
2. 只加入旧候选最终 `009-edma-v1-split-napi-candidate.patch` 和对应测试；
3. 保留当前 `008` correctness、APCS、stock DTS、ECM 与 Wi-Fi 不变；
4. 明确断言不存在 `napi_gro_receive`、`NETIF_F_GRO` 默认启用；
5. 新建构建分支锁定该提交，完整构建并独立审查 artifact；
6. 用户确认后才备份、全新刷写并执行同一 routed 矩阵。

### F3：6.18.41 / Wi-Fi

在 F1/F2 结论完成前不开始。内核与 Wi-Fi 各自独立；如果 6.18.41 是 Wi-Fi 更新的
必要前置，文档必须明确依赖，仍不得加入 split-NAPI 或高频默认。

## 7. 实机测试矩阵和验收

### 7.1 拓扑

```text
LAN 测试机 --有线--> AX6 LAN | NAT/路由/ECM/NSS | AX6 WAN --有线--> WAN 侧 iperf3 服务器
```

两端使用相同主版本 iperf3。服务器不能是 AX6 本机，目标路由不能返回 `br-lan` 或
LAN 物理口。测试目标应设置为 OpenClash 直连，不能修改订阅文件；使用运行态的
独立直连规则或物理隔离测试网，具体操作需另行确认。

### 7.2 可执行入口

WAN 侧独立 Linux 服务器先启动：

```sh
iperf3 -s -p 15211
```

LAN 测试机先只做路径和身份检查。`AX6_EXPECTED_SOURCE_REVISION` 必须使用实机
`/etc/openwrt_release` 的完整值，不能凭提交短号猜测：

```sh
AX6_IPERF_TARGET=<WAN侧服务器IPv4> \
AX6_EXPECTED_WAN_DEVICE=wan \
AX6_EXPECTED_SOURCE_REVISION=<实机DISTRIB_REVISION> \
AX6_BUILD_COMMIT=d8d9bd9c1da95dc73dc9635112f6dadd70e127eb \
bash AX6-IPQ/scripts/ax6-routed-perf-test.sh preflight
```

preflight 必须同时显示 LAN 测试机经 `192.168.5.1`、路由器经预期 WAN 设备到达
服务器。任何一侧路径不匹配都会拒绝压测。用户确认满载测试后，TCP 单流和四流分别
执行：

```sh
AX6_IPERF_TARGET=<WAN侧服务器IPv4> AX6_EXPECTED_WAN_DEVICE=wan \
AX6_EXPECTED_SOURCE_REVISION=<实机DISTRIB_REVISION> AX6_BUILD_COMMIT=d8d9bd9c1da95dc73dc9635112f6dadd70e127eb \
AX6_PARALLEL=1 bash AX6-IPQ/scripts/ax6-routed-perf-test.sh run --confirm-load-test

AX6_IPERF_TARGET=<WAN侧服务器IPv4> AX6_EXPECTED_WAN_DEVICE=wan \
AX6_EXPECTED_SOURCE_REVISION=<实机DISTRIB_REVISION> AX6_BUILD_COMMIT=d8d9bd9c1da95dc73dc9635112f6dadd70e127eb \
AX6_PARALLEL=4 bash AX6-IPQ/scripts/ax6-routed-perf-test.sh run --confirm-load-test
```

UDP 每次只改变一个目标速率，按 100/300/500/700/900 Mbps 分轮运行：

```sh
AX6_IPERF_TARGET=<WAN侧服务器IPv4> AX6_EXPECTED_WAN_DEVICE=wan \
AX6_EXPECTED_SOURCE_REVISION=<实机DISTRIB_REVISION> AX6_BUILD_COMMIT=d8d9bd9c1da95dc73dc9635112f6dadd70e127eb \
AX6_PROTOCOL=udp AX6_UDP_RATE=500M \
bash AX6-IPQ/scripts/ax6-routed-perf-test.sh run --confirm-load-test
```

每次 run 自动执行 LAN→WAN、WAN→LAN、同时双向三种方向，保存原始 JSON、ping 和
路由器前后计数。双向 JSON 缺任一反向字段、路径错误、SSH/iperf 失败或测试中重启，
结果都会标记 `INCOMPLETE`，不得用于性能结论。

### 7.3 每个候选的顺序

1. 备份和哈希；记录固件、source/build SHA、boot ID、UCI diff。
2. 空载 10 分钟：ping、TCP/UDP/softnet、端口、ECM、EDMA、温度。
3. `parallel=1`：三个方向各 60 秒，三轮。
4. `parallel=4`：三个方向各 60 秒，三轮。
5. UDP 分档：100/300/500/700/900 Mbps，双向分别测试。
6. OpenClash DNS/LuCI、ZeroTier 双向访问、2.4G IoT、5G HE80、UPnP（仅启用时）。
7. network/ECM/WAN/Wi-Fi reload 新格式矩阵。
8. 24 小时观察；冷启动 10 次需要用户物理操作。

### 7.4 硬门禁

任一条件出现即停止该候选：

- boot ID 改变、panic/Oops/watchdog、ath11k fatal、NSS/EDMA fatal；
- `nss-check` 或 `ax6-config-audit` FAIL；
- CRC/FCS/frame/FIFO error 增长，softnet drop 或 EDMA alloc fail 持续增长；
- ECM routed flow 没有进入连接统计；
- ZeroTier/OpenClash DNS/LuCI/2.4G IoT 出现可重复回归；
- 吞吐改善只出现在单轮、单方向，或伴随明显重传/延迟/温度恶化。

通过需要三轮结果稳定、两个方向均无回归、双向结果可复现，并完成服务与长稳门禁。
绝不以“成功启动一次”或“iperf 峰值更高”代替完整验收。

## 8. 当前剩余任务

| 顺序 | 任务 | 当前状态 |
|---:|---|---|
| 1 | 完成新工具、锁定和文档本地审查 | 已完成；TCP/UDP/路径/频率 fixture 通过 |
| 2 | 推送源码测试头 `4e350435` | 已完成 |
| 3 | 提交并推送构建候选门禁和测试工具 | `d8d9bd9`/`e66dd45` 已完成 |
| 4 | 云端 lint + 完整 STOCK build | 两轮 lint 及 build `31351445144` 全部通过 |
| 5 | 独立下载和产物复核 | 已完成；外层、rootfs、manifest、OpenClash、kmod 闭环 |
| 6 | 建立审查 PR | build 仓库可建 draft；源码只能建阻断标注的 tracking PR |
| 7 | 经用户确认执行 F1 频率 A/B | 未授权 |
| 8 | 重建当前基线上的 F2 split-NAPI 候选 | M0-M3 后执行 |
| 9 | 6.18.41 与 Wi-Fi 独立候选 | F1/F2 后执行 |
| 10 | 选择源码 main 的全局同步或 AX6 回移植路线 | 未选择；当前禁止直接合并 70 提交 |

当前最重要的不是继续堆叠上游提交，而是先让基线合并证据闭环，再用真正经过 AX6
转发路径的测试回答“双向吞吐是否由 NSS 频率或 NAPI 调度造成”。
