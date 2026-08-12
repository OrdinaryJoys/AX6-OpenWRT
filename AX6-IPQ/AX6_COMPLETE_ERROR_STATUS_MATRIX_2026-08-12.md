# AX6 全部已发现错误与验证状态总表 (2026-08-12)

## 1. 状态定义

| 状态 | 含义 |
|---|---|
| A 已闭环 | 修复已进入仓库，静态/fixture/构建或既有实机证据满足该问题的关闭条件 |
| B 已修待验证 | 修复已进入当前独立分支，但尚未完成本轮云端构建、产物或实机验证 |
| C 部分修复 | 已降低或修复部分故障，但原现象仍可能复现，根因没有完全关闭 |
| D 未修 | 已确认存在，当前仓库没有最终修复 |
| E 未验证/阻塞 | 有风险或现象，但证据不足，缺端点、客户端、维护窗口或长期观察 |
| N 非故障/拒绝项 | 已确认是正常行为、策略状态或不适用于 AX6，不应据此改配置 |

本表以源码分支
`codex/ax6-regmap-pbuf-hardening-20260812@3854ea2aa18e977240b194d0fb35c5007e2e9f3b`
和构建分支 `codex/ax6-regmap-pbuf-build-validation-20260812` 为当前对象。没有合并主线、
没有生成本轮新固件，也没有用本轮候选修改实机。

当前共归类 75 个故障/风险条目：A=32、B=6、C=3、D=14、E=16、N=4；另列
15 个尚未完成的验证和发布动作。14 个 D 项中，10 个是已经封存、无法补救的旧测试
证据错误；当前产品/仓库真正明确未修的 4 项是 EDMA portable DMA、EDMA invalid
store 清理、NSS 调试日志级别和 OpenClash 重复 overlay core。

## 2. 核心驱动、内核与启动链

