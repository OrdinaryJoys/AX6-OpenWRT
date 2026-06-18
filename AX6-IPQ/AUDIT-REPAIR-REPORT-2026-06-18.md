# AX6 OpenWrt/NSS 检查、修复与遗留问题总报告

> 报告对象：`OrdinaryJoys/AX6-OpenWRT`  
> 工作分支：`codex/p0-ax6-stability`  
> 已验证提交：`0b75a6b590cb72e267b485ab76e8e37859942fdc`  
> 报告快照日期：2026-06-18（Asia/Shanghai）  
> 适用设备：Xiaomi AX6，重点为 STOCK 128MB NAND 变体  
> 安全边界：本轮未刷写路由器；“通过”表示代码、配置、云端编译和 rootfs
> 内容验证通过，不等同于所有现场网络拓扑和客户端均已完成实机验证。

## 1. 结论摘要

| 项目 | 当前结论 | 证据或限制 |
|---|---|---|
| 本地工作区 | 干净 | `git status` 无未提交修改（新增本报告前） |
| 测试分支 | 已推送 | 远端 `codex/p0-ax6-stability` 指向 `0b75a6b...` |
| STOCK NSS 固件 | 云端构建成功 | Actions run `27614279917` |
| 最终 rootfs 内容 | 验证成功 | `Validate final rootfs contents` 步骤成功 |
| Release | 已生成 | `AX6_NSS_STOCK_20260616203522` |
| NSS/WiFi/VLAN/ZRAM/IRQ 启动文件 | 已纳入构建验证 | rootfs 校验检查对应文件与启动链接 |
| ZeroTier/UPnP/OpenClash | 已加入只读审计 | 不再由启动脚本猜测或强制修改场景策略 |
| 静态检查 | 通过 | `actionlint`、`yamllint`、`shellcheck`、`git diff --check` |
| 实机运行状态 | 尚未由本报告确认 | 仍需在人工刷写后执行运行时检查 |
| 当前最高风险 | **锁定 NSS feed 仓库已不可访问** | 2026-06-18 返回 `Repository not found`，会破坏后续从零重构 |
| 合并状态 | 尚未合并到 `main` | 测试分支为 `0b75a6b...`，远端 `main` 仍为 `190d071...` |

## 2. 修复提交链

| 顺序 | 提交 | 日期 | 作用 | 构建结果 |
|---:|---|---|---|---|
| 1 | `71a4ce9` | 2026-06-15 | 应用 P0 NSS、WiFi、VLAN、IRQ 等稳定性修复 | 首次构建失败，后续继续修正 |
| 2 | `ceb951d` | 2026-06-15 | 处理空自定义 files 目录，避免构建复制失败 | 构建成功 |
| 3 | `4f3cb24` | 2026-06-15 | 保留 Release 来源提交和固件安全说明 | 纳入后续构建 |
| 4 | `276c4a0` | 2026-06-15 | 移除自动覆盖上游 IRQ 策略的行为 | 构建成功 |
| 5 | `0b75a6b` | 2026-06-16 | 完成构建锁、rootfs 验证、WiFi/VLAN/审计工具等加固 | STOCK NSS 完整构建成功 |

## 3. 已检查范围

