# AX6 当前全状态报告（2026-08-03）

## 1. 文档定位

本文记录 Redmi AX6 在新固件已经全新刷写、配置恢复并投入实际运行后的
当前状态。内容同时覆盖：

1. 构建仓库、锁定源码、CI 和产物状态。
2. 实机版本、核心驱动、网络链路、服务和资源状态。
3. 已完成测试、未完整测试和不能直接归因的结果。
4. 确定故障、可疑项、已关闭问题及禁止操作边界。

采集时间：`2026-08-03 08:17-08:19 CST`。除健康探针和只读命令外，
本轮没有执行持久配置修改、服务重启、系统重启或固件刷写。

## 2. 总体结论

当前正常业务转发路径可用，NSS、ECM、SSDK、EDMA、ath11k、VLAN、
OpenClash 和 ZeroTier 均处于运行状态，两个仓库审计工具返回 0。25 分钟
TCP 单流持续达到 938 Mbps，未出现核心驱动错误增长。

但当前不能表述为“完全没有故障”，原因如下：

| 优先级 | 项目 | 当前状态 |
|---|---|---|
| P0（维护面） | APCS regmap debugfs 越界可触发 kernel panic | 已确认根因边界，尚未编码和构建修复；禁止实机复现 |
| P1 | 系统 UDP `RcvbufErrors` 出现 1,365,195 次峰值 | 峰值已停止；当前 ZeroTier socket drops=0、Clash 7895 drops=18，原接收 socket 已关闭，归因证据不完整 |
| P1 | ZeroTier 高速上行曾持续 receive-drop | 4 MiB socket 补丁已进入实机，但旧定点测试仍未关闭问题 |
| P2 | 60 分钟压力测试未完整结束 | P1 完成；P2 在 1033 秒收到 SIGTERM；P3/P4 未执行 |
| P2 | LAN-LAN 原生双向公平性 | Windows/Mac 边界尚未由两台 Linux 同版 iperf3 排除 |
| P2 | OpenClash overlay 更新峰值 | 当前剩余 17.7 MiB，保留全部 Geo 自动更新并继续监控 |
| 观察 | qca-mcs 启动期调试消息 | 仅启动后出现 3 次，此后未增长，未关联断流 |

## 3. 版本、仓库与构建

### 3.1 实机版本

| 项目 | 值 |
|---|---|
| 设备 | Redmi AX6（stock layout） |
| Target | `qualcommax/ipq807x` |
| Rootfs | squashfs + UBI overlay |
| 固件 revision | `r0-0ea8486` |
| Kernel | `6.18.38` |
| 当前 boot ID | `da88533e-a533-47af-b757-7c3674d4ce5f` |
| ZeroTier | `1.16.2` |
| OpenClash | `0.47.133`，AArch64 Meta core |

压力脚本中显示的 `r0-84fc0f2` 是标签歧义：`84fc0f2` 是构建仓库提交
前缀，真实固件 revision 是 `r0-0ea8486`，不表示刷入了错误固件。

### 3.2 仓库状态

| 项目 | 值 |
|---|---|
| 构建仓库分支 | `codex/ax6-postflash-build-repair-20260801` |
| HEAD/远端分支 | `84fc0f2266e265b43152ada6b4b519dc2adc2f70` |
| 功能修复提交 | `ac30a317fea1ac0bc36cad26bebbf52153bee781` |
| 锁定源码 | `OrdinaryJoys/immortalwrt-nss@0ea848641f031dc37440e082163b3de1d8ccb9cf` |
| 工作区状态 | `AX6-IPQ/HARDWARE.md` 已修改；状态和计划文档未提交 |

当前修改是文档和维护安全说明，不表示 APCS 内核修复已完成，也未推送或
合并主分支。

### 3.3 CI 与产物

| 检查 | 运行 | 结果 |
|---|---|---|
| Lint | [30707216199](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/30707216199) | success，HEAD 与 84fc0f2 一致 |
| Stock build | [30707218161](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/30707218161) | success，HEAD 与 84fc0f2 一致 |

已验证过 stock sysupgrade、factory UBI、initramfs、kmod、manifest、
BUILD-LOCK、OpenClash core ELF/哈希和 rootfs 包清单。当前没有新的构建提交，
因此不需要把旧构建成功误写成 APCS 修复已经验证。