| ID | 已发现问题 | 当前状态 | 已完成 | 仍缺少 |
|---|---|---|---|---|
| K-01 | `qcom_hwspinlock` 包含式 `max_register=0x20000` 越过 0x20000 字节 MMIO，08-10 实机 panic | B | `1002` 使用 `min(原上限, size-stride)` 和小资源 guard；fixture 16/16 | 云端内核/DTB 构建、离线产物、新固件实机；当前旧固件仍禁止读取危险 debugfs |
| K-02 | APCS 原修复直接覆盖上限，可能扩大其他 SoC 范围并发生小资源下溢 | B | `1001` 改为 clamp；IPQ8074/IPQ6018/SDX55 22/22 | 本轮完整构建和新固件启动验证 |
| K-03 | NSS PBUF 写失败被吞、重复写代替确认、非零错误 profile 被接受 | B | PAGE_SIZE 对齐回读、零值有限重试、一次性分配保护、失败传播；8/8 | 完整构建和冷启动十轮 |
| K-04 | NSS `current_freq`/`auto_scale` 在 core 未初始化时可进入入口或 workqueue | B | 两个 sysctl 入口、IPQ60xx/IPQ807x 消费端保护；IPQ807x 检查 `npu_reg`；13/13 合并门禁 | qca-nss-drv prepare/编译、冷启动和频率日志回归 |
| K-05 | ECM multicast 将负接口数存入 `uint32_t`，负错误码可能变为巨大循环上限 | B | 精确移植 CodeLinaro `5ff84400`，覆盖 NSS/SFE IPv4/IPv6 四路径 | qca-nss-ecm prepare/编译和实机 IGMP/MLD/multicast 回归 |
| K-06 | 其他 NSS 启动 sysctl 可静默失败 | B | high-water、Wi-Fi pool、auto-scale、queue limit、RPS bitmap 精确回读 | 新固件启动日志和真实 readback |
| K-07 | EDMA portable DMA：RX 路径依赖 identity-DMA/`phys_to_virt(dma_addr)` | D | AX6 当前 identity-DMA 被门禁约束 | 独立 Track B 重构及非 identity-DMA 平台验证 |
| K-08 | EDMA invalid store index 可能跳过 descriptor 清理 | D | 当前 AX6 ring/store 约束降低命中面 | counter/warning、skb/DMA 清理模型和故障注入 |
| K-09 | EDMA 多 ring store 模型冲突 | C | 发布门禁固定 1/1/1/1，当前 AX6 符合 | 重构完成前不得扩大 ring 数 |
| K-10 | `phy_connect()` 失败/error-pointer teardown 路径证据不足 | E | 已有 DP 基础修复和静态门禁 | 精确故障注入与资源释放验证 |
| K-11 | NSS netlink 管理权限只观察到拒绝，未定位精确 handler | E | 基础权限拒绝符合预期 | GENL handler 级源码与运行验证 |
| K-12 | 全量读取 `dev.nss` 产生 warn/alert 级调试打印 | D/P2 | 不影响当前数据面 | 定向降低日志级别，不能夹带频率逻辑变更 |
| K-13 | NSS 与 OpenWrt software/hardware flow offload、通用 packet steering 冲突 | A | UCI、boot guard、rootfs 和审计门禁关闭冲突路径；保留 NSS 自有策略 | 每个新固件继续核对，不得回开 |
| K-14 | ECM host-terminated 流量 GRO/GSO/checksum 处理边界 | A/持续门禁 | `disable_offloads=1`、host-path 和物理口策略已进入仓库并做既有构建/实机验证 | 新固件仍需复核实际 ethtool/offload 状态 |
| K-15 | Linux RPS/RFS/XPS 被错误 overlay 禁用，LAN host-path 集中 CPU0 | A/本轮待复核 | 删除错误 overlay，枚举 `device` 与 `ports[]`；实机从 607/774 提升到 908/930 Mbps | 本轮候选构建后重启持久性复核 |
| K-16 | EDMA `alloc_fail_cnt` 累计 4990 | E | 11 个旧快照中未增长，不能判为活动故障 | 新固件 72 小时同负载增量窗 |

## 3. 网络、VLAN、IRQ 与服务配置

| ID | 已发现问题 | 当前状态 | 已完成 | 仍缺少 |
|---|---|---|---|---|
| N-01 | DSA `bridge-vlan`/`vlan_filtering=1` 与 NSS Wi-Fi offload 拓扑冲突 | A | boot/config audit 拒绝冲突；VLAN 使用 802.1q 子接口和独立 bridge | 新固件/新增 VLAN 后继续门禁 |
| N-02 | 旧 `vlan-add` 只创建部分 network，缺 firewall/DHCP/回滚/冲突检查 | A | 完整创建、输入检查和失败回滚；fixture PASS | 实机新增具体 VLAN 仍需用户确认 |
| N-03 | 自定义 IRQ 脚本与 qualcommax `set-irq-affinity` 所有权冲突 | A | 删除重叠 overlay，建立唯一所有权和 lint | 新固件启动后核对 affinity/RPS/RFS/XPS |
| N-04 | SQM 普通框架被误判为 NSS 冲突，可能缺运行依赖 | A | 保留 `sqm-scripts`/CAKE 依赖，SQM 默认关闭 | 启用 SQM 时需单独与 NSS qdisc 验证 |
| N-05 | ZeroTier 控制面 OK 但接口偶发无 managed 地址 | A | L3 reconcile health guard；真实 network restart 和故障注入通过 | 新固件回归 |
| N-06 | ZeroTier restart 返回非零但 replacement daemon 已 ONLINE | A | 以 PID/CLI online 二次判定，避免假失败 | 新版本插件更新时复核 |
| N-07 | ZeroTier 动态/secondaryPort 与 fw4 include 不一致 | A | 动态端口协调、`zerotier-fw4`、health/reconcile fixtures 均通过 | 新固件运行态复核实际 socket/规则 |
| N-08 | ZeroTier 高速上行 UDP receive drops | C | 4 MiB socket buffer 补丁、prepared-source 门禁已完成 | 高速 drops 仍未证明归零；需新固件、对齐版本、逐 socket 压测 |
| N-09 | OpenVPN 关闭后可能残留旧 zone/forwarding/DNAT | A | 只删除完全匹配旧模板的残留；禁用态审计和实机迁移通过 | 新配置恢复后复核 |
| N-10 | UPnP/5G 客户端隔离配置歧义 | A/N | 当前 UPnP 显式关闭且无映射；5G isolation 已关闭 | 若未来启用 UPnP，只能做受控 WAN/LAN 映射测试 |
| N-11 | ZRAM 仅选包、没有启动链验证 | A/观察 | 包、默认配置、启动链和审计已进入仓库；ZRAM 空闲为 0 不自动判故障 | 内存压力下验证压缩算法、CPU、OOM 和写回 |
| N-12 | root 密码被恢复流程覆盖或错误恢复 | A/运行态未知 | 备份/恢复脚本排除 `/etc/shadow`，密码由用户手动设置 | 本轮未重新读取或修改认证状态 |
| N-13 | LAN1 低速累计 rx_dropped | E | 错误子类为 0，短窗口曾不增长 | 新固件长窗口差分和同负载对比 |
| N-14 | EasyRSA 有两个 orphan certificate | E/P2 | 未发现服务故障，保留原文件 | 追溯用途后才能删除/归档 |