| 范围 | 已检查内容 | 当前状态 |
|---|---|---|
| Git 工作区 | 分支、提交、未提交文件、远端 HEAD | 已检查 |
| GitHub Actions | NSS 构建、历史失败、最终 rootfs 校验、Release 上传 | 已检查 |
| 构建可复现性 | 源码、feeds、SQM、Argon、OpenClash 的完整 SHA 锁定 | 已修复，但 NSS feed URL 新近失效 |
| NSS | ECM、驱动包、netlink、qdisc、flow offload 冲突、frame mode、启动链 | 已检查和加固 |
| WiFi | US 国家码、regdom、2.4G HE40/20 共存、IoT 兼容项、SSID 策略所有权 | 已检查和加固 |
| SQM | `sqm-scripts-nss`、普通脚本框架、CAKE 依赖和运行脚本选择 | 已检查和加固 |
| VLAN | NSS WiFi 不兼容的 DSA bridge VLAN filtering、802.1q 辅助工具 | 已修复 |
| ZeroTier | daemon、接口、路由授权、DNS、动态 nftables include | 已加入只读审计 |
| UPnP | secure mode、最终 deny 规则、内部接口、私网 WAN | 已加入只读审计 |
| OpenClash | 独立版本锁、核心进程、DNS 重定向、残留 DNS 单点依赖 | 已加入构建锁和只读审计 |
| ZRAM | 包依赖、swap、启动链接 `S15zram` | 已加入配置和 rootfs 校验 |
| IRQ/RPS | 上游服务链、自定义脚本冲突、NSS internal RPS | 已修复和加固 |
| 文档 | 硬件变体、VLAN、IRQ、WiFi、刷写边界、检查命令 | 已修正 |
| 上游仓库 | VIKINGYFY、qosmio、OrdinaryJoys 源分支、NSS feed | 已交叉检查 |

## 4. 问题与处理状态总表

### 4.1 已修复的确定问题

| 优先级 | 问题 | 根因 | 影响 | 修复结果 |
|---|---|---|---|---|
| P0 | 构建输入未完整锁定 | 源码和外部 feeds 可能随分支移动 | 同一提交产生不同固件，难以复现和追责 | 新增统一锁文件并在 workflow 中校验完整 SHA |
| P0 | NSS 构建可能混入普通 flow offload | firewall4/netfilter offload 与 NSS ECM 所有权冲突 | 加速路径冲突、连接异常或性能不稳定 | 固定关闭 UCI flow offload，并检查冲突模块 |
| P0 | 自定义 IRQ 脚本自动覆盖上游策略 | 同时存在 qualcommax/NSS 和本地 IRQ 亲和性逻辑 | WiFi/NSS IRQ 被反复重写，可能造成性能回退 | 删除自动 init/hotplug 覆盖，仅保留手动基准工具 |
| P0 | VLAN 守护脚本会开机删除用户配置 | 将拓扑审计实现为破坏性自动修复 | VLAN 配置丢失、网络中断、难以恢复 | 删除 `95-ax6-nss-vlan-guard`，改为只读报告 |
| P0 | DSA bridge VLAN filtering 与 NSS WiFi 冲突 | 使用 `vlan_filtering=1` / `config bridge-vlan` | NSS WiFi offload 失效或 VLAN/WiFi 异常 | 审计并拒绝该拓扑，改用 802.1q 子接口 |
| P0 | `vlan-add` 只创建部分配置 | 缺少 firewall、forwarding、DHCP 和冲突检测 | VLAN 创建后不可用或形成重复 zone | 补全 network/firewall/DHCP，并加入完整输入检查 |
| P0 | WiFi 2.4G 强制 HE40 但缺少共存保护 | `HE40` 与 `noscan`/共存配置不一致 | 老旧 IoT 设备关联失败、邻频环境不稳定 | 使用 `HE40 + ht_coex=1`，禁止 `noscan=1` |
| P0 | WiFi 启动脚本强制场景策略 | 隔离、proxy ARP、多播转换等不应全局猜测 | 智能家居发现、配网或局域网访问失败 | 启动阶段只管理通用无线参数，不强制 SSID 策略 |
| P0 | regdom 只写 UCI，运行时可能未同步 | cfg80211 国家码与 UCI 状态可能不同步 | 功率、信道和可用频段不一致 | 新增 `ax6-wifi-regdom`，同步 UCI 和 `iw reg set` |
| P0 | 构建未验证关键 rootfs 文件 | 编译成功不代表脚本、模块和启动链接进入镜像 | 生成“成功”固件但运行时缺功能 | 增加最终 rootfs 内容校验步骤 |
| P1 | 选择了不存在的 `kmod-qca-nss-nft` | 配置引用了锁定源/feed 中不存在的包 | defconfig 或编译失败 | 从配置中移除并加入 lint 防回归 |
| P1 | `sqm-scripts-nss` 依赖不完整 | 误将普通 SQM 框架和 CAKE 包视为 NSS 冲突 | NSS SQM 脚本缺运行框架 | 保留 `sqm-scripts` 与 `kmod-sched-cake` 依赖 |
| P1 | ZeroTier/UPnP/OpenClash 配置可能被自动猜测 | 场景相关策略混入默认/启动脚本 | 安全策略错误、DNS 或路由被意外修改 | 改为 `ax6-config-audit` 只读审计 |
| P1 | OpenClash 版本和来源可能漂移 | 从 LuCI feed 取得的版本与预期不一致 | 配置、脚本和核心版本组合不可复现 | OpenClash 独立固定版本和完整 SHA |
| P1 | ZRAM 只选包但未验证启动链 | 包存在不等于 swap 实际初始化 | 内存压力下 OOM 风险增加 | 检查 `kmod-zram`、`zram-swap` 和 `S15zram` |
| P1 | Release 可能缺少来源信息 | 构建标签未明确绑定 workflow 提交 | 无法确认固件对应代码 | Release 固定记录 `${{ github.sha }}` 和锁文件 |
| P1 | 空 files 目录导致复制步骤失败 | workflow 假设自定义目录一定含文件 | 构建提前失败 | 对空目录和复制过程做兼容处理 |
| P2 | 文档中的 VLAN/IRQ 说明与实现不一致 | 历史行为变化后文档未同步 | 用户按旧说明执行错误配置 | 更新 `README.md` 和 `HARDWARE.md` |

