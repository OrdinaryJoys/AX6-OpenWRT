# AX6 当前状态、上游差异与分步修复方案（2026-08-09）

## 1. 审查范围和执行边界

本文基于以下四类证据更新 2026-08-03/08 的旧结论：

1. 2026-08-09 06:06-06:15、22:34-22:35 CST 的 AX6 实机 SSH 只读快照。
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
| 运行时间 | 1 天 21 小时 48 分 | boot ID 未变，无非预期重启证据 |
| `nss-check -v` | PASS=45、WARN=4、FAIL=0 | PASS；4 项均为物理口 report-only offload 提示 |
| `ax6-config-audit -v` | PASS=29、WARN=2、FAIL=0 | PASS；2 项均为 OpenClash overlay 更新空间提示 |
| OpenClash | 进程在线 | 正常 |
| ZeroTier | 1.16.2、ONLINE、network OK | 正常 |
| 内核日志 | 无新 panic/Oops/watchdog/ath11k fatal/EDMA fatal | 正常 |

### 2.2 资源和物理链路

| 项目 | 实测 | 判断 |
|---|---:|---|
| RAM available | 约 471 MiB | 正常 |
| ZRAM | 256 MiB，使用 0 | 正常，无交换压力 |
| Overlay | 25.5/41.0 MiB，66%，剩余 13.3 MiB | 可用，继续观察更新峰值 |
| WAN/LAN1/LAN2 | 1000 Mbps/full/up | 正常 |
| LAN3 | no carrier | 未接线，不是驱动故障 |
| WAN/LAN2 error/drop | 0 | 正常 |
| LAN1 | rx_drop=185、tx_drop=3，error=0 | 历史累计；15 秒复核窗口内不增长 |

LAN1 的累计 drop 在长时间运行中缓慢增加，但进入 22:35 定点 15 秒窗口后保持
`185/3` 不变，且没有 CRC/FCS/frame/FIFO error 或速率下降。它仍是观察项，
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

### 2.4 22:34 核心驱动与链路复核

| 检查 | 实测 | 结论 |
|---|---|---|
| NSS/SSDK/ECM/ath11k | 两个 NSS core、NSS-DP、SSDK、ECM、ath11k NSS offload 均在线 | 无缺失模块或初始化失败 |
| NSS 频率 | `auto_scale=0`、`current_freq=748800000` | 与 VIKINGYFY/qosmio 默认固定中频一致，不是已确认故障 |
| ECM host path | `disable_offloads=1`、`disable_gro_list=1`、`br-lan` 覆盖完整 | 本机终结流量保护生效 |
| OpenWrt flow offload | software=0、hardware=0 | 未与 NSS ECM 重复接管 |
| 物理端口 | WAN/LAN1/LAN2 均 1000/full；CRC/FCS=0；qdisc drop=0 | 当前链路健康 |
| 15 秒计数器差分 | UDP InErrors/RcvbufErrors、softnet、端口 drop 均不增长；TCP RetransSegs +1 | 无持续丢包证据，单次重传不足以定性 |
| Mac 到路由器 | 20/20，0% loss，平均 0.854 ms | 本地链路稳定 |
| 路由器到公共 DNS | 223.5.5.5 与 119.29.29.29 均 0% loss，约 7-8 ms | WAN 短窗口稳定 |
| ZeroTier/OpenClash | reconcile、动态 nft 端口、DNS 7874 与 dnsmasq redirect 全部通过 | 未复现服务故障 |
| 内核日志 | 无 panic/Oops/watchdog/NSS/EDMA/ath11k fatal | 无新增核心异常 |

本轮没有执行 reload、吞吐压测、服务重启或任何持久写入。短窗口健康不能替代
双端点满载测试，但已经排除“空闲或普通业务时持续发生核心驱动丢包”的判断。

## 3. 仓库和 CI 当前状态

