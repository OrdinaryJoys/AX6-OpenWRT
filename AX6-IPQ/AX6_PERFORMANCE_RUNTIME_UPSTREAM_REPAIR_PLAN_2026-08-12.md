# AX6 性能、实机状态与上游交叉验证修复方案 (2026-08-12)

## 1. 结论先行

本轮已经完成 AX6 实机只读状态审计、LAN-LAN TCP/UDP 吞吐矩阵、路由器本机对照、
PAUSE 计数探针，以及 Qualcomm CodeLinaro、qosmio、VIKINGYFY、ImmortalWrt 和
OpenWrt qca-nss-dp 的精确提交交叉检查。

当前结论分为三层：

1. AX6 单向千兆交换能力正常。Mac 到 Windows 和 Windows 到 Mac 单向 TCP 均约
   946-949 Mbps；负载期间没有接口错误/丢包、softnet drop/time_squeeze、qdisc
   drop/overlimit/backlog 或 EDMA 活动错误增量。
2. 双向异常尚未修复，但方向已经定位到 Windows 接收侧。无论发送端是经 LAN1
   交换的 Mac，还是路由器本机协议栈，Windows 接收方向都会在双向负载时下降；
   Windows 发送方向持续约 936-948 Mbps。该证据不支持把根因直接归给 NSS、ECM、
   EDMA、SSDK 某一端口或 AX6 CPU 频率。
3. 本轮没有真实 WAN-LAN/NAT routed 测试。Mac 与 Windows 都位于 192.168.5.0/24，
   本轮 LAN1-LAN2 流量是二层交换，不能用来证明或否定 NSS/ECM routed 性能。
   关闭 W-06 必须增加 WAN 上游侧 iperf3 端点。

因此，当前不应为了双向低速而默认关闭 Ethernet PAUSE、改变 ECM
`disable_flow_control`、合入 split-NAPI、提高 NSS 固定频率或替换官方驱动锁。

## 2. 测试对象与身份

| 项目 | 本轮值 |
|---|---|
| 设备 | Redmi AX6 stock layout，1 GiB SKU |
| 固件 revision | `r0-4e35043` |
| 内核 | `6.18.38` |
| boot ID | `22db9604-eb47-4bbd-94eb-d9ceab8c369b` |
| 路由 LAN | `192.168.5.1/24` |
| 路由 WAN | `192.168.1.2`，网关 `192.168.1.1` |
| Mac 有线端点 | `192.168.5.190`，`en0`，1 Gbps full duplex |
| Windows 有线端点 | `192.168.5.111:5201`，iperf3 3.21 |
| 推断物理口 | Mac=`lan1`，Windows=`lan2`，由定向 MIB 增量交叉确认 |
| SSH 身份 | `ax6_check`，`IdentitiesOnly=yes`，严格 confirmed known_hosts |

禁止把 Wi-Fi 同时在线的 `en1=192.168.5.232` 误当成测试路径；Mac 到 Windows 的
路由在测试前已确认走 `en0`。

## 3. 可复核证据

证据当前位于本机 `/private/tmp`。目录中的每个文件均由 `SHA256SUMS.txt` 校验；
下面给出清单文件自身的 SHA256，防止后续混用不同批次。

| 证据目录 | 内容 | `SHA256SUMS.txt` SHA256 |
|---|---|---|
| `/private/tmp/ax6-perf-lanlan-20260812-212427` | TCP 18 阶段、前后快照、ping、汇总 | `c8159db2b2591d7421250bceb0b5bd4c0160249de944f327f8cb542608678cb0` |
| `/private/tmp/ax6-perf-router-host-20260812-213312` | 路由器本机到 Windows 9 阶段对照 | `7c6a1ba56e384bdbd12d2a3a73581acada3702bbb666bbd53df5a6867b17fd97` |
| `/private/tmp/ax6-perf-lanlan-udp-20260812-213554` | UDP 单向 12 阶段、失败的双向首轮、正确 EDMA 末态 | `086ab20c3804b9bf41cc5b675055ee480c72e2b6ee84263f49a3db007c1df6a4` |
| `/private/tmp/ax6-pause-probe-20260812-214053` | 20 秒 TCP 双向 PAUSE/MIB 探针 | `873b75b8b84868bc9212fd310d5f2b479a818db57841856c4bae2b8a3e0e6338` |