### 4.2 尚未解决或需要额外验证的问题

| 优先级 | 遗留问题 | 当前证据 | 影响 | 建议下一步 |
|---|---|---|---|---|
| **P0** | `VIKINGYFY/nss-packages-618` 已不可访问 | 2026-06-18 `git ls-remote` 返回 `Repository not found`；VIKINGYFY 公开仓库列表中也不存在 | 当前锁定构建无法从零重新拉取 NSS feed | 在 OrdinaryJoys 账号建立已验证提交 `2d826ed...` 的只读镜像，或迁移到新版内置 `package/qca-nss` 方案；迁移后重新全量构建 |
| P0 | 测试修复尚未合并到 `main` | 测试分支 `0b75a6b...`，远端 `main` 为 `190d071...` | 默认分支仍不包含本报告修复 | 在解决 NSS feed 可用性后，通过 PR 合并测试分支 |
| P0 | 新 VIKINGYFY 上游已迁移 qca-nss | 2026-06-17 `b22a17c... update qca-nss`，大量 NSS 包迁入 `package/qca-nss` | 旧外部 feed 架构可能已被上游替代 | 单独建迁移分支，不要在已验证分支直接覆盖；比较包名、init、pbuf、ECM 和 firmware |
| P1 | 最新上游尚未在本仓库完成集成构建 | VIKINGYFY `main` 已从 `46878c...` 移动到 `b22a17c...` | 可能错过修复，也可能引入新回归 | 先同步 `OrdinaryJoys/immortalwrt-nss` 候选分支，再跑 STOCK/EXPAND 构建矩阵 |
| P1 | 只完成 STOCK 变体构建验证 | 成功 Release 为 `AX6_NSS_STOCK_20260616203522` | EXPAND 256MB NAND 变体未由本轮重新验证 | 仅在确有 256MB 硬改设备需求时触发 EXPAND 构建 |
| P1 | 未完成路由器实机运行时验证 | 本轮明确未刷写 | 无法证明真实无线环境、NSS 计数器、VLAN 和客户端兼容性 | 人工升级后执行第 11 节运行时检查 |
| P1 | 未做多型号 IoT 客户端回归矩阵 | 只修正了最可疑通用配置 | 某些 WPA/PMF/隐藏 SSID/配网应用仍可能失败 | 对典型 2.4G IoT 设备记录芯片、加密、RSSI、关联日志 |
| P2 | 本机存在两个 AX6 仓库副本 | `AX6-OpenWRT` 与 `OrdinaryJoys-AX6-OpenWRT` 同时存在，前者停在旧 `main` | 容易在错误目录修改或构建 | 后续操作统一使用 `OrdinaryJoys-AX6-OpenWRT`，旧副本只读归档或明确标记 |

