# AX6 修复进度汇总与完整测试方案（2026-08-02，更新至 2026-08-03）

## 1. 文档目的与适用范围

本文是 Redmi AX6（IPQ807x、stock 分区布局、NSS 固件）的阶段性主记录，
用于统一说明：

1. 已发现问题、根因、影响、修复逻辑和验证证据。
2. 当前实机状态与新构建固件状态之间的差异。
3. 已排除的错误方向和仍需观察的边界。
4. 后续刷机前、刷机后、性能、故障恢复和长时间稳定性测试方案。

2026-08-02 已由用户完成新固件全新刷写和配置恢复，本文第 14、15 节记录
刷机后的真实运行结果。后续刷写、清空配置、服务故障注入或网络中断测试，
仍须在用户明确确认和维护窗口内执行。

历史详细数据见：

- `AX6-IPQ/FULL-TEST-REPAIR-REPORT-2026-08-01.md`
- `router-backups/Redmi-AX6-20260801-fulltest/`

## 2. 截止状态结论

### 2.1 总体结论

截至 2026-08-02，仓库修复、静态检查、完整 stock 构建和产物离线检查
已经闭环。当前没有检出确定的 NSS、ECM、SSDK、EDMA、ath11k、VLAN、
IRQ/RPS、ZRAM、OpenClash 或 ZeroTier 核心冲突。

当前状态不能表述为“所有未来场景绝对无故障”，因为下列边界仍需新固件
刷入后在实机关闭：

- ZeroTier 4 MiB UDP socket buffer 是否消除高速上行 drop。
- 新增健康服务在全新启动、网络重启和 24/72 小时运行后的持续行为。
- 两台 Linux 有线端点上的真正双向 TCP 公平性。
- 2.4 GHz HE40/20 自动共存下的 IoT 兼容矩阵。

### 2.2 进度总览

| 阶段 | 状态 | 完成度 | 说明 |
|---|---|---:|---|
| 实机基线与核心驱动审计 | 已完成 | 100% | NSS/ECM/SSDK/ath11k/IRQ/ZRAM/VLAN/链路均已检查 |
| 故障复现与根因边界 | 已完成 | 100% | OpenClash DNS、ZeroTier L3、OpenVPN 残留均有可复现条件 |
| 仓库结构性修复 | 已完成 | 100% | 修复进入 files、package patch、审计、测试和 rootfs 门禁 |
| 本地测试 | 已完成 | 100% | 13 个仓库测试、Shell 语法、YAML、diff 门禁通过 |
| 云端 lint | 已完成 | 100% | 运行 30707216199 成功 |
| stock 完整构建 | 已完成 | 100% | 运行 30707218161 成功，用时 1 小时 56 分 |
| 产物独立检查 | 已完成 | 100% | 三类 artifact、SHA256、manifest、rootfs、ELF 均通过 |
| 新固件实机验证 | 进行中 | 75% | 已完成冷启动、核心链路、服务和 25 分钟单流；双向阶段仅完成 1033/1200 秒，UDP/综合压力与长稳未闭环 |
| 24/72 小时长稳 | 未开始 | 0% | 在新固件功能测试全部通过后执行 |

## 3. 版本、提交与构建证据

### 3.1 仓库状态

| 项目 | 值 |
|---|---|
| 构建仓库 | `OrdinaryJoys/AX6-OpenWRT` |
| 验证分支 | `codex/ax6-postflash-build-repair-20260801` |
| 最终提交 | `84fc0f2266e265b43152ada6b4b519dc2adc2f70` |
| 功能修复提交 | `ac30a317fea1ac0bc36cad26bebbf52153bee781` |
| CI 修正提交 | `84fc0f2266e265b43152ada6b4b519dc2adc2f70` |
| 锁定源码仓库 | `OrdinaryJoys/immortalwrt-nss` |
| 锁定源码提交 | `0ea848641f031dc37440e082163b3de1d8ccb9cf` |
| 源码基线提交 | `56807d9661dbe7df421d1fd31feba76677b5703d` |

### 3.2 云端结果

| 检查 | 运行 | 结果 | 关键范围 |
|---|---:|---|---|
| Lint | [30707216199](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/30707216199) | 成功 | ShellCheck、Actionlint、Yamllint、NSS/ECM/Wi-Fi/ZRAM/IRQ/SMEM 门禁 |
| Stock build | [30707218161](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/30707218161) | 成功 | prepared source、NSS 回归、完整编译、DTB、rootfs、artifact |

第一轮 lint 在 Actionlint 阶段检出四条 `SC2016`。根因是 rootfs 门禁用
单引号表达需要匹配的字面 shell 变量。修复为双引号加转义美元符号，匹配
内容和运行语义不变。修正后新提交的全部 lint 项通过；旧 SHA 构建在尚未
进入编译时取消，避免浪费资源。

### 3.3 固件与插件版本

| 组件 | 新构建值 |
|---|---|
| 固件版本 | `r0-0ea8486` |
| Kernel | `6.18.38` |
| OpenClash | `0.47.133` |
| OpenClash Meta core | AArch64，SHA256 `2374c3dc2bed8c6c9369c55c63fd12904f5aa7a5491e3d1f07bfee195798b358` |
| ZeroTier | `1.16.2-r1` |
| qca-ssdk | `2025.11.14~d9a19649-r1` |
| qca-nss-dp | `2026.01.19~d8f802f0-r1` |
| qca-nss-drv | `2026.01.12~6aa14c7-r18` |
| qca-nss-ecm | `2026.04.03~8c7355b-r9` |
| ath11k | `6.18.26-r1`（随内核包版本 6.18.38） |

## 4. 已发现问题、根因与修复状态

