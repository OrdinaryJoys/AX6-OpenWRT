# AX6 NSS 上游冲突审查、修复验证与后续方案

日期: 2026-07-02

## 当前结论

当前仓库修复不是单点补丁式修复,而是把实机确认的故障边界固化到源码、构建锁、CI rootfs 校验和运行审计工具里:

1. NSS/ECM 的本机终结流量丢包根因已按 `ecm.general.disable_offloads=1`、`disable_gro_list=1`、`br-lan` hotplug 复用官方 helper 的路径修复。
2. pbuf/N2H 已在源仓固定为 `S19qca-nss-pbuf`,并由最终 rootfs 校验防回归。
3. VLAN 默认策略保持 qosmio 说明要求: 不使用 DSA bridge VLAN filtering,改用 802.1q 子接口。
4. OpenClash 插件不再锁定固定提交或固定版本,构建时跟踪官方 `master`,同时不修改订阅文件和覆写文件。
5. VIKING/qosmio 上游的大改动不能整分支合并,只能按 AX6 相关路径选择性移植。

尚未做的事: 没有刷写实机,也没有把所有候选上游补丁继续合并。当前目标是稳定 AX6 固件,不是追平上游所有平台改动。

## 仓库与远端状态

| 仓库 | 最新检查点 | 当前判断 |
|---|---:|---|
| OrdinaryJoys/AX6-OpenWRT | `d4919964adf3ae528752a8563c1ac03599cc83d8` | 当前构建仓库 HEAD,工作区干净 |
| OrdinaryJoys/immortalwrt-nss | `0aea4a034fc7123003288a51bfec75f063a6777e` | 当前源码锁定提交,包含 S19 pbuf 与 qca-nss 稳定补丁 |
| VIKINGYFY/immortalwrt | `baee485f7f` | 相对本仓仍有大量差异,最新大块主要是 `qualcommbe` |
| qosmio/openwrt-ipq | `92a2d10414` | 相对本仓为另一套组织和 rebase 路径,不能直接合并 |
| immortalwrt/immortalwrt | `master=41c75c5a90`, `openwrt-24.10=253a70f1f8` | 官方主线有 AX6 stock nvmem 更新,需单独移植审查 |
| vernesong/OpenClash | `master=23896d2662`, `v0.47.110=23896d2662` | 构建跟踪 `master`,不再固定 `OPENCLASH_COMMIT` |

差异规模:

| 对比 | 提交差异 | 文件差异 | 结论 |
|---|---:|---:|---|
| `origin/main...viking/main` | `77 / 244` | 709 文件, `+20237/-40306` | 必须按目录/功能筛选 |
| `origin/main...qosmio/main-nss` | `5627 / 168` | 2082 文件, `+117336/-143973` | 不能整合,只能参考具体修复语义 |
| `origin/main...immortal/master` | 未作为 merge 基准 | 514 个 qualcommax/mac80211/wifi-scripts/hostapd 相关文件差异 | 官方非 NSS 主线,只能摘取与 AX6 stock layout 明确相关的修复 |

## 已通过验证

| 验证项 | 结果 |
|---|---|
| 本地 `git diff --check` | 通过 |
| 本地 `yamllint -d relaxed .github/` | 通过 |
| 本地 `actionlint -color .github/workflows/*.yml` | 通过 |
| 本地 `shellcheck -S error` | 通过 |
| 本地 `tests/test-vlan-add.sh` | 通过 |
| 本地 `tests/test-openclash-archive.sh` | 通过 |
| GitHub Actions `Lint` run `28554384967` | 成功 |
| GitHub Actions `Build OpenWRT for AX6-NSS` run `28554436442` | 成功 |
| 云端最终 rootfs 校验 | 成功,包含 `Validate final rootfs contents` |
| 发布标签 | `AX6_NSS_STOCK_20260702091829` 指向 `d491996` |

旧的 `Sync upstream check` run `28350588687` 失败原因是旧提交仍锁定 `OPENCLASH_COMMIT`,当时 OpenClash upstream 从 `a86fb8...` 移动到 `23896d...`。当前主分支已改为 `OPENCLASH_REF=master` 并只做引用可达检查,该旧失败不再代表当前故障。

## 必须保持的核心边界

