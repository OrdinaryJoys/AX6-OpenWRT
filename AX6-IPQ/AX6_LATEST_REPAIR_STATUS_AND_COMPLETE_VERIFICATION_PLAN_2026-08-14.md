# AX6 最新修复状态与完整检查测试方案（2026-08-14）

## 1. 文档用途与结论边界

本文是截至 2026-08-14 17:31 CST 的主状态备份，统一记录：

- 仓库修复、云端构建和真实产物验收状态；
- 当前实机的只读运行状态；
- 已修复、仍可疑、尚未验证和环境受限项目；
- 后续刷机、恢复、吞吐和性能测试的执行顺序及验收门禁。

当前结论不是“所有故障已经消失”。候选固件已经通过构建、产物和
`sysupgrade -T` 门禁，但当前实机仍运行旧固件，候选修复尚未完成刷后 A/B。
本轮只做只读检查和临时兼容性预检，没有刷写、重启或修改配置。

## 2. 身份与证据锁

| 项目 | 当前事实 |
|---|---|
| 构建仓库 | `OrdinaryJoys/AX6-OpenWRT` |
| 候选分支 | `codex/ax6-runtime-hardening-build-20260814` |
| 最新分支提交 | `3adf2485b169e10fcd3e31e7e6b5451653c12fd8` |
| 固件内容提交 | `d67d4f75f2b8a691d9d0254f82401bfbbc610e6d` |
| 锁定源码提交 | `OrdinaryJoys/immortalwrt-nss@14f713a2a1e623cdd40b0bb50030ad09a2cf6fb0` |
| 锁定源码基线 | `56807d9661dbe7df421d1fd31feba76677b5703d` |
| 成功构建 | GitHub Actions `31779338123` |
| 最新 Lint | `31788237945`，提交 `3adf248`，全部通过 |
| 候选产物目录 | `router-backups/NOT-FLASHED/run31779338123-20260814` |
| 当前实机 | Redmi AX6 stock layout，`redmi,ax6-stock` |
| 当前实机固件 | `ImmortalWrt SNAPSHOT r0-956cf06` |
| 当前内核 | `6.18.38` |
| 当前 Boot ID | `02239d26-7a72-43cb-a2d1-52a752d8f522` |

`2c20098` 只修改吞吐测试工具，`3adf248` 只修改文档；候选固件二进制
仍精确对应 `d67d4f7`，不能把分支 HEAD 当成镜像内容提交。

## 3. 已完成修复与验证

| ID | 修复内容 | 状态与证据 |
|---|---|---|
| F-01 | 阻止危险的整包配置恢复和密码回灌 | `3b27db6`、`9b211af`；恢复逻辑只允许审计后的白名单配置 |
| F-02 | 双向负载同步采集 NSS/PBUF/softnet/IRQ/RPS/XPS/接口/CPU | `8c71164`；已生成有线、Wi-Fi 和 LAN-LAN 实机样本 |
| F-03 | 修复离线 kmod feed 缺 23 个依赖 IPK | `d67d4f7`；新 feed 索引和磁盘均为 166 个 IPK |
| F-04 | 修复 lint 对 helper 重构的错误失败 | `b565969`；云端 Lint 通过 |
| F-05 | 为 probe/TCP/UDP/长时测试增加硬超时、按 PID 清理和阶段冷却 | `2c20098`；挂起样本被拒绝，无伪完成 |
| F-06 | 增加路由器到端点 P1/P4 正向、反向、双向测试 | `2c20098`；有线和 Wi-Fi Mac 各完成 18 个场景 |
| F-07 | 区分 N2H OCM 首选池压力与 default/payload/queue 最终失败 | `2c20098`；OCM-only 为 WARN，最终分配或队列失败仍为 FAIL |
| F-08 | ECM 主机路径和物理数据面分层 | `br-lan` 强制关闭 offload；物理口保持 `report`，不盲目牺牲 NSS 转发性能 |
| F-09 | NSS 与 firewall4/packet steering 所有权冲突防护 | 软件/硬件 flow offload 与 packet steering 均为 0，NSS ECM 是唯一卸载所有者 |
| F-10 | PBUF one-shot 写入、顺序和读回校验 | 候选 1GB 配置为 `10000000/65536/32768`，high-water 最后写入 |
| F-11 | ZeroTier 动态端口/防火墙/OpenClash bypass 对账 | 当前 daemon、接口、地址、nft input/forward/srcnat 与 bypass 全部一致 |
| F-12 | OpenClash DNS 单点健康保护 | 核心 DNS 7874 可直接应答，dnsmasq 指向 7874，健康探测和受控重启已启用 |