`/private/tmp` 不是长期归档位置；本文件保留了关键数值和证据边界。不得只保留截图
而丢弃 JSON、原始计数器和校验清单。

## 4. TCP 吞吐结果

### 4.1 LAN1-LAN2 二层交换

每项运行 3 轮、每轮 20 秒。

| 模式 | Mac 到 Windows 接收 | Windows 到 Mac 接收 | 重传特征 |
|---|---:|---:|---|
| P1 单向正向 | 946.1-947.9 Mbps | 不适用 | 0 |
| P1 单向反向 | 不适用 | 949.0-949.1 Mbps | 0 |
| P1 双向 | 341.8 / 489.6 / 483.4 Mbps | 946.4-947.3 Mbps | Mac 到 Windows首轮 405，其他两轮 0 |
| P4 单向正向 | 947.8-947.9 Mbps | 不适用 | 149-241 |
| P4 单向反向 | 不适用 | 949.0-949.1 Mbps | 0 |
| P4 双向 | 351.7 / 366.1 / 158.6 Mbps | 944.5-947.0 Mbps | Mac 到 Windows 733 / 731 / 4898 |

最差一轮不是稳定限速：Mac 到 Windows 从约 715 Mbps 逐步下降，在第 8-12 秒附近
出现接近 0 Mbps 和集中重传，之后恢复到约 162 Mbps；同时 Windows 到 Mac 始终约
945-950 Mbps。这更像接收端处理/队列/驱动背压，而不是共享交换带宽被平均分配。

### 4.2 路由器本机到 Windows 对照

| 模式 | AX6 到 Windows | Windows 到 AX6 | 重传 |
|---|---:|---:|---:|
| P1 单向正向 | 900.2-916.7 Mbps | 不适用 | 0 |
| P1 单向反向 | 不适用 | 944.5-949.1 Mbps | 0 |
| P1 双向 | 123.5 / 217.0 / 472.9 Mbps | 935.8-947.9 Mbps | 双向均 0 |

路由器本机流量不走与 Mac 完全相同的交换路径，但低速仍然跟随 Windows 接收方向。
这是目前排除“只坏 lan1、只坏 Mac 发送路径、只坏某条 NSS 转发路径”的最强对照。

## 5. UDP、延迟与计数器结果

### 5.1 单向 UDP

| 方向 | 300 Mbps | 600 Mbps | 900 Mbps |
|---|---:|---:|---:|
| Mac 到 Windows | 0.05%-0.18% loss | 0.53%-0.66% loss | 1.07%-3.49% loss |
| Windows 到 Mac | 0% loss | 0% loss | 0%-0.089% loss，实际约 890 Mbps |

UDP 也呈现 Windows 接收方向更弱，但 900 Mbps UDP 已接近 1 GbE 的线速边界，不能
只凭该档丢包判断交换驱动故障。600 Mbps 已出现稳定方向差异，必须在 Windows NIC
A/B 和第二端点复测中继续追踪。

Windows iperf3 在首个双向 UDP 阶段报：
`unable to read from stream socket: Resource temporarily unavailable`。脚本按 fail-fast
停止，没有盲目重跑。该错误暂按端点/工具会话限制处理，不归因于 AX6。

一次性 UDP 采集脚本误用了不存在的 EDMA debugfs 路径，因此阶段文件中的 EDMA
部分代表“未采样”，不是“计数为 0”。21:51 使用正确路径补采：除累计
`edma_err_alloc_fail_cnt=4990` 外全部为 0；`nss-check` 的 2 秒差分仍为 +0。

### 5.2 延迟与数据面计数

- 18 个 TCP 阶段中，每阶段路由器 ping 均收到 100/101 个响应，平均约 0.97-1.77 ms，
  最大约 2.1-3.8 ms。