| 优先级 | 问题 | 根因 | 修复状态 | 当前边界 |
|---|---|---|---|---|
| 已关闭 P0 | root 密码为空但管理面可从 LAN/ZeroTier 到达 | 全新刷写时按要求未恢复登录密码 | 不允许脚本或备份自动写入密码；用户已手动设置 | 2026-08-03 复核 `/etc/shadow` 为 SET，SSH 密钥登录正常 |
| P0（维护面） | root 递归读取 `debugfs/regmap` 可触发 IPQ807x 内核 panic | APCS 资源只有 `0x1000`，通用 regmap 上限却为 `0x1008`，读到资源边界外 | 已禁止实机递归 debugfs 内容扫描并保存 pstore；内核修复尚未进入构建 | 正常业务流不触发；需独立源码分支和构建验证，禁止在实机复现 |
| P0 | OpenClash 进程存在但 DNS 不响应 | 官方进程 watchdog 不能识别活锁 | 仓库、构建、刷机后冷启动和负载验证均通过 | 24/72 小时长稳仍待完成 |
| P0 | ZeroTier 控制面 OK、内核 L3 地址偶发缺失 | procd/控制面与内核接口收敛存在时序分离 | 仓库、构建及本次刷机启动收敛均通过 | 显式网络重启回归和长稳仍待完成 |
| P1 | ZeroTier 高速 UDP 上行出现 receive drops | 应用显式设置 1 MiB `SO_RCVBUF`，全局 `rmem_default` 不能覆盖 | 4 MiB package patch 已构建并刷入实机 | 30 秒 4 流上行仍使主 UDP socket drops 增加 2730，修复不完整 |
| P1 | ZeroTier init restart 返回非零但替换 daemon 已在线 | 上游启动后钩子返回值覆盖 procd 成功状态 | 健康脚本改为核对 PID 更换和 CLI ONLINE；刷机后守护状态正常 | 尚需显式 restart 回归 |
| P1 | OpenVPN 关闭后可能保留旧模板网络/防火墙项 | 旧固件或备份恢复遗留精确模板 | 仅精确匹配时清理，用户自定义配置不动 | 当前实机无活动残留 |
| P2 | 审计只检查静态配置，不能识别活锁/L3 丢失 | 缺少直接运行态探针 | 已接入两个健康探针和禁用态检查 | 已通过夹具和实机检查 |
| P2 | 测试场景变量可能泄漏 | shell 函数前置赋值在不同 shell 下恢复行为不同 | 场景间显式复位 | 全部测试通过 |
| P2 | 新 rootfs 门禁触发 Actionlint `SC2016` | 字面变量使用单引号 | 改为转义字面量 | 云端 lint 已通过 |

## 5. 修复逻辑说明

### 5.1 OpenClash DNS 健康恢复

新增 `ax6-openclash-dns-health`，只在下列条件同时成立时工作：

1. OpenClash 已启用。
2. DNS 劫持模式为 dnsmasq 转发。
3. dnsmasq 上游精确指向 `127.0.0.1:<OpenClash DNS port>`。
4. Meta core PID 确实存在。

探针直接查询 `127.0.0.1:7874`，不经过 dnsmasq，避免单点链路自证。
默认连续 3 次失败后重启 OpenClash，并设置 300 秒冷却。该逻辑不改订阅、
覆写、配置 YAML、GeoIP、GeoSite、GeoASN 或 CHNR 更新设置。

验证中对 Meta core 执行可回滚 `SIGSTOP` 后，服务约 26 秒恢复；恢复前后
配置和覆写目录哈希不变。

### 5.2 ZeroTier L3 健康恢复

新增 `ax6-zerotier-health`，只有同时满足以下条件才允许恢复：

1. ZeroTier UCI 已启用。
2. CLI 状态为 ONLINE。
3. 配置网络在 CLI 中为 `OK`。
4. `allowManaged=true`。
5. 控制面声明了分配地址，但对应内核接口确实缺少该地址。

脚本不手工添加地址、路由或 nftables 规则，也不会对 OFFLINE、REQUESTING
或未授权网络反复重启。默认连续 3 次异常、30 秒间隔、300 秒冷却后重启。

若上游 init 返回非零，但旧 PID 已替换且新 daemon 已 ONLINE，按实际运行态
判定恢复成功，避免误报和重复重启。

### 5.3 ZeroTier UDP 缓冲

构建层对 ZeroTier 上游常量做精确 package patch：

```text
ZT_UDP_DESIRED_BUF_SIZE: 1048576 -> 4194304
```

该方案只影响 ZeroTier 自己创建的 UDP socket，不修改全局 `rmem_default`，
也不影响 OpenClash、dnsmasq 或其他 UDP 服务。构建门禁会实际 prepare
ZeroTier 源码，要求新值存在且旧值不存在。

### 5.4 OpenVPN 禁用态迁移

只有在 OpenVPN 服务关闭且旧模板的名称、协议、接口、zone 和 forwarding
字段全部精确匹配时才删除。任意用户自定义差异都会阻止删除。审计同时检查：

- OpenVPN 进程和 init 状态。
- `tun0` 或其他活动隧道接口。
- UDP/TCP 1194 监听。
- WAN 开放规则。
- 旧 network、zone 和 forwarding。

## 6. 仓库修复文件与职责

| 文件/区域 | 作用 |
|---|---|
| `AX6-IPQ/files/usr/sbin/ax6-openclash-dns-health` | OpenClash 直连 DNS 探针、阈值、冷却和恢复 |
| `AX6-IPQ/files/etc/init.d/ax6-openclash-dns-health` | procd 生命周期和启动顺序 |
| `AX6-IPQ/files/usr/sbin/ax6-zerotier-health` | ZeroTier 控制面/内核 L3 一致性检查 |
| `AX6-IPQ/files/etc/init.d/ax6-zerotier-health` | procd 生命周期和启动顺序 |
| `AX6-IPQ/package-patches/zerotier/100-openwrt-increase-udp-socket-buffer.patch` | ZeroTier 4 MiB UDP socket buffer |
| `AX6-IPQ/files/etc/uci-defaults/zz-ax6-openvpn-defaults` | OpenVPN 精确旧模板迁移 |
| `AX6-IPQ/files/sbin/ax6-config-audit` | OpenClash、ZeroTier、OpenVPN 运行态审计 |
| `AX6-IPQ/diy.sh` | 将 package patch 安装到实际被选中的 ZeroTier 包 |
| `.github/workflows/build-AX6-NSS.yml` | prepared source、rootfs、启动链接和产物门禁 |
| `.github/workflows/lint.yml` | 新增测试进入云端 lint |
| `tests/test-*.sh` | 故障夹具、迁移边界、缓冲补丁和健康恢复测试 |

## 7. 已完成验证证据

### 7.1 本地与云端门禁

