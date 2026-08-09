# AX6 当前状态、上游差异与分步修复方案（2026-08-09）

## 1. 审查范围和执行边界

本文基于以下四类证据更新 2026-08-03/08 的旧结论：

1. 2026-08-09 06:06-06:15 CST 的 AX6 实机 SSH 只读快照。
2. `OrdinaryJoys/AX6-OpenWRT` 本地、远端分支和 GitHub Actions 状态。
3. `OrdinaryJoys/immortalwrt-nss`、`VIKINGYFY/immortalwrt`、
   `qosmio/openwrt-ipq`、ImmortalWRT 及插件 feed 的最新远端提交。
4. 原始 72 小时、重启、reload 和 UDP 证据文件的重新审查。

本轮没有修改实机 UCI、订阅或覆写，没有重载服务、重启或刷写。仓库修改只在
`codex/ax6-postvalidation-integration-20260809` 独立候选分支进行。

## 2. 当前实机状态

### 2.1 版本和基础健康

| 项目 | 2026-08-09 实测 | 判断 |
|---|---|---|
| 固件 | `r0-be691ad`，Linux `6.18.38` | 与成功构建 `8c722a14` 匹配 |
| 设备 | Redmi AX6 stock layout | 正确 |
| boot ID | `d56c39e9-4141-4108-8dc7-19fa492a3657` | 与 08-08 基线一致 |
| 运行时间 | 1 天 5 小时 20 分 | 无非预期重启证据 |
| `nss-check -q` | 0 | PASS |
| `ax6-config-audit -q` | 0 | PASS |
| OpenClash | 进程在线 | 正常 |
| ZeroTier | 1.16.2、ONLINE、network OK | 正常 |
| 内核日志 | 无新 panic/Oops/watchdog/ath11k fatal/EDMA fatal | 正常 |

### 2.2 资源和物理链路

| 项目 | 实测 | 判断 |
|---|---:|---|
| RAM available | 约 479 MiB | 正常 |
| ZRAM | 256 MiB，使用 0 | 正常，无交换压力 |
| Overlay | 25.4/41.0 MiB，65%，剩余 13.5 MiB | 可用，继续观察更新峰值 |
| WAN/LAN1/LAN2 | 1000 Mbps/full/up | 正常 |
| LAN3 | no carrier | 未接线，不是驱动故障 |
| WAN/LAN2 error/drop | 0 | 正常 |
| LAN1 | rx_drop=116、tx_drop=3，error=0 | 历史累计；复核窗口内不增长 |

LAN1 的累计 drop 在前后快照间从 115 到 116，但进入定点 10 秒窗口后保持
`116/3` 不变，且没有 CRC/FCS/frame/FIFO error 或速率下降。它仍是观察项，
不能据单个累计值修改交换、PAUSE、IRQ 或 NSS 配置。

### 2.3 UDP/socket 定点复核

修正采集逻辑后，10 秒实机窗口结果为：

```text
InErrors       133 -> 133   delta=0
RcvbufErrors   133 -> 133   delta=0
softnet drops    0 -> 0     delta=0
ZeroTier drops   0 -> 0     delta=0
Clash drops      8 -> 8     delta=0
nss_rc=0 audit_rc=0 boot_same=1
result=PASS
```

ZeroTier PID 和 socket inode 集保持稳定。Clash PID 保持稳定，但临时 DNS/代理
socket 集发生变化；这是进程正常创建和关闭 socket，不能当成服务重启。当前没有
持续 UDP 丢包、softnet 丢包或 ZeroTier socket drop 证据。

## 3. 仓库和 CI 当前状态

| 项目 | 当前状态 |
|---|---|
| 构建仓库 main | `099556aae4c0` |
| 已验证构建候选 | `8c722a14e6af` |
| 当前集成分支 | `codex/ax6-postvalidation-integration-20260809` |
| 当前候选提交 | `193e5fbc276e` |
| 锁定源码候选 | `be691ad79541` |
| 源码 main | `56807d9661db` |
| 当前 lint | Actions `31315671414`，全部通过 |
| 当前 STOCK build | Actions `31315718824`，已通过 defconfig/下载/快速 NSS 门禁，正在正式编译 |
| 前一失败 build | Actions `31281669689`，packages HEAD 引入全局 Kconfig 递归依赖 |