性能工具回归结果为 `36 PASS / 0 FAIL`；shellcheck 通过；最新云端 Lint 的
NSS、ECM、Wi-Fi、ZRAM、IRQ、Kconfig、包所有权和 stock 安全门禁全部通过。

## 4. 候选固件真实产物验收

| 检查项 | 结果 |
|---|---|
| sysupgrade SHA256 | PASS |
| recovery initramfs/factory UBI SHA256 | PASS |
| 离线 kmod feed 与压缩包 SHA256 | PASS |
| sysupgrade/recovery BUILD-LOCK | 完全一致 |
| sysupgrade/recovery 设备 manifest | 完全一致 |
| rootfs opkg 与 manifest | 391 个已安装包，逐项一致 |
| kmod `Packages` 与磁盘 IPK | 166/166，无缺件、无孤立 IPK |
| kmod 压缩包 | 171 项，与 feed 文件加校验清单一致 |
| OpenClash 插件 | `0.47.156` |
| OpenClash Meta core | 静态 AArch64 ELF，SHA256 `453066ac9e5045d95d035a96b5c02fb593fdc0427c3c9153ff4d6a4403feab6a` |
| stock 型号兼容性 | 实机 `sysupgrade -T` 返回 0 |

实机预检时，本地和路由器上的镜像 SHA256 都是：

`1be19846a1b13a8eb54934f543694f5e142795b66d4945b71a86f6b7720b1c4f`

预检后临时镜像已从 `/tmp` 删除。没有刷写或重启。

## 5. 最新实机运行状态

### 5.1 核心驱动与资源

| 项目 | 状态 |
|---|---|
| NSS core | 2 个核心启动成功，当前频率 748.8 MHz |
| 核心模块 | `qca_nss_drv/qca_nss_dp/qca_ssdk/ecm` 已加载 |
| Wi-Fi | ath11k 已加载，`nss_offload=1`、`frame_mode=2`、硬件加密 |
| Wi-Fi 固件 | WLAN.HK.2.12-01460-QCAHKSWPL_SILICONZ-1 |
| EDMA | EDMA v1 初始化成功，无当前崩溃或 call trace |
| SKB recycler | 已启用，`2048/1024`，proc 接口存在 |
| ZRAM | 256 MiB、zstd、当前未使用 swap |
| 内存 | 约 916 MiB，总可用约 478 MiB |
| overlay | 39.4 MiB，总使用 15.7 MiB，可用 21.7 MiB |
| softnet dropped | 0 |

当前旧固件 PBUF 为：

- `extra_pbuf_core0=10002432`
- `n2h_high_water_core0=32768`
- `n2h_wifi_pool_buf=32768`
- core0/core1 queue limit 均为 2048

候选固件的 high-water 是 65536，因此 PBUF 修复尚未完成实机 A/B。

### 5.2 配置与服务

- `nss-check -v`：`45 PASS / 5 WARN / 0 FAIL`。
- `ax6-config-audit -v`：`29 PASS / 2 WARN / 0 FAIL`。
- ECM、NSS DP、SSDK 和 ath11k 模块实际运行正常。
- rc.common 对 ECM/SKB recycler 显示无常驻进程，不代表模块停止；必须以内核模块、
  debugfs/proc 和计数器为准。
- OpenClash 核心进程运行，DNS 7874 可直接应答。
- ZeroTier `1.16.2 ONLINE`，网络状态 `OK PRIVATE`。
- UPnP 关闭；OpenVPN 关闭且没有残留进程、接口、监听或 WAN 规则。
- SQM/CAKE/IFB/NSS qdisc 已安装，但 `sqm.eth1.enabled=0`，当前不与 NSS 争用。
- 2.4 GHz HE40/HE20 coexistence 安全；国家码为 US。
- 当前无 DSA bridge VLAN filtering；现有 802.1q 子接口路径由 NSS VLAN 模块支持。

### 5.3 当前告警而非确定故障

| 告警 | 解释与处置边界 |
|---|---|
| 物理 wan/lan1/lan2/lan3 offload 为 on | 属于 `report-only` 数据面策略；在没有合格端点 A/B 前不批量关闭 |
| PBUF split 为 32768/32768 | 当前旧固件的已知状态；候选 65536/32768 必须刷后复测 |
| OpenClash geo 数据表观占用约 39 MiB | 自动更新按用户要求保留；更新前后必须监控 overlay，不通过删除订阅/覆写解决 |
| lan1 累计 `rx_errors=1/rx_dropped=85/tx_dropped=5` | 是启动以来累计值；softnet 为 0，需用负载前后增量判断，不能直接定性驱动故障 |
| N2H OCM 首选池历史压力 | default/payload/queue 没有同步增长时为 WARN；仍需全阶段同步采样定位 |