| 子系统 | 必须保持 | 原因 |
|---|---|---|
| NSS/ECM | `packet_steering=0`, `flow_offloading=0`, `flow_offloading_hw=0` | NSS ECM 接管加速路径,避免 OpenWrt 通用 offload 争用 |
| ECM netdev offload | `ecm.general.disable_offloads=1`, `disable_gro_list=1` | IPQ807x 本机终结流量在 GRO/GSO/checksum 等 offload 开启时会丢包/重传 |
| br-lan | `100-disable_offloads_br_lan` 调用 `/lib/netifd/offload/disable_offloads.sh` | 解决 LuCI/SSH/DNS 等本机终结流量经过 bridge 时的慢加载 |
| pbuf/N2H | `S19qca-nss-pbuf`, `START=19` | 必须在 netifd 创建 ath11k AP 接口前应用 pbuf/N2H |
| WiFi NSS | `ath11k frame_mode=2`, `nss_offload=1` | 维持 ath11k NSS redirect 入口 |
| VLAN | 禁止 `option vlan_filtering 1`、`config bridge-vlan`、`lan1:u*` | qosmio 说明 bridge VLAN filtering 与 NSS WiFi offload 不兼容 |
| IRQ | 保留上游 `S93smp_affinity` 与 `S99set-irq-affinity`,自定义 `ax6-irq-affinity` 仅手动 | 避免多个 IRQ/RPS/XPS 脚本互相覆盖 |
| OpenClash | 不修改订阅文件、覆写文件,插件跟踪官方 `master` | 避免订阅更新覆盖修复或引入隐藏状态 |

## 已完成修复

| 仓库 | 修复 | 验证 |
|---|---|---|
| immortalwrt-nss | 合入 VIKING `bcc56131b8` 的 9 个 qca-nss 稳定补丁 | 源仓 clean,构建仓锁到 `0aea4a034f` |
| immortalwrt-nss | `qca-nss-pbuf` 固定早启动 `START=19` | CI 解包 rootfs 检查 `S19qca-nss-pbuf` |
| AX6-OpenWRT | `.github/ax6-nss-lock.env` 锁定新源码提交 | Lint 与 NSS 构建成功 |
| AX6-OpenWRT | OpenClash 改为 `OPENCLASH_REF=master` | Lint 检查禁止 `OPENCLASH_COMMIT/OPENCLASH_VERSION` |
| AX6-OpenWRT | `diy.sh` 读取 OpenClash 实际版本和提交 | 构建成功 |
| AX6-OpenWRT | rootfs 校验加入 pbuf/IRQ/offload/ath11k 关键文件检查 | `Validate final rootfs contents` 成功 |
| AX6-OpenWRT | `ax6-config-audit` 增加 OpenClash overlay 数据审计 | shellcheck 通过 |
| AX6-OpenWRT | `nss-check` 检查 ECM disable_offloads、VLAN、IRQ、pbuf、ZRAM 等 | shellcheck 通过 |

## 上游大改动拆解

### VIKINGYFY/immortalwrt

| 区域 | 变化 | 合并判断 |
|---|---|---|
| `baee485f7f improve qualcommbe support` | 新增/增强 IPQ5332/IPQ957x、PPE、NSSCC、ath12k caldata,43 文件 `+5117/-5` | 与 AX6 IPQ807x 主路径无直接关系,不合并 |
| `package/qca-nss` | 大量 patch 重命名/reorder,另有少量新增修复 | 已只合入确定安全的 9 个稳定补丁；剩余需单独分支验证 |
| `package/kernel/mac80211/files/qca-nss-pbuf.init` | 把 `START=19` 改回 `START=27`,运行后重启 WiFi,删除早期 OF/PCI/sysfs 检测 | 拒绝,会破坏 pbuf 早启动策略 |
| `package/qca-nss/qca-nss-ecm/files/disable_offloads.sh` | 从完整 offload helper 缩减为只关闭 `rx-gro-list` | 拒绝,会重新暴露 LuCI/SSH 本机终结流量丢包 |
| `991_set-network.sh` | 删除首次启动无条件关闭 packet steering/flow offload 的保护,只在 IPv6 分支里设置 `packet_steering=0` | 拒绝,会让 dirty config 或默认 offload 泄漏 |
| `smp_affinity` | `START=93` 改为 `START=29`,删除 UCI enable gating,强制运行 | 暂不合并,可能改变 EDMA/NSS/WiFi 初始化顺序 |
| `set-irq-affinity` | 从固定 `f` 改为动态 online CPU mask | 可作为候选,但需实机 IRQ/RPS/XPS 对比后再决定 |
| `wifi-scripts` | iwinfo/supplicant/scan/disabled vif 等修复 | 可候选,但会影响 WiFi 生成逻辑,需隔离测试 |
| `ath11k 999-922/999-923` | station rate reporting 与 tx status flags 修复 | 可候选,需要 WiFi NSS 运行与吞吐/断流验证 |

