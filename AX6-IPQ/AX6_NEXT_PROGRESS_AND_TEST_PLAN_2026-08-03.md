# AX6 下一步进度与检查测试方案（2026-08-03）

## 1. 目标和执行边界

下一阶段目标不是继续堆叠补丁，而是分别关闭以下证据缺口：

1. APCS regmap debugfs 越界 panic 的源码级修复和构建验证。
2. 系统 UDP `RcvbufErrors` 峰值的 socket 级归因。
3. ZeroTier 高速上行 receive-drop 的控制面、socket、调度和网络路径边界。
4. TCP 双向、UDP 转发、burst、bufferbloat 和长稳测试的完整证据链。
5. Wi-Fi IoT、OpenClash 空间、VLAN、UPnP 和服务恢复的最终回归。

执行规则：

- 默认只读检查，不修改实机持久配置。
- 不刷写、不重启、不重载网络/防火墙/OpenClash/ZeroTier，除非用户单独确认。
- 不读取整个 `/sys/kernel/debug`，只访问仓库白名单中的精确节点。
- 每次只验证一个变量；禁止同时改 IRQ、PAUSE、ECM、SQM、Wi-Fi 和 socket 参数。
- 所有源码修复先进入独立 `codex/` 分支，完成 lint、完整 stock 构建和产物审查。
- 失败后先保存原始日志和差分，不盲目重跑。

## 2. 当前进度基线

| 工作流 | 状态 | 完成度 | 下一关闭条件 |
|---|---|---:|---|
| 仓库 lint/stock 构建 | 已完成 | 100% | 当前 HEAD 84fc0f2 已通过，不代表后续 APCS 提交通过 |
| 新固件刷写与基础恢复 | 已完成 | 100% | 版本、认证、配置和服务已核对 |
| 核心驱动基础审计 | 已完成 | 100% | NSS/ECM/SSDK/EDMA/ath11k 当前健康 |
| TCP 单流 25 分钟 | 已完成 | 100% | 938 Mbps、3 retrans、驱动错误不增长 |
| TCP 双向 20 分钟 | 部分完成 | 86% | 1033/1200 秒，797/778 Mbps，需无外部终止完整复测 |
| UDP socket 归因 | 未完成 | 20% | 已知峰值和停止状态，缺少存活 socket inode |
| ZeroTier 高上行 | 未完成 | 40% | 基础健康通过，高速 receive-drop 未关闭 |
| UDP 转发/P3/P4 | 未开始 | 0% | 旧脚本未执行这些阶段 |
| APCS 内核修复 | 未开始 | 10% | 根因已定位，代码/构建尚无 |
| 24/72 小时长稳 | 未开始 | 0% | 所有 P0/P1 测试通过后启动 |

## 3. 阶段 0：冻结证据和修复测试框架

优先级：P0（测试正确性）。本阶段只修改仓库测试脚本和文档，不操作路由配置。

### 3.1 新测试脚本要求

新建仓库脚本时必须具备：

1. `trap` 捕获 `EXIT INT TERM HUP`，记录信号、阶段、时间和退出码。
2. 每阶段写入唯一 `phase_id`、客户端 PID、路由端 server PID/端口和 boot ID。
3. 测试前后分别采集：
   - `/proc/net/snmp` 的 UDP InErrors/RcvbufErrors。
   - `/proc/net/udp`、`/proc/net/udp6` 的 inode、rx_queue、drops。
   - ZeroTier PID/fd socket inode映射。
   - Clash 7874/7895 socket inode和 drops。
   - 临时 iperf UDP socket inode和 drops。
   - EDMA 精确 `err_stats`、softnet、端口 errors/drops。
   - `nss-check -q`、`ax6-config-audit -q` 和 boot ID。
4. 用 source revision 和 build repo commit 两个字段，禁止再写合成 revision。
5. 阶段失败后输出 `INCOMPLETE`，不得继续打印 `COMPLETE`。
6. 只清理脚本自己创建并记录 PID 的进程，不使用宽泛 `killall iperf3`。
7. 使用独立端口，避免与其他终端或历史 server 混用。