## 5. 子系统修复说明

### 5.1 NSS、ECM 和 flow offload

| 检查项 | 期望状态 | 实现位置 |
|---|---|---|
| NSS 驱动/ECM 包 | 启用并进入 rootfs | `.config-*`、`nss-extra.config`、构建 rootfs 校验 |
| NSS netlink/qdisc | `kmod-qca-nss-drv-netlink=y`、`qdisc=y` | `AX6-IPQ/nss-extra.config` |
| 普通 flow offload | UCI 软件/硬件 flow offload 均为 `0` | `98-nss-tune`、`ax6-boot-guard`、`nss-check` |
| packet steering | 全局 `network.globals.packet_steering=0` | `ax6-boot-guard` |
| 设备级伪配置 | 不再写入 device section | lint 防回归 |
| NSS/WiFi frame mode | 运行时由 `nss-check` 检查 | `AX6-IPQ/files/sbin/nss-check` |
| ECM 连接计数 | 运行时检查 debugfs | `nss-check` |

### 5.2 WiFi 与 IoT 兼容性

| 项目 | 修复后策略 | 说明 |
|---|---|---|
| 默认国家码 | `US` | 用户已明确要求；可由 `/etc/config/ax6_wifi_country` 覆盖 |
| 运行时 regdom | UCI 与 `iw reg set` 同步 | 由 `S10ax6-wifi-regdom` 启动服务执行 |
| 2.4G 模式 | WiFi 6 / `HE40` | 保留性能目标 |
| 20/40 MHz 自动共存 | `ht_coex=1`，不允许 `noscan=1` | 邻频环境下允许回退到 20MHz |
| legacy rates | 保持启用 | 降低老旧 IoT 无法关联的概率 |
| WMM | 审计禁用情况 | 802.11n/ac/ax 需要 WMM |
| PMF/WPA3-only/隐藏 SSID | 只告警，不自动改 | 这些选项高度依赖 SSID 安全需求 |
| 客户端隔离 | 不再全局强制 | 5G 隔离和访客隔离由具体 SSID 管理 |
| proxy ARP / multicast-to-unicast | 不再默认强制 | 避免破坏 mDNS、发现和智能家居配网 |

### 5.3 SQM

| 项目 | 当前处理 |
|---|---|
| NSS SQM 脚本 | `sqm-scripts-nss=y` |
| 脚本框架 | `sqm-scripts=y` 作为运行依赖 |
| CAKE 依赖 | `kmod-sched-cake=y` 作为框架依赖 |
| 推荐运行脚本 | `nss-zk.qos` |
| 非 NSS 脚本启用 | `ax6-config-audit` 告警其会走 CPU 路径 |

### 5.4 VLAN

| 项目 | 当前处理 |
|---|---|
| 禁止拓扑 | `option vlan_filtering 1`、`config bridge-vlan`、DSA bridge VLAN filtering |
| 推荐拓扑 | `lanX.<VID>` 802.1q 子接口 + 独立 bridge |
| 自动删除用户 VLAN | 已取消 |
| `vlan-add` | 创建 bridge、静态接口、firewall zone、WAN forwarding 和 DHCP |
| 冲突检查 | VLAN ID、IPv4 CIDR、端口、network/device/firewall/DHCP section 和匿名 zone 名称 |
| WiFi SSID | 保持手动配置，避免猜测密码、隔离和安全策略 |

### 5.5 ZeroTier

`ax6-config-audit` 只读检查以下内容：

| 检查项 | 风险 |
|---|---|
| daemon 与 `zt*` 接口 | 服务启用但运行失败 |
| network id | 启用网络缺少 ID |
| `allow_default` | 远端安装默认路由 |
| `allow_global` | 接受全局路由 |
| `allow_dns` | 远端替换 DNS |
| DHCP proto | ZeroTier 接口不应由 DHCP 管理地址 |
| nftables input/forward/srcnat include | 授权开启但动态规则缺失或格式错误 |