## 4. 当前实机资源

| 项目 | 当前值 | 判断 |
|---|---:|---|
| 运行时间 | 约 56 分钟 | panic 后自动重启的当前启动，采集期间 boot ID 不变 |
| RAM | 916 MiB，总可用约 466 MiB | 正常 |
| ZRAM | 256 MiB、zstd、使用 0 | 正常，无 swap 压力 |
| Overlay | 21.1/41.0 MiB，54% | 可用 17.7 MiB，需要监控更新峰值 |
| 负载 | 0.09 / 0.70 / 1.08 | 压力结束后已回落 |
| 压力温度峰值 | 约 59.3 C | 未见热失控 |

OpenClash GeoIP/GeoSite/ASN/CHNR 在 overlay 的逻辑大小约 39.5 MiB，
dashboard 上层文件约 12.3 MiB。固件只读层同时包含 dashboard 基线，
overlay 中是更新后的替换文件；UBI 实际占用以 `df` 为准，不能把两个目录的
逻辑大小简单相加。按既定要求保留 GeoIP、GeoSite、GeoASN 和 CHNR 自动更新。

## 5. 核心驱动和网络链路

### 5.1 NSS、ECM、SSDK 与 EDMA

- `qca_nss_drv`、`qca_nss_dp`、`qca_ssdk`、`ecm`、`qca_nss_vlan`、
  `qca_nss_bridge_mgr` 和 `qca_mcs` 均已加载。
- 两个 NSS core 正常启动，当前频率 748.8 MHz；NSS 内部 RPS 开启，
  hash bitmap=15，1 GB pbuf profile 已应用。
- ECM：`disable_offloads=1`、`disable_gro_list=1`、
  `disable_flow_control=0`，`br-lan` 位于 host-path 保护范围。
- 防火墙 UCI 的软件和硬件 flow offload 均为 0；未加载 shortcut-fe、
  fast-classifier 或 netfilter flow-offload 冲突模块。
- EDMA 除 `alloc_fail_cnt=102` 外全部为 0。该值从 TCP 压力开始到结束没有增长，
  因此不能把本轮 UDP socket drop 归因于 EDMA 分配失败。
- `nss-check -q` 返回 0：PASS=45、WARN=4、FAIL=0。

### 5.2 IRQ、RPS、SQM 与 qdisc

- irqbalance 禁用且未运行。
- IRQ/RPS 由 qualcommax 上游 `smp_affinity`、`set-irq-affinity` 和 NSS 服务管理，
  没有检出多个自定义脚本互相覆盖。
- `network.globals.packet_steering=0`，物理端口 Linux RPS mask 为 0，
  与 NSS 内部 RPS 路径一致。
- SQM UCI 配置存在但 `enabled=0`；无 IFB 网络设备，无活动 cake qdisc。
  `sch_cake`/`ifb` 模块已安装并加载不等于流量经过 SQM。

### 5.3 物理端口

| 端口 | 状态 | 错误/丢包 |
|---|---|---|
| WAN | 1000 Mbps/full/up | rx/tx error=0，drop=0 |
| LAN1 | 1000 Mbps/full/up | error=0，rx drop=8，tx drop=3 |
| LAN2 | 1000 Mbps/full/up | error=0，drop=0 |
| LAN3 | no carrier | 未连接，不是驱动故障 |

LAN1 的小量 drop 从前一快照 6 增至 8，但没有 CRC/FCS/frame/FIFO 错误，
且主要 TCP 压力端口 LAN2 始终为 0。需要后续按时间差分观察，当前证据不足以
判定为交换芯片或线缆故障。

## 6. Wi-Fi、VLAN 与基础配置

| 项目 | 当前状态 |
|---|---|
| 5 GHz | US、信道 44、HE80、29 dBm、隔离关闭、PMF optional |
| 2.4 GHz | US、HE40 配置、自动信道和 20/40 coexistence；当前信道 1/实际 20 MHz |
| ath11k | NSS offload=1、frame mode=2、hardware crypto、fw memory mode=1 |
| Wi-Fi 内核错误 | 未检出 firmware crash、timeout 或 fatal |
| VLAN | 无 bridge-vlan/filtering 混用；qca_nss_vlan 就绪 |