- 13 个仓库可执行测试全部通过。
- 相关 Shell 文件 `sh -n` 全部通过。
- 6 份 GitHub Actions YAML 解析通过。
- `git diff --check` 和暂存差异检查通过。
- 云端 ShellCheck、Actionlint、Yamllint 全部通过。
- stock/expand 配置差异、NSS 黑名单、ECM 策略、ath11k NSS、SMEM、
  ZRAM、IRQ、PBUF 和 Kconfig 一致性门禁通过。

### 7.2 完整构建与产物

| 产物 | 大小 | 结果 |
|---|---:|---|
| stock sysupgrade | 52,101,922 bytes | SHA256、tar 成员、rootfs 通过 |
| stock factory UBI | 54,132,736 bytes | SHA256、stock 大小门禁通过 |
| stock initramfs ITB | 51,460,492 bytes | SHA256 通过 |
| kmod artifact | 约 7.3 MiB | archive、索引、全部 IPK SHA256 通过 |

独立下载后再次确认：

- Recovery 和 sysupgrade 的 `BUILD-LOCK-AX6.txt` 完全一致。
- Recovery 和 sysupgrade 的设备 manifest 完全一致。
- 设备 manifest 与 rootfs 中 opkg 实际安装清单完全一致。
- OpenClash Meta core 是静态链接 AArch64 ELF，哈希与锁定值一致。
- 固件内两个健康脚本和 `ax6-config-audit` 与仓库字节级一致。
- rootfs 包含 S92/S93 健康服务链接、NSS DRV/DP、SSDK、ath11k 模块。
- `kmod-nf-flow`、`kmod-ipt-offload`、`kmod-nft-offload`、
  `kmod-fast-classifier`、shortcut-fe 系列全部缺席。

## 8. 2026-08-02 当前实机快照

采集时间：`2026-08-02T11:05:04+08:00`。

| 项目 | 当前实机状态 |
|---|---|
| 运行时间 | 1 天 12 小时 47 分 |
| 固件 | `ImmortalWRT SNAPSHOT r0-0ea8486` |
| Kernel | `6.18.38` |
| `nss-check -v` | PASS=45、WARN=4、FAIL=0 |
| `ax6-config-audit -v` | PASS=29、WARN=2、FAIL=0 |
| WAN/LAN1/LAN2 | 1000 Mbps、Full Duplex、Link up |
| LAN3 | 未连接，属于物理状态而非故障 |
| 物理错误 | WAN/LAN1/LAN2 CRC/FCS/drop/error/overflow 等为 0 |
| ZeroTier | 1.16.2、ONLINE、网络 OK、地址 `172.29.205.171/16` |
| OpenClash DNS 探针 | 返回 0 |
| ZeroTier L3 探针 | 返回 0 |
| Overlay | 41%，可用 22.8 MiB |
| RAM | 可用约 438 MiB |
| ZRAM | 256 MiB，当前使用 0 |
| UDP socket drops | 当前快照无非零项 |
| 内核严重错误 | 未检出 BUG、Oops、panic、NSS/ath11k fatal |

该快照属于刷机前旧固件。2026-08-02 已刷入提交 `84fc0f2` 对应的新固件，
后续实测结果见第 14 节；其中 4 MiB ZeroTier socket buffer 已确认进入实机，
但高上行压力下仍会发生 receive drops。

## 9. 已排除或不能直接归因的方向

### 9.1 NSS 与软件加速冲突

仓库配置、rootfs 和 kmod artifact 均确认软件 flow-offload/shortcut-fe 冲突包
不存在。当前不能把网络波动归因于“隐藏的软件加速与 NSS 同时开启”。

### 9.2 2.4 GHz HE40/HE20

配置为 US、HE40 并开启 20/40 coexistence 时，驱动根据环境降到 20 MHz
属于标准共存行为。不能仅因实时宽度为 20 MHz 判定 Wi-Fi 故障。

### 9.3 交换机 PAUSE

LAN1/LAN2 临时关闭 PAUSE 后，双向吞吐不对称没有改善，且链路重新协商
期间出现瞬时重传。仓库保持 `disable_flow_control=0`，不将 PAUSE 关闭作为
默认修复。

### 9.4 LAN-LAN 双向不公平

Mac 和 Windows 的两个单向测试均约 948-949 Mbps，但 iperf3 原生双向出现
约 946 + 325 Mbps。该流量主要走同网段交换/桥路径，物理错误为零；Windows
iperf3 又不能完成同条件 UDP 双向测试。因此尚不能归因 NSS、SSDK 或 EDMA。

## 10. 仍需关闭的风险和观察项

| 级别 | 项目 | 当前判断 | 关闭条件 |
|---|---|---|---|
| 已完成 | 固件与实机一致性 | 已刷入并完成版本、rootfs、包清单和哈希一致性验证 | 无 |
| 已完成 | root 登录认证 | 用户已手动设置密码，SSH 密钥与 LuCI 认证边界复核正常 | 无；恢复脚本继续禁止写入密码 |
| P0（维护面） | APCS regmap debugfs 越界 panic | 仅 root 读取特定 `registers` 节点触发，正常转发路径不涉及 | 独立源码修复、编译与离线验证；实机禁止复现 |
| P1 | ZeroTier 高速 UDP drops | 4 MiB 修复已进入实机但不能消除高上行 drops | 重新设计并验证 socket/调度方案；高速测试期间 drop 无持续增长 |
| P2 | LAN-LAN 原生双向不公平 | 端点/工具边界尚未排除 | 两台 Linux 同版 iperf3 复测 |
| P2 | 2.4 GHz IoT 兼容性 | 缺少受控客户端矩阵 | legacy/HT/HE 设备逐类通过连接、DHCP、DNS、长稳 |
| P2 | Mihomo UDP 7895 历史累计 drop | 曾见累计 109，20 秒窗口不增长；当前 socket 无非零 drop | 在可控 UDP 压力下按时间差分观察 |
| P2 | Wi-Fi invalid REO 计数 | 负载时增长但未关联用户可见故障 | 仅在与丢包/断流时间相关时升级 |
| 接受 | Geo 数据自动更新占用 overlay | 用户明确要求保留 | 监控空间，不关闭自动更新 |

