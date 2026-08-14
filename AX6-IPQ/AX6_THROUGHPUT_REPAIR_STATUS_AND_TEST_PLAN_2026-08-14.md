# AX6 吞吐、修复状态与复测方案（2026-08-14）

## 1. 文档状态与结论边界

本文记录当前实机 `Redmi AX6 (stock layout)`、仓库测试分支和云端构建的
可复核状态。所有吞吐结果均保留原始 iperf3 JSON、路由器同步采样、环境身份和
SHA256；“测试执行完成”不等于“故障已经修复”。

本轮没有修改路由器配置、没有刷机、没有重启。测试期间只运行临时 iperf3
进程和只读 SSH 采样，测试进程均按 PID 清理。

## 2. 身份与拓扑

| 项目 | 当前值 |
|---|---|
| 实机固件 | `ImmortalWrt r0-956cf06` |
| 源码提交 | `956cf06b6c86c10de28670157a9c986a74a91454` |
| 构建仓库提交 | `7034c37bfdf3fe575a1bf22334b9ac9f89cb093c` |
| 内核 | `6.18.38` |
| Boot ID | `02239d26-7a72-43cb-a2d1-52a752d8f522` |
| 有线 Mac | `192.168.5.190`, `en0`, 1000baseT 全双工 |
| Wi-Fi Mac | `192.168.5.232`, `en1`, MAC `b2:07:ce:13:f7:85` |
| Wi-Fi 关联 | 5 GHz `RIFI`, HE80, 2x2, 信号约 `-32 dBm`, PHY 最高约 1200.9 Mbit/s |
| Windows 端点 | `192.168.5.111:5201`, iperf3 3.21, AX88179 USB3 有线网卡；当前不在 AP station 表中 |
| Windows USB Wi-Fi | 尚未关联到 AX6；当前无线 station 只有 Mac `.232` 和 2.4 GHz IoT 设备，无法伪造已完成结果 |

## 3. 本轮已完成的仓库修复

| 提交/工作区 | 修复 | 验证状态 |
|---|---|---|
| `8c71164` | 双向负载期间同步采集 NSS、PBUF、softnet、IRQ、RPS/RFS/XPS、接口和 CPU | 本地夹具通过；已在三类实机拓扑产生完整样本 |
| `d67d4f7` | 按 `Packages` 精确复制全部依赖 IPK，生成自包含离线 kmod feed、索引和双层 SHA256 | 正/负夹具、完整 stock 构建和下载产物独立校验均通过 |
| `b565969` | lint 按 helper 所有权验证离线 feed，不再错误要求实现字符串必须位于 workflow | 云端 Lint `31779695328` 全部通过 |
| `2c20098` | LAN-LAN runner 增加 probe/TCP/UDP/长时硬超时、按 PID 清理、阶段冷却、全阶段同步采样和 N2H 总快照 | 挂起负样本通过；性能工具夹具 `36/36`、shellcheck 和云端 Lint `31787844185` 通过 |
| `2c20098` | 新增路由器到 Mac 的 P1/P4 正向、反向、双向和同步采样工具 | 有线、Wi-Fi 各 18 个 TCP 场景完整执行 |
| `2c20098` | 分离 N2H OCM pool pressure 与 default/payload/queue 最终失败 | OCM-only fixture=`WARN/exit 0`；payload fail fixture=`FAIL/exit 1` |

### 3.1 新发现并修复的测试工具错误

第一次完整 LAN-LAN 运行在 `UDP 600M reverse round 2` 出现 iperf3 挂起，
超过 30 秒契约且 JSON 保持 0 字节。旧 runner 没有硬超时，会无限等待。

当前修复逻辑：

1. 每个 probe、TCP、UDP 和长时会话使用 `持续时间 + grace` 硬截止时间。
2. 只记录并清理由 runner 自己启动的 PID，不使用 `killall`。
3. 超时返回 `INCOMPLETE`，绝不生成成功结论。
4. 阶段间加入可配置冷却，降低 USB 网卡连续负载状态对后续场景的污染。
5. 离线 mock `hang` 样本必须在 10 秒内失败；当前夹具已通过。