2.4 GHz 当前实际 20 MHz 是环境共存降宽，不是 HE40 配置失败。IoT 客户端
兼容性仍必须通过 legacy/HT/HE 设备矩阵验证，不能只看 AP 侧带宽判断。

qca-mcs 在启动后 46-89 秒记录 3 次
`MC_DEV returned NULL for device br-lan`，随后不再增长。它与重启后客户端
重新关联的时间吻合，目前无吞吐、EDMA、ath11k fatal 或用户断流证据与其对应。

## 7. OpenClash、ZeroTier、UPnP 与 OpenVPN

### 7.1 OpenClash

- core、watchdog、DNS health daemon 均运行。
- 直连 `127.0.0.1:7874` DNS 探针返回 0。
- dnsmasq `noresolv=1`，唯一上游为 `127.0.0.1#7874`。
- Fake-IP、UDP proxy 和自定义 DNS 启用；默认 DNS 禁用 IPv6。
- GeoIP、GeoSite、GeoASN、CHNR 自动更新全部保持开启。
- 当前 Clash UDP 7895 socket 的内核 drops=18，没有持续增长证据。

### 7.2 ZeroTier

- `1.16.2 ONLINE`，network `OK`，地址 `172.29.205.171/16`。
- 本次动态端口为 `9993/24469/50150`。
- CLI settings、实际 UDP socket、reconcile 状态文件、生成 nft include 和实时
  nft 规则完全一致。
- L3 健康探针返回 0，当前六个 ZeroTier UDP socket 的 drops 均为 0。
- 既有高速上行定点测试曾出现 receive-drop，因此不能用当前空闲值关闭 P1。

### 7.3 UPnP、OpenVPN 和防火墙

- UPnP UCI `enabled=0`，无 miniupnpd 进程；空的 upnp nft chain 不代表服务开启。
- OpenVPN 保留标准禁用骨架：`tun0/auto=0`、WAN 1194 规则 `enabled=0`，
  无进程、无接口、无监听、无活动 nft 放行。
- 三个历史 DNAT（OPO、ZT、SOAP8080）均 `enabled=0`。
- fw4/nft 规则完整存在。`/etc/init.d/firewall running` 返回 false 是因为 fw4
  没有常驻 procd 实例，不表示防火墙已停止。
- root 密码已经手动设置；恢复脚本没有写入密码。Dropbear 直连限制为 LAN，
  LuCI 可从 LAN/ZeroTier 到达并受登录认证保护。

## 8. 压力测试结果

日志：
`/Volumes/FX-MD87/Review/backups/flash-20260802/60min-continuous-v2-20260803-072556.log`

### 8.1 Phase 1：TCP 单流

| 指标 | 结果 |
|---|---:|
| 时长 | 1500 秒 |
| 传输 | 164 GiB |
| 平均发送/接收 | 938/938 Mbps |
| TCP retransmission | 3 |
| 温度 | 55.7-57.3 C |
| EDMA/物理错误增长 | 0 |

Phase 1 通过，可排除“持续单向千兆必然触发 NSS/EDMA 故障”。

### 8.2 Phase 2：TCP 双向

计划时长 1200 秒，实际在 1033.33 秒时收到 `SIGTERM`：

| 方向 | 实际平均 | 重传 |
|---|---:|---:|
| TX-C | 797 Mbps | 0 |
| RX-C | 778 Mbps | 接收方向未提供发送端重传 |

该结果说明路由器端点可以同时维持较高双向吞吐，但测试提前约 167 秒结束，
只能记为“部分通过”，不能替代完整双向测试和两台 LAN 端点转发测试。

### 8.3 Phase 3/4 和脚本完整性

Phase 3 UDP 梯度、Phase 4 burst/bufferbloat/concurrent 以及 FINAL AUDIT 均未执行。
主脚本和客户端进程已退出，路由器上的三个 iperf3 daemon 仍在等待测试连接。

现有脚本存在以下证据缺口：

1. 没有 trap 记录收到的终止信号和停止阶段。
2. 每阶段没有记录 `/proc/net/snmp` UDP 差分和 socket inode/drops 归属。
3. 没有区分“路由器作为 UDP 接收端”和“路由器只做 NSS 转发”。
4. P2 提前退出后没有生成明确 FAILED/INCOMPLETE 总结。
5. 固件标签混用了 source revision 与 build repo commit。

