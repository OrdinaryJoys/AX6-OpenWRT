# AX6 完整审计、修复与验证备份总档 (2026-08-12)

## 0. 文档用途与权威边界

本文是 2026-08-12 当前状态的单一入口，用于后续会话、构建、实机测试和故障回溯。
它整合以下内容：

- 实机身份、当前固件和运行状态；
- 核心驱动、网络链路、服务和配置审计；
- 本轮 TCP/UDP/延迟/PAUSE 性能测试；
- 已修复、部分修复、未修复、未验证和明确拒绝项；
- Qualcomm CodeLinaro 与四个 OpenWrt 上下游仓库的精确状态；
- 当前仓库分支、提交、工具修复、测试和构建缺口；
- 后续单变量验证、真实 routed 测试、构建和实机验收顺序。

本文不包含私钥、密码、订阅内容、OpenClash 节点、ZeroTier network secret 或其他认证
材料。SSH 只记录公钥指纹、主机指纹和安全边界。

### 0.1 文档权威顺序

发生冲突时按以下顺序解释：

1. 本文档的状态和边界；
2. `AX6_COMPLETE_ERROR_STATUS_MATRIX_2026-08-12.md` 的逐项状态；
3. `AX6_PERFORMANCE_RUNTIME_UPSTREAM_REPAIR_PLAN_2026-08-12.md` 的原始性能数值和方案；
4. `AX6_REGMAP_NSS_HARDENING_STATUS_2026-08-12.md` 的内核/NSS 候选细节；
5. `AX6_UPSTREAM_DRIVER_TARGETED_MERGE_PLAN_2026-08-12.md` 的上游拆解；
6. `AX6_VALIDATION_BACKUP_AUDIT_2026-08-12.md` 的旧证据错误说明；
7. 更早文档仅作历史参考，不得覆盖本轮重新验证结果。

### 0.2 已被取代的旧结论

下列文件保留原始取证价值，但整体结论标记为 `PARTIAL / SUPERSEDED`：

- `/Volumes/FX-MD87/Review/AX6_FULL_VALIDATION_REPORT_2026-08-12.md`
- `/Volumes/FX-MD87/Review/AX6_REPAIR_AND_FAULTS_ISSUE_LIST_2026-08-12.md`
- `/Volumes/FX-MD87/Review/backups/r0-4e35043-validation-20260812/`

不能继续引用其中的“全量验证完成”“P2 双向对称”“NSS 转发已经验证”或“吞吐全部
闭环”。具体错误包括：

- iperf3 `-d` 是 debug，不是 bidirectional；
- P2 未完整运行 1200 秒；
- P1 JSON 为 0 字节；
- 后补 JSON 覆盖同名旧文件；
- 双向摘要漏掉第二方向；
- 测试服务器在路由器本机，不是 WAN-LAN/NAT/NSS routed 流量；
- softnet 十六进制字段解析错误；
- 多个阶段没有一一对应的前后计数器；
- 旧 hwspinlock 草稿补丁损坏且返回类型错误。

## 1. 当前执行摘要

| 维度 | 当前结论 |
|---|---|
| 实机基本健康 | `nss-check` PASS=46/WARN=4/FAIL=0；`ax6-config-audit` PASS=30/WARN=3/FAIL=0 |
| 单向交换吞吐 | Mac 到 Windows、Windows 到 Mac 均约 946-949 Mbps |
| 双向异常 | 未关闭；Windows 接收方向约 159-490 Mbps，发送方向约 944-947 Mbps |
| 当前根因方向 | Windows NIC/驱动/接收卸载/流控或 Windows iperf3 高疑；尚不能宣称最终根因 |
| AX6 数据面证据 | 负载期接口、softnet、qdisc 和 EDMA 活动错误增量均为 0 |
| NSS/ECM/SSDK | 当前未发现与本轮 LAN-LAN 异常同步的确定驱动故障 |
| routed/NAT 测试 | 未完成；缺 WAN 上游 iperf3 端点，LAN-LAN 结果不能代替 |
| Wi-Fi | ath11k/NSS Wi-Fi offload 正常；2.4G HE40+20/40 coexistence 为预期配置 |
| VLAN | 无 DSA bridge-vlan/vlan_filtering 冲突；使用 NSS 兼容的 802.1q 子接口拓扑 |
| ZeroTier | daemon、接口、managed address 和 fw4 动态端口规则一致；高速 UDP drops 未闭环 |
| OpenClash DNS | core、7874、dnsmasq redirect 和健康守护正常；不修改订阅/覆写 |
| 仓库状态 | 源码和构建候选均干净；本轮修复已本地提交，未推送、未构建、未合并主线 |
| 发布状态 | 阻塞；尚缺云端 stock 构建、产物审计、新固件冷启动/reload/长稳验证 |