### 3.2 静态测试

- `sh -n`/`bash -n` 通过。
- ShellCheck 通过。
- 使用 fixture 验证正常退出、SIGTERM、SSH 失败、boot ID 改变和 socket 消失。
- 验证任何阶段失败都会保留原始日志并停止后续阶段。
- 仓库 lint 不允许出现递归 `/sys/kernel/debug` 内容读取。

通过门槛：测试脚本可在本地 fixture 中可靠生成 PASS/FAIL/INCOMPLETE，且不需要
改动路由器配置。未通过前禁止重跑完整压力测试。

## 4. 阶段 1：APCS regmap P0 源码修复

建议独立分支：

- 源码：`codex/ax6-apcs-regmap-boundary-20260803`
- 构建：`codex/ax6-apcs-regmap-build-validation-20260803`

### 4.1 修复原则

当前驱动用一个全局 regmap 配置服务多个 SoC。IPQ8074/IPQ6018 资源是
`0x1000`，SDX55 需要 `0x1008`。候选修复必须让 `max_register` 与具体 SoC
和实际 resource size 匹配，不能简单全局改回 `0xffc` 而破坏 SDX55。

优先方案：

1. 在 `qcom_apcs_ipc_data` 中增加每 SoC 的最大寄存器范围，或在 probe 中复制
   `regmap_config` 并以 `min(SoC max, resource_size - reg_stride)` 限制。
2. 验证 `apcs_data->offset <= max_register`。
3. IPQ8074/IPQ6018 保持 offset=8，SDX55 保持 offset=0x1008。
4. 审查 clock child 是否独立映射资源，避免 regmap 范围调整影响时钟驱动。

不得采用：

- 删除 debugfs 以掩盖驱动资源范围错误。
- 只在 AX6 DTS 扩大 MMIO resource，越界映射未知寄存器区域。
- 在实机再次读取危险 registers 节点确认“是否还会崩”。

### 4.2 验证顺序

1. 对比 Linux 主线、锁定 ImmortalWRT、VIKINGYFY 和 qosmio 对应驱动。
2. 编写静态测试覆盖 IPQ8074、IPQ6018、SDX55 的 offset/resource/max 关系。
3. `git diff --check`、目标文件编译和相关内核包编译通过。
4. 完整 AX6 stock 构建通过。
5. 检查 DTB、kernel、rootfs、kmod、manifest、SHA256 和 BUILD-LOCK。
6. 只做离线代码和产物验证；不刷写、不发布、不合并主分支。

通过门槛：所有 SoC 的合法 mailbox offset 可访问，任何 debugfs 最大范围不超过
实际 resource；AX6 完整构建和现有 NSS/Wi-Fi 门禁全部通过。

## 5. 阶段 2：UDP RcvbufErrors 定点归因

本阶段先测试，不改变 socket buffer、sysctl、IRQ 或服务配置。

### 5.1 基线

连续 60 秒无主动压力，10 秒采样一次：

- UDP RcvbufErrors/InErrors 差分应为 0。
- ZeroTier 每个 socket drops 差分应为 0。
- Clash 7895 drops 不应持续增长。
- EDMA、softnet、端口 error 不增长。

若基线也增长，先捕获 socket inode和进程，停止后续压力测试。

### 5.2 场景 A：路由器作为 UDP 接收端

Mac -> AX6 独立 iperf UDP 端口，按 100/200/300/400/500 Mbps，每档 15 秒，
在每档进行前、中、后 socket inode采样。

目的：测量路由 CPU/iperf socket 消费上限。此场景的 RcvbufErrors 属于本机
终结流量，不能直接用于评价 NSS 转发。

停止条件：

- 任一档出现 kernel Oops、服务退出或 boot ID 改变。
- RcvbufErrors 快速增长且无法绑定到 iperf socket。
- 温度超过 80 C 或持续上升无法稳定。