- 每个 TCP 阶段接口 error delta=0、drop delta=0。
- 每个 TCP 阶段 softnet drop delta=0、time_squeeze delta=0。
- 所有 qdisc `dropped=0`、`overlimits=0`、`backlog=0`。
- EDMA `alloc_fail` 在 18 个 TCP 阶段均无增长；其他 EDMA error/drop 均为 0。
- 负载温度约 49.8-51.1 C，没有热降频证据。

## 6. 实机末态

21:51 的只读复核结果：

| 子系统 | 状态 |
|---|---|
| `nss-check -v` | PASS=46、WARN=4、FAIL=0 |
| `ax6-config-audit -v` | PASS=30、WARN=3、FAIL=0 |
| NSS | 两核启动，748.8 MHz 固定频率，内部 RPS bitmap=15 |
| ECM | healthy，`disable_offloads=1`、`disable_gro_list=1`、`disable_flow_control=0` |
| OpenWrt flow offload | software=0、hardware=0，未见冲突模块 |
| Linux 数据面分流 | 4 个 NSS 数据面设备的 RPS/RFS/XPS 已生效 |
| Ethernet | wan/lan1/lan2 1 Gbps full；lan3 未接线 |
| Wi-Fi | ath11k、NSS Wi-Fi offload、frame_mode=2、crypto_mode=0；country=US |
| VLAN | 无 DSA bridge-vlan/vlan_filtering；qca_nss_vlan 就绪 |
| ZeroTier | daemon/interface/address/fw4 动态端口规则一致 |
| OpenClash DNS | core 与 7874 探测正常，dnsmasq 指向单一受保护 owner |
| ZRAM | 256 MiB、zstd、active，当前无压力使用 |
| 存储 | overlay 69%；10.5 MiB ROM-identical core 和约 39 MiB Geo 数据为已知警告 |

累计 `lan1 rx_dropped=123`、`lan2 rx_dropped=654` 是历史值，本轮全部性能阶段增量为
0，不能作为本轮低速根因。累计 `EDMA alloc_fail=4990` 同样必须按增量判断。

## 7. 官方驱动逻辑核对

### 7.1 当前锁定提交

| 组件 | 仓库锁定 | 2026-08-12 官方分支 | 结论 |
|---|---|---|---|
| qca-nss-dp | `d8f802f08fd8` | `win.nss.1.1` 与 `.r35` 同值 | 已是当前官方值 |
| qca-ssdk | `d9a196497ece` | `win.nss.1.1` 与 `.r35` 同值 | 已是当前官方值 |
| qca-nss-drv | `6aa14c78e097` | `win.nss.1.1` 与 `.r35` 同值 | 已是当前官方值 |
| qca-nss-ecm | `8c7355bf80db` | 通用=`fafe228f08ba`，`.r35`=`8c7355bf80db` | 当前 `.r35` 更新，禁止误降级 |

官方仓库：

- <https://git.codelinaro.org/clo/qsdk/oss/lklm/nss-dp>
- <https://git.codelinaro.org/clo/qsdk/oss/lklm/qca-ssdk>
- <https://git.codelinaro.org/clo/qsdk/oss/lklm/nss-drv>
- <https://git.codelinaro.org/clo/qsdk/oss/lklm/qca-nss-ecm>

### 7.2 PAUSE 显示与实际协商

官方 qca-nss-dp 的 `nss_dp_get_pauseparam()` 返回 `dp_priv->pause`，也就是驱动保存的
请求值；`nss_dp_set_pauseparam()` 会修改 PHY Pause/Asym_Pause advertisement，并调用
`genphy_config_aneg()`。这不是只改一个软件开关，而会改变链路协商。

官方 SSDK 的 `qca_hppe_mac_sw_sync_task()` 会读取 PHY 的实际 `tx_flowctrl` 和
`rx_flowctrl`，在非 force mode 下同步到 MAC。EDMA v1 的 `edma_if_pause_on_off()`
仍是返回成功的空实现。由此可知：

- `ethtool -a` 的 requested RX/TX=off 与 negotiated RX/TX=on 可以同时出现；
- 不能仅凭两组值不同就判断 NSS/SSDK 冲突；
- 本轮双向探针观察到 `lan1 rx_pause +32`、`lan2 tx_pause +45`，说明链路确有背压，
  但没有 overflow/underrun/error/drop 增长，PAUSE 更可能是接收压力的结果；