## 9. UDP RcvbufErrors 新证据

在 P2 结束后采集到：

```text
Udp InErrors      = 1365195
Udp RcvbufErrors  = 1365195
```

5 秒复核期间两个值均不再增长。当前 `/proc/net/udp*` 显示：

- ZeroTier 六个 socket drops 全部为 0。
- Clash 7895 drops=18。
- iperf3 UDP 会话 socket 已关闭，只保留 TCP daemon，因此无法从当前 inode
  反向证明 1,365,195 全部属于哪个已关闭 socket。
- EDMA `alloc_fail_cnt` 仍为 102，其他 EDMA error=0。

因此当前最严格结论是：发生过一次应用/socket 接收层 UDP 丢包峰值，峰值已经
停止，且没有证据指向 EDMA；它很可能来自已关闭的临时 UDP 压力会话，但由于
测试脚本没有在会话存活时采集 socket inode 和 drop，不能写成已完成归因。

## 10. 已确认的 APCS regmap 内核故障

本轮较早的只读审计错误地递归读取 `/sys/kernel/debug`，命中
`regmap/b111000.mailbox/registers` 后触发 kernel panic。pstore 调用链为：

```text
regmap_mmio_read32le
_regmap_read
regmap_read_debugfs
regmap_map_read_file
Kernel panic - not syncing: Oops: Fatal exception
```

上游交叉验证：

- [IPQ8074 DTS](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/qcom/ipq8074.dtsi)
  为 APCS mailbox 分配 `0x1000` MMIO 资源。
- [Qualcomm APCS mailbox 驱动](https://github.com/torvalds/linux/blob/master/drivers/mailbox/qcom-apcs-ipc-mailbox.c)
  的共享 regmap `max_register=0x1008`。
- [regmap debugfs](https://github.com/torvalds/linux/blob/master/drivers/base/regmap/regmap-debugfs.c)
  会读取到 `map->max_register`。

这是 root 维护面读取漏洞，不是正常 NSS 转发路径故障。当前禁止递归读取整个
debugfs；现有 `nss-check` 只读取白名单精确节点。修复必须在独立源码分支完成，
不能在实机重复制造 panic。

pstore 永久备份：
`/Volumes/FX-MD87/Review/backups/flash-20260802/pstore-20260803-regmap-panic/`

## 11. 已关闭和已排除项

| 项目 | 当前结论 |
|---|---|
| root 空密码 | 已关闭，密码由用户手动设置 |
| NSS 与软件 flow offload 冲突 | 已排除，UCI、模块和 rootfs 三层均无活动冲突 |
| SQM 限速 | 已排除，SQM disabled 且无活动 qdisc/IFB |
| 2.4G HE40/HE20 | 当前为标准共存降宽，不能作为故障根因 |
| PAUSE 默认关闭 | 已否决，旧 A/B 无改善；保持 `disable_flow_control=0` |
| ZeroTier 动态端口规则遗漏 | 已排除，当前三端口完整一致 |
| OpenClash DNS 单点无保护 | 已修复，直连 DNS health probe 和受控恢复运行正常 |
| UPnP/OpenVPN 实际运行 | 均处于完整禁用态 |

## 12. 当前不可宣称完成的部分

1. APCS regmap 内核修复尚未实现和构建。
2. UDP 1,365,195 次 RcvbufErrors 尚未获得 socket 存活期归属证据。
3. ZeroTier 高速上行 receive-drop 尚未关闭。
4. 60 分钟压力测试只完成 P1 和 86% 的 P2，P3/P4 未执行。
5. 两台 Linux 同版本 iperf3 的 LAN-LAN 双向转发测试未完成。
6. 24 小时压力、72 小时正常业务和 2.4 GHz IoT 客户端矩阵未完成。
7. Overlay 自动更新临时峰值仍需长稳期间监控。

下一步以 `AX6_NEXT_PROGRESS_AND_TEST_PLAN_2026-08-03.md` 为唯一执行顺序，
先修测试证据链，再做定点 UDP 归因和独立 APCS 构建；不得直接重跑旧脚本，
不得在实机重复读取危险 regmap 节点。