旧 build success 只证明 `8c722a14`。当前候选的静态门禁、feed 生成、DIY、
OpenClash/cgi-io 溯源、`make defconfig`、源包下载、NSS-DP/NSS-DRV/ZeroTier prepare
和补丁回归断言已经通过；完整编译、rootfs 和产物审查仍在进行。

## 4. 本轮重新检出的确定问题

### P0：UDP 归因脚本读取了错误 inode 列

当前 Linux 6.18.38 的 `/proc/net/udp{,6}` 实测字段为：inode 第 10 列、drops
第 13 列。旧脚本用第 11 列作为 inode，实际读取的是 refcount，因此此前按该
脚本生成的 PID/socket 归属不能作为 NSS、ZeroTier 或 Clash 的根因证据。

同时旧脚本还硬编码：

- 已过期固件 `r0-0ea8486`；
- 已过期构建 `84fc0f2`；
- 会变化的 ZeroTier 动态端口；
- 把 Clash 端口 drops 合并标记为 ZeroTier drops。

这些已在候选分支修复，并新增真实表头 fixture。

### P0：旧 reload 矩阵不能判定 80/80 PASS

原始 `reload-matrix-20260808.log` 显示：

- network：`wanip=0` 为 19/20，`tproxy` 为 0/2 混合；
- ECM：`do`、`dgl` 20/20 为空；
- WAN：ZeroTier 在 5/20 个即时采样中尚未恢复；
- Wi-Fi：`queue` 20/20 为空；
- 每轮均缺少 `boot_same`、`audit_rc`、`nss_rc` 和明确 `result`。

这些数据可能只是采样早于服务收敛，不等于 reload 本身失败；但它们也绝不能
证明通过。本文将该门禁从“PASS”改为“证据不完整，必须重测”。仓库新增只读
验证器，旧日志会被明确拒绝。执行新 reload 测试仍需用户单独授权。

### P1：NSS 定时失败只保留退出码

当前固件 cron 只执行 `nss-check -q`，失败时仅记录 exit code。08-08 03:00 的
单次失败因此无法知道具体项目。旧 uci-defaults 还用任意 `/sbin/nss-check` 匹配
阻止升级，用户自定义探针可能导致托管任务永远不更新。

候选修复保持正常路径静默，只在失败时立即追加完整 `nss-check` 快照；升级时
只替换本包托管行，保留用户自定义探针，并使用原子 crontab 替换。

### P0：直接同步 packages HEAD 会破坏全局 Kconfig

| 依赖 | 锁定 | 最新 | 影响分析 |
|---|---|---|---|
| packages | 兼容锁 `4db836e` | `1ae9a383` | HEAD 不能直接用于当前 6.18/NSS 核心树 |
| routing | `b40e628` | `b40e628` | 已同步；仅 bird2/bird3，当前固件未安装 |
| Argon | `e2935dc`/2.4.6 | `e2935dc`/2.4.6 | 已同步，Lint 已通过 |
| OpenClash | master | `a9e5d98`/0.47.133 | 实机和最新仓库版本一致 |

`31281669689` 的准确日志显示两个独立递归依赖：

1. `trafficshaper` 提交 `2e945de2` 用已选 nftables variant 决定是否依赖虚拟包
   `nftables`；默认 provider 又回选 `nftables-nojson`，生成自选择。
2. `freeradius3` 提交 `71223e9e` 新增条件 `libopenssl-legacy` 依赖，与
   `freeradius3-common` 控制的 SSL choice 形成递归链。

两者即使未进入固件，也会在 `feeds install -a` 后被全局 Kconfig 解析，因此不能
靠“没有选择该插件”规避。当前方案恢复最后一次完整构建通过的 packages 锁，
只回移植官方 packages 提交 `50dec501`：把 `cgi-io` 锁到
`31cb3c89f02d918d7f17bf62a80c852fc38a1ca1`，修复 malformed POST decoding 的
authenticated use-after-free。回移植脚本严格拒绝混合、未知和部分更新状态；
当前云端 `defconfig` 已证明该组合不再产生上述递归依赖。