最重要的判断：当前不能为了双向低速而默认关闭 PAUSE、修改 ECM
`disable_flow_control`、提高 NSS 固定频率、合入 split-NAPI 或替换官方驱动锁。

## 2. 实机身份与测试拓扑

| 项目 | 当前值 |
|---|---|
| 设备 | Redmi AX6 stock layout，1 GiB SKU |
| 固件 revision | `r0-4e35043` |
| 源码标识 | `4e350435cd9` 系列旧实机固件；不是本轮 `3854ea2` 候选 |
| 内核 | Linux `6.18.38` |
| NSS firmware | `12.5-210-HK.R`，EDMA v1 |
| 当前 boot ID | `22db9604-eb47-4bbd-94eb-d9ceab8c369b` |
| 启动时间 | 约 2026-08-11 18:53，末态采集时 uptime 1 天 2:57 |
| LAN | `192.168.5.1/24` |
| WAN | `192.168.1.2`，gateway `192.168.1.1` |
| Mac 有线端点 | `192.168.5.190`，`en0`，1 Gbps full duplex，推断连接 `lan1` |
| Windows 有线端点 | `192.168.5.111:5201`，iperf3 3.21，推断连接 `lan2` |
| Mac Wi-Fi | `en1=192.168.5.232`，测试时在线但未作为数据路径 |
| SSH 公钥指纹 | `SHA256:yFtq2ICMaCTj08Ule8NYf9/Uiq6LHhUYYrpa1UXjLbk` |
| 路由 ED25519 主机指纹 | `SHA256:CwFnr3PlOkNqEZ9BepAaURHnWmlRAm6irI5Tdw5Dmok` |

Mac 到 Windows 的路由已确认走 `en0`。`lan1`/`lan2` 映射由定向 MIB 字节增量交叉
确认，不是仅按线缆记忆推断。

本轮 LAN1-LAN2 流量属于同一 `192.168.5.0/24` 内的二层交换。它可验证 PHY、SSDK/PPE
交换、端口和端点，但不能验证 WAN NAT、ECM classifier 或 NSS routed offload。

## 3. 当前仓库和提交状态

### 3.1 源码仓库

| 项目 | 值 |
|---|---|
| 路径 | `/Users/ordinaryfun/Documents/New project/immortalwrt-nss` |
| 分支 | `codex/ax6-regmap-pbuf-hardening-20260812` |
| HEAD | `3854ea2aa18e977240b194d0fb35c5007e2e9f3b` |
| 提交 | `fix(ax6): harden regmap and NSS startup boundaries` |
| 工作区 | 干净 |
| 远端状态 | 当前候选分支未推送 |

### 3.2 构建仓库

| 项目 | 值 |
|---|---|
| 路径 | `/Users/ordinaryfun/Documents/New project/OrdinaryJoys-AX6-OpenWRT` |
| 分支 | `codex/ax6-regmap-pbuf-build-validation-20260812` |
| HEAD | `3fd06da` |
| 提交 | `test(ax6): harden performance audit evidence` |
| 工作区 | 干净 |
| 远端状态 | 当前候选分支未推送，GitHub Actions 无本轮运行 |

### 3.3 `3fd06da` 包含内容

- 三个性能/频率工具统一：
  - `BatchMode=yes`
  - `IdentitiesOnly=yes`
  - `StrictHostKeyChecking=yes`
  - `UserKnownHostsFile=$AX6_KNOWN_HOSTS`
- 修复旧 `ax6-perf-test.sh` 的 EDMA 路径：
  `/sys/kernel/debug/qca-nss-drv/stats/edma/err_stats`。
- fixtures 拒绝 `StrictHostKeyChecking=no` 和过期 EDMA 路径。
- 更新全部问题状态矩阵。
- 新增性能、实机、上游交叉验证与分阶段修复方案。

没有推送、没有触发构建、没有生成新固件、没有合并主线。

## 4. 实机运行状态

### 4.1 NSS、ECM 与核心驱动