### qosmio/openwrt-ipq

| 区域 | 变化 | 合并判断 |
|---|---|---|
| qca-nss package tree | 对本仓表现为大量删除,说明组织方式不同 | 不能直接合并 |
| `7deb71dacb` dynamic VLAN | AP_VLAN/dynamic VLAN 初始化修复 | 当前仓已语义覆盖,不重复 cherry-pick |
| `819196f2be` AP_VLAN ext_vdev cleanup | AP_VLAN open/error cleanup | 当前仓已语义覆盖,不重复 cherry-pick |
| `823027c8b7` mesh tx flags | NSS mesh offload 保留 tx flags | AX6 默认不启用 mesh,低优先级候选 |
| `70e395a3e0` backports 6.18.26 rebase | 整套 backports/mac80211 NSS patch rebase | 高风险,只在需要整体 rebase 时做新分支 |
| `92a2d10414` kernel 6.12.92 rebase | 6.12 路径 rebase | 当前主线是 6.18,不适用 |

### immortalwrt/immortalwrt

| 区域 | 变化 | 合并判断 |
|---|---|---|
| `a949f0445e qualcommax: add nvmem support for xiaomi ax6/ax3600/ax9000 stock layout` | AX6/AX3600/AX9000 stock DTS 从删除 inherited `nvmem-cells` 改为在 `0:art` smem 分区下声明 fixed-layout MAC cells,并删除 ath10k caldata hotplug | 不能整提交 cherry-pick; 本仓 stock DTS/ath10k hotplug 有冲突。AX6 部分可作为单独候选,需保留/评估本仓 aliases 与多机型 caldata 脚本 |
| `da28c7a67e wifi-scripts: add EHT beamforming options to hostapd config` | hostapd 生成 EHT beamforming 选项 | AX6 是 WiFi 6/ath11k,不是 EHT/ath12k 主目标,暂不合并 |
| `92143f94b6 mac80211: notify driver on airtime weight changes` | mac80211 通知 driver airtime weight 变化 | 非当前故障根因,需等 NSS/WiFi 补丁栈同步窗口再评估 |
| `9c48477cf7 hostapd: fix misplaced radar-detected ubus notification` | DFS/radar ubus 通知修复 | 与当前 AX6 US 默认国家码和稳定性目标弱相关,暂不合并 |

## 剩余候选补丁分级

| 优先级 | 候选 | 状态 | 需要验证 |
|---|---|---|---|
| P1 | VIKING `qca-nss-drv/011-backport-fix-shaper-bounce-lock-unwind.patch` | 可单独评估 | qdisc/SQM 编译和运行 |
| P1 | VIKING `qca-nss-drv/012-fix-keep-core-stats-with-autoscale-disabled.patch` | 可单独评估 | NSS stats、autoscale、CPU 频率 |
| P1 | VIKING `qca-nss-ecm/007-fix-pcc-module-refcount-ordering.patch` | 可单独评估 | ECM 加载/卸载、PCC 未启用场景 |
| P1 | VIKING `qca-nss-ecm/008-backport-sfe-mcast-clear-pending-on-errors.patch` | 可单独评估 | multicast/IGMP 与 OpenClash 共存 |
| P2 | VIKING `qca-mcs/007-fix-wifi-events-quiet-without-nl80211.patch` | 低风险但低优先级 | 无 WiFi/no-nl80211 场景日志 |
| P2 | VIKING `qca-nss-dp/005-fix-switchdev-stp-fdb-roaming.patch` | 高风险候选 | bridge/FDB/STP/roaming/LAN SMB |
| P2 | VIKING `qca-ssdk/005/008/009/010` | 高风险候选 | switch link、MAC sync、LAN 断流 |
| P2 | VIKING ath11k `999-922/999-923` | 中风险候选 | WiFi NSS、速率显示、断流、2.4G/5G |
| P2 | 官方 `a949f0445e` 的 AX6 stock nvmem 子集 | 官方提交可解决 stock layout MAC/nvmem 描述缺口,但整提交冲突 | 单独 DTS 移植、dtc/编译、MAC/分区/校准交叉验证 |
| Hold | VIKING pbuf `START=27` | 拒绝 | 与当前修复方向冲突 |
| Hold | VIKING `disable_offloads.sh` 简化 | 拒绝 | 与实机根因修复冲突 |
| Hold | VIKING `991_set-network.sh` 简化 | 拒绝 | 与 NSS offload 防漏配置冲突 |
| Hold | qosmio 整分支 rebase | 拒绝 | 会替换包结构和 kernel patch 栈 |