- 仓库 `offload_physical_policy=report` 会在物理端口分支直接继续，因此把 ECM
  `disable_flow_control=1` 只会处理 host-path，不能按想象自动关闭 lan1/lan2；
- 若要验证物理 PAUSE，必须在维护窗口显式对两个端口逐项 A/B，并准备恢复广告和
  链路重协商，不能持久修改默认值。

## 8. 上游仓库动态与可合并性

| 上游 | 精确 HEAD | 本轮相关性 | 处理决定 |
|---|---|---|---|
| qosmio/openwrt-ipq `main-nss` | `92a2d104145c` | Linux 6.12.92 NSS 补丁上下文重排；不是新的 AX6 PAUSE/吞吐修复 | 不移植；本仓库是 6.18，继续按语义逐补丁审计 |
| VIKINGYFY/immortalwrt `main` | `de810bc8e2ce` | 主要是 TL-ER2260T、IPQ60xx 设备/镜像/固件默认；未改 Redmi AX6 数据面 | 不整提交合并；仅设备无关项另开候选 |
| immortalwrt/immortalwrt `master` | `bf1f49d07a93` | 合并官方源，主要涉及 Airoha、mbedtls、其他平台 | 与本症状无直接修复，不混入性能分支 |
| openwrt/qca-nss-dp `openwrt` | `6a5c4716ca25` | ethtool string API 清理；前一项为 EDMA v2 PPEDS 柔性数组布局 | AX6 使用 EDMA v1，不能宣称修复当前问题；可作为独立兼容候选 |

qosmio 的说明要求 NSS 环境关闭 OpenWrt packet steering 与 software/hardware flow
offload，并指出 DSA bridge VLAN filtering 与 NSS Wi-Fi offload 不兼容。实机当前
flow offload=0、通用 packet steering=0、无 bridge-vlan，符合该边界；NSS 自有 RPS
和 qualcommax IRQ/RPS 服务不等于 LuCI 的通用 packet steering。

上游链接：

- <https://github.com/qosmio/openwrt-ipq>
- <https://github.com/VIKINGYFY/immortalwrt>
- <https://github.com/immortalwrt/immortalwrt>
- <https://github.com/openwrt/qca-nss-dp>

## 9. 分阶段修复与验证方案

### P0：先关闭端点变量

一次只改一个 Windows NIC 变量，每项执行 P1/P4 双向 3 轮并立即恢复：

1. 导出 NIC 型号、硬件 ID、驱动版本/日期、固件、PCIe link、RSS 队列和高级属性。
2. 禁用 EEE/Green Ethernet 后复测；无改善则恢复。
3. Flow Control 做 `Auto -> Disabled` A/B；无改善则恢复。
4. 分别 A/B RSS、RSC、LSO、checksum offload、interrupt moderation；禁止组合修改。
5. 交换 Mac 与 Windows 的网线和 lan1/lan2 端口；症状跟 Windows 走则排除端口，
   跟 lan2 走才进入 SSDK/PHY 端口调查。
6. 用第二台 Linux/macOS 有线设备替换 Windows，或在同一 Windows 硬件临时启动
   Linux，再跑相同矩阵，排除 Windows iperf3/驱动实现。

P0 通过标准：单向两边均 >=930 Mbps；双向每方向 >=850 Mbps，三轮方向差异 <=10%；
无异常集中重传；路由器接口/softnet/qdisc/EDMA 活动错误增量均为 0。

### P1：端点排除后才做路由器临时 A/B

1. 在可回滚维护窗口记录两个端口完整 `ethtool -a/-k/-S` 和 SSDK MIB。
2. 仅临时显式测试 lan1/lan2 PAUSE advertisement，不修改 UCI 默认，不重启 ECM，
   每次链路重新协商后确认 1 Gbps full，再运行固定矩阵。
3. 若关闭 PAUSE 无稳定三轮收益或引入 drop/overflow，立即恢复并否决该方向。
4. 不把 split-NAPI、NSS 频率、IRQ、GRO、PAUSE 放在同一轮；否则无法归因。