### 5.3 场景 B：两台 LAN 端点 UDP 转发

使用两台有线 Linux、同版本 iperf3，路由器不作为接收端。依次测试单向和反向，
再测试双向；每档记录端点 loss/jitter 和路由 EDMA/softnet/端口差分。

通过门槛：

- 低于端点处理能力的速率下，无系统性丢包。
- 路由器 UDP RcvbufErrors 不应因纯转发流量增长。
- EDMA/端口/softnet error 不增长。

若端点丢包但路由所有计数稳定，继续排查端点应用、NIC、驱动和 iperf 版本，
不得直接修改 NSS。

### 5.4 场景 C：ZeroTier 高速上行

使用远端 ZeroTier 对端分档测试，实时绑定 ZeroTier socket inode：

- 记录三个本地端口在 WAN/LAN 地址上的六个 socket。
- 每 5 秒记录 socket drops、rx_queue、CPU/线程调度和系统 RcvbufErrors。
- 同时记录 CLI ONLINE、network OK、L3 地址和动态 nft 端口一致性。

通过门槛：在目标业务速率和持续时间内，ZeroTier socket drop 不持续增长，
服务不重启、L3 不丢失、动态端口规则不漂移。

只有该场景确认 drops 属于 ZeroTier socket 后，才评估 4 MiB 常量、线程调度、
CPU affinity 或上游实现；禁止先继续放大全局 `rmem_max/default`。

## 6. 阶段 3：完整 TCP 与综合压力复测

在阶段 0 新脚本通过后执行：

1. TCP 单流 15 分钟。已有 25 分钟通过证据，本轮用于验证新脚本。
2. TCP 双向 20 分钟，必须完整 1200 秒，无外部 SIGTERM。
3. 两台 LAN Linux 端点单向、反向、双向各 10 分钟。
4. Burst 40 轮，每轮记录吞吐、重传和端口差分。
5. Bufferbloat 分别测空闲、单向饱和、双向饱和；报告平均、P95、最大时延。
6. Concurrent 场景使用不同 server 端口和唯一 PID，避免同一 iperf daemon 争用。

通过门槛：

- boot ID 不变，无 Oops/panic/watchdog/ath11k fatal。
- `nss-check` 和 `ax6-config-audit` 始终返回 0。
- EDMA、softnet、物理端口错误无持续增长。
- TCP 重传可解释且不形成持续上升趋势。
- 双向结果必须分别报告两个方向，不能只报告总和。

## 7. 阶段 4：服务、Wi-Fi、空间和故障恢复

### 7.1 OpenClash

- 连续 DNS 查询、LuCI 加载和实际网站访问。
- 记录 7874 探针、dnsmasq owner、OpenClash PID 和 7895 drops。
- 等待一次正常 Geo 更新，记录更新前、临时峰值和更新后 overlay。
- 不修改订阅、覆写和 Geo 自动更新配置。

空间门槛：保持至少 10 MiB 可用；若更新临时峰值逼近该门槛，先评估将 dashboard
更新文件烘焙进下一固件或清理可再生成缓存，不删除订阅和 Geo 数据。

### 7.2 ZeroTier

- 冷启动、WAN renew、正常网络波动后的 ONLINE/L3/规则收敛。
- 远端 Mac -> LuCI、远端 Mac -> LAN 设备、LAN 设备 -> 远端 Mac 三个方向。
- 不主动重启服务；故障注入测试必须单独获得用户确认。

### 7.3 Wi-Fi 和 IoT

建立客户端矩阵：

| 类别 | 连接 | DHCP | DNS | 互联网 | 2 小时长稳 |
|---|---|---|---|---|---|
| 2.4G legacy 11b/g | 待测 | 待测 | 待测 | 待测 | 待测 |
| 2.4G HT20/HT40 | 待测 | 待测 | 待测 | 待测 | 待测 |
| 2.4G HE20/HE40 | 待测 | 待测 | 待测 | 待测 | 待测 |
| 5G HE80 | 待测 | 待测 | 待测 | 待测 | 待测 |