| 检查项 | 当前状态 | 判定 |
|---|---|---|
| `qca_nss_drv/qca_nss_dp/qca_ssdk/ecm` | 已加载 | 正常 |
| NSS core | 2 个均启动 | 正常 |
| `current_freq` | 748800000 Hz | 固定中频，当前无瓶颈证据 |
| `auto_scale` | 0 | 与当前固定频率策略一致 |
| NSS internal RPS | enable=1，hash_bitmap=15 | 正常 |
| Linux RPS/RFS/XPS | 4 个 NSS 数据面设备启用 | 正常 |
| ECM connection counter | 可读并增长 | 正常 |
| `disable_offloads` | 1 | host-path 保护开启 |
| `disable_gro_list` | 1 | 避免 GRO fraglist UDP/DNS 风险 |
| `disable_flow_control` | 0 | 不强制改 PAUSE/autoneg，正确 |
| `offload_host_ifaces` | 包含 `br-lan` | 正常 |
| OpenWrt software/hardware flow offload | 0/0 | 未与 NSS 冲突 |
| 通用 packet steering | 0 | 未与 NSS 策略冲突 |

`br-lan` 的 checksum/GRO/GSO/TSO 关闭；物理 `wan/lan1/lan2/lan3` 的部分 offload 保持
开启并采用 report-only 策略。当前性能和完整性测试没有证据支持对物理口做 blanket
disable。

### 4.2 EDMA、交换与物理链路

| 项目 | 当前状态 |
|---|---|
| wan | 1000 Mbps full duplex，link up |
| lan1 | 1000 Mbps full duplex，link up |
| lan2 | 1000 Mbps full duplex，link up |
| lan3 | 无对端，link down；不是故障 |
| EDMA AXI/read/write/FIFO/length errors | 全部 0 |
| EDMA QoS invalid destination drops | 0 |
| EDMA `alloc_fail_cnt` | 累计 4990，本轮全部差分窗口 +0 |
| qdisc | dropped=0、overlimits=0、backlog=0 |
| 本轮接口 error/drop delta | 全部 0 |
| 本轮 softnet drop/time_squeeze delta | 全部 0 |
| 负载温度 | 约 49.8-51.1 C |

历史累计 `lan1 rx_dropped=123`、`lan2 rx_dropped=654` 和 EDMA `alloc_fail=4990` 不能
用单点值判断本轮故障。当前仅接受相同负载窗口的前后差分。

### 4.3 Wi-Fi

| 项目 | 当前状态 |
|---|---|
| ath11k | loaded，board_id 0xff |
| NSS Wi-Fi offload | `nss_offload=1` |
| frame mode | 2，Ethernet decapsulation |
| crypto mode | 0，硬件加密 |
| firmware memory mode | 1，与 DTS 一致 |
| regulatory country | US |
| 5G | HE80/HE160 能力正常；客户端隔离关闭 |
| 2.4G | HE40 配置，`ht_coex=1`，允许运行时回退 HE20 |
| `noscan` | 不用于强制破坏 20/40 coexistence |

2.4G 从配置 HE40 自动降为 20 MHz 是 coexistence 行为，不是驱动故障。IoT 个别设备
高 `tx failed` 或断流仍需按 MAC、芯片、RSSI、关联/DHCP/DNS 做长稳矩阵，不能只归因
于 HE40。

### 4.4 VLAN、IRQ 与 SQM

- 无 `config bridge-vlan`、`vlan_filtering=1` 或 `lan1:u*` DSA bridge VLAN filtering。
- 使用 802.1q 端口子接口和独立 bridge，符合 NSS Wi-Fi offload 拓扑边界。
- `qca_nss_vlan` 已加载并就绪。
- IRQ affinity 由 qualcommax 上游 `set-irq-affinity` 管理；无重复自定义所有者。
- `sqm-scripts`/CAKE 依赖保留，但 SQM 默认关闭；未见 SQM 与 NSS qdisc 同时运行。

### 4.5 ZeroTier、OpenClash、UPnP、OpenVPN 与 ZRAM