## 4. OpenClash、DNS、插件与构建供应链

| ID | 已发现问题 | 当前状态 | 已完成 | 仍缺少 |
|---|---|---|---|---|
| O-01 | OpenClash 进程存在但 DNS 活锁，普通 PID watchdog 不恢复 | A | 直接探测 `127.0.0.1:7874`，三次失败和冷却重启；SIGSTOP 故障注入通过 | 新固件运行回归；短暂重启窗口仍存在 |
| O-02 | 修改订阅/覆写作为 DNS 修复会被更新覆盖并产生叠加冲突 | A/N | 修复位于健康守护和运行合同，不修改订阅/覆写 | 保持当前边界 |
| O-03 | OpenClash moving ref 可能在单次构建中混合来源 | A/本轮待构建 | 先解析实际 commit，再按不可变 SHA 检出；记录版本和 Meta core SHA256 | 本轮新构建 provenance 重验 |
| O-04 | 设备 manifest 曾遗漏/递归误选 Packages.manifest | A/本轮待构建 | 唯一设备 manifest 与 rootfs opkg 清单门禁已在上一构建通过 | 本轮产物必须再次逐项一致 |
| O-05 | packages feed HEAD 引入 trafficshaper/freeradius3 Kconfig 递归依赖 | A | 保持兼容锁，只定向回移 cgi-io 安全修复；fixture PASS | 上游解决递归依赖前不得整 feed 更新 |
| O-06 | cgi-io malformed POST use-after-free | A | 锁定官方修复提交并有回移脚本/fixture | 本轮完整构建确认最终包来源 |
| O-07 | OpenClash ROM-identical overlay core 重复约 10.5 MiB | D/P2 | 空间仍有安全余量，未在线删除 upperdir | 只在干净刷写或离线维护时清理 |
| O-08 | Geo 数据更新占用 overlay | N/观察 | 用户要求保留自动更新；不做小空间仓库配置 | 监控更新峰值和剩余空间 |
| O-09 | OpenClash/ZeroTier bypass 与 DNS runtime contract 回归风险 | A | 相关 fixtures 全部通过 | 每次插件更新和最终 rootfs 重验 |
| O-10 | 构建锁曾错误/不可达、空 files 目录复制失败、失败仍继续 | A | 精确 commit 锁、source patchset、空目录兼容和 fail-fast 门禁 | 本轮云端执行 |
| O-11 | 本轮 source patchset/构建 workflow 尚无云端结果 | E/发布阻塞 | 202 present/15 absent、本地 SHA256 provenance PASS | 推送分支并完成一次 stock build |
| O-12 | 编译后 AX6 stock DTB 本地门禁未运行 | E/发布阻塞 | fixture 存在；本地缺 `dtc` | CI 必须执行并核对 aliases/nvmem/stock layout |
| O-13 | 本轮 kernel/rootfs/kmod/manifest/SHA256 产物不存在 | E/发布阻塞 | workflow 门禁已接入 | 构建成功后独立下载/解包审计 |