| 项目 | 当前状态 |
|---|---|
| 构建仓库 main | `099556aae4c0` |
| 已验证构建候选 | `8c722a14e6af` |
| 当前集成分支 | `codex/ax6-postvalidation-integration-20260809` |
| 固件构建验证头 | 远端 `d8d9bd9`（锁定源码 `4e350435`） |
| 测试工具头 | 远端 `e66dd45`；不改变上述固件目标内容 |
| 成功构建源码 | `be691ad79541` |
| 新的测试/合并源码头 | `4e350435cd9e`（只新增 APCS fixture/test） |
| 源码 main | `56807d9661db` |
| 当前 lint | `31351390852`（构建头）及 `31352053415`（TCP/UDP 测试头）均通过 |
| 当前 STOCK build | 新锁 `31351445144` 完整成功，artifact 独立复核通过 |
| 前一失败 build | Actions `31281669689`，packages HEAD 引入全局 Kconfig 递归依赖 |

运行 `31351445144` 已证明 `d8d9bd9 + 4e350435` 的完整编译、rootfs 和产物链。
独立下载后，sysupgrade/recovery、143 个 kmod 及归档的 SHA256 全部通过；最终 rootfs
的 391 个安装包与设备 manifest 完全一致，OpenClash `0.47.133` 的 AArch64 Meta core
哈希与 BUILD-LOCK 相同，36 个 AX6 运行文件也与仓库源文件逐字节一致。该组合现在可
进入用户确认后的实机测试，但不能据此跳过源码分支的全局合并边界。

补充合并边界：源码候选相对 `main` 包含 70 个提交和 202 个文件，不仅是 AX6 修复，
还包括 6.18.35→6.18.38 及多个非 AX6 target 的全局变化。单一 AX6 stock build 不足以
证明可直接合并源码 main；当前只把 `4e350435` 视为精确锁定的 AX6 实机候选，源码
主线需另行选择“全局多目标同步”或“回移植 AX6 修复到 main”路线。

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
| Argon | `e2935dc`/2.4.6 | `86c3156`/2.4.6 | 两个模板的浏览器标签修复；冻结当前构建，列为 P2 独立候选 |
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

远端已在 22:13 CST 更新到 `5cc85e6c534d`。从此前审计基线 `0bad8929` 到
该提交的 AX6 相关变化按语义拆解如下：

| 上游组 | 当前候选覆盖 | 处理 |
|---|---|---|
| NSS/EDMA startup hardening | auto-scale core guard、IRQ/N2H unwind、current_freq 等已有等价修复 | 不重复移植 |
| `nss_freq` 管理工具 | 新增 `mid/high/status` 和 UCI 持久化；默认仍是 `mid=748.8 MHz`，pbuf 仍写 `auto_scale=0` | 仅作为可观测性/后续 A/B 候选，不改当前默认 |
| vendor qca-nss-dp split NAPI | 上游新增 Rx/Tx 独立 NAPI 并默认 GRO；本仓无 GRO 默认的独立候选已完整构建通过 | 缺少 AX6 实机双端点回归，不合入当前修复链 |
| Linux 6.18 threaded NAPI | 当前 ath11k 候选已有 `cedce1dc` 等价适配 | 保持现状 |
| qca_edma split NAPI/GRO | 属上游主线 qca_edma 路径；当前 AX6 使用 qca-nss-dp vendor EDMA | 不直接合并 |
| 专用 CPU 固定 EDMA IRQ | 与当前上游 smp_affinity + NSS RPS 策略可能冲突 | 单独 A/B，不默认合并 |
| DSA conduit 固定 MAC | 针对 qca_edma/DSA 路径 | 当前 stock qca-nss-dp 不直接适用 |
| kernel 6.18.40 与 patch refresh | 大范围内核/patch offset 迁移 | 建立独立源码升级候选，不与本轮证据修复混合 |
| hostapd/wifi-scripts 更新 | 大量 MLD/CSA/STA 修复 | 单独 Wi-Fi 回归分支，不整包覆盖 NSS patch stack |
| AX6 stock ART/nvmem 恢复 | 最新 DTS 再次声明 `partition-0-art` 和 MAC cells | 与当前 custom U-Boot/SMEM 运行边界冲突，不覆盖已验证的悬空 phandle 修复 |
| QCA8084/QCA81xx PHY 修复 | 2.5G EEE、10G PHY 互操作修复 | AX6 的 QCA8075 千兆端口不命中 |

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
独立“6.18.40+ + Wi-Fi”候选，避免无法区分驱动回归和常规包更新。

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
NSS monitor、pbuf、ZeroTier reconcile/health/fw4/buffer、OpenClash DNS/runtime/bypass
和 cgi-io backport 均 PASS；云端 ShellCheck、Actionlint、Yamllint、DTB 夹具和全部
lint 门禁通过。

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