| 服务 | 当前状态 | 未关闭边界 |
|---|---|---|
| ZeroTier | 1.16.2 ONLINE；接口和 managed address 一致；input/forward/srcnat include 与 daemon 端口一致 | 高速 UDP receive drops 尚未证明归零 |
| OpenClash | core 运行；7874 DNS 直探正常；dnsmasq redirect 正确；ZT 动态端口 bypass 正确 | overlay 重复 core 约 10.5 MiB；Geo 数据约 39 MiB |
| UPnP | 显式关闭，无活动映射 | 若未来启用必须做受控 WAN/LAN 映射测试 |
| OpenVPN | 关闭/未安装，无接口、进程、监听、WAN rule 或残留 forwarding | 当前符合用户策略 |
| ZRAM | 256 MiB、zstd、active | 尚未做内存压力/OOM/CPU 开销测试 |

OpenClash 修复边界保持不变：不修改订阅文件和覆写，不关闭 GeoIP/GeoSite/GeoASN/CHNR
自动更新。空间采用监控而不是“小空间仓库配置”。

## 5. 性能与吞吐测试

### 5.1 TCP LAN-LAN 矩阵

18 个阶段：P1/P4，forward/reverse/bidir，各 3 轮，每轮 20 秒。

| 模式 | Mac 到 Windows | Windows 到 Mac | 重传 |
|---|---:|---:|---|
| P1 forward | 946.1-947.9 Mbps | 不适用 | 0 |
| P1 reverse | 不适用 | 949.0-949.1 Mbps | 0 |
| P1 bidir | 341.8 / 489.6 / 483.4 Mbps | 946.4-947.3 Mbps | 405 / 0 / 0 对 0 |
| P4 forward | 947.8-947.9 Mbps | 不适用 | 149-241 |
| P4 reverse | 不适用 | 949.0-949.1 Mbps | 0 |
| P4 bidir | 351.7 / 366.1 / 158.6 Mbps | 944.5-947.0 Mbps | 733 / 731 / 4898 对 0 |

最差 P4 双向轮次中，Mac 到 Windows 方向从约 715 Mbps 下降，在第 8-12 秒出现接近
0 Mbps 和集中重传，随后恢复；Windows 到 Mac 同期保持约 945-950 Mbps。

### 5.2 路由器本机对照

| 模式 | AX6 到 Windows | Windows 到 AX6 | 重传 |
|---|---:|---:|---:|
| P1 forward | 900.2-916.7 Mbps | 不适用 | 0 |
| P1 reverse | 不适用 | 944.5-949.1 Mbps | 0 |
| P1 bidir | 123.5 / 217.0 / 472.9 Mbps | 935.8-947.9 Mbps | 0/0 |

路由器本机与 Mac 的发送路径不同，但双向低速仍跟随 Windows 接收方向。因此当前最强
推断是端点接收栈/NIC/驱动背压，不是只坏 `lan1`、Mac 发送口或某一条 NSS 转发路径。
这仍是推断，不是最终根因。

### 5.3 UDP 单向矩阵

| 方向 | 300 Mbps | 600 Mbps | 900 Mbps |
|---|---:|---:|---:|
| Mac 到 Windows | 0.05%-0.18% loss | 0.53%-0.66% loss | 1.07%-3.49% loss |
| Windows 到 Mac | 0% loss | 0% loss | 0%-0.089%，实际约 890 Mbps |

Windows iperf3 双向 UDP 首轮报
`unable to read from stream socket: Resource temporarily unavailable`。测试按 fail-fast 停止，
没有盲目重跑，也没有把工具/端点错误归给 AX6。

一次性 UDP 脚本的阶段快照用了错误 EDMA 路径，这些阶段的 EDMA 数据应解释为“未
采样”，不是“为 0”。本轮已使用正确路径补采末态，并修复仓库旧 perf 工具。

### 5.4 延迟、PAUSE 与负载期计数

- TCP 阶段 ping 平均约 0.97-1.77 ms，最大约 2.1-3.8 ms。
- PAUSE 探针中 `lan1 rx_pause +32`、`lan2 tx_pause +45`。
- 同一窗口 overflow/underrun/error/drop 均无增长。
- PAUSE 计数说明存在背压，但不能区分它是原因还是 Windows 接收压力的结果。
- 不应直接把 ECM `disable_flow_control=1` 作为修复。

## 6. 性能证据索引和完整性