## 11. 后续完整测试方案

### 阶段 A：刷机前完整性检查

目的：确保使用的文件、硬件布局和恢复条件正确。

步骤：

1. 从 Actions 运行 30707218161 下载 stock sysupgrade artifact。
2. 校验 artifact 内 `SHA256SUMS-AX6.txt`，禁止使用聊天附件或二次转存的
   未校验镜像。
3. 核对文件名必须包含 `redmi_ax6-stock-squashfs-sysupgrade.bin`。
4. 核对构建提交必须是 `84fc0f2266e265b43152ada6b4b519dc2adc2f70`。
5. 在路由器执行只读 `sysupgrade -T` 镜像兼容性检查。
6. 重新备份 `/etc/config`、OpenClash 配置、ZeroTier identity/network、
   DHCP 租约和当前审计输出。
7. 备份中排除路由登录密码恢复；密码继续由用户手动设置。
8. 保存当前 MTD/UBI、board JSON、内核版本、已安装包和 SHA256 清单。
9. 明确恢复路径：可用 initramfs/factory 产物、串口或已验证的 U-Boot 恢复。

通过标准：

- 所有 SHA256 成功。
- `sysupgrade -T` 返回兼容。
- 设备确认为 AX6 stock/SMEM 布局，不误用 expand 版本。
- 至少存在一份本地离线备份和一条可执行恢复路径。

停止条件：任何哈希不一致、分区布局不明确、供电不稳定或恢复路径不可用。

### 阶段 B：全新刷写与最小恢复

该阶段必须再次取得用户明确确认。

建议流程：

1. 使用 stock sysupgrade，执行不保留配置的全新刷写。
2. 首次启动只设置新的登录密码和管理网络连通性。
3. 不立即恢复完整备份，先完成阶段 C 的纯固件基线检查。
4. 分组恢复网络、DHCP、Wi-Fi、OpenClash、ZeroTier、UPnP/VLAN 配置。
5. 每恢复一组立即运行审计并保存差异，禁止一次性覆盖全部 `/etc`。
6. 不恢复旧登录密码、旧二进制、旧 init 脚本、旧 kmod 或 opkg status。

通过标准：首次启动稳定、SSH 密钥可用、无只读 rootfs/UBI 错误、无重复服务。

### 阶段 C：启动与核心驱动测试（P0）

检查范围：

- `dmesg`/`logread` 中 BUG、Oops、panic、RCU stall、watchdog lockup。
- NSS 双核状态、qca-nss-drv、qca-nss-dp、qca-ssdk、ECM 加载。
- ath11k AHB/PCI、固件加载、NSS offload 和无线 PHY。
- `nss-check -v`、`ax6-config-audit -v` 完整输出。
- `frame_mode=2`、`nss_offload=1`，无不支持的 `rx_hash` 参数。
- 软件 flow-offload 和 shortcut-fe 冲突模块不存在。
- pbuf 水位、ZRAM、IRQ/RPS、CPU 频率和温度。
- bridge/VLAN、WAN、LAN1-3 的 link、speed、duplex 和错误计数。

通过标准：

- 两个审计 `FAIL=0`。
- 无内核 fatal/crash。
- 在用链路为期望速率和全双工。
- CRC/FCS/align/overflow/underrun/collision 不增长。
- 只有仓库声明的 NSS/IRQ/offload 所有者生效。

### 阶段 D：基础连通性与延迟

每类测试保存原始输出、时间戳和端点：

1. LAN 到路由：1000 次 ICMP，记录 loss、avg、p95、max、jitter。
2. 路由到默认网关：500 次 ICMP。
3. 路由到 1.1.1.1/8.8.8.8：各 500 次 ICMP。
4. DNS：Mihomo 直连、dnsmasq、本地常用域名各 200 次。
5. LuCI：静态资源、状态页、OpenClash 页各做 30 次冷/热加载。
6. 记录测试前后 CPU、softirq、内存、conntrack 和接口 counters。

通过标准：LAN loss=0；公网不出现持续丢包；DNS 成功率 100%；延迟异常必须
能与 WAN、DNS、CPU、socket drop 或物理计数中的至少一项时间相关。

### 阶段 E：有线吞吐与 NSS/交换路径

端点要求：两台 Linux 有线设备、不同 LAN 物理口、相同 iperf3 版本，关闭
端点省电并记录 NIC offload/flow-control 状态。

矩阵：

| 场景 | 参数 | 时长/次数 |
|---|---|---|
| LAN1 -> LAN2 TCP | 1、4、8 流 | 每项 60 秒，3 次 |
| LAN2 -> LAN1 TCP | 1、4、8 流 | 每项 60 秒，3 次 |
| TCP 原生双向 | 4 流/方向 | 300 秒，3 次 |
| UDP 单向 | 100/300/600/900 Mbps | 每档 60 秒 |
| UDP 双向 | 300+300、450+450 Mbps | 每档 180 秒 |
| WAN NAT TCP | 上行、下行、双向 | 每项 300 秒 |
| 小包 PPS | 64/128/256 byte | 在可控测试网执行 |

同步采集：

- 两端 iperf3 JSON、CPU、重传、拥塞窗口和 NIC counters。
- 路由器 NSS/ECM connection counters、softirq、负载和温度。
- SSDK 端口 CRC/drop/pause/queue counters。
- 测试前后 `/proc/net/softnet_stat` 和 conntrack 数量。

通过标准：单向千兆 TCP 不低于 930 Mbps；Linux-Linux 双向应接近链路可用总量
且方向间无稳定的 3:1 以上不公平；物理错误为零；无内核或 NSS 报错。

若双向仍异常，按顺序排查端点 CPU/NIC、TCP 重传、交换队列、PAUSE、桥路径，
最后才进入 SSDK/EDMA 驱动修改。不得先关闭 PAUSE 或改 NSS 默认策略。

### 阶段 F：Wi-Fi 性能与兼容性

#### 5 GHz

- US、HE80，分别测试近、中、远距离。
- 上行、下行、双向各 300 秒，至少 3 次。
- 并发 2、4、8 客户端，混合 TCP/UDP。
- 记录 RSSI、MCS、NSS、带宽、重试率、ath11k/NSS counters。

#### 2.4 GHz