## 5. 核心上游拆解

### 5.1 VIKINGYFY/immortalwrt

从此前审计基线 `0bad8929` 到 `3fd1e27a` 有 488 个提交。与 AX6 直接相关的组：

| 上游组 | 当前候选覆盖 | 处理 |
|---|---|---|
| NSS/EDMA startup hardening | auto-scale core guard、IRQ/N2H unwind、current_freq 等已有等价修复 | 不重复移植 |
| Linux 6.18 threaded NAPI | 当前 ath11k 候选已有 `cedce1dc` 等价适配 | 保持现状 |
| qca_edma split NAPI/GRO | 属上游主线 qca_edma 路径；当前 AX6 使用 qca-nss-dp vendor EDMA | 不直接合并 |
| 专用 CPU 固定 EDMA IRQ | 与当前上游 smp_affinity + NSS RPS 策略可能冲突 | 单独 A/B，不默认合并 |
| DSA conduit 固定 MAC | 针对 qca_edma/DSA 路径 | 当前 stock qca-nss-dp 不直接适用 |
| kernel 6.18.39-41 | 大范围内核迁移 | 建立独立源码升级候选，不与本轮证据修复混合 |
| hostapd/wifi-scripts 更新 | 大量 MLD/CSA/STA 修复 | 单独 Wi-Fi 回归分支，不整包覆盖 NSS patch stack |

当前 `be691ad` 已包含针对 AX6 实际 vendor NSS 路径验证过的 EDMA correctness、
NSS drv unwind、current_freq、auto-scale guard、ECM host-path 保护和 APCS resource
边界修复。不能再把 VIKINGYFY 的同名上游补丁整组叠加，否则会重复或覆盖本地
已重构 patch stack。

### 5.2 qosmio/openwrt-ipq

默认 `main-nss` 已强制重写到 `92a2d104`，当前顶部仍是 Linux 6.12.92 NSS patch
rebase；qca-nss-dp 源为 `6a5c4716`，SSDK 源为 `446db12b`。它是 ath11k NSS、
AP_VLAN、mesh 和 vendor DP 的重要参考，但不能直接覆盖当前 Linux 6.18.38、
qca-nss-dp `d8f802f0`、SSDK `d9a19649` 的已验证组合。

后续只能逐提交比较语义和调用路径，不能按目录替换或按 branch merge。

### 5.3 ImmortalWRT 主线

ImmortalWRT 和 VIKINGYFY 已继续推进内核、hostapd、wifi-scripts 和 qualcommax。
这些变化的优先级低于当前已验证固件的证据闭环。先完成本轮 stock 构建，再开
独立“6.18.41 + Wi-Fi”候选，避免无法区分驱动回归和常规包更新。

## 6. 已完成的仓库修复

1. 修正 NSS monitor：失败时采集详细快照、精确升级托管行、保留用户 cron。
2. NSS monitor 加入 lint fixture 和两个最终 rootfs 文件门禁。
3. 重构 UDP idle baseline：动态版本、显式 build commit、PID→inode 归属、
   inode 第 10 列、ZeroTier/Clash 分离、softnet 十六进制解析和严格结果码。
4. 新增 UDP fixture，禁止旧版本、旧构建和动态端口常量回归。
5. 新增 reload evidence validator；缺字段、缺健康门禁或缺显式 PASS 一律失败。
6. 把 Phase-0 性能 fixture、UDP fixture、reload fixture 接入 lint。
7. 撤销不兼容的 packages HEAD 整体同步，保留 routing 和 Argon 的已审查更新。
8. 新增带来源提交、上游源码提交和 mirror hash 的 `cgi-io` 安全回移植。
9. 新增回移植幂等/混合状态/未知漂移 fixture、BUILD-LOCK 溯源和云端源码门禁。

当前本地 fixture：UDP baseline PASS、reload validator PASS、性能框架 21/21、
NSS monitor PASS、cgi-io backport PASS；云端 ShellCheck、Actionlint、Yamllint、
DTB 夹具和全部 lint 门禁通过。

## 7. 分步推进方案

### 阶段 A：完成证据链修复（已完成）