| 目录 | 内容 | `SHA256SUMS.txt` 的 SHA256 |
|---|---|---|
| `/private/tmp/ax6-perf-lanlan-20260812-212427` | TCP 18 阶段、前后快照、ping、JSON、汇总 | `c8159db2b2591d7421250bceb0b5bd4c0160249de944f327f8cb542608678cb0` |
| `/private/tmp/ax6-perf-router-host-20260812-213312` | 路由器本机对照 9 阶段 | `7c6a1ba56e384bdbd12d2a3a73581acada3702bbb666bbd53df5a6867b17fd97` |
| `/private/tmp/ax6-perf-lanlan-udp-20260812-213554` | UDP 单向 12 阶段、双向失败证据、正确 EDMA 末态 | `086ab20c3804b9bf41cc5b675055ee480c72e2b6ee84263f49a3db007c1df6a4` |
| `/private/tmp/ax6-pause-probe-20260812-214053` | PAUSE/MIB 前后快照和双向结果 | `873b75b8b84868bc9212fd310d5f2b479a818db57841856c4bae2b8a3e0e6338` |

四套证据已再次执行 `shasum -a 256 -c SHA256SUMS.txt`，全部通过。`/private/tmp` 是易失
位置，备用归档必须复制原始 JSON/快照和校验清单，不能只复制本文。

## 7. Qualcomm 官方驱动交叉验证

### 7.1 当前锁定

| 组件 | 当前锁定 | 2026-08-12 官方分支 | 结论 |
|---|---|---|---|
| qca-nss-dp | `d8f802f08fd8ff31057ba58edb20bbe448e7b505` | `win.nss.1.1`/`.r35` 同值 | 保持 |
| qca-ssdk | `d9a196497ecee2530722d906e0efe1b7408b6ef6` | `win.nss.1.1`/`.r35` 同值 | 保持 |
| qca-nss-drv | `6aa14c78e097b29c493ff2fef87e4d35906b2b5a` | `win.nss.1.1`/`.r35` 同值 | 保持 |
| qca-nss-ecm | `8c7355bf80db40c0a52e1620518d521423dfd7a4` | 通用 `fafe228...`；`.r35` 同当前 | 保持 `.r35`，禁止误降级 |

官方仓库：

- <https://git.codelinaro.org/clo/qsdk/oss/lklm/nss-dp>
- <https://git.codelinaro.org/clo/qsdk/oss/lklm/qca-ssdk>
- <https://git.codelinaro.org/clo/qsdk/oss/lklm/nss-drv>
- <https://git.codelinaro.org/clo/qsdk/oss/lklm/qca-nss-ecm>

### 7.2 PAUSE/flow-control 代码逻辑

- qca-nss-dp `nss_dp_get_pauseparam()` 返回 `dp_priv->pause` 请求值。
- `nss_dp_set_pauseparam()` 修改 PHY Pause/Asym_Pause advertisement 并调用
  `genphy_config_aneg()`，可能触发重新协商。
- SSDK `qca_hppe_mac_sw_sync_task()` 读取 PHY 实际 `tx_flowctrl/rx_flowctrl`，在非 force
  mode 下同步至 MAC。
- EDMA v1 的 `edma_if_pause_on_off()` 仍是返回成功的空实现。

因此 `ethtool -a` requested RX/TX=off 与 negotiated RX/TX=on 可以同时存在，不是单凭
输出即可确认的驱动冲突。

## 8. 上游仓库状态和处理决定

| 仓库/分支 | 精确 HEAD | 当前相关性 | 决定 |
|---|---|---|---|
| qosmio/openwrt-ipq `main-nss` | `92a2d104145c8d265851c4b388a41bd8e9c21cd9` | Linux 6.12.92 NSS patch rebase | 不移植为 6.18 吞吐修复 |
| VIKINGYFY/immortalwrt `main` | `de810bc8e2ce6cdaf9b791b231c49aa8804cac11` | TL-ER2260T/IPQ60xx/设备镜像和 firmware 默认 | 不整提交合并到 AX6 |
| immortalwrt/immortalwrt `master` | `bf1f49d07a93125882e50c4f33ca6b6a38c024dc` | 官方源合并，主要为 Airoha/mbedtls/其他平台 | 与本症状分离 |
| openwrt/qca-nss-dp `openwrt` | `6a5c4716ca258d67202fc7964c9294dfefa3ccfa` | ethtool string API 清理；EDMA v2 PPEDS 修复 | 可作独立兼容候选，不是 AX6 EDMA v1 性能修复 |

qosmio 的适配约束继续作为门禁：NSS 下关闭通用 packet steering 和 OpenWrt software/
hardware flow offload；不使用 DSA bridge VLAN filtering；AP_VLAN 保持不支持；NSS firmware
12.5 只按 AP/STA 基线，不强行宣称 WDS/Mesh 支持。