## 6. 尚未闭合的问题

| ID | 优先级 | 状态 | 问题与当前边界 |
|---|---|---|---|
| R-01 | P0 | 确定异常、根因未定 | 路由器到 Wi-Fi Mac 双向时下行约 14-36 Mbit/s，上行约 597-959 Mbit/s |
| R-02 | P0 | 环境故障高度可疑 | Windows AX88179 接收方向持续负载后退化；当前不能归因 AX6 |
| R-03 | P1 | 待复测 | 有线 Mac 到路由器 P4 双向存在较多 TCP 重传 |
| R-04 | P1 | 待新固件验证 | 候选 PBUF high-water=65536 的实际效果和副作用 |
| R-05 | P1 | 未执行 | Windows USB Wi-Fi 网卡没有关联 AP，缺芯片、驱动、IP、MAC 身份 |
| R-06 | P1 | 未执行 | 合格 Wi-Fi 客户端到有线端点的转发吞吐与空口公平性 |
| R-07 | P2 | 未执行 | WAN-LAN NAT/ECM/NSS routed 双向吞吐，缺独立 WAN 端点 |
| R-08 | P2 | 容量风险 | OpenClash geo 自动更新可能重新填满 overlay |

当前 Windows `192.168.5.111` 是 AX88179 USB3 有线端点，不在 AP station 表中。
不能把已有 AX88179 结果写成 Windows USB Wi-Fi 测试。

## 7. 下一阶段完整执行方案

### 阶段 A：Windows USB Wi-Fi 端点资格门禁

连接 Windows USB Wi-Fi 后先记录：

1. USB Wi-Fi 芯片、USB VID/PID、厂商和型号。
2. Windows 驱动提供者、版本、日期和电源管理状态。
3. Wi-Fi MAC、IPv4、SSID/BSSID、频段、信道、带宽、协议和协商速率。
4. iperf3 版本、监听端口和 Windows 防火墙规则。
5. 禁用 AX88179 或拔出有线网卡，确认路由邻居表和 station 表只指向 USB Wi-Fi。

推荐采集命令：

```powershell
Get-NetAdapter | Format-Table Name, InterfaceDescription, Status, LinkSpeed, MacAddress
Get-NetAdapterAdvancedProperty -Name "<Wi-Fi adapter name>"
Get-NetIPConfiguration -InterfaceAlias "<Wi-Fi adapter name>"
Get-PnpDevice -Class Net
netsh wlan show interfaces
```

任何身份缺失、双路径并存、端点 CPU/DPC 饱和或 iperf JSON 不完整，都标记为
`ENV-BLOCKED`，不得判给 AX6。

### 阶段 B：USB Wi-Fi 核心测试矩阵

拓扑必须分别执行：

1. 路由器 ↔ Windows USB Wi-Fi：验证 ath11k/NSS 主机终结路径。
2. 有线 Mac ↔ Windows USB Wi-Fi：验证 Wi-Fi 到 LAN 的 NSS 转发路径。
3. Wi-Fi Mac ↔ Windows USB Wi-Fi：验证同 AP 无线客户端间转发和公平性。
4. 路由器 ↔ Wi-Fi Mac：复现既有极端双向不公平作为对照。

每个拓扑执行：

- TCP P1/P4 正向、反向、双向，各 30 秒、3 轮；
- UDP 300/600/900 Mbit/s 正反向，各 3 轮；
- 短矩阵通过后再执行 P4 双向 600 秒耐久；
- 阶段间冷却，所有进程按 PID 清理，超时必须为 `INCOMPLETE`。

同步采样必须包含：

- boot ID、固件/源码/构建身份；
- PBUF profile 和 N2H OCM/default/payload/queue；
- EDMA/PPE/ECM、接口 errors/drops；
- softnet dropped/time_squeeze；
- IRQ、RPS/RFS/XPS、CPU 和内存；
- ath11k peer/TID、TX completion、RX reorder、queue stop/wake 和 airtime；
- 端点 CPU、驱动、USB 状态、TCP 重传和 UDP 丢包。

### 阶段 C：候选固件刷写门禁

刷写前必须同时满足：