- 保持 US、HE40 和 20/40 coexistence，不强制固定 40 MHz。
- 客户端至少覆盖 802.11b/g、HT20、HT40、HE20、HE40/20 自适应和典型 IoT。
- 每台执行关联、WPA 握手、DHCP、DNS、局域网、互联网、休眠唤醒。
- 每类设备连续运行至少 2 小时，IoT 设备观察 24 小时重连次数。
- 分别测试 WPA2、WPA2/WPA3 兼容模式；不得为单个设备全局降低安全性，
  除非单独 SSID A/B 明确证明必要。

通过标准：无批量关联失败、DHCP 超时、周期性断流或驱动 crash；动态降到
20 MHz 本身不算失败。

### 阶段 G：OpenClash DNS 与代理链路

基础测试：

1. 核对 dnsmasq 上游和 OpenClash DNS 端口所有权唯一。
2. 直连 `127.0.0.1:7874`、dnsmasq 和客户端查询各 200 次。
3. 国内/海外/IPv4/无效域名并发查询，记录失败和 p95。
4. 规则、全局、直连切换后检查 DNS owner 不漂移。
5. 保持订阅、覆写和 Geo 自动更新，不以修改订阅作为修复手段。

故障恢复测试需维护窗口确认：

- 暂停 Meta core，验证健康服务达到阈值后只重启一次。
- 检查 300 秒冷却期间不会形成重启风暴。
- 验证配置、订阅、覆写和 Geo 文件哈希不变。
- 恢复后完成 DNS、TCP、UDP 和 LuCI 页面回归。

UDP 7895 采用时间差分：空闲 10 分钟、UDP 压力 10 分钟、恢复 10 分钟，
分别记录 socket drop 增量，不能用进程全生命周期累计值直接归因。

### 阶段 H：ZeroTier 功能、恢复与吞吐

基础检查：

- CLI ONLINE、network OK、`allowManaged=true`。
- 分配地址存在于正确的 ZeroTier 接口。
- 路由、fw4 zone/forwarding、自流量 bypass 与仓库策略一致。
- 远程 Mac -> 路由后台和路由 LAN -> 远程 Mac 两个方向都可建立连接。

吞吐矩阵：

| 方向 | 协议 | 时长 |
|---|---|---:|
| LAN -> 远程节点 | TCP 1/4 流 | 各 300 秒 |
| 远程节点 -> LAN | TCP 1/4 流 | 各 300 秒 |
| 双向 | TCP | 900 秒 |
| 双向 | UDP 分档 | 每档 300 秒 |

测试前、每 30 秒和结束后记录 ZeroTier UDP socket 的 receive queue/drop、
进程 CPU、系统 UDP 统计、接口 packet/drop 和公网基础丢包。

故障恢复测试需维护窗口确认：

1. 执行一次真实 network restart。
2. 验证控制面/内核 L3 暂时不一致时，连续计数符合 30 秒间隔。
3. 第 3 次才允许恢复，且冷却期内不重复重启。
4. 替换 daemon ONLINE 后，地址、路由和远程访问全部恢复。
5. OFFLINE/REQUESTING 场景不得触发重启风暴。

通过标准：高速测试期间 ZeroTier socket drop 不持续增长；无 L3 地址永久丢失；
无手工地址/路由残留；健康恢复不影响 OpenClash、LAN 或 WAN。

### 阶段 I：VLAN、UPnP、OpenVPN 与防火墙

#### VLAN

- 核对 bridge VLAN membership、PVID、tagged/untagged 和 CPU/用户口映射。
- 每个 VLAN 测 DHCP、DNS、网关、互联网和预期的跨 VLAN 策略。
- 网络/firewall reload 后规则不重复，接口名不漂移。
- VLAN 压力下检查 SSDK、bridge 和 NSS counters。

#### UPnP

- 只允许预期 LAN zone 请求映射。
- 只在 WAN 创建对应临时规则。
- 客户端删除或租期到期后规则消失。
- 不允许 ZeroTier/VLAN 管理区意外获得广泛 UPnP 权限。

#### OpenVPN 禁用态

- 服务、进程、tun 接口和 1194 监听全部不存在。
- 无旧模板 WAN 规则、zone 或 forwarding。
- 用户自定义但禁用的 OpenVPN 配置不被迁移脚本误删。

### 阶段 J：ZRAM、资源和长时间稳定性

1. 空闲 24 小时：每 5 分钟采集负载、内存、ZRAM、温度、接口和服务状态。
2. 混合压力 8 小时：有线吞吐、Wi-Fi、OpenClash、ZeroTier、DNS 并发。
3. 正常业务 72 小时：记录重启次数、OOM、watchdog、服务 PID、drop 差分。
4. Geo 自动更新前后记录 overlay 使用量和失败日志。
5. ZRAM 使用时检查压缩算法、写回量、CPU 和 OOM；不以“ZRAM 为 0”判故障。

通过标准：无 OOM、panic、服务重启风暴、持续丢包、overlay 异常增长或核心
驱动 reset；24/72 小时结束时两个审计仍 `FAIL=0`。

## 12. 故障判定与停止规则

出现以下任一情况立即停止压力测试并保存现场，不自动修复：

- Kernel BUG、Oops、panic、RCU stall、watchdog lockup。
- ath11k/NSS/remoteproc fatal、固件 crash 或接口持续消失。
- UBI I/O error、overlay 只读、空间快速耗尽。
- CRC/FCS/overflow 持续增长。
- 健康服务在冷却期内重复重启。
- ZeroTier 或 OpenClash 恢复导致 LAN/WAN 管理失联。
- 温度达到设备不安全范围或供电不稳定。

每次异常必须保存：时间戳、触发测试、两端日志、路由 `dmesg/logread`、接口
counters、进程/PID、配置哈希和最近 5 分钟监控数据。没有时间相关证据时，
不得直接归因 NSS、Wi-Fi、OpenClash 或 ZeroTier。

## 13. 最终验收标准

只有同时满足以下条件，才可把本轮修复标记为“实机闭环”：