## 5. Wi-Fi、交换链路与性能现象

| ID | 已发现问题 | 当前状态 | 已完成 | 仍缺少 |
|---|---|---|---|---|
| W-01 | 2.4G 强制 HE40、`noscan`/共存策略可能导致 IoT 关联失败 | A | US、HE40、`ht_coex=1`，禁止 `noscan=1`；不强制隔离/proxy ARP | 受控 legacy/HT/HE 客户端矩阵 |
| W-02 | 运行时从 HE40 降到 20 MHz | N | 已确认是 20/40 coexistence 正常行为 | 不应据此改驱动 |
| W-03 | 个别 IoT 高 `tx failed`/低速或断流 | E | 未见持续 deauth/disassoc，不能归咎 HE40 | 按设备 MAC、芯片、RSSI、关联/DHCP/DNS 长稳矩阵 |
| W-04 | 5G `wifili_wbm_src_reo_code_inv` 随负载增长 | E/P2 | 未与用户可见丢包、crash 或端口错误同步 | 时间关联采样后再决定是否驱动修复 |
| W-05 | LAN-LAN 原生双向不公平，Windows 接收方向约 159-490 Mbps、反向约 944-947 Mbps | C/端点侧高疑 | 18 组 TCP、12 组单向 UDP、路由器本机对照和 PAUSE 计数完成；低速始终跟随 Windows 接收方向，所有阶段接口/softnet/qdisc/EDMA 活动错误增量为 0 | Windows NIC 驱动/固件、EEE/Green Ethernet、Flow Control、RSS/RSC/LSO/校验和、端口互换和第二个 Linux 端点逐项 A/B；尚未关闭用户可见现象 |
| W-06 | WAN-LAN NSS/ECM routed 双向上限未验证 | E/阻塞 | 新 routed-perf 工具和 fixture PASS；本轮 LAN1-LAN2 仅覆盖 SSDK/PPE 二层交换，不冒充 routed/NAT/NSS 测试 | 在 WAN 上游网络增加受控 iperf3 端点，确认路由、ECM connection delta 和 wan 计数后执行完整矩阵 |
| W-07 | NSS 固定中频是否是吞吐瓶颈 | E | 非持久中/高频 A/B 工具 fixture PASS | routed 双端点三轮 A/B；不能与 IRQ/GRO/内核同时改 |
| W-08 | split-NAPI 是否改善双向调度 | E/独立候选 | 只允许无 GRO 默认候选 | 双端点、reload、冷启动和长稳通过前不合入 |
| W-09 | AP_VLAN 在 ath11k NSS 路径为已知故障 | N/不支持 | 当前不启用、不宣称支持 | 只有上游明确修复和独立矩阵后再评估 |
| W-10 | NSS firmware 12.5 下 WDS/Mesh 不在当前验证基线 | N/不支持 | 当前仅按 AP/STA 基线 | 不用局部补丁强行开启 |

## 6. 旧验证备份中的错误

以下项目存在于
`r0-4e35043-validation-20260812`，原目录未修改。替代工具已进入仓库并通过 fixture，
但旧数据必须标记为 `PARTIAL / SUPERSEDED`。