## P1 单独验证进度

临时源码验证分支: `codex/ax6-p1-nss-candidates`

临时工作区: `/private/tmp/ax6-p1-nss-candidates`

基线: `0aea4a034fc7123003288a51bfec75f063a6777e`

远端状态: 已推送到 `OrdinaryJoys/immortalwrt-nss:codex/ax6-p1-nss-candidates`

| 顺序 | 提交 | 补丁 | 本地静态结果 | 风险判断 |
|---:|---:|---|---|---|
| 1 | `83f221f29b` | `qca-nss-drv/011-backport-fix-shaper-bounce-lock-unwind.patch` | 通过,只新增 1 个 patch 文件 | 纯锁配对修复,不触碰配置策略 |
| 2 | `76fec876c8` | `qca-nss-drv/012-fix-keep-core-stats-with-autoscale-disabled.patch` | 通过,只新增 1 个 patch 文件 | 会影响 NSS stats/autoscale 观测,需运行期确认 |
| 3 | `3356ab7cee` | `qca-nss-ecm/007-fix-pcc-module-refcount-ordering.patch` | 通过,只新增 1 个 patch 文件 | 纯 refcount 顺序修复,默认 PCC 未启用时风险低 |
| 4 | `8a22411dc1` | `qca-nss-ecm/008-backport-sfe-mcast-clear-pending-on-errors.patch` | 通过,只新增 1 个 patch 文件 | 修复 multicast 错误路径 pending 状态,需 IGMP/多播观察 |

已完成检查:

| 检查 | 结果 |
|---|---|
| 每个候选单独 `git diff --cached --check` | 通过 |
| 整体 `git diff --check origin/main..HEAD` | 通过 |
| 整体差异 | 4 文件,411 行新增 |
| 危险策略关键词扫描 | 未命中 `disable_offloads`、`qca-nss-pbuf`、`START=27`、`991_set-network`、`smp_affinity`、`vlan_filtering`、`bridge-vlan`、`packet_steering`、`flow_offloading`、`wifi up` |
| 本地 OpenWrt `package/*/prepare` | 未执行到补丁阶段: macOS Apple `make` 版本不支持 OpenWrt,本机也无 `gmake`/Docker |

下一步实际验证应在 Linux/GitHub Actions 中进行:

1. 推送 `codex/ax6-p1-nss-candidates` 源码分支。
2. 在 AX6 构建仓建立验证分支,把 `.github/ax6-nss-lock.env` 的 `SOURCE_COMMIT` 指向 `8a22411dc1`。
3. 触发 stock 构建并检查 `Compile firmware` 与 `Validate final rootfs contents`。
4. 如果组合构建失败,按 4 个独立提交回退定位;如果通过,再决定是否进入主线。
5. 实机验证仍需用户确认后进行,不自动刷写。

当前已完成第 1 步。第 2 步已在本地验证工作区完成并提交,随后修正了两个验证通道问题:

| 仓库 | 本地分支 | 本地提交 | 状态 |
|---|---|---:|---|
| AX6-OpenWRT | `codex/ax6-p1-nss-build-validation` | `8ca8fd6` | 已推送并触发云端 stock 构建 |

云端验证状态:

| Run | 结果 | 根因/状态 |
|---:|---|---|
| `28565743423` | 失败在 `Clone locked source code` | `git fetch origin <裸 SHA>` 无法抓取非默认分支提交,不是补丁失败 |
| `28565849017` | 失败在 `Clone locked source code` | 锁文件使用了错误的 40 位 SHA,真实 P1 HEAD 是 `8a22411dc1d0e50ba52bc015ba5ef193ee3bd7b4` |
| `28565953957` | 成功 | clone、feeds、DIY、package download、`Compile firmware`、`Validate final rootfs contents`、artifact/kmod 上传均通过 |

## P2 单独静态审查进度

P2 暂不进入构建验证分支。原因是这些补丁碰到交换、FDB、DSA、WiFi 用户态生成或 ath11k 运行路径,需要实机专项场景验证。