1. 新固件 SHA256 和 stock 布局确认无误。
2. 全新刷写和分组配置恢复成功，登录密码未从备份恢复。
3. NSS/配置审计 `FAIL=0`，无内核 fatal。
4. 两台 Linux 单向与双向有线吞吐通过。
5. 5 GHz 性能和 2.4 GHz IoT 兼容矩阵通过。
6. OpenClash DNS 活锁恢复通过，且不修改订阅/覆写。
7. ZeroTier L3 恢复和 4 MiB 缓冲高速测试通过。
8. VLAN、UPnP、OpenVPN 禁用态和防火墙边界通过。
9. 24 小时压力和 72 小时正常业务运行无确定故障。
10. 所有原始结果、SHA256、日志和异常说明完成归档。

在上述实机项目全部完成前，当前准确状态是：**仓库、构建和刷机后核心运行态
已验证；ZeroTier 高速 UDP receive drops、LAN-LAN 双向端点边界、IoT 矩阵与
24/72 小时长稳仍未闭环**。

## 14. 2026-08-02 刷机后实机审计

### 14.1 固件与产物一致性

- 设备：Redmi AX6 stock layout，squashfs/UBI 正常读写。
- 固件：`ImmortalWRT SNAPSHOT r0-0ea8486`，Linux `6.18.38`。
- 构建仓库提交：`84fc0f2266e265b43152ada6b4b519dc2adc2f70`。
- 云端 lint `30707216199`、stock 构建 `30707218161` 均成功。
- 实机包版本、OpenClash core、ZeroTier 二进制和 AX6 健康脚本哈希均与
  已下载 artifact 一致。
- 实机 opkg installed/hold 清单与设备 manifest 完全一致。

### 14.2 核心驱动与配置

| 项目 | 刷机后结果 |
|---|---|
| `nss-check -v` | `PASS=45 WARN=4 FAIL=0` |
| `ax6-config-audit -v` | `PASS=29 WARN=2 FAIL=0` |
| NSS | 两核启动，748.8 MHz，ECM 连接计数正常 |
| EDMA | AXI/FIFO/descriptor/length/QoS 错误为 0；`alloc_fail_cnt=4085` 在空闲和负载后均不增长 |
| ECM/offload | 软件/硬件 flow offload 关闭；`disable_offloads=1`、`disable_gro_list=1`；`br-lan` host path offload 关闭 |
| Wi-Fi | ath11k NSS offload、硬件 crypto、`fw_mem_mode=1`；US；5 GHz HE80；2.4 GHz HE40 配置按共存机制运行在 HE20 |
| IRQ/RPS/pbuf | 上游 qualcommax 服务拥有策略；RPS bitmap 15；1 GB pbuf profile 已应用 |
| ZRAM | 256 MiB、zstd、活动正常，无 swap 错误 |
| VLAN | 无 DSA bridge-vlan/filtering 冲突；qca_nss_vlan 就绪 |
| UPnP/OpenVPN | 均为完整禁用态，无残留进程、接口或 WAN 规则 |

启动日志中的 `mtdsplit: no squashfs found in rootfs` 来自 stock 合并 rootfs 的
探测路径，实际 squashfs/UBI 和文件系统一致性均通过；PSCI PC mode 提示是
平台固件兼容提示。两者当前均无运行故障证据。

### 14.3 有线、DNS 与本机管理路径

| 测试 | 结果 |
|---|---:|
| Mac -> AX6 ICMP 50 包 | 0% 丢包，平均 0.799 ms |
| AX6 -> 上级网关 30 包 | 0% 丢包，平均 0.849 ms |
| AX6 -> 223.5.5.5 10 包 | 0% 丢包，平均 7.948 ms |
| AX6 -> 1.1.1.1 10 包 | 0% 丢包，平均 68.401 ms，属于远端路径差异 |
| LAN LuCI 10 次 | 首字节 70-87 ms |
| LAN DNS 30 次 | 全部成功，1-3 ms |

WAN/LAN 物理端口均为 1000 Mbps/full duplex，无 CRC/FCS、overflow、underrun、
carrier 或 queue 错误；满载前后 softnet drops、LSO pbuf、EDMA 和端口错误不增长。

### 14.4 LAN-LAN 吞吐

Mac `192.168.5.190` 位于 LAN2，Windows `192.168.5.111` 位于 LAN1，流量确实
经过 AX6 桥/交换路径：

| 测试 | 结果 |
|---|---:|
| Mac -> Windows，TCP 单流 | 949 Mbps，0 重传 |
| Windows -> Mac，TCP 单流 | 949 Mbps |
| `--bidir -P1` Mac -> Windows | 484-485 Mbps，0 重传 |
| `--bidir -P1` Windows -> Mac | 947-948 Mbps |
| `--bidir -P4` Mac -> Windows | 平均 353 Mbps，首秒 849 重传，随后重传归零 |
| `--bidir -P4` Windows -> Mac | 946 Mbps |

双向不公平与旧固件记录一致，并非本次构建新回归。测试时路由 CPU 仍有
91-97% 空闲，NSS/EDMA/端口/softnet 无对应 drop 增量；临时关闭 PAUSE 的旧
A/B 也无改善。当前不能归因 NSS、SSDK 或 PAUSE，关闭条件仍是两台 Linux、
同版 iperf3 的独立交叉测试。ESnet 对 Windows 端仅提供 best-effort 支持。

### 14.5 ZeroTier

基础功能通过：1.16.2 `ONLINE`、network `OK`、managed 地址/路由/接口一致，
主端口 9993、secondaryPort 29937、tertiaryPort 43062 与动态 nftables 精确匹配；
健康守护状态为 0 次失败。通过 ZeroTier 地址访问 LuCI 首字节约 76-98 ms，
DNS 连续 10 次均为 2 ms。

高速上行未通过：

- 4 MiB 补丁后的实机二进制已由 artifact 哈希确认。
- `net.core.rmem_max=8388608`。
- 30 秒、4 流、Mac -> 路由 ZeroTier TCP 为约 263 Mbps。
- 路由主 UDP socket drops 从 6613 增至 9343，即 `+2730`；系统
  `RcvbufErrors` 同步增加约 2735。
- 同期 EDMA `alloc_fail_cnt` 保持 4085，排除 EDMA 分配失败与该增量相关。
- 停止负载后 drops 不再增长，服务仍 ONLINE，无重启或 L3 丢失。