## 4. 实机吞吐结果

### 4.1 LAN-LAN：有线 Mac 到 Windows AX88179

证据：

- `router-backups/perf-runs/20260814-150413-sync-pilot-r0-956cf06`
- `router-backups/perf-runs/20260814-152543-full-matrix-r0-956cf06`

冷启动/短时单向链路可达到约 `944-962 Mbit/s`。双向时 Windows 接收方向明显
下降，而 Windows 发送方向仍约 `941-953 Mbit/s`。连续负载后，Mac 到 Windows
单向曾下降至约 `164-238 Mbit/s`，最终在 Wi-Fi 恢复门禁中仍只有约
`58-76 Mbit/s`，说明 Windows/AX88179 接收状态会持续退化。

第一份完整运行因上述 UDP 会话挂起被严格标记为 `INCOMPLETE`，已单独生成
`ABORTED.txt` 与 SHA256，不能作为完整通过样本。

同步双向采样结果：PBUF 不变化、softnet dropped 不增长、default/payload/queue
失败不增长、EDMA 错误不增长、接口错误不增长。后续 Wi-Fi 全矩阵确实观察到
OCM 首选池压力增长，但长期低吞吐阶段 OCM 计数也保持不变，因此当前证据仍不
支持把 Windows 接收退化单独归因于 AX6 NSS/PBUF。

### 4.2 路由器到有线 Mac（本机终结，不是 NSS 转发）

证据：`router-backups/perf-runs/20260814-160327-router-wired-mac-r0-956cf06`

| 场景 | 路由器到 Mac | Mac 到路由器 |
|---|---:|---:|
| P1 单向范围 | 764.3-800.8 | 935.4-938.2 Mbit/s |
| P1 双向范围 | 673.1-756.8 | 706.1-852.2 Mbit/s |
| P4 单向范围 | 930.5-935.9 | 939.9-940.6 Mbit/s |
| P4 双向范围 | 848.8-859.1 | 931.6-932.5 Mbit/s |

三轮 P4 双向 Mac 到路由器累计重传分别为 `524/3191/5648`，但 PBUF、NSS/EDMA
错误和 softnet dropped 均未增长。P1 reverse round 3 期间 `lan1.rx_dropped +1`，
属于需要复测的单包异常，不能据此宣称驱动故障，也不能忽略。

### 4.3 路由器到 Wi-Fi Mac（本机终结，不是 NSS 转发）

证据：`router-backups/perf-runs/20260814-154825-router-wifi-mac-r0-956cf06`

| 场景 | 路由器到 Wi-Fi Mac | Wi-Fi Mac 到路由器 |
|---|---:|---:|
| P1 单向范围 | 371.2-403.2 | 718.7-780.4 Mbit/s |
| P1 双向范围 | 14.4-35.8 | 596.7-787.7 Mbit/s |
| P4 单向范围 | 564.2-688.9 | 666.3-1018.4 Mbit/s |
| P4 双向范围 | 31.1-33.3 | 893.6-958.5 Mbit/s |

该极端方向性在三轮中重复，且同一台 Mac 的有线对照没有复现，因此不能用
“iperf3 双向模式普遍异常”解释。无线单向链路与 PHY 状态正常，但同时双向时
上行占用几乎压制下行。

同步采样中：PBUF 始终稳定，softnet dropped 为 0，NSS/EDMA 和接口错误增量为 0，
CPU 总忙碌最高约 66%，未达到整体饱和。个别场景 `time_squeeze` 增长，但没有转化
为 softnet 丢包。现阶段应标记为“ath11k/NSS Wi-Fi 主机终结路径、空口争用或队列
公平性可疑”，不能在没有第二台 Wi-Fi 客户端和 forwarding 对照时直接认定驱动 bug。

### 4.4 Wi-Fi Mac 到有线 Windows AX88179

证据目录：`router-backups/perf-runs/20260814-162313-wifi-mac-windows-ax88179-r0-956cf06`

有线 `en0` 已停用，Mac 仅保留 Wi-Fi `en1`，因此路径不再混入有线接口。

TCP 三轮短时结果：