1. 将 monitor、UDP 归因、reload validator 和 rootfs 门禁作为一个测试正确性提交。
2. 跑仓库全部 shell fixture、Actionlint/YAML、ShellCheck 和 diff gate。
3. 不包含 feed 更新、内核更新或实机配置。

完成条件：本地全部门禁通过，旧 reload 日志被正确拒绝，实机只读 baseline PASS。

### 阶段 B：兼容依赖同步和安全回移植（已完成）

1. packages 保持 `4db836e2` 兼容锁，拒绝当前 HEAD 的全局 Kconfig 回归。
2. 单独回移植 `cgi-io` 官方安全提交并记录 source/hash/provenance。
3. routing 更新到 `b40e628`；Argon 更新到 `e2935dc`/2.4.6。
4. 不修改 NSS/ECM/EDMA/ath11k/SSDK 源码或运行配置。

完成条件：兼容锁被明确标记，安全回移植门禁通过，配置不出现额外 proxy core、
flow offload、SQM、WireGuard 或 VLAN 依赖。当前已满足。

### 阶段 C：云端 lint 和统一 stock 构建（进行中）

按顺序执行：

1. push 独立候选分支；
2. Lint；
3. 完整 AX6 stock build，不做 EXPAND；
4. 失败先读准确日志，不盲目重跑。

构建必须同时验证 NSS/ECM/DP/SSDK/ath11k、stock sysupgrade/factory/initramfs、
kmod、唯一设备 manifest、BUILD-LOCK、OpenClash provenance、SHA256 和新增 monitor
rootfs 路径。

### 阶段 D：独立产物审查

下载 artifact 后离线核对：

- source/build/feed/OpenClash 实际提交；
- `cgi-io`、Argon、OpenClash 实际版本；
- rootfs 中 monitor、UDP/网络脚本和禁用组件；
- manifest 与 opkg status 一致；
- stock MTD/layout、镜像大小和校验完整。

未通过前不合并、不发布、不刷写。

### 阶段 E：需授权的实机回归

只有用户确认测试窗口后执行：

1. 新格式 network/ECM/WAN/Wi-Fi reload，每轮等待收敛而非固定过早采样。
2. 每轮记录 boot ID、NSS/config audit、最终服务和 socket owner，再写显式 PASS。
3. 两台同版本 Linux 有线端点执行 LAN-LAN 和 WAN-LAN 单向/反向/双向测试。
4. UDP 先做 idle baseline，再做接收端和纯转发场景，避免混淆本机 socket 与 NSS。
5. 冷启动 x10 仍需物理断电配合；不得用软件 reboot 替代。

### 阶段 F：核心上游升级候选

在本轮候选完整构建通过后，另开两个互不混合的源码分支：

1. Linux 6.18.41/qualcommax 核心迁移。
2. hostapd/wifi-scripts 更新和 2.4G IoT/5G HE80 回归。

VIKINGYFY IRQ/EDMA CPU 固定方案只在双端吞吐能够稳定复现问题、且驱动计数显示
调度瓶颈后做单变量 A/B；当前不作为默认优化合并。

## 8. 仍未关闭的项目

| 项目 | 状态 | 关闭条件 |
|---|---|---|
| 本轮仓库修复完整构建 | `31315718824` 正在编译 | 阶段 C/D 全通过 |
| 当前实机 monitor 详细快照 | 固件尚未包含 | 新固件经用户授权刷入后观察 |
| reload 80 次 | 旧证据作废 | 新格式、每场景 20/20 严格 PASS |
| 冷启动 x10 | 未完成 | 用户物理断电 10 轮 |
| 双端转发吞吐 | 未完成 | 两台 Linux 同版 iperf3 完整矩阵 |
| LAN1 drops | 观察 | 长窗口差分和错误子类持续为 0 |
| Overlay 65% | 观察 | Geo/订阅更新峰值后仍保留安全余量 |
| 6.18.41/Wi-Fi 上游 | 尚未移植 | 独立候选、独立构建和回归 |

因此当前可以确认“正常业务运行态健康”，但不能声称“所有故障已完全关闭”。
最优推进路径是先关闭测试证据错误，再同步低风险依赖并统一构建，最后才进行
经授权的 reload、吞吐和冷启动实机验证。