| 候选 | 静态拆解 | 风险判断 | 后续验证条件 |
|---|---|---|---|
| `qca-mcs/007-fix-wifi-events-quiet-without-nl80211.patch` | 处理 `NLMSG_ERROR`,无 nl80211 时返回 `-ENOENT`,把无 WiFi 场景日志从 error 降为 info | 低风险,但 AX6 有 WiFi,收益主要是日志降噪 | 可在 P1 通过后单独验证 |
| `qca-nss-dp/005-fix-switchdev-stp-fdb-roaming.patch` | 注册 netdevice notifier,端口离开 bridge 时恢复 STP forwarding;增加 FDB delete 递归处理 | 高风险,直接影响 bridge/FDB/STP/roaming 和 LAN 转发 | 必须做 LAN 单/多文件 SMB、桥接切换、端口上下线、FDB 观察 |
| `qca-ssdk/005-fix-dsa-link-polling-netdev-event.patch` | 移除 DSA blocking notifier,改用 NETDEV_CHANGE 触发 link polling | 高风险,改变 link polling 触发源 | 必须做有线端口 link flap、LAN2/lan* 断开重连、速率协商观察 |
| `qca-ssdk/008-fix-mac-sw-sync-lock-unwind.patch` | 修复 `mac_sw_sync_lock` 持锁 return 路径 | 单点 bugfix,但位于 SSDK switch 初始化任务 | 可作为 SSDK 子组里最低风险项单独验证 |
| `qca-ssdk/009-feature-nss-dp-netdev-mac-sync.patch` | 增加 `qcom,nss-dp` netdev 识别,NETDEV_CHANGE 时刷新 MAC SW sync | 高风险,直接影响 NSS DP 端口和 MAC sync | 必须和 005/008 一起做端口状态/吞吐/丢包测试 |
| `qca-ssdk/010-compat-drop-manual-phy-read-status.patch` | 删除手动 `phy_read_status()`,改信任 phydev 已缓存状态 | 中高风险,可能影响实时链路状态读取 | 必须做 PHY 状态与实际链路交叉验证 |
| `ath11k/999-922-ath11k-nss-fix-station-rate-reporting.patch` | NSS offload 绕过常规 mac80211 统计时,用 ath11k/NSS 缓存速率补全 station dump | 中风险,主要影响速率显示和统计路径 | 需要 WiFi 客户端连接、`iwinfo assoclist`、LuCI WiFi 状态、吞吐观察 |
| `ath11k/999-923-ath11k-fix-uninitialized-tx-status-flags.patch` | 在 `ath11k_dp_tx_complete_msdu()` 使用前初始化 `flags = skb_cb->flags` | 低到中风险,明确未初始化变量修复 | 可与 999-922 分开,优先单独编译验证 |
| `wifi-scripts` 四文件更新 | 修 HE/EHT/VHT 扫描输出字段、connected_time、EAP STA 生成、disabled vif key | 中风险,用户态生成逻辑变化,影响 netifd/wpa_supplicant/iwinfo | 需要 2.4G/5G AP、STA/EAP、扫描、重启 WiFi、禁用/启用 VIF 场景 |

P2 合并原则:

1. 不把 `qca-nss-dp/005` 和 `qca-ssdk/005/009/010` 混在 P1 中。
2. SSDK/DP 相关补丁必须建立单独分支,并先构建再实机测端口/FDB/link/SMB。
3. ath11k `999-923` 可作为下一个低风险候选;`999-922` 和 wifi-scripts 需 WiFi 观测验证。
4. 任何导致 link flap、FDB 异常、SMB 多文件掉速变差、WiFi 断流的新补丁必须立即回退。

已准备但未推送/未构建的隔离候选:

| 临时分支 | 提交 | 内容 | 当前验证 |
|---|---:|---|---|
| `/private/tmp/ax6-ath11k-999923-candidate` `codex/ax6-ath11k-999923-candidate` | `96a0f90fde` | 仅新增 VIKING `999-923-ath11k-fix-uninitialized-tx-status-flags.patch` | 已重放到 P1 基线;`git diff --check` 已通过,危险配置关键词无命中;等待 P1 主锁构建完成后再考虑云端构建 |
| `/private/tmp/ax6-ath11k-999922-candidate` `codex/ax6-ath11k-999922-candidate` | `b52d08da5a` | 仅新增 VIKING `999-922-ath11k-nss-fix-station-rate-reporting.patch` | 已重放到 P1 基线;`git diff --check` 已通过,危险配置关键词无命中;需 WiFi assoclist/速率显示实机验证 |
| `/private/tmp/ax6-qca-mcs-007-candidate` `codex/ax6-qca-mcs-007-candidate` | `35f03b6aed` | 仅新增 VIKING `qca-mcs/007-fix-wifi-events-quiet-without-nl80211.patch` | 已重放到 P1 基线;`git diff --check` 已通过,危险配置关键词无命中;等待 P1 主锁构建完成后再考虑云端构建 |
| `/private/tmp/ax6-stock-nvmem-candidate` `codex/ax6-stock-nvmem-candidate` | `aa5ee57c3b` | 仅移植官方 AX6 stock nvmem 子集到 `ipq8071-ax6-stock.dts`,保留本仓 aliases 和 `11-ath10k-caldata` | `git diff --check` 已通过;确认父层 `ipq8071-xiaomi.dtsi` 已引用 `macaddr_dp2..dp5`;仍需单独 stock 构建验证 |

