# AX6 无线栈与 EDMA 候选合并计划

日期: 2026-07-29

## 目标与边界

本计划只面向 Redmi AX6 stock layout 的 NSS-DP/ECM 固件。所有候选必须在
独立分支验证，不直接合并主线、不发布固件、不自动修改或刷写实机。

禁止整合以下上游范围:

- ImmortalWrt 2026-07-11 之后将 IPQ807x 切换到 PPE 的整套 qualcommax 网络栈。
- VIKINGYFY `20f42148a48` 的整提交。该提交同时修改 NSS-DP、NSS driver、
  ECM、IRQ、诊断脚本和 TMEL 补丁，与当前稳定分支存在多个语义冲突。
- VIKINGYFY `smp_affinity` 对所有物理 Ethernet 端口强制打开 GRO/checksum 的
  策略。当前 AX6 使用主机路径关闭、物理 NSS 数据面仅报告的分层策略。
- 默认开机启用 NSS high frequency。高频只用于受控 A/B。

## 当前已具备的修复

| 功能 | 当前实现 |
|---|---|
| EDMA 告警限速 | qca-nss-dp `006-ratelimit-edma-warnings.patch` |
| TX ring 取模 | qca-nss-dp `007-fix-tx-ring-modulo.patch` |
| NSS 初始化保护 | qca-nss-drv `017-guard-auto-scale-against-uninit-core.patch` |
| NAPI IRQ 回滚 | qca-nss-drv `018-fix-napi-request-irq-unwind.patch` |
| N2H DMA 回滚 | qca-nss-drv `019-fix-n2h-pool-dma-unwind.patch` |
| 频率统计与读取 | 融合后的 `012-fix-autoscale-stats-and-current-freq-read.patch` |
| ECM 主机路径 | `br-lan` 强制关闭，物理 NSS 数据面端口 `report` |

以上修复不得被上游同名补丁重复叠加。

## 候选 A: wifi-scripts

只选择 2026-07-16 至 2026-07-22 的 wifi-scripts 修复，不合并 qualcommax PPE
转换。重点候选包括 handler 竞争、wdev 状态、country_code 和多 device path。

已确认冲突文件:

- `files/lib/netifd/wireless-device.uc`
- `files/usr/share/hostap/wdev.uc`
- `files-ucode/lib/netifd/wireless/mac80211.sh`
- `files/lib/netifd/wireless/mac80211.sh`
- `files/usr/share/ucode/wifi/utils.uc`

合并要求:

1. 按上游提交时间顺序移植，不用最终目录覆盖当前目录。
2. 保留默认国家码 US。
3. 保留 2.4 GHz HE40 与 20/40 coexistence。
4. 保留 5 GHz 固定信道 `noscan=1`，不得重新引入 ACS 覆盖。
5. 不改变 NSS WiFi offload、VLAN 和 OpenClash 策略。

## 候选 B: hostapd 2026-07-09

上游提交 `345404476ac` 不能直接 cherry-pick。新源码已经包含当前补丁
`001-008` 的 MLD 修复，继续保留会导致重复应用或编译失败。

合并要求:

1. 更新 hostapd 源码版本和 hash。
2. 删除确认已经上游化的补丁，不按文件名猜测。
3. 逐一刷新 mesh、noscan、ubus、ucode 和 APuP 补丁。
4. 保留 OpenWrt multicall 和本仓固定信道逻辑。
5. 单独编译 `hostapd-common` 与 `wpad-openssl` 后再构建完整固件。

## 候选 C: mac80211 6.18.39

上游提交 `aac6df7bdc7` 对普通补丁的上下文修改较小，但当前仓库额外包含完整
ath11k NSS patch stack，不能依据三方文本自动合并结果判断兼容。

合并要求:

1. 只更新 mac80211/backports 版本，不删除 `patches/nss`。
2. 执行完整 mac80211 prepare，任何 fuzz 或 reject 都视为失败。
3. 编译 `kmod-cfg80211`、`kmod-mac80211`、`kmod-ath11k`。
4. 检查 ath11k recovery、peer statistics、NSS queue drop 和 threaded NAPI 补丁。
5. 在候选 A、B 分别通过后再开始，避免同时更换三个无线层次。

## 候选 D: EDMA split-NAPI

VIKINGYFY 最终补丁位于 `a4638cd4389` 的
`007-edma-v1-split-napi-gro.patch`。它同时包含正确性修复、RX/TX NAPI 拆分、
IRQ 回滚、DMA 生命周期、描述符检查和 GRO 功能，必须拆开验证。

### D1 正确性部分

- DMA mapping error 检查和 DMA 地址生命周期。
- RX/TX descriptor store index 边界检查。
- `platform_get_irq()` 负值处理和已申请 IRQ 计数回滚。
- 排除已经存在的 TX ring modulo 和 qca-nss-drv 018/019 重复修复。

### D2 性能部分

- RX descriptor/fill 使用独立 RX NAPI。
- TX completion 使用独立 TX NAPI。
- RX 和 TX completion IRQ 分配到不同 CPU。
- 保留 misc IRQ 的明确所有者，不同时运行第二套 IRQ 覆盖脚本。

当前实机四个 EDMA IRQ 的 configured/effective affinity 均为 CPU3。5 秒空闲采样
中 EDMA IRQ 无增长，NSS queue0 和 NET_RX 主要分布在 CPU0/CPU3。因此 split-NAPI
是高负载慢路径候选，不能仅凭空闲累计值认定为双向吞吐根因。

### D3 GRO 部分

GRO 必须是第三个独立变量:

- 初始 split-NAPI 候选保持当前功能状态，不默认启用 GRO。
- `br-lan` 始终执行主机路径关闭策略。
- 只对物理 NSS 数据面端口做 GRO on/off A/B。
- 每次测试 DNS、DHCP、UDP、LuCI、SSH 和本机终结流量。

## 候选 E: nss_freq

VIKINGYFY 默认 `mid` 与当前 `auto_scale=0` 后保持当前中频的策略基本等价。
候选只加入手动诊断命令，不默认启用 init 服务。

使用 high A/B 的前置条件:

- `current_freq` 可读写且两个 NSS core 已初始化。
- 记录测试前后频率、温度、功耗和系统负载。
- 同一客户端、同一链路、同一流数分别测试 mid/high。
- 测试后恢复 mid；任何超温、重启或错误计数增长立即终止。

## 构建门禁

每个候选必须独立通过:

1. `git diff --check`、shellcheck、actionlint、yamllint。
2. NSS patch prepare 和来源锁校验。
3. qca-nss-dp、qca-nss-drv、ath11k NSS 和相关 kmod 编译。
4. STOCK DTB、sysupgrade、recovery、rootfs、manifest 和 SHA256。
5. 最终 rootfs 必须包含 ZeroTier 标量渲染、ECM 四项迁移和单次 offload 调用。

## 实机 A/B 门禁

需要用户确认后才能进行:

1. 测试前备份并记录当前固件、配置和计数器。
2. 同时测试单向、反向、`iperf3 --bidir`、多流 TCP 和 UDP。
3. 同步采集 `/proc/interrupts`、`/proc/softirqs`、CPU、温度和 NSS/EDMA 计数。
4. 检查 LAN/WAN errors、drops、TCP retrans、UDP receive errors。
5. 验证 ZeroTier 不再周期性重写，OpenClash DNS 与 LuCI 无慢请求。
6. 持续压力至少 30 分钟，随后空闲跟踪至少 30 分钟。

任何候选失败时只回退该候选，不把失败修复带入下一阶段。