1. 当前备份可读取且 SHA256 正确。
2. 不恢复路由器登录密码。
3. 禁止整包恢复 `/etc/config`、overlay 或 `sysupgrade -b` 全量归档。
4. 只恢复审计后的网络、无线、OpenClash、ZeroTier 和必要身份文件。
5. 候选镜像仍与 BUILD-LOCK 和已验收 SHA256 一致。
6. 再次获得用户明确确认后才允许刷写。

### 阶段 D：刷后基础验收

全新刷写、不保留配置后，先验证：

1. 型号、stock layout、内核、固件、源码和构建提交全部匹配。
2. NSS 两核、EDMA、SSDK、ECM、ath11k 和 NSS Wi-Fi offload 正常。
3. PBUF 精确读回 `extra=10002432/high=65536/wifi=32768`。
4. software/hardware flow offload 与 packet steering 仍为 0。
5. `br-lan/report` ECM 策略完整；SQM 仍关闭。
6. `nss-check -v` 和 `ax6-config-audit -v` 均为 0 FAIL。
7. OpenClash DNS、ZeroTier、UPnP、ZRAM、IRQ/RPS、VLAN 和 Wi-Fi 恢复后逐项通过。

基础验收失败时停止恢复和性能测试，不用额外补丁掩盖身份或驱动错误。

### 阶段 E：旧固件与候选固件 A/B

使用完全相同的端点、线缆、端口、无线信道、脚本和时间契约复测阶段 B。
重点比较：

- Wi-Fi 双向方向公平性；
- P4 TCP 重传和 UDP 丢包；
- OCM/default/payload/queue 增量；
- lan1/lan2 接口错误增量；
- softnet、IRQ 和 CPU 峰值；
- 600 秒耐久是否出现持续退化。

只有候选固件在合格端点上重复通过，才能把 PBUF/驱动修复标记为“实机完成”。

### 阶段 F：物理端口 offload 定点 A/B

仅当端点资格和基线稳定后进行：

1. 一次只改变一个物理端口或一个 offload 特性。
2. 仅临时修改，记录修改前值和自动回滚命令。
3. 同步抓取 TCP checksum、重传、接口错误、NSS/ECM/PBUF 和吞吐。
4. 没有可重复改善就保持仓库当前 `report-only` 策略。

不得根据“IPQ807x 没有硬件校验和”这一句话直接批量关闭全部物理 offload；
Linux 软件 GRO/GSO 与 NSS 数据面必须通过实际 A/B 区分。

### 阶段 G：WAN-LAN routed 验证

增加独立 WAN 侧 Linux/iperf3 端点后，执行 NAT、桥接、VLAN、TCP/UDP 和双向
矩阵，核对 ECM accelerated connection、PPE/NSS 计数和 CPU。LAN-LAN 或
路由器本机测试不能替代 WAN-LAN。

## 8. 最终验收标准

只有同时满足以下条件，才允许声明“修复完成”：

1. 仓库 Lint、完整 stock build、真实 artifact、manifest、rootfs、kmod feed、
   SHA256 和 `sysupgrade -T` 全部通过。
2. 刷后实机身份与 BUILD-LOCK 一致，PBUF 读回精确。
3. 核心驱动无 crash、oops、call trace 或负载相关错误增长。
4. 合格端点所有短矩阵无超时、空 JSON、缺轮次或 boot ID 变化。
5. 600 秒双向耐久没有持续单侧饥饿、异常重传或计数器硬失败。
6. ZeroTier、OpenClash DNS、Wi-Fi、VLAN、ZRAM 和 IRQ/RPS 均通过运行审计。
7. Windows AX88179 环境故障与 AX6 故障已经通过替代端点隔离。
8. 尚未执行的 Windows USB Wi-Fi 和 WAN-LAN 项不得写成已验证。

## 9. 证据索引

- 详细吞吐与构建记录：
  `AX6-IPQ/AX6_THROUGHPUT_REPAIR_STATUS_AND_TEST_PLAN_2026-08-14.md`
- 清洁刷写与恢复边界：
  `AX6-IPQ/AX6_CLEAN_FLASH_RESTORE_SAFETY_2026-08-14.md`
- 顺序修复记录：
  `AX6-IPQ/AX6_SEQUENTIAL_REPAIR_STATUS_2026-08-14.md`
- 原始性能样本：
  `router-backups/perf-runs/`
- 已验收但未刷写产物：
  `router-backups/NOT-FLASHED/run31779338123-20260814/`

本文档不包含订阅内容、ZeroTier secret、SSH 私钥或登录密码。