### 5.6 UPnP

| 检查项 | 期望状态 |
|---|---|
| `secure_mode` | 启用 UPnP 时必须为 `1` |
| 权限规则 | 最后一条为完整默认拒绝 |
| internal interface | 不得包含 WAN |
| 私网 WAN | 给出上游 NAT/CGNAT 可能导致映射失败的告警 |
| 默认启用状态 | 不由仓库启动脚本强制决定 |

### 5.7 OpenClash 和 DNS

| 检查项 | 当前处理 |
|---|---|
| OpenClash 来源 | 独立 URL、版本和完整 SHA 锁定 |
| 核心进程 | 启用时检查 `clash` 是否运行 |
| Dnsmasq Redirect | 检查是否指向本地 OpenClash DNS 端口 |
| Firewall Redirect | 检查 nftables `openclash_dns_redirect` 链 |
| 停用残留 | OpenClash 停用后仍指向本地 DNS 端口则 FAIL |
| DNS 单点依赖 | Dnsmasq Redirect 模式明确告警核心故障会影响全网 DNS |
| 自动修改 | 审计工具保持只读，不重写用户代理策略 |

### 5.8 ZRAM

| 检查项 | 当前状态 |
|---|---|
| `CONFIG_SWAP` | 由配置和运行时 `/proc/swaps` 检查 |
| `kmod-zram` | 已选中 |
| `zram-swap` | 已选中 |
| 启动链接 | 构建时验证 `S15zram` |
| 运行时 | `nss-check` 要求 `/dev/zram` 已加入 swap |

### 5.9 IRQ/RPS

| 项目 | 修复后所有权 |
|---|---|
| EDMA IRQ | 上游 `S93smp_affinity` |
| NSS 驱动/RPS | 上游 `S94qca-nss-drv` |
| NSS pbuf/hash bitmap | 上游 `S95qca-nss-pbuf` |
| Linux RPS/XPS | 上游 `S99set-irq-affinity` |
| 自定义 `ax6-irq-affinity` | 仅保留手动 `show/apply` 基准工具 |
| WiFi hotplug 重写 IRQ | 已删除 |
| 自定义开机 IRQ 服务 | 已删除 |
| 防回归 | lint 禁止重新加入自动启动链接或启动调用 |

## 6. 文件变更清单

### 6.1 新增文件

| 文件 | 作用 |
|---|---|
| `.github/ax6-nss-lock.env` | 集中锁定源码、feeds、主题和 OpenClash 提交 |
| `AX6-IPQ/files/etc/init.d/ax6-wifi-regdom` | 启动时同步 WiFi UCI 国家码与内核 regdom |
| `AX6-IPQ/files/sbin/ax6-config-audit` | ZeroTier、UPnP、OpenClash、WiFi、VLAN、SQM 的只读审计 |
| `AX6-IPQ/files/usr/sbin/ax6-irq-affinity` | 手动 IRQ 基准和临时实验工具，不自动启动 |
| `AX6-IPQ/AUDIT-REPAIR-REPORT-2026-06-18.md` | 本检查、修复与遗留问题总报告 |

### 6.2 删除文件

| 文件 | 删除原因 |
|---|---|
| `AX6-IPQ/files/etc/hotplug.d/ieee80211/99-ax6-reapply-irq` | WiFi hotplug 自动覆盖上游 IRQ 策略 |
| `AX6-IPQ/files/etc/init.d/ax6-irq-affinity` | 自定义开机 IRQ 服务与上游启动链冲突 |
| `AX6-IPQ/files/etc/uci-defaults/95-ax6-nss-vlan-guard` | 会破坏性删除用户 VLAN 配置 |

### 6.3 修改文件