官方 ZeroTier 1.16.2 仍将 `ZT_UDP_DESIRED_BUF_SIZE` 定义为 1 MiB，并经
`Binder::udpBind()` 传给 Linux `SO_RCVBUF`；截至 2026-08-02，官方 dev 相对
1.16.2 没有修改 `Constants.hpp`、`Phy.hpp` 或 `Binder.hpp` 的该路径。因此
不能把继续放大常量当作官方修复。下一方案必须同时验证实际 socket 缓冲、
持续消费速率、CPU/线程调度和长期 drops，且不得以全局盲目扩容替代根因分析。

### 14.6 OpenClash、空间与安全项

- OpenClash 0.47.133、Meta core、dnsmasq 7874 单一 DNS owner 和健康守护均正常。
- 负载后 OpenClash/ZeroTier PID 稳定，无重启循环；启动早期 ZeroTier 规则
  两次未读到稳定端口后在 2 秒内自动收敛，之后未复发。
- Geo 数据逻辑大小约 40.7 MiB，均位于 overlay；UBI 压缩后 `/overlay`
  实际使用 15.8 MiB/41.0 MiB，剩余 23.0 MiB。保留自动更新，但必须监控
  更新临时峰值。
- **原 P0 安全项已关闭。** root 密码已由用户手动设置，`/etc/shadow` 状态
  为 `SET`；备份和恢复脚本仍不写入密码。Dropbear 继续限制为 LAN 直连，
  LuCI 可经 LAN/ZeroTier 到达并由登录认证保护。

### 14.7 仓库与上游动态

- 当前测试分支 lint、stock 构建、rootfs 与 artifact 门禁全部通过。
- 主分支定时 `sync-check` 的失败原因是锁定仓库 HEAD 漂移，非网络不可达。
- 当前锁定 source、SQM、LuCI、telephony、video、argon-config 仍与远端一致。
- `routing` 仅有 BIRD 版本更新；`argon` 前进到 2.4.6，主要是 UI/OpenClash
  样式修正；`immortalwrt/packages` 为大量常规包更新。均应按实际安装包独立
  评估，不与 ZeroTier 或 NSS 核心故障打包合并。

### 14.8 当前未关闭项

1. P0（维护面）：修复 APCS regmap 范围与 IPQ807x `0x1000` 资源不一致，
   只在独立源码分支完成编译和离线审查，禁止再次在实机读取该 registers 节点。
2. P1：重新设计并验证 ZeroTier 高上行 UDP receive-drop 修复。
3. P2：用两台 Linux 同版 iperf3 关闭 LAN-LAN 双向不公平的端点边界。
4. P2：完成 2.4 GHz legacy/HT/HE IoT 客户端矩阵。
5. P2：继续观察 Wi-Fi invalid REO 和 OpenClash UDP 7895 小量累计 drop，
   仅在与用户可见断流存在时间相关时升级。
6. 长稳：完成 24 小时压力与 72 小时正常业务观察。

## 15. 2026-08-03 刷机后重启与完整运行复核

### 15.1 当前启动与资源

采集启动标识：`da88533e-a533-47af-b757-7c3674d4ce5f`。采集期间启动标识
保持不变，未发生第二次重启。

| 项目 | 结果 |
|---|---|
| 设备/布局 | Redmi AX6，stock layout，squashfs |
| 固件/内核 | `r0-0ea8486` / Linux `6.18.38` |
| 构建仓库提交 | `84fc0f2266e265b43152ada6b4b519dc2adc2f70` |
| 内存 | 约 916 MiB，总可用约 478 MiB |
| ZRAM | 256 MiB、zstd、当前使用 0 |
| Overlay | 41.0 MiB，总使用 21.1 MiB（54%），可用 17.7 MiB |
| `nss-check` | PASS=45、WARN=4、FAIL=0 |
| `ax6-config-audit` | PASS=29、WARN=3、FAIL=0 |
| root 认证 | 密码已设置；Dropbear 密钥登录正常 |

OpenClash GeoIP/GeoSite/ASN/CHNR 文件在 overlay 的逻辑大小约 39.5 MiB，
dashboard UI 上层文件约 12.3 MiB。固件只读层已包含约 18.6 MiB dashboard，
overlay 中是自动更新后的替换文件，不是两个目录同时计入 UBI；但更新时仍会
产生临时峰值。按用户要求保留所有 Geo 自动更新，当前只监控空间，不关闭更新。

### 15.2 核心驱动与链路

- `qca_nss_drv`、`qca_nss_dp`、`qca_ssdk`、`ecm`、`qca_nss_vlan`、
  `qca_mcs`、`ath11k` 均已加载；两个 NSS core 正常启动，当前频率 748.8 MHz。
- ECM 为 `disable_offloads=1`、`disable_gro_list=1`、
  `disable_flow_control=0`；防火墙软件/硬件 flow offload 都为 0，未加载
  shortcut-fe、fast-classifier 或 netfilter flow-offload 冲突模块。
- SQM 配置存在但 `enabled=0`，没有 IFB 设备和 cake qdisc 实例；`sch_cake`
  与 `ifb` 模块仅为安装依赖，不构成正在运行的整形路径。
- irqbalance 停止且禁用；IRQ/RPS 由 qualcommax 上游脚本和 NSS 内部 RPS 管理，
  `dev.nss.rps.enable=1`、hash bitmap=15，未发现脚本互相覆盖。
- WAN、LAN1、LAN2 均为 1000 Mbps/full duplex；LAN3 无载波。所有活动口
  CRC/FCS/frame/FIFO error 为 0。LAN1 累计少量 `rx_dropped=6`、
  `tx_dropped=3`，在高流量采样中无连续增长，暂不构成物理链路故障。
- EDMA 除 `alloc_fail_cnt=102` 外全部为 0；该值在连续高流量前后保持不变。
  softnet drop、NSS LSO drop、pbuf alloc/reference error 也未增长。

### 15.3 Wi-Fi、VLAN 与服务

- 5 GHz：US、HE80、信道 44、29 dBm、客户端隔离关闭、PMF optional。
- 2.4 GHz：US、配置 HE40/自动信道/20-40 coexistence，当前环境选择信道 1
  和实际 20 MHz；这是兼容降宽，不是配置故障。客户端隔离关闭、PMF 关闭。