本阶段需要用户再次明确授权，因为操作可能短暂断链。当前未执行。

### P1：真实 WAN-LAN/NAT/NSS routed 测试

1. 在 192.168.1.0/24 WAN 上游增加独立 iperf3 server。
2. 预检 Mac 到 server 的路由必须经过 `192.168.5.1 -> wan`，拒绝同 LAN 测试。
3. 记录 ECM connection count、wan/lan MIB、EDMA、softnet、NSS 频率、CPU、温度。
4. 运行 TCP P1/P4 forward/reverse/bidir 各 3 轮，以及 UDP 300/600/900 Mbps 阶梯。
5. 对照 NSS/ECM 连接增量和 egress=wan，确认测试确实覆盖 routed offload。

没有 WAN 侧端点时，W-06 保持阻塞，不能用路由器本机或 LAN-LAN 结果代替。

### P2：仓库修复与独立候选

1. 提交 routed-perf、旧 perf 和 NSS frequency A/B 工具的严格 SSH host-key 修复及
   fixtures；旧 perf 同时改用实际存在的 qca-nss-drv EDMA 计数路径。
2. 不为 W-05 合入 split-NAPI；它只保留在独立候选分支，等 P0/P1 证明路由器瓶颈。
3. 保持 CodeLinaro 当前锁：DP/SSDK/NSS-DRV 官方 HEAD，ECM `.r35` HEAD。
4. EDMA portable DMA、invalid store cleanup、NSS 调试日志级别和 OpenClash 重复
   overlay core 继续作为四个独立问题，不与吞吐修复捆绑。
5. 当前源码/构建候选分支尚未推送，GitHub Actions 无本轮结果；完成本地审查后才
   推送并执行一次 stock 构建，不能用旧构建冒充。

## 10. 当前状态分类

### 已验证正常

- AX6 单向千兆 LAN-LAN、链路协商、EDMA 活动错误、softnet、qdisc、温度。
- NSS/ECM/ath11k/NSS Wi-Fi/SSDK/VLAN/IRQ-RPS 基本运行状态。
- OpenWrt software/hardware flow offload 与通用 packet steering 未和 NSS 同开。
- OpenClash DNS、ZeroTier L3/fw4 动态端口、ZRAM 当前运行合同。
- Qualcomm NSS-DP/SSDK/NSS-DRV/ECM 锁定版本与官方分支关系。

### 已发现但未关闭

- Windows 接收方向在双向 TCP/UDP 负载下性能下降。
- Windows iperf3 双向 UDP 会话失败，需端点/版本替代验证。
- ZeroTier 高速 UDP drops、IoT 长稳、5G invalid REO 时间关联仍是原有未关闭项。
- EDMA portable DMA、invalid store cleanup、NSS 调试日志级别、重复 overlay core。

### 尚未验证

- 真实 WAN-LAN/NAT/NSS/ECM routed 吞吐与 bufferbloat。
- 第二个独立有线 Linux 端点矩阵。
- Windows NIC 逐变量 A/B 和端口互换。
- 本轮未推送候选的云端 stock 构建、DTB/rootfs/kmod/manifest/SHA256 产物审计。
- 新候选固件冷启动、reload、24/72 小时长稳与 recovery。

## 11. 禁止的错误修复

- 不因 `ethtool` requested/negotiated 值不同就默认关闭 PAUSE。
- 不把 LAN-LAN 二层交换结果写成 WAN-LAN/NAT/NSS routed 结果。
- 不把累计 drop/alloc_fail 当成本轮活动增量。
- 不把 Windows 接收方向问题直接归因于 AX6 NSS/EDMA。
- 不整分支合并 qosmio、VIKINGYFY 或 ImmortalWrt；只按设备、内核和补丁语义拆分。
- 不修改 OpenClash 订阅/覆写，不关闭 GeoIP/GeoSite/GeoASN/CHNR 自动更新。
- 不刷写、不重启、不做持久 UCI/PHY 调整，除非用户另行确认维护窗口和回滚方案。