- Mac 到 Windows P1：约 `60-76 Mbit/s`，每轮大量重传。
- Windows 到 Mac P1：约 `809-908 Mbit/s`，零重传。
- Mac 到 Windows P4：约 `108-120 Mbit/s`，每轮约 3487-4177 重传。
- Windows 到 Mac P4：约 `938-947 Mbit/s`，零重传。
- P4 双向：Mac 到 Windows约 `101-119 Mbit/s`，Windows 到 Mac约 `249-262 Mbit/s`。

UDP 三轮短时结果：

- Mac 到 Windows：300 Mbit/s 丢包约 `3.49-5.04%`；600 Mbit/s 约
  `2.42-2.62%`；900 Mbit/s 约 `2.42-2.58%`。
- Windows 到 Mac：300/600 Mbit/s 基本零丢包；900 Mbit/s 实收约
  `789-806 Mbit/s`，丢包约 `0.13-0.38%`。

600 秒 P4 双向耐久已经完整结束：Mac 到 Windows `57.8 Mbit/s`、`51102` 次
重传；Windows 到 Mac `241.6 Mbit/s`、零重传。全部 JSON、302 个长时同步样本
和 SHA256 完整，数据完整性为 `PASS`，但测试结论为 `FAIL/ENV-BLOCKED`：

1. Windows AX88179 接收方向的吞吐、TCP 重传和 UDP 丢包显著异常，端点未通过
   资格门禁，不能据此把低吞吐判给 AX6。
2. 全程 `lan1.rx_errors +1`、`lan1.rx_dropped +3`，其中长时阶段各增长 1，必须
   在非 AX88179 端点复测，不能删除该故障证据。
3. P1 双向第一轮出现 OCM payload/nopayload `+1008/+8`，P4 双向第二轮 OCM
   payload `+350`；但 `default alloc fail`、`payload_alloc_fails`、N2H queue drop、
   softnet drop 均未增长。
4. 600 秒低吞吐期间 OCM/default/payload/N2H queue 全部零增量，说明 OCM 压力
   不是持续低速的充分条件。

旧 runner 只在双向阶段采样，无法确定约 36 万次 OCM 累计增长具体发生在哪个
单向或 UDP 阶段。新 runner 已改为每个 TCP/UDP/长时阶段都采样，并在 pre/post
总快照加入 N2H 计数，下一轮可以精确定位。

## 5. 当前故障与可信度分级

| ID | 状态 | 问题 | 当前证据与边界 |
|---|---|---|---|
| T-01 | 确定 | 旧 LAN-LAN runner 可被 iperf 会话永久挂住 | 已修复并由 hang fixture 验证 |
| T-02 | 已修复并验收 | 旧 kmod artifact 缺少 `Packages` 引用的 23 个 IPK | 新 artifact 索引和磁盘均为 166 个 IPK；压缩包 171 项与目录加校验文件精确一致，全部 SHA256 通过 |
| T-03 | 确定 | lint 对 helper 重构产生错误失败 | 已修复；云端全门禁通过 |
| R-01 | 确定异常 | Wi-Fi 路由终结双向极端不公平 | 三轮重复；有线同机对照不复现；根因仍待 forwarding/第二客户端验证 |
| R-02 | 确定异常 | Windows AX88179 接收方向在持续负载后严重退化 | 有线和 Wi-Fi 客户端均指向 Windows 接收方向；不能归因 AX6 NSS |
| R-03 | 可疑 | 有线 Mac 到路由器 P4 双向存在较多 TCP 重传 | 无 NSS/PBUF/softnet dropped 对应增量；需新固件和端点抓包复测 |
| R-04 | 低频可疑 | 一次 `lan1.rx_dropped +1` | 只有单次单包；需要重复出现才升级 |
| R-05 | 未验证 | 新固件把 PBUF high water 从 32768 提高到 65536 后的实际效果 | 当前实机仍为旧固件，不能用当前测试替代刷后验证 |
| R-06 | 未验证 | WAN-LAN NAT/ECM/NSS routed 双向吞吐 | 缺 WAN 侧独立 iperf3 端点；LAN-LAN 与路由本机测试不能替代 |
| R-07 | 确定压力信号 | N2H core0 OCM 首选池在短时负载中突增 | default/payload/queue 未同步增长，降级为 WARN；新固件 PBUF 需同契约 A/B |
| R-08 | 已补工具、待复测 | 旧采样只覆盖 bidir，遗漏单向和 UDP 阶段 | runner 已改为 `sample_scope=all`，旧证据不能反推具体阶段 |
| R-09 | 环境待就绪 | Windows USB Wi-Fi 网卡核心测试 | 只读 station/DHCP 盘点确认 `.111` 仍是有线端点且未关联 AP；需连接 USB Wi-Fi、记录芯片/驱动/IP/MAC 后单独执行 |