| ID | 错误 | 状态 |
|---|---|---|
| T-01 | `P1.json` 为 0 字节，`--logfile` 与 JSON 输出使用错误 | D（旧数据不可修复；P1 文本仅可人工参考） |
| T-02 | 原 P2 用 `-d` debug 冒充双向 | D（旧结论作废） |
| T-03 | 原 P2 在 1155.76/1200 秒被 SIGTERM | D（旧结论作废） |
| T-04 | 脚本只有 `set -u`，阶段失败不可靠传播 | A（新仓库 perf 工具已 fail-fast；旧脚本仍不可用） |
| T-05 | 测试终结于路由器，未覆盖 NSS/ECM 转发 | A/E（新 routed 工具会拒绝 LAN 路径；尚未真实双端点执行） |
| T-06 | bidir 摘要只显示第一方向，P2 实际 887/804 却会报 887/887 | A（新工具按双向字段校验；旧摘要作废） |
| T-07 | S5 补测丢失原 `-P 4`，改变并发条件 | D（旧结果不可横向比较） |
| T-08 | P1 标称 60 秒窗口但未使用 `-i 60` | A（新工具不沿用该错误；旧窗口结论作废） |
| T-09 | S5/P2 同名 JSON 被后补测试覆盖 | A（新工具使用独立 run 目录；旧来源仍混合） |
| T-10 | Wi-Fi W1/W1R 上下行标签反向 | D（旧标签必须反向解释） |
| T-11 | 后补 S5/P2/W1/W1R 无前后 snapshot | D（旧数据无法补齐） |
| T-12 | softnet 十六进制字段直接 awk 累加，出现 339→33 不可能回退 | A（新工具保存原始/正确快照；旧汇总作废） |
| T-13 | UDP 900 Mbps 丢 52.59%，950 Mbps 又只丢 2.30%，单轮断崖不可复现 | E |
| T-14 | SSH 未固定 `IdentitiesOnly`、严格主机密钥和 known_hosts | D（旧脚本）；当前 routed-perf 已在工作区修复并通过 fixture，提交/CI 前保持 B |
| T-15 | `server.log` 只有 `Address in use`，没有 PID/版本归属 | D（旧 server 证据不完整） |
| T-16 | 目录无 SHA256/inventory，覆盖后不可验证完整性 | D（旧目录）；新测试必须生成 inventory |
| T-17 | P4 丢弃 stderr 且不检查每轮返回码 | D（40/40 只能作为有限参考） |
| T-18 | BB 对路由器本机压测，不能评价 WAN/SQM bufferbloat | E（需 WAN 端点重测） |
| T-19 | hwspinlock 草稿补丁尾部混入说明，`git apply` 在 line 87 损坏 | A（草稿废弃，使用源码提交 `3854ea2`） |
| T-20 | hwspinlock 草稿在 pointer 返回函数中使用裸 `return -EINVAL` | A（正式补丁使用 `ERR_PTR(-EINVAL)`） |
| T-21 | 本轮一次性 UDP 采集脚本和旧 `ax6-perf-test.sh` 使用了不存在的 EDMA 路径，阶段快照不能表示 EDMA 为 0 | A（明确标记一次性 UDP 阶段未采样；使用正确 `/sys/kernel/debug/qca-nss-drv/stats/edma/err_stats` 补采末态并生成 SHA256；仓库 routed-perf 原本即正确，旧 perf 工具已统一修复并增加 fixture） |
| T-22 | Windows iperf3 双向 UDP 在首轮报 `Resource temporarily unavailable` | E（工具/端点会话限制高疑；单向 12 轮有效，不把失败归因于 AX6，也不盲目重跑） |

## 7. 尚未完成的验证与发布动作