| 文件 | 主要修正 |
|---|---|
| `.github/workflows/build-AX6-NSS.yml` | 锁定输入、验证 commit、准备 feeds、rootfs 校验、Release 来源和校验和 |
| `.github/workflows/build-AX6-IPQ.yml` | 同步 rootfs 内容校验和安全说明 |
| `.github/workflows/build-IMM.yml` | Release 来源提交修正 |
| `.github/workflows/build-LEDE.yml` | Release 来源提交修正 |
| `.github/workflows/lint.yml` | 构建锁、WiFi、VLAN、ZRAM、IRQ、场景策略所有权防回归 |
| `.github/workflows/sync-check.yml` | 比较锁定提交与跟踪分支，不直接盲目升级 |
| `AX6-IPQ/.config-stock` | NSS netlink、SQM、ZRAM 和冲突包修正 |
| `AX6-IPQ/.config-expand` | 与 stock 同步软件配置，保留不同 NAND 布局 |
| `AX6-IPQ/nss-extra.config` | NSS qdisc/netlink、802.1q、SQM 依赖、OpenClash |
| `AX6-IPQ/diy.sh` | 使用锁定外部包、移除冲突依赖、生成正确启动链接 |
| `AX6-IPQ/files/etc/init.d/ax6-boot-guard` | 只维护 NSS 通用不变量，不再修改场景配置 |
| `AX6-IPQ/files/etc/sysctl.d/99-ax6-tune.conf` | 明确 IRQ/RPS 由上游管理 |
| `AX6-IPQ/files/etc/uci-defaults/98-nss-tune` | 关闭 firewall flow offload |
| `AX6-IPQ/files/etc/uci-defaults/99-ax6-wifi-tune` | US、HE40、20/40 共存、IoT 兼容，不强制 SSID 策略 |
| `AX6-IPQ/files/sbin/nss-check` | NSS/WiFi/VLAN/ZRAM/IRQ 确定性运行时检查 |
| `AX6-IPQ/files/sbin/vlan-add` | 完整 NSS 兼容 VLAN 创建与冲突检查 |
| `AX6-IPQ/HARDWARE.md` | 修正 VLAN、IRQ、NSS 和 WiFi 操作说明 |
| `README.md` | 修正功能、检查工具、锁定来源和安全边界说明 |

## 7. 当前构建锁快照

| 输入 | 锁定值 |
|---|---|
| 源码仓库 | `OrdinaryJoys/immortalwrt-nss` |
| 源码跟踪分支 | `codex/p0-nss-sync` |
| 源码提交 | `d652cebfc765541d92f7a78a2a3fb318b90fede7` |
| NSS feed URL | `VIKINGYFY/nss-packages-618`（**当前不可访问**） |
| NSS feed 提交 | `2d826ed6e20185820a00bf674cff911bb27fe48e` |
| SQM NSS | `4b4ed8639229be5e70cf94b73cdf7dbc09e66d5d` |
| LuCI feed | `48884afb432f84c93052f32603ceaed4b49feb14` |
| packages feed | `a53af9bb5da9145f01e0c7cff30fddf9480b47f6` |
| routing feed | `6ea029dcc96645836d34dbed56c05e7468916fdc` |
| telephony feed | `4d8d33a023b24c52cd9443b9dc201fbdfe9c6aef` |
| video feed | `a951381b6c58b9b1eb087f09c9a20cff4ffe8063` |
| Argon theme | `3c8dc64bca054be0c184dc1dc9847b249710a466` |
| Argon config | `3e099a37c3f71d0de677f1b6b0f4bffd57d91dac` |
| OpenClash | `0.47.097` / `a86fb847719815ff3ab1e94261d5b2bbeabdaef1` |

## 8. 验证证据

### 8.1 本地静态验证

| 检查 | 结果 | 说明 |
|---|---|---|
| `actionlint .github/workflows/*.yml` | PASS | GitHub Actions 语法和内嵌 shell 检查通过 |
| `yamllint -d relaxed .github/` | PASS | YAML 检查通过 |
| 核心脚本 `shellcheck` | PASS | NSS、VLAN、审计、boot guard、regdom、WiFi、IRQ 脚本 |
| `bash -n` | PASS | 核心 shell 语法通过 |
| `git diff --check` | PASS | 无空白或 patch 格式问题 |
| 策略残留扫描 | PASS | 未发现启动脚本继续强制 ZeroTier/UPnP/OpenClash/SSID 隔离 |