## 6. 云端构建状态

- 构建运行：GitHub Actions `31779338123`
- 固件构建提交：`d67d4f75f2b8a691d9d0254f82401bfbbc610e6d`
- 结果：`success`。
- 已通过：锁定源码、feeds、配置、OpenClash 输入、安全回移、NSS patch prepare、
  007/008/012/018/019 回归门禁、完整编译、DTB、最终 rootfs、artifact staging、
  离线 kmod feed、sysupgrade 和 recovery 上传。
- Release 上传按策略跳过；当前产物仍是候选验证件，不是已发布固件。

`b565969` 只修改 lint 门禁，不改变固件输入；因此运行 `31779338123` 的固件内容
仍覆盖所有实际固件修复。测试工具的后续提交也不改变固件 rootfs。

### 6.1 下载产物独立验收

持久证据目录：
`router-backups/NOT-FLASHED/run31779338123-20260814`

1. sysupgrade、recovery、离线 kmod feed 和 kmod 压缩包的全部 SHA256 均通过。
2. sysupgrade 与 recovery 的设备 manifest 和 BUILD-LOCK 逐字一致。
3. rootfs 的 opkg 状态与设备 manifest 均为 391 个已安装包，逐项无差异。
4. 离线 feed 的 `Packages` 索引与磁盘均为 166 个 IPK，无缺件或孤立 IPK；
   `kmod-packages.tar.gz` 的内容与目录加 `KMOD-SHA256SUMS.txt` 精确一致。
5. rootfs 内 OpenClash 为 `0.47.156`；Meta core 是静态链接 AArch64 ELF，
   SHA256 为 `453066ac9e5045d95d035a96b5c02fb593fdc0427c3c9153ff4d6a4403feab6a`，
   与 BUILD-LOCK 一致。
6. rootfs 内 SQM/CAKE/IFB/NSS qdisc 组件已安装，但默认队列
   `sqm.eth1.enabled=0`；当前没有 SQM 与 NSS 同时接管流量的运行冲突。
7. `98-nss-tune` 首次启动写入 ECM `br-lan/report` 分层策略；
   `ax6-boot-guard` 每次启动还会修复旧保留配置，和实际 helper 逻辑闭合。
8. 实机重新校验镜像 SHA256 后，`sysupgrade -T` 返回 0；没有刷写或重启，
   临时镜像已经删除。

### 6.2 驱动仓库交叉验证

| 来源 | 锁定/当前事实 | 对本轮结论的约束 |
|---|---|---|
| Qualcomm CodeLinaro `nss-drv` | 本仓库锁定 `6aa14c78`，QSDK 13.1；`nss_n2h.h` 分别定义 OCM、DDR/default pool 与 payload allocation fail | OCM 失败不能与最终 payload/queue drop 混为一个计数；后两类增长仍按 FAIL |
| Qualcomm `nss_n2h.c` | empty pool 合法范围 `32..131072`；`extra_pbuf_core0` 是一次性额外分配 | 65536 在驱动允许范围内，但运行中不能重复改 extra pool，必须随启动配置并读回 |
| `qosmio/openwrt-ipq` `main-nss` | 1GB profile 为 `extra=10000000/high=72512/wifi=36864`，且明确 extra pool 已分配后不可重复修改 | 我们候选 `10000000/65536/32768` 是更保守的兼容配置，不是直接照抄；必须实机 A/B 才能验收 |
| 当前 `OrdinaryJoys/immortalwrt-nss` | 1GB profile 为 `10000000/65536/32768`，启动后逐项读回；high-water 最后写入，防止 Wi-Fi pool 更新覆盖 | 代码顺序和 one-shot 约束已闭合；效果尚未由当前旧固件验证 |
| 当前实机 | `extra=10002432/high=32768/wifi=32768`；SKB recycler 已启用 `2048/1024`，当前回收缓存总数 14282 | 旧文档所称“缺 SKB recycler”已不成立；当前差异集中在 high-water 仍为 32768 |