| ID | 项目 | 状态/条件 |
|---|---|---|
| V-01 | 推送源码和构建独立分支 | 尚未完成；外部执行额度受限 |
| V-02 | 本轮一次完整 stock 构建 | 尚未完成；不得用上一固件构建替代 |
| V-03 | DTB、rootfs、kmod、manifest、OpenClash provenance、SHA256 独立审计 | 等 V-02 产物 |
| V-04 | `sysupgrade -T` | 等通过离线审计的真实镜像；只预检不刷写 |
| V-05 | 新固件实机验证 | 需用户再次授权；当前不刷写、不重启 |
| V-06 | 物理冷启动十轮 | 需用户配合；逐轮查 PBUF、NSS、ath11k、pstore |
| V-07 | reload matrix 80 次 | 旧证据作废；新格式每场景严格 20/20 |
| V-08 | recovery 与回退镜像演练 | 需维护窗口和明确授权 |
| V-09 | 两台 Linux 有线端点完整吞吐矩阵 | 缺第二端点；用于关闭 W-05；W-06 另需 WAN 侧端点 |
| V-10 | 2.4G IoT legacy/HT/HE 矩阵 | 缺受控客户端 |
| V-11 | 24 小时压力和 72 小时正常业务 | 尚未完成；用于 alloc_fail、内存、DNS、ZT、Wi-Fi 长稳 |
| V-12 | ECM multicast/IGMP/MLD 实机回归 | 等新固件 |
| V-13 | 本轮新固件 RPS/RFS/XPS 重启持久性 | 等新固件重启测试 |
| V-14 | Linux 6.18.40/6.18.41 与 mac80211 后续更新 | 独立候选，先内核后 Wi-Fi，不混入本轮正确性修复 |
| V-15 | 主线合并、tag、Release | 所有发布阻塞门禁通过前禁止 |

## 8. 本次重新验证结果

- 源码门禁：hwspinlock 16/16、APCS 22/22、PBUF 8/8、NSS/ECM 13/13、EDMA PASS。
- 构建仓 source patchset：202 present / 15 absent，SHA256 provenance PASS。
- routed-perf、UDP baseline、旧 perf 替代工具和 reload validator fixtures：全部 PASS。
- 仓库顶层 fixtures：21 PASS；`test-ax6-stock-compiled-dtb.sh` 因本机无 `dtc` 返回 69，
  属环境未执行，不是测试失败，也不能标记为通过。
- 2026-08-12 新增实机性能复核：TCP 18 阶段、UDP 单向 12 阶段和路由器本机 9 阶段；
  负载期接口错误/丢包、softnet drop/time_squeeze、qdisc drop/overlimit/backlog、EDMA
  `alloc_fail` 增量均为 0。末态 `nss-check` 46/4/0、`ax6-config-audit` 30/3/0。
- 当前构建工作区的有意修改包括：三个性能/频率工具统一严格 SSH host-key、旧 perf
  的 EDMA 路径修复、对应 fixtures、总矩阵及本轮方案文档；源码工作区保持干净。
  两个当前候选分支均未推送，GitHub Actions 尚无本轮结果。
- 修正后的 NSS frequency A/B 工具已用 confirmed known_hosts 对实机执行只读 `status`：
  compatible、boot ID、`auto_scale=0`、`current_freq=748800000` 均与基线一致。

## 9. 当前总判断

当前没有证据要求回滚已经完成的 VLAN、RPS、OpenClash DNS、ZeroTier L3、OpenVPN、
flow-offload 或构建溯源修复。本轮新增的内核/NSS/ECM 修复在源码和 fixture 层成立，
但尚未进入云端固件和实机，因此统一保持 B 状态。

当前真正未修或未关闭的重点是：EDMA portable DMA/store 模型、NSS 调试日志级别、
ZeroTier 高速 UDP drops、Windows 接收方向双向性能根因、真实 WAN-LAN routed 性能、
IoT/invalid REO 关联、旧验证数据缺陷，以及完整构建、产物、冷启动、reload、长稳和
recovery 验证。当前证据不支持为解决 W-05 而默认关闭 PAUSE、合入 split-NAPI 或更换
NSS/SSDK/ECM 锁定版本。