测试期间保持 US、2.4G HE40/coexistence 和 5G HE80，不同时改变国家码、加密、
PMF、带宽和信道。只有具体客户端失败可复现后才做单变量 A/B。

### 7.4 VLAN、UPnP、OpenVPN

- 保持当前无 bridge-vlan/filtering 混用基线。
- UPnP disabled：确认无进程、无租约、空动态 chain。
- OpenVPN disabled：确认无 tun0、1194 listener 和活动 WAN rule。
- 不删除标准禁用骨架，除非用户决定永久移除 OpenVPN 功能。

## 8. 阶段 5：24/72 小时长稳

启动条件：P0 APCS 候选完成构建验证，UDP 归因和完整压力测试无未解释 P1。

### 8.1 24 小时压力观察

- 正常业务为主，每小时短时 TCP/UDP 健康检查，不持续跑满 24 小时。
- 每 5 分钟记录 boot ID、负载、温度、内存、overlay、EDMA、UDP、端口和服务 PID。
- 任何 boot ID 改变、核心服务重启或计数突增立即封存日志并停止。

### 8.2 72 小时正常业务

- 不做故障注入和配置修改。
- 覆盖 Geo 更新、IoT 睡眠唤醒、ZeroTier 远程访问和多文件传输。
- 结束后对比所有累计计数与用户感知问题时间线。

通过门槛：无非预期重启、无服务循环恢复、无持续丢包、overlay 保持安全余量，
NSS/EDMA/ath11k 无 fatal，OpenClash/ZeroTier 健康探针持续通过。

## 9. 合并和发布门禁

任何源码或构建仓库修改必须按以下顺序：

1. 独立分支提交，提交只包含一个问题域。
2. 本地测试、Shell/YAML、`git diff --check` 通过。
3. 云端 lint 通过。
4. 完整 stock 构建通过，不使用 EXPAND 代替 stock。
5. 下载 artifact 独立验证 rootfs、kmod、manifest、BUILD-LOCK 和 SHA256。
6. 对比当前实机配置与新 rootfs 默认，防止恢复脚本覆盖用户订阅和密码。
7. 输出变更、风险、回滚和实机验证边界。
8. 用户确认后才允许合并、发布或刷写。

APCS、UDP/ZeroTier、测试框架三个问题域必须使用独立提交；不得将上游常规包
更新与核心驱动修复打包在同一验证分支。

## 10. 下一步执行顺序

| 顺序 | 工作 | 类型 | 是否需要实机修改 |
|---:|---|---|---|
| 1 | 把测试框架重构为可归因、可中断、可审计版本 | 仓库 | 否 |
| 2 | 建立 APCS per-SoC/resource 边界候选补丁和静态测试 | 源码仓库 | 否 |
| 3 | 对 APCS 候选执行 lint、内核包和完整 stock 构建 | 云端构建 | 否 |
| 4 | 60 秒 UDP 空闲基线和 socket inode 采集 | 实机只读 | 否 |
| 5 | 路由端点 UDP 分档，定位临时 socket drops | 主动测试 | 需用户确认测试窗口 |
| 6 | 两台 Linux LAN-LAN UDP/TCP 转发测试 | 主动测试 | 需端点准备，不改路由配置 |
| 7 | ZeroTier 远端分档和 socket/线程归因 | 主动测试 | 需远端对端和用户确认 |
| 8 | 新脚本完整 TCP/UDP/burst 回归 | 主动测试 | 需用户确认测试窗口 |
| 9 | Wi-Fi IoT、Geo 更新和 24/72 小时长稳 | 观察 | 不改配置 |

当前最先执行的是第 1、2 项；它们可以并行进行且不会触碰实机。第 5 项以后
都必须在脚本证据链修正后执行，避免再次得到无法归因的大量 UDP 累计值。