已启动的 P2 构建验证:

| Run | 验证分支 | 源码候选 | 当前目的 |
|---:|---|---|---|
| `28581157917` | `codex/ax6-p2a-ath11k-999923-build-validation` | `codex/ax6-ath11k-999923-candidate` / `96a0f90fdeb4cf7575228424f948ff8f0f6f10f4` | 单独验证 ath11k `999-923` 是否通过 stock 构建和最终 rootfs 检查 |

## 当前仍需注意的问题

| 问题 | 状态 | 建议 |
|---|---|---|
| 实机是否已运行最新 `S19` 固件 | 未刷写,未实机验证新产物 | 需要用户确认后手动刷写/升级,再跑 `nss-check` 和页面/丢包测试 |
| `/overlay` 空间 | 属于实机空间管理问题,仓库不做小空间默认配置 | 只保留审计,清理由实机确认后处理 |
| OpenClash DNS | 不改订阅/覆写,避免更新覆盖 | 只检查官方 UCI 生成路径与运行日志 |
| ZeroTier | 仓库已有动态端口 firewall 修复,实机仍需按当前配置复查 | 需要实机只读检查运行状态 |
| 多文件 SMB 掉速/应用延迟 | 暂未证明是路由端核心驱动问题 | 应在新固件或当前固件下继续做定点链路/重传/IRQ 采样 |
| 上游继续移动 | VIKING 已出现 force update | 每次合并前必须重新 fetch 并按功能审查 |

## 下一步建议

1. 当前稳定分支不要再合入高风险上游大改动。
2. 单独开候选分支验证 P1 的 4 个 qca-nss 补丁,每次只合一组,构建和 rootfs 校验通过后再看是否进入主线。
3. P2 的 SSDK/DP/switchdev/WiFi 脚本类补丁必须实机专项验证,不能只靠编译成功。
4. 新固件手动升级后,实机验证顺序为: `nss-check`、`ax6-config-audit`、LuCI 大页面加载、OpenClash XHR、ping 丢包、LAN SMB 单文件/多文件、WiFi 2.4G/5G 稳定性。
5. 如果后续仍有 Web 卡顿或断流,优先采集 `ethtool -k br-lan/lan*/wan`、ECM sysctl、NSS stats、IRQ/RPS、`logread` 与 TCP 重传,再判断是否进入 SSDK/DP 候选补丁。

## 交叉验证方法

本仓后续修复必须按下面证据链验证,避免因为上游标题相似或单次构建通过而误合并:

| 修改类型 | 必须交叉检查 | 通过标准 | 禁止合并条件 |
|---|---|---|---|
| qca-nss-drv/qca-nss-ecm 补丁 | VIKING 原补丁、本仓 patch stack、危险关键词、云端 stock 构建、最终 rootfs | 只新增或最小修改 qca-nss patch;不触碰 pbuf/ECM offload/IRQ/VLAN 策略;`Compile firmware` 与 `Validate final rootfs contents` 通过 | 引入 `disable_offloads`、`qca-nss-pbuf`、`START=27`、`packet_steering`、`flow_offloading`、`vlan_filtering` 等策略变化 |
| pbuf/N2H | 本仓 `S19qca-nss-pbuf`、VIKING `qca-nss-pbuf.init`、最终 rootfs 解包 | rootfs 中只有早启动 `S19qca-nss-pbuf`,脚本 `START=19`,并保留 pbuf profile 与 ath11k sysfs/OF/PCI 检测 | 上游把 `START` 改回 27、运行后重启 WiFi、或删除早期检测逻辑 |
| ECM 本机终结流量 offload | 实机根因记录、`disable_offloads.sh`、`ecm.general.disable_offloads`、br-lan hotplug、nss-check | `disable_offloads=1`, `disable_gro_list=1`, br-lan hotplug 调用官方 helper,OpenWrt flow offload 关闭 | 只关闭 `rx-gro-list`、重新启用 software/hardware flow offload、或绕开 br-lan hotplug |
| WiFi/ath11k 补丁 | VIKING 补丁本体、mac80211 patch 应用顺序、WiFi NSS 参数、2.4G/5G 实机稳定性 | 不改国家码默认 US、不改 `frame_mode=2/nss_offload=1`,不改 UCI 默认兼容边界;编译和 WiFi 运行观察通过 | 混入 pbuf/ECM/VLAN/IRQ 策略,或导致 2.4G/5G 断流、assoclist 异常、速率/吞吐明显退化 |
| SSDK/DP/switchdev 补丁 | VIKING/qosmio 补丁语义、bridge/FDB/STP/link polling、SMB 单/多文件、端口 link flap | 必须单独分支、单独构建、实机端口上下线/FDB/吞吐/丢包观察通过 | 与 P1 混合合并,或无法解释 LAN 多文件掉速/link 状态变化 |
| VLAN 配置 | qosmio NSS support matrix、本仓 UCI 默认、`ax6-config-audit`、rootfs | 使用 802.1q 子接口方案,不启用 DSA bridge VLAN filtering | 出现 `option vlan_filtering 1`、`config bridge-vlan`、`lan1:u*` 等 bridge VLAN filtering |
| OpenClash | vernesong/OpenClash `master`/tag 引用、`diy.sh`、lint、运行审计 | 构建跟踪 `OPENCLASH_REF=master`,不固定 `OPENCLASH_COMMIT/OPENCLASH_VERSION`,不改订阅/覆写 | 写入订阅 YAML、修改 `openclash_custom_overwrite.rb` 作为默认修复、或锁死插件版本 |
| stock layout/nvmem | immortalwrt 官方提交、当前 DTS 父子关系、分区/ART/nvmem cell、ath10k/ath11k caldata | 只能按设备子集移植;AX6 stock 需验证 MAC cell、aliases、`0:art`、ath11k caldata 不被破坏 | 整提交 cherry-pick 导致 AX3600/AX9000 caldata 删除冲突,或未解释 stock layout 分区变化 |

每个候选必须保留四个结论:

1. 来源: 上游仓库、提交号、文件路径。
2. 影响面: 只列实际 touched path,不能用标题推断。
3. 冲突面: 与 NSS/ECM/WiFi/VLAN/IRQ/OpenClash/stock layout 哪些边界相交。
4. 验证面: 本地静态、云端构建、rootfs、实机只读/临时验证分别完成到哪一步。

## 当前不能误判的点

| 现象 | 正确判断 | 不能做的事 |
|---|---|---|
| P1 前两次云端失败 | 是验证分支 clone/锁定 SHA 问题,不是 qca-nss 补丁编译失败 | 不能因此回退 P1 补丁或判断补丁不可用 |
| P1 第三次构建 `28565953957` | 已通过编译与最终 rootfs 校验 | 可作为 P1 合入依据,但仍需后续新主锁构建验证 |
| 官方 `a949f0445e` 和 AX6 stock 有关 | 这是值得单独审查的 stock layout/nvmem 候选 | 不能整提交合并,也不能删除本仓 ath10k caldata 脚本影响其他设备 |
| ath11k `999-923` 静态通过 | 只证明单 patch 范围干净 | 不能和 P1 或 SSDK/DP 混合提交 |
| OpenClash `master` 与 `v0.47.110` 当前同指向 | 当前官方版本相同 | 不能把仓库重新改成固定 tag/ipk/raw core |

## P0-P2 执行队列