实机测试后最新只读状态：N2H queue drop 和 softnet drop 均为 0，OCM fail 为
`368227/1285`，default fail 为 `3493/0`，payload fail 为 `3496`；default/payload
值在本轮所有已采样阶段之前就已存在且全程未增长。内核日志没有新的 NSS、EDMA、
ath11k crash/warning；仅有用户停用有线接口对应的物理链路 down 事件。

## 7. 下一阶段修复与验证方案

### P0：闭合当前证据

1. Wi-Fi 到 Windows 的 600 秒双向阶段、JSON、样本、boot ID 和 SHA256 已闭合。
2. 测试工具硬超时、全阶段采样、N2H 总快照和 router-endpoint runner 已通过
   `36/36` 夹具、shellcheck 和云端 Lint `31787844185`。
3. 使用新的 `sample_scope=all` 在非 AX88179 合格端点复测，定位 OCM 压力究竟
   出现在 Wi-Fi 上行、有线接收还是 UDP 峰值阶段。
4. 保持 default/payload/queue/softnet/接口错误为硬失败；OCM-only 保留 WARN，
   不再制造伪 FAIL，也不忽略压力信号。
5. Windows USB Wi-Fi 网卡需先记录真实芯片、驱动、IP 和 MAC，再执行相同
   P1/P4/UDP/600 秒矩阵；未采集身份前不得写成已测试。

### P1：新固件产物闭环

1. 云端构建、下载、SHA256、manifest/rootfs、离线 feed 和
   `sysupgrade -T` 已全部通过。
2. 当前镜像仍保留在 `NOT-FLASHED`，没有发布或自动刷写。
3. 经用户确认后全新刷写，再按同一测试契约复测，禁止保留旧配置影响结论。

### P1：Wi-Fi 定点 A/B（先只读，后临时）

1. 增加 ath11k peer/TID、TX completion、RX reorder、queue stop/wake 和 airtime
   统计；当前通用 station 计数在 NSS offload 下并不完整，不能作为唯一证据。
2. 使用第二台非 AX88179 的有线 Linux 端点执行 Wi-Fi forwarding 对照。
3. 使用第二台 Wi-Fi 6 客户端重复双向测试，区分 Mac 客户端行为与 AP 驱动行为。
4. 仅在基线证据完成后，临时 A/B NSS Wi-Fi datapath、RPS 或队列策略；每次只改
   一个变量，并完整回滚。未经用户确认不持久化。

### P2：Windows AX88179 定点排查

1. 冷启动 Windows 或重置 AX88179 后立即记录 P1/P4 基线和退化时间。
2. 同步采集 Windows NIC 驱动版本、USB 链路、CPU/DPC、丢包和接收错误。
3. A/B 测试 LSO/RSC/checksum/EEE/流控，但每次只改一个设置并记录回滚值。
4. 使用主板原生网卡或 Linux 同端口替换 AX88179，验证故障是否随端点移动。

## 8. 验收门禁

只有同时满足以下条件才能声明修复完成：

1. 完整测试无超时、空 JSON、缺轮次或 boot ID 变化。
2. PBUF、NSS/EDMA、softnet dropped、接口错误没有负载相关增长。
3. 合格的非 AX88179 端点上，P4 单向接近 1GbE 上限，双向没有单侧长期饥饿。
4. 新固件 artifact、manifest、rootfs、kmod feed 和 SHA256 全部独立验证。
5. 刷机后的实机身份与构建锁一致，且同一测试矩阵重复通过。