### 阶段 C：云端 lint 和统一 stock 构建（旧锁完成，新锁待运行）

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

在本轮候选完整构建通过后，另开四个互不混合的源码分支：

1. Linux 6.18.40+ / qualcommax 核心迁移。
2. hostapd/wifi-scripts 更新和 2.4G IoT/5G HE80 回归。
3. NSS 固定中频与固定高频单变量 A/B；不把 `auto_scale=1` 和 split-NAPI 混入同轮。
4. vendor qca-nss-dp split-NAPI（保持 GRO 默认不变）独立 A/B。

VIKINGYFY IRQ/EDMA CPU 固定方案只在双端吞吐能够稳定复现问题、且驱动计数显示
调度瓶颈后做单变量 A/B；当前不作为默认优化合并。

#### 阶段 F 的单变量 A/B 规则

1. NSS 频率测试必须使用会经过三层转发和 ECM/NSS 的 WAN-LAN 双端点；LAN-LAN
   同网段桥接结果不能用于判断 NSS core 频率。
2. 第一轮只比较当前固定中频 748.8 MHz 与固定高频 1689.6 MHz；两组均保持
   当前 IRQ、GRO、ECM、Wi-Fi、SQM 和 flow-offload 配置不变。
3. `auto_scale=1` 是另一个变量，只有固定频率 A/B 证明频率确为瓶颈后才单独测试。
4. split-NAPI 使用已完整构建的无 GRO 默认变更候选，保持固定中频；不得同时合入
   VIKINGYFY 的 GRO 默认、专用 IRQ 或新内核。
5. 每组至少 3 轮，逐方向记录吞吐、P95 延迟、TCP retrans、UDP loss/jitter、
   EDMA/softnet/端口 drop、ECM accelerated、NSS core load、CPU 和温度。
6. 只有三轮结果稳定改善超过测量噪声，且 reload、冷启动、ZeroTier、OpenClash、
   2.4G/5G 和 24 小时观察均无回归，才进入默认配置候选。

任何临时频率写入、主动满载测试或候选固件刷写都需要用户再次确认；本文不授权
在当前实机执行这些操作。

## 8. 仍未关闭的项目

| 项目 | 状态 | 关闭条件 |
|---|---|---|
| `be691ad/193e5fb` 完整构建 | `31315718824` 成功且产物独立复核通过 | 已关闭 |
| `4e350435` 测试锁完整构建 | `31351445144` 成功且产物独立复核通过 | 已关闭 |
| 当前实机 monitor 详细快照 | 固件尚未包含 | 新固件经用户授权刷入后观察 |
| reload 80 次 | 旧证据作废 | 新格式、每场景 20/20 严格 PASS |
| 冷启动 x10 | 未完成 | 用户物理断电 10 轮 |
| 双端转发吞吐 | 未完成 | 两台 Linux 同版 iperf3 完整矩阵 |
| LAN1 drops | 观察；15 秒窗口 `185/3` 不变 | 长窗口差分和错误子类持续为 0 |
| NSS 固定中频 | 上游默认一致，未证明为瓶颈 | 双端点固定中频/高频 A/B，驱动计数和温度同时通过 |
| split-NAPI | 独立候选已完整构建，未实机验证 | 两台 Linux 单向/反向/双向与 reload/长稳均通过 |
| Overlay 66% | 观察 | Geo/订阅更新峰值后仍保留安全余量 |
| 6.18.41/Wi-Fi 上游 | 尚未移植 | 独立候选、独立构建和回归 |

因此当前可以确认“正常业务运行态健康”，但不能声称“所有故障已完全关闭”。
最优推进路径是先关闭测试证据错误，再同步低风险依赖并统一构建，最后才进行
经授权的 reload、吞吐和冷启动实机验证。