禁止整分支 merge。任何候选必须从共同基点按单个文件、设备、内核 API、数据路径和
回退边界审查。

## 9. 全部问题状态汇总

完整逐项表位于 `AX6_COMPLETE_ERROR_STATUS_MATRIX_2026-08-12.md`。当前 75 个故障/风险
条目分布为：

| 状态 | 数量 | 说明 |
|---|---:|---|
| A 已闭环 | 32 | 修复与既有门禁/实机证据达到当前关闭条件 |
| B 已修待验证 | 6 | 已进入源码候选，尚缺本轮云端构建/产物/新固件实机 |
| C 部分修复 | 3 | 风险已降低或方向已缩小，但用户现象/完整根因未关闭 |
| D 未修 | 14 | 4 个产品/仓库问题，另含 10 个无法补救的旧证据错误 |
| E 未验证/阻塞 | 16 | 缺端点、维护窗口、故障注入、构建或长稳数据 |
| N 非故障/拒绝项 | 4 | 正常行为或不适用于 AX6，不应据此修改 |

### 9.1 已修待验证的 6 项

| ID | 修复 | 当前缺口 |
|---|---|---|
| K-01 | hwspinlock regmap 上限 clamp 和小资源 guard | 完整内核/DTB 构建、新固件实机；旧固件仍禁止危险 debugfs |
| K-02 | APCS regmap 改为 clamp，避免扩大其他 SoC 范围 | 完整构建和启动验证 |
| K-03 | PBUF 精确写入、readback、有限重试、失败传播 | 构建和十轮物理冷启动 |
| K-04 | NSS current_freq/auto_scale 初始化边界保护 | qca-nss-drv 编译、冷启动和日志回归 |
| K-05 | ECM multicast 负接口计数有符号类型修复 | ECM 编译和 IPv4/IPv6 multicast 实机回归 |
| K-06 | NSS 启动 sysctl 精确 readback | 新固件真实 readback 和启动日志 |

### 9.2 部分修复的 3 项

| ID | 当前状态 | 关闭条件 |
|---|---|---|
| K-09 | EDMA 多 ring store 风险以 1/1/1/1 门禁限制 | 完成 store 模型重构前不得扩大 ring 数 |
| N-08 | ZeroTier 4 MiB socket buffer 补丁已进入 prepared-source 门禁 | 新固件逐 socket UDP 压测证明 drops 不增长 |
| W-05 | 双向异常定位到 Windows 接收方向高疑 | Windows NIC 单变量 A/B、端口互换、第二 Linux 端点复测 |

### 9.3 当前产品/仓库明确未修的 4 项

| ID | 问题 | 影响/边界 |
|---|---|---|
| K-07 | EDMA portable DMA 仍依赖 identity-DMA/`phys_to_virt(dma_addr)` | AX6 当前门禁降低风险；跨平台需 Track B 重构 |
| K-08 | EDMA invalid store index 可能跳过 descriptor 清理 | 需 counter/warning、skb/DMA 清理模型和故障注入 |
| K-12 | 读取全量 `dev.nss` 产生 warn/alert 级调试打印 | 不影响数据面；仅定向降低日志级别 |
| O-07 | OpenClash overlay core 与 ROM 重复约 10.5 MiB | 只在干净刷写/离线维护清理，不在线删除 upperdir |

### 9.4 重点未验证或阻塞项

- K-10：`phy_connect()` 失败和 error-pointer teardown 故障注入。
- K-11：NSS netlink 精确 GENL admin handler 权限验证。
- K-16：EDMA alloc_fail 72 小时同负载增量窗口。
- N-13：LAN 累计 drop 的长窗口差分。
- N-14：EasyRSA orphan certificate 用途追溯。
- O-11/O-12/O-13：本轮云端构建、DTB、rootfs、kmod、manifest、SHA256 产物。
- W-03：IoT legacy/HT/HE 关联、DHCP、DNS 和长稳矩阵。
- W-04：5G invalid REO 与用户可见断流的时间关联。
- W-06：真实 WAN-LAN/NAT/NSS routed 双向吞吐。
- W-07：NSS 中频/高频单变量 routed A/B。
- W-08：split-NAPI 独立候选，当前不得合入主线。
- T-13/T-22：旧 UDP 非单调结果和 Windows 双向 UDP 工具错误重测。