| 等级 | 范围 | 当前动作 | 当前状态 | 下一步 |
|---|---|---|---|---|
| P0 | 稳定主线防回归: NSS/ECM offload、pbuf S19、WiFi NSS 参数、VLAN 禁止项、OpenClash tracking、ZeroTier/UPnP/OpenClash 只读审计 | 主仓 `main` 扫描危险项、本地测试、云端 Lint | 本地 `test-vlan-add`/`test-openclash-archive`/`git diff --check` 通过;最新 Lint `28566358880` 通过 | 不合入会改变 P0 边界的上游脚本;继续等待 P1 构建完成 |
| P1 | 4 个 qca-nss-drv/qca-nss-ecm 低风险补丁 | 源码候选分支 `codex/ax6-p1-nss-candidates`;构建验证分支 `codex/ax6-p1-nss-build-validation` | `28565953957` 完整通过;P1 已 fast-forward 合入 `immortalwrt-nss/main`,AX6 主锁已指向 `8a22411dc1d0e50ba52bc015ba5ef193ee3bd7b4` | 推送 AX6 主线后触发 stock 构建,验证新主锁 rootfs |
| P2a | ath11k 低风险单补丁 `999-923` | 本地隔离候选 `/private/tmp/ax6-ath11k-999923-candidate` | 只新增 1 个 patch 文件,静态检查通过,未推送 | P1 通过后单独推送/构建,不能与 P1 混合 |
| P2b | ath11k `999-922` rate reporting | 本地隔离候选 `/private/tmp/ax6-ath11k-999922-candidate` | 只新增 1 个 patch 文件,静态检查通过,未推送 | 在 `999-923` 后单独构建;需 WiFi 客户端验证 |
| P2c | qca-mcs no-nl80211 日志降噪 | 本地隔离候选 `/private/tmp/ax6-qca-mcs-007-candidate` | 只新增 1 个 patch 文件,静态检查通过,未推送 | 可排在 ath11k 后单独验证 |
| P2d | qca-nss-dp/SSDK/switchdev/link polling/MAC sync | 只做静态拆解,不进入 P1 | 高风险,直接碰 LAN link/FDB/STP/SMB 路径 | 必须单独分支、单独构建、实机端口/FDB/SMB 测试后才允许合入 |
| P2e | wifi-scripts 用户态生成逻辑 | 只做静态拆解 | 中风险,影响 hostapd/wpa_supplicant/iwinfo/disabled vif | 需要 2.4G/5G、IoT、扫描、重启 WiFi 场景验证 |
| P2f | 官方 AX6 stock nvmem 子集 | 已验证整提交 cherry-pick 冲突;隔离候选 `aa5ee57c3b` 已准备 | 不能整提交合并;AX6 子集保留 aliases 和 `11-ath10k-caldata`,只修改 `ipq8071-ax6-stock.dts` | 等 P1 主锁构建完成后,单独推送候选并做 stock 构建验证 |

P0-P2 的推进规则:

1. P0 永远优先,任何 P1/P2 候选触碰 P0 边界即回退。
2. P1 只允许 qca-nss patch 进入,不允许混入 ath11k/SSDK/DP/WiFi 脚本。
3. P2 必须按子类单独分支,每个分支只验证一个影响面。
4. 需要实机验证的 P2 项只做只读/临时验证,不擅自刷写。

## P2 高风险拆解补充

| 子项 | 上游变化 | 风险点 | 当前结论 |
|---|---|---|---|
| P2d DP/SSDK 整组 | `qca-nss-dp`/`qca-ssdk` 共 17 个文件差异,包含重命名、删除旧 patch、新增 link/FDB/MAC sync 补丁 | 不是单点 bugfix,会影响 EDMA/NSS DP、DSA link polling、FDB 删除、STP forwarding、PHY 状态读取 | 不能整组合并;必须拆成 `008` 小修复、DP FDB/STP、SSDK link polling、MAC sync、PHY status 五类 |
| P2d `qca-nss-dp/005` | 注册 netdevice notifier,端口离开 bridge 时恢复 STP forwarding,并递归删除 lower device FDB | 直接影响 bridge/FDB/STP 和 LAN roaming/SMB | 高风险,必须实机端口/FDB/SMB 测试 |
| P2d `qca-ssdk/005` | 从 DSA blocking notifier 改成 NETDEV_CHANGE 触发 link polling | 改变链路事件触发源,可能影响 LAN2/lan* link flap 判断 | 高风险,必须端口上下线和速率协商测试 |
| P2d `qca-ssdk/008` | 修复 `mac_sw_sync_lock` 持锁 return 路径 | 纯锁释放修复,但在 SSDK 任务路径 | 可作为 P2d 中最低风险单独候选 |
| P2d `qca-ssdk/009` | 对 `qcom,nss-dp` netdev 增加 MAC SW sync refresh | 直接影响 NSS DP netdev 和 MAC sync | 高风险,必须和 005 联动验证 |
| P2d `qca-ssdk/010` | 删除手动 `phy_read_status()`,使用 phydev 缓存状态 | 可能影响实时链路状态读取 | 中高风险,必须用实际链路状态交叉验证 |
| P2e wifi-scripts | 修改 4 个文件,涉及 iwinfo VHT/HE/EHT 字段条件输出、assoclist `connected_time`、EAP `eap/phase2` 生成、disabled vif key 修复 | 用户态生成逻辑变化,可能影响 STA/EAP、扫描显示、禁用/启用 VIF | 不碰驱动参数,但仍需单独分支和 WiFi 场景验证 |