- ath11k 固件正常，未检出 firmware crash、timeout 或 fatal。启动后 46-89 秒
  有 3 次 qca-mcs `MC_DEV returned NULL for device br-lan` 调试消息，此后未增长，
  与客户端重连时间吻合；当前无证据表明它造成断流。
- 当前没有 bridge VLAN filtering 或 bridge-vlan 混用，NSS VLAN 模块就绪。
- OpenClash core/DNS 直连探针返回 0；dnsmasq 唯一上游为
  `127.0.0.1#7874`，所有 Geo 自动更新保持开启。
- ZeroTier 1.16.2 ONLINE、network OK、地址 `172.29.205.171/16`；本次动态端口
  `9993/24469/50150` 与实际 UDP socket、状态文件和 nft include 完全一致，
  L3 健康探针返回 0。启动基础阶段 `RcvbufErrors=0`；后续压力窗口出现的
  系统 UDP 累计错误见 15.5，不能将其反向归因给当前 drops=0 的 ZeroTier socket。
- UPnP 配置关闭且无进程。OpenVPN 仅保留仓库设计的标准禁用骨架，1194 规则
  和三个历史 DNAT 均 `enabled=0`，无监听、无活动 nft 放行。
- firewall init 脚本不提供常驻 procd 实例，因此 `running` 返回 false；实际
  fw4/nft 规则完整存在。这不是防火墙停止。

### 15.4 本次确定的新内核故障

只读审计曾错误执行递归 `grep` 读取 `/sys/kernel/debug`，命中
`regmap/b111000.mailbox/registers` 后触发内核 panic。pstore 显示：

```text
PID: grep
pc: regmap_mmio_read32le
regmap_read_debugfs -> regmap_map_read_file
Unable to handle kernel paging request at ffffffc080e86000
Kernel panic - not syncing: Oops: Fatal exception
```

交叉验证结果：IPQ8074 DTS 为 `mailbox@b111000` 分配 `0x1000` 字节；当前
Qualcomm APCS mailbox 驱动共用 regmap 配置却将 `max_register` 设为
`0x1008`，该值用于 SDX55，但 IPQ8074 使用同一配置。regmap debugfs 的
`registers` 文件会从 0 读到 `max_register`，从而访问 IPQ8074 资源边界外。
当前 Linux 主线仍保留这组组合，已检查的 OrdinaryJoys、VIKINGYFY 和 qosmio
树中也未发现针对该边界的修复。

pstore 证据 SHA256：

| 文件 | SHA256 |
|---|---|
| `console-ramoops-0` | `749a0e9dfcf7296000a21c8d03783f0d7f45a84da0afb1731185d57ab355b4f5` |
| `dmesg-ramoops-0` | `07151ca3b25b9678d0dc8430b71d6d5ce857bcd4be1091513671e6c7a7f9adb9` |
| `dmesg-ramoops-1` | `369d77521a99262ee89bcc6800ce1bc6395a70f20f3311a4e5cae01868e92b3a` |

这不是正常 LAN/WAN/NSS 流量会触发的路径，而是 root 维护面 debugfs 读取漏洞。
当前禁止任何 `grep -R`、`cat` 或通用采集器读取整个 `/sys/kernel/debug`；
现有 `nss-check` 只读取白名单精确节点，不会触发该路径。修复应在独立源码
分支按 SoC/资源长度限制 APCS regmap 范围，完成编译、静态检查和离线审查后
再决定是否进入固件，不能在实机重复验证 panic。

### 15.5 当前压力测试与未关闭边界

外部 60 分钟脚本没有完整结束。25 分钟单流阶段传输 164 GiB，平均
938/938 Mbps，累计 3 次 TCP retransmission；并行 ICMP 为 0% 丢包，
路由到 Mac 平均约 1.62 ms，到 `223.5.5.5` 平均约 8.40 ms。温度约 57 C，
NSS/EDMA/端口错误未随流量增长，该阶段通过。

路由器端点 `iperf3 --bidir` 原计划 1200 秒，客户端在 1033.33 秒收到
`SIGTERM`。已完成窗口内 TX-C 平均 797 Mbps、0 retransmission，RX-C 平均
778 Mbps；该阶段只能记为部分通过。主脚本随后退出，UDP 梯度、burst、
bufferbloat、concurrent 和 FINAL AUDIT 均未执行。

测试结束后系统累计值为 `Udp InErrors=1365195`、
`Udp RcvbufErrors=1365195`，5 秒复核不再增长。当前六个 ZeroTier UDP socket
drops 均为 0，Clash 7895 socket drops=18；临时 iperf UDP socket 已关闭，
现有日志没有记录存活期 inode/drops，因而无法严谨确定 1,365,195 次错误属于
哪个已关闭 socket。EDMA `alloc_fail_cnt=102` 在压力前后不变，其他 EDMA
错误为 0，当前没有证据把这次应用/socket 接收层峰值归因给 EDMA/NSS。

测试日志将固件写为 `r0-84fc0f2`，其中 `84fc0f2` 实际是构建仓库提交前缀，
系统真实固件 revision 为 `r0-0ea8486`。这是测试报告标签歧义，不是刷错固件。

截至本节更新时间，仍不能关闭：

1. UDP 1,365,195 次 `RcvbufErrors` 缺少 socket 存活期归属证据；必须先修正
   测试脚本，再分别测试路由端点接收和两台 LAN 端点转发。
2. ZeroTier 高速上行 UDP receive-drop 需要独立定点测试，不能用当前空闲时
   socket drops=0 替代压力场景。
3. 双向 TCP 只完成 1033/1200 秒；UDP 梯度和综合压力阶段未执行。
4. 两台 Linux 同版本 iperf3 的 LAN-LAN 原生双向公平性仍未完成。
5. 24 小时压力、72 小时正常业务和 2.4 GHz IoT 客户端矩阵仍未完成。
6. APCS regmap 修复尚未编码和构建，不能宣称内核维护面已经完全无故障。

后续统一按 `AX6_CURRENT_FULL_STATUS_2026-08-03.md` 和
`AX6_NEXT_PROGRESS_AND_TEST_PLAN_2026-08-03.md` 执行；本节保留为 8 月 2 日
主报告的状态校正，不再把中途测试状态作为最终结论。