### 9.5 明确非故障或拒绝项

- 2.4G HE40 在 coexistence 下运行 HE20 是正常行为。
- Geo 自动更新按用户要求保留，不做小空间仓库配置。
- AP_VLAN 在当前 ath11k NSS 路径不宣称支持。
- NSS firmware 12.5 的 WDS/Mesh 不在当前验证基线。

## 10. 已完成的仓库修复类别

- NSS 与 OpenWrt flow offload/packet steering 冲突门禁。
- ECM host-terminated offload 策略和 br-lan 保护。
- RPS/RFS/XPS 恢复并由 qualcommax 单一 IRQ 策略管理。
- VLAN 802.1q 子接口、独立 bridge、firewall/DHCP/回滚完整创建。
- ZeroTier L3 reconcile、restart 二次判定、secondaryPort/fw4 动态规则。
- OpenClash DNS 直探、三次失败/冷却恢复和单一 DNS owner 合同。
- OpenVPN 禁用残留的精确清理。
- ZRAM 包、默认配置、启动链和审计。
- OpenClash provenance、Meta core 架构/哈希、设备 manifest 与 rootfs 包清单门禁。
- cgi-io 官方安全修复定向回移。
- 构建 source lock、patchset SHA、fail-fast、stock layout 和备份/恢复门禁。
- hwspinlock/APCS/PBUF/NSS 初始化/ECM multicast 当前候选修复。
- 性能工具 fail-fast、独立 run、严格 SSH 身份、正确 EDMA 路径和 fixtures。

## 11. 本轮验证结果

### 11.1 已通过

- ShellCheck error 级全仓脚本检查。
- `test-ax6-routed-perf-fixture.sh`。
- `test-ax6-nss-frequency-ab.sh`。
- `test-ax6-perf-fixture.sh`：23/23。
- VLAN、OpenVPN defaults、OpenClash DNS/archive/runtime/ROM core/keep。
- ZeroTier fw4/reconcile/health/buffer、OpenClash-ZeroTier bypass。
- router backup、device manifest、cgi-io backport、boot guard。
- PBUF、NSS monitor、source patchset、reload matrix、UDP baseline fixtures。
- 四套性能证据 SHA256 全量校验。
- 修正后 NSS frequency 工具使用严格 known_hosts 对实机只读 `status`，boot ID 和频率
  与基线一致。

### 11.2 本机未执行

| 门禁 | 原因 | 正确解释 |
|---|---|---|
| compiled DTB fixture | 本机缺 `dtc`，返回 69 | 未执行，不是失败，也不能标为通过 |
| actionlint | 本机未安装 | 本轮未改 workflow；CI 仍必须执行 |
| yamllint | 本机未安装 | 本轮未改 YAML；CI 仍必须执行 |

## 12. 后续修复和测试顺序

### 阶段 A：Windows 接收方向单变量 A/B

1. 导出 Windows NIC 型号、硬件 ID、驱动/固件版本、PCIe link、RSS 队列和高级属性。
2. A/B EEE/Green Ethernet，三轮 P1/P4 bidir，随后恢复。
3. A/B Flow Control Auto/Disabled，三轮复测，随后恢复。
4. 分别 A/B RSS、RSC、LSO、checksum offload、interrupt moderation；禁止组合修改。
5. 交换 Mac/Windows 的 lan1/lan2 端口和网线。
6. 使用第二台 Linux/macOS 有线端点，或同一 Windows 硬件临时启动 Linux。

验收：单向两边 >=930 Mbps；双向每方向 >=850 Mbps，三轮差异 <=10%；无集中重传；
AX6 接口/softnet/qdisc/EDMA 活动错误增量为 0。

### 阶段 B：必要时临时验证物理 PAUSE

只有阶段 A 排除端点后执行，并需用户再次授权维护窗口：

1. 保存 lan1/lan2 `ethtool -a/-k/-S` 和 SSDK MIB。
2. 显式临时调整两个端口 advertisement，不改 UCI，不重启 ECM。
3. 确认重新协商回 1 Gbps full，再跑固定矩阵。
4. 无稳定三轮收益或出现 drop/overflow，立即恢复并否决。

### 阶段 C：真实 WAN-LAN/NSS routed 验证