### 8.2 GitHub Actions

| Run | 提交 | 结果 | 说明 |
|---|---|---|---|
| [27614279917](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/27614279917) | `0b75a6b...` | SUCCESS | 最新完整 STOCK NSS 构建 |
| [27516345453](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/27516345453) | `276c4a0...` | SUCCESS | IRQ 所有权修复后构建 |
| [27505191734](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/27505191734) | `ceb951d...` | SUCCESS | 空目录修正后构建 |
| [27505031470](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/27505031470) | `71a4ce9...` | FAILURE | 初次 P0 修复构建，后续提交已解决 |

最新构建中以下步骤均为 `success`：

1. STOCK 变体和 NAND 安全预检查。
2. 构建锁读取与完整 SHA 校验。
3. 锁定源码克隆。
4. NSS feed 和其他 feeds 准备。
5. 自定义配置和 `diy.sh` 应用。
6. 包下载。
7. 固件编译。
8. 最终 rootfs 内容验证。
9. 固件、检查工具和校验和整理。
10. Release 上传。

### 8.3 Release

| Release | 状态 | 对应说明 |
|---|---|---|
| `AX6_NSS_STOCK_20260616203522` | Latest | 对应已验证提交 `0b75a6b...` |
| `AX6_NSS_STOCK_20260615095708` | 历史成功 | 对应较早测试提交 |
| `AX6_NSS_STOCK_20260615023226` | INVALID / Pre-release | 已明确标记 IRQ 策略回归，不应使用 |

## 9. 上游状态与可合并判断

快照日期：2026-06-18。

| 仓库/分支 | 当前 HEAD | 与已验证状态的关系 | 判断 |
|---|---|---|---|
| `OrdinaryJoys/AX6-OpenWRT codex/p0-ax6-stability` | `0b75a6b...` | 当前已验证构建分支 | 可作为现有稳定基线 |
| `OrdinaryJoys/AX6-OpenWRT main` | `190d071...` | 未包含 P0 修复 | 暂不应作为本报告修复后的构建基线 |
| `OrdinaryJoys/immortalwrt-nss codex/p0-nss-sync` | `d652ceb...` | 与锁文件一致 | 当前源码锁仍可访问 |
| `VIKINGYFY/immortalwrt main` | `b22a17c...` | 比此前检查的 `46878c...` 前进 3 个提交 | 不能直接合并，需迁移验证 |
| `VIKINGYFY/immortalwrt owrt` | `dfe9c76...` | 非当前 NSS 构建基线 | 不作为本次 NSS 源 |
| `qosmio/openwrt-ipq main-nss` | `92a2d10...` | 与此前检查一致 | VLAN/NSS 说明仍可作为参考 |
| `VIKINGYFY/nss-packages-618` | 不可访问 | 锁定 URL 失效 | 必须先处理镜像或迁移 |

VIKINGYFY 最新三个相关提交为：

| 提交 | 摘要 | 影响范围 |
|---|---|---|
| `c3d4399869` | migration qca-nss | NSS 包从外部 feed 迁入源码树 |
| `5d6329e84c` | update hostapd | WiFi/认证路径可能变化 |
| `b22a17c65d` | update qca-nss | NSS 驱动、clients、ECM、pbuf 等继续更新 |

主要变化包括：

- `package/qca-nss/qca-nss-drv`
- `package/qca-nss/qca-nss-clients`
- `package/qca-nss/qca-nss-ecm`
- `package/qca-nss/qca-mcs`
- `package/qca-nss/nss-firmware`
- `package/kernel/mac80211/files/qca-nss-pbuf.init`
- `target/linux/qualcommax`

这些是核心驱动和启动链变化，不能只改一个 SHA 后直接视为安全升级。

## 10. 建议修复顺序

| 顺序 | 动作 | 完成条件 |
|---:|---|---|
| 1 | 恢复 NSS feed 的可获取性 | 锁定提交可从 OrdinaryJoys 控制的只读镜像拉取 |
| 2 | 重新触发当前 `0b75a6b` STOCK 构建 | 从空 runner 成功完成所有步骤，证明可复现性恢复 |
| 3 | 建立 VIKINGYFY qca-nss 迁移实验分支 | 不影响当前稳定分支 |
| 4 | 比较包名、Kconfig、init、pbuf、ECM、firmware 和 rootfs | 形成迁移差异表 |
| 5 | 对迁移分支运行 lint + STOCK 构建 | 构建和 rootfs 校验全部通过 |
| 6 | 必要时运行 EXPAND 构建 | 仅验证 256MB NAND 变体，不改变 STOCK 安全默认 |
| 7 | 提交 PR 合并到 `main` | PR 明确列出构建证据和剩余实机风险 |
| 8 | 用户人工升级测试机 | 不自动刷写生产路由器 |
| 9 | 完成运行时检查和 IoT 兼容矩阵 | 所有确定性 FAIL 清零并记录现场结果 |

## 11. 人工升级后的运行时检查清单

以下命令仅在用户手动升级并确认可回滚后执行：

```sh
nss-check -v
ax6-config-audit -v

uci get network.globals.packet_steering
uci get firewall.@defaults[0].flow_offloading
uci get firewall.@defaults[0].flow_offloading_hw

iw reg get
iw dev
uci show wireless

ls -l /etc/rc.d/S10ax6-wifi-regdom
ls -l /etc/rc.d/S12ax6-boot-guard
ls -l /etc/rc.d/S15zram
ls -l /etc/rc.d/S93smp_affinity
ls -l /etc/rc.d/S94qca-nss-drv
ls -l /etc/rc.d/S95qca-nss-pbuf
ls -l /etc/rc.d/S99set-irq-affinity

cat /proc/swaps
sysctl dev.nss.rps.enable
sysctl dev.nss.rps.hash_bitmap

uci show network | grep -E 'bridge-vlan|vlan_filtering'
logread | grep -Ei 'nss|ecm|ath11k|wifi|zram|zerotier|upnp|openclash'
```

### IoT 兼容测试记录建议

| 测试项 | 记录内容 |
|---|---|
| 设备 | 品牌、型号、WiFi 芯片或大致年代 |
| SSID | 2.4G 独立/合并 SSID、是否隐藏 |
| 加密 | WPA2、WPA2/WPA3 mixed、WPA3-only |
| PMF | disabled/optional/required |
| 信道 | 自动结果、实际信道、20/40MHz |
| 信号 | RSSI、距离和遮挡 |
| 结果 | 扫描、认证、DHCP、联网、局域网发现 |
| 日志 | hostapd、kernel、DHCP 失败原因 |

## 12. 不应执行的操作

1. 不要直接把 `VIKINGYFY/immortalwrt main` 合并到已验证分支。
2. 不要只更新 NSS feed SHA，而不验证其 URL、包结构和启动脚本。
3. 不要恢复开机自动运行的自定义 `ax6-irq-affinity`。
4. 不要恢复会删除 `bridge-vlan` 或 VLAN 配置的启动守护脚本。
5. 不要在 NSS WiFi offload 场景启用 DSA bridge VLAN filtering。
6. 不要将 EXPAND 固件刷入原厂 128MB NAND AX6。
7. 不要把云端构建成功等同于实机网络场景已经全部验证。

## 13. 最终状态说明

截至本报告日期，`0b75a6b...` 对应的 STOCK 固件已经完成一次完整云端构建、
最终 rootfs 校验和 Release 上传，P0 修复逻辑本身没有发现新的静态或编译错误。

但“当前仍可从零复现相同构建”已经受到 NSS feed 仓库消失影响，因此整体状态应定义为：

> **代码与历史构建已验证；当前构建供应链存在 P0 可用性故障；尚未完成实机运行时验证。**

在修复 NSS feed 来源、重新跑通空环境构建并完成测试机运行时检查前，不应宣称所有
故障和风险已经彻底清零。