1. 在 WAN 上游 `192.168.1.0/24` 添加独立 iperf3 server。
2. preflight 必须证明路由经过 AX6 `wan`，拒绝同 LAN 路径。
3. 记录 ECM connection delta、wan/lan MIB、EDMA、softnet、CPU、NSS 频率和温度。
4. TCP P1/P4 forward/reverse/bidir 各 3 轮。
5. UDP 300/600/900 Mbps 随机顺序各 3 轮。
6. 只有 egress=wan 且 ECM/NSS 计数匹配才可写为 routed offload 结果。

### 阶段 D：候选分支构建

1. 推送源码 `3854ea2...` 和构建 `3fd06da` 两个独立分支。
2. 仅触发一次 stock 构建；失败读取准确日志，不盲目重跑。
3. 检查 source lock、202 present/15 absent、NSS/ECM/EDMA/ath11k、DTB。
4. 下载并独立核对 sysupgrade、recovery/initramfs、kmod、manifest、rootfs、OpenClash
   provenance 和全部 SHA256。
5. 只对通过离线审计的镜像执行 `sysupgrade -T`；不自动刷写。

### 阶段 E：授权后的新固件实机验收

- 不保留配置刷写需要用户单独确认；先验证备份和回退镜像。
- 冷启动十轮：PBUF/NSS/ath11k/pstore/频率/服务状态逐轮记录。
- reload matrix 每场景严格 20/20。
- ECM multicast IPv4/IPv6、IGMP/MLD、bridge MDB 回归。
- 24 小时压力和 72 小时正常业务，观察 alloc_fail、内存、DNS、ZeroTier 和 Wi-Fi。
- recovery 和回退演练需要独立维护窗口。

## 13. 禁止的错误修复和操作红线

1. 禁止递归读取路由器 debugfs。
2. 禁止读取 `/sys/kernel/debug/regmap/1905000.hwlock/registers`；当前实机旧固件仍可能
   因包含式 0x20000 上限越界 panic。
3. 不把 LAN-LAN 二层结果写成 WAN-LAN/NAT/NSS routed 结果。
4. 不把累计 drop/alloc_fail 单点值当作本轮活动故障。
5. 不因 requested/negotiated PAUSE 不同就默认关闭流控。
6. 不把 Windows 接收方向异常直接归因于 NSS/EDMA/SSDK。
7. 不整分支 merge qosmio、VIKINGYFY、ImmortalWrt 或 CodeLinaro 新产品线。
8. 不同时修改 split-NAPI、GRO、IRQ、NSS frequency、PAUSE 和内核版本。
9. 不开启 OpenWrt software/hardware flow offload 或通用 packet steering 与 NSS 并行。
10. 不启用 DSA bridge VLAN filtering 破坏 NSS Wi-Fi offload 拓扑。
11. 不修改 OpenClash 订阅/覆写，不关闭 Geo 自动更新。
12. 不在线删除 OpenClash overlay upperdir core。
13. 不恢复路由器登录密码；密码由用户手动设置。
14. 不自动刷写、重启、恢复配置、合并主线、tag 或发布 Release。

## 14. 当前发布门禁

以下任一未完成，禁止主线合并和发布：

- 当前候选分支推送和唯一一次 stock CI；
- compiled DTB、kernel、rootfs、kmod、manifest、OpenClash provenance、SHA256 审计；
- `sysupgrade -T`；
- 新固件十轮冷启动；
- reload matrix 80 次；
- routed WAN-LAN 吞吐；
- Windows/第二端点双向异常关闭或明确记录为端点问题；
- ECM multicast 回归；
- 24/72 小时稳定性；
- recovery/回退演练。

## 15. 最终状态

当前 AX6 在已测试的 LAN-LAN 单向、核心驱动运行、服务合同和配置门禁上没有发现活动
严重故障；本轮也没有证据要求回滚 VLAN、RPS、OpenClash DNS、ZeroTier L3、OpenVPN、
flow-offload 或构建 provenance 修复。

但系统不能被描述为“已经完全无问题”：

- 双向吞吐的 Windows 接收方向异常尚未关闭；
- 真实 WAN-LAN/NAT/NSS routed 性能尚未测试；
- 6 项候选修复尚未完成构建和新固件实机验证；
- EDMA portable DMA、invalid store、NSS 日志级别和重复 overlay core 仍未修；
- ZeroTier 高速 UDP、IoT、invalid REO、冷启动/reload/长稳/recovery 仍有验证缺口。

下一步必须按本文阶段 A-E 顺序推进，不能用新的大范围合并或多变量配置修改代替根因
验证。
