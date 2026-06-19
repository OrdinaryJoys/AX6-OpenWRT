# AX6 OpenWrt/NSS 全量审计、修复与重构报告

> 审计日期：2026-06-19（Asia/Shanghai）
> 仓库：`OrdinaryJoys/AX6-OpenWRT`
> 审计基线：`main@878c97d79bd2e999185cf8066c9c6ea348917228`
> 修复分支：`codex/full-audit-20260619`
> 源码仓库：`OrdinaryJoys/immortalwrt-nss`
> 原源码基线：`3e7a3febdd3fba88a8ca248afd3cc946f9853ee9`
> 修复源码：`4b0b74e7da5a04c2a054e6d33363defb0abd77de`
> 用户提供清单：`FIX_CHECKLIST_2026-06-19.md`

## 1. 最终结论

| 项目 | 审计结论 |
|---|---|
| 6 月 16 日旧源码 STOCK 固件 | 已成功构建并生成 Release |
| 迁移到 built-in `package/qca-nss` 后的新源码固件 | 已完成编译和 rootfs 校验；测试分支 Release 权限失败不影响固件内容 |
| 清单中的 CI `#27774751677` | 不是“编译中”，而是超过一天卡在 `Initialize environment` |
| 清单中的 `SOURCE_COMMIT` | **错误**；写入了 GitHub 上不存在的完整 SHA |
| NSS init START 修正 | 新镜像 rootfs 已验证 `S28qca-nss-drv` / `S27qca-nss-pbuf` |
| 构建供应链 | 外部 NSS feed 已移除；源码锁和 ATH11K NSS 依赖已通过完整编译 |
| 配置状态 | 已继续清理 ATH11K、NSS、ZRAM、IPQ 和直接内核符号残留，并关闭 SFE 专用 SKB 预分配 |
| 路由器备份脚本 | 原实现不是完整备份，已重构 |
| OpenClash 恢复脚本 | 原实现未使用备份目录且硬编码订阅名，已重构 |
| VIKINGYFY 最新更新 | 远端 `main` 已移动到 `321f440d...`；当前锁定源码未盲目跟随 |
| packages feed | 落后 51 个提交；变化广泛，不应在本轮盲目升级 |
| 实机验证 | 尚未完成；本轮不刷写路由器 |

当前状态不能表述为“所有问题已修复”。准确表述应为：

> **确定性仓库问题已修正并通过本地检查、完整 STOCK 编译和 rootfs 校验；
> 尚未完成的是测试分支 Artifact 整体成功状态和经用户确认后的实机运行时验证。**

## 2. 用户检查清单复核

### 2.1 清单中确认属实的内容

| 项目 | 复核结果 |
|---|---|
| P0 stability 修复链 | 大部分已存在于 `main` |
| 外部 `nss-packages-618` 已移除 | 属实，NSS 包已迁入源码树 |
| `S94/S95` 校验已改为 `S28/S27` | 属实 |
| lint 最近多次成功 | 属实 |
| `main` 最新提交为 `878c97d` | 属实 |
| `immortalwrt-nss` 本地/远端 main 与 sync 分支一致 | 属实，均为真实 SHA `3e7a3febdd3f...` |
| STOCK 与 EXPAND 配置软件部分一致 | 属实，差异仅为目标设备/profile |

### 2.2 清单中错误或过度结论

| 清单结论 | 实际情况 | 影响 |
|---|---|---|
| `SOURCE_COMMIT` 已修复 | 锁文件使用不存在的 `3e7a3febddf04...`；真实 SHA 为 `3e7a3febdd3fb...` | 新构建在源码锁校验处必然失败 |
| CI `#27774751677` 正在编译 | 卡在 `Initialize environment`，未进入锁校验、源码克隆或编译 | 不能作为任何代码验证证据 |
| U2 新 Release 等待生成 | 截至审计时仍无 built-in qca-nss 新 Release | 最新 Release 仍是 6 月 16 日旧源码 |
| `nss-extra.config` 23/23 完美且不可变 | 配置中存在陈旧符号；VIKINGYFY 最新提交又改写 NSS 配置模型 | 必须持续审计，不能列为不可变 |
| `.config-stock` 完全正确 | 存在 9 个已无定义符号及无效 `TRUSTSEC_RX=y` | defconfig 会清理，但源码配置不干净 |
| 备份脚本已完成 | 只保存订阅 YAML 前 100 行，未完整备份 | 无法可靠恢复 |
| 部署脚本已完成 | `BACKUP_DIR` 未使用，硬编码订阅文件名，关键失败仍继续 | 可能误报部署成功 |
| 仓库最终状态 `main=b7888e7` | 页首写 `878c97d`，两处矛盾；实际为 `878c97d` | 清单内部状态不一致 |
| 上游落后为 0 | VIKINGYFY 随后继续移动，2026-06-19 已到 `321f440d...` | 当前源码与上游再次分叉 |

## 3. 本轮发现并修复的问题

| 优先级 | 问题 | 根因 | 修复 |
|---|---|---|---|
| P0 | 源码锁完整 SHA 不存在 | 只核对了短 SHA `3e7a3feb`，手工拼写完整 SHA | 改为真实 `3e7a3febdd3fba88a8ca248afd3cc946f9853ee9` |
| P0 | 构建按分支拉取后才比较 SHA | 分支移动会让历史锁定构建无故失败 | workflow 改为直接 `fetch $SOURCE_COMMIT` |
| P0 | 锁检查漏掉 3 个关键 commit | lint/build 只验证部分 feed SHA | 补充 SOURCE、SQM、LuCI 的 40 位 SHA 校验 |
| P1 | CI 可无限挂起 | jobs 未设置超时 | NSS/IPQ/IMM/LEDE 设 180 分钟，lint 20 分钟，sync 15 分钟 |
| P1 | 环境初始化拉取整套 TeX Live | `asciidoc` 推荐依赖导致数 GB 无关文档工具链安装 | 所有构建统一使用 `--no-install-recommends`、下载重试并移除全局 autoremove |
| P1 | NSS 磁盘清理后重新安装编译器 | `large-packages: true` 删除显式依赖的 Clang/LLVM，初始化又装回 | 保留 large packages，只清理 Android/.NET/Haskell/Docker 等无关内容 |
| P0 | `kmod-ath11k` 缺少 NSS 驱动包依赖 | 上游合并解决冲突时丢失 `ath.mk` 的四条条件依赖 | 源码分支恢复依赖，构建仓库锁定修复提交并增加前置检查 |
| P1 | Actions 仍使用 Node 20 版本 | 之前所谓 Node 24 SHA 未正确验证后被回退 | 使用官方标签验证的 checkout v7、release-action v1.21 完整 SHA |
| P1 | `.config-*` 含陈旧 NSS 符号 | built-in qca-nss 迁移后保留旧配置项 | 从 stock/expand 同步删除并加入 lint 防回归 |
| P1 | `TRUSTSEC_RX=y` 但 TRUSTSEC 关闭 | 旧配置未经过当前 Kconfig 依赖清理 | 删除无效项并加入 lint 依赖检查 |
| P1 | 备份目录可能被提交 | `.gitignore` 未忽略 `ax6-backup-*` | 加入忽略规则 |
| P1 | sysupgrade 备份可能被 stdout 污染 | `sysupgrade -b` 提示与 tar 数据共用 stdout | 将命令提示重定向，仅输出归档数据 |
| P1 | OpenClash 备份不完整 | 只截取单个硬编码 YAML 的前 100 行 | 改为完整归档 config/custom/provider/UCI |
| P1 | OpenClash 恢复不读取备份 | 原脚本生成固定模板，`BACKUP_DIR` 未使用 | 恢复真实归档，并先保存目标机回滚包 |
| P1 | 恢复脚本可能覆盖全部 crontab | 直接恢复 root crontab 会删除新固件任务 | 只合并 OpenClash/fix_dot 相关 cron 行 |
| P1 | 恢复失败仍显示完成 | 多处 `|| echo` 吞掉错误 | 关键步骤改为失败即中止 |
| P2 | 部署脚本硬编码订阅文件 | 绑定个人文件 `el1si7d_doggygosubs.yaml` | 改为动态检查所有 YAML |
| P2 | CI 无维护脚本安全检查 | 新脚本不在策略防回归范围 | lint 增加完整归档、无硬编码、忽略敏感备份检查 |

## 4. 配置清理详情

当前锁定源码中已经没有下列 Kconfig 定义，因此从 stock 和 expand 配置中删除：

| 陈旧符号 |
|---|
| `CONFIG_NSS_DRV_C2C_ENABLE` |
| `CONFIG_NSS_DRV_IPV4_FORWARD_ENABLE` |
| `CONFIG_NSS_DRV_IPV6_FORWARD_ENABLE` |
| `CONFIG_NSS_DRV_CONNTRACK_ENABLE` |
| `CONFIG_NSS_DRV_QVPN_ENABLE` |
| `CONFIG_NSS_DRV_TSTAMP_ENABLE` |
| `CONFIG_NSS_DRV_WIFI_LEGACY_ENABLE` |
| `CONFIG_NSS_DRV_NATP_ENABLE` |
| `CONFIG_NSS_DRV_PORTID_ENABLE` |

同时删除：

| 无效组合 | 原因 |
|---|---|
| `CONFIG_NSS_DRV_TRUSTSEC_RX_ENABLE=y` | 当前 Kconfig 要求 `NSS_DRV_TRUSTSEC_ENABLE=y`，但父项关闭 |

保留的关键配置包括：

- `CONFIG_NSS_DRV_WIFIOFFLOAD_ENABLE=y`
- `CONFIG_NSS_DRV_WIFI_EXT_VDEV_ENABLE=y`
- `CONFIG_ATH11K_NSS_SUPPORT=y`
- `CONFIG_ATH11K_NSS_MESH_SUPPORT=n`
- `CONFIG_PACKAGE_MAC80211_MESH=n`
- `CONFIG_NSS_DRV_RMNET_ENABLE=y`
- `CONFIG_PACKAGE_kmod-qca-nss-drv-netlink=y`
- `CONFIG_PACKAGE_kmod-qca-nss-drv-qdisc=y`
- `CONFIG_PACKAGE_sqm-scripts-nss=y`
- `CONFIG_PACKAGE_zram-swap=y`

## 5. 上游状态

### 5.1 直接源码上游

| 仓库/分支 | HEAD | 状态 |
|---|---|---|
| OrdinaryJoys `codex/fix-ath11k-nss-depends` | `4b0b74e7da5a...` | 当前锁定的 ATH11K NSS 依赖修复源码 |
| OrdinaryJoys `codex/p0-nss-sync` | `3e7a3febdd3f...` | 与 OrdinaryJoys main 一致 |
| OrdinaryJoys `main` | `3e7a3febdd3f...` | 原始审计基线，尚未包含 ATH11K 依赖修复 |
| VIKINGYFY `main` | `321f440d4af8...` | 2026-06-19 远端 HEAD；未在本轮直接合并 |
| VIKINGYFY `owrt` | `dfe9c76b658c...` | 非当前 NSS 构建基线 |
| qosmio/openwrt-ipq `main-nss` | `92a2d104145c...` | 与前次检查一致 |
| qosmio/nss-packages `NSS-12.5-K6.x` | `0d970dbf0185...` | 参考 feed 已继续更新 |

此前相对本地已抓取的 VIKINGYFY `38e28da...` 为 `42 left / 1 right`。远端现在已经
继续移动到 `321f440d...`，因此该计数不再代表最新差异，不能据此直接 rebase。

### 5.2 已抓取的 VIKINGYFY 清理提交影响

`38e28da... cleanup qca-nss config` 修改 19 个核心文件，约 307 行新增、451 行删除：

- `config/Config-ipq.in`
- `package/kernel/mac80211/Makefile`
- `package/kernel/mac80211/ath.mk`
- `package/kernel/mac80211/files/qca-nss-pbuf.init`
- `package/qca-nss/qca-nss-drv`
- `package/qca-nss/qca-nss-clients`
- `package/qca-nss/qca-nss-ecm`
- `target/linux/qualcommax`

三方合并预演在 `package/kernel/mac80211/ath.mk` 出现真实冲突，涉及：

- `ATH11K_MEM_PROFILE_512M`
- `ATH11K_NSS_SUPPORT`
- `ATH11K_NSS_MESH_SUPPORT`
- NSS package `select` 关系

结论：该更新需要独立集成分支、重新生成 defconfig、完整 STOCK 构建和 WiFi/NSS
实机验证，不能直接并入本轮修复。

### 5.3 锁定 feeds

| 输入 | 锁定提交 | 当前 HEAD | 结论 |
|---|---|---|---|
| SQM NSS | `4b4ed863...` | 相同 | current |
| OrdinaryJoys LuCI | `48884afb...` | 相同 | current |
| immortalwrt packages | `a53af9bb...` | `8ed3556d...` | 漂移 51 commits |
| routing | `6ea029dc...` | 相同 | current |
| telephony | `4d8d33a...` | 相同 | current |
| video | `a951381b...` | 相同 | current |
| Argon theme | `3c8dc64b...` | 相同 | current |
| Argon config | `3e099a37...` | 相同 | current |
| OpenClash | `a86fb847...` | 相同 | current |

packages 的 51 个提交包含 Go 安全更新、strongSwan 修复、Python 包删除以及大量无关
软件更新。当前 AX6 核心修复不依赖这些变化，因此保留锁定版本，后续单独升级并构建。

## 6. GitHub Actions 状态

| Run | 提交 | 结果 | 正确解释 |
|---|---|---|---|
| `27614279917` | `0b75a6b...` | success | 6 月 16 日旧源码 STOCK 成功基线 |
| `27760103841` | `257e86b...` | failure | 编译通过，旧 rootfs START 校验失败 |
| `27767524533` | `5eda3bd...` | failure | 新源码编译通过，仍使用旧 START 校验 |
| `27774751677` | `6e3b963...` | in_progress/stale | 超过一天卡在环境初始化，未进入编译 |
| `27774914959` | `878c97d...` | success | 仅 lint 成功，不能替代固件构建 |
| `27776232029` | `35bc28f...` | cancelled | 复现环境初始化异常；日志确认卡在 TeX Live 推荐依赖解包 |
| `27777378927` | `9eee531...` | cancelled | 去除推荐依赖后仍慢；交叉确认磁盘清理删除了随后要重装的 Clang/LLVM |
| `27778615180` | `4a0f6b2...` | failure | 编译到 `kmod-ath11k` 后因缺少 `qca-nss-drv.ko` 包依赖失败 |
| `27798416475` | `c56c020...` | release failure | Compile、ATH11K 打包、rootfs 和制品整理成功；测试分支创建 Release 返回 403 |
| `27801325559` | `0ed2e88...` | in progress | 截至本轮收尾仍在 Compile；不轮询等待，且不包含本轮后续配置清理 |

截至审计时，最新 Release 仍为：

`AX6_NSS_STOCK_20260616203522`

该旧 Release 仍不应刷写；built-in qca-nss 新源码已由 run `27798416475`
完成编译和 rootfs 校验，但尚未发布为正式 Release。

## 7. GitHub Actions 供应链修复

| Action | 原固定版本 | 新固定版本 | 验证 |
|---|---|---|---|
| `actions/checkout` | v4.1.1 / Node 20 | v7.0.0 / Node 24 | 官方 tag SHA `9c091bb...` |
| `actions/upload-artifact` | 未配置 | v7.0.1 / Node 24 | 官方 tag SHA `043fb46...` |
| `ncipollo/release-action` | v1.14.0 | v1.21.0 / Node 24 | 官方 tag SHA `339a818...` |
| `dev-drprasad/delete-older-releases` | v0.3.4 | 保持 | 当前最新仍为 v0.3.4 |
| `jlumbroso/free-disk-space` | v1.3.1 | 保持 | tag SHA 与 workflow 一致 |
| `easimon/maximize-build-space` | v10 | 保持 | tag SHA 与 workflow 一致 |
| `P3TERX/ssh2actions` | v1.0.0 | 保持 | tag SHA 与 workflow 一致 |

## 8. 备份与恢复安全模型

### 8.1 新备份内容

- OpenWrt `sysupgrade -b` 完整配置归档。
- OpenClash UCI、custom、config、proxy/rule provider 和 `fix_dot.sh`。
- network、wireless、firewall、DHCP、ZeroTier、UPnP、SQM UCI 导出。
- `nss-check`、`ax6-config-audit`、MTD、mount、packages 和网络状态。
- 本地 SHA-256 清单。

### 8.2 新恢复边界

- 只自动恢复 OpenClash 运行时文件。
- 不自动恢复整机 sysupgrade 归档。
- 恢复前先保存目标机当前 OpenClash 状态。
- 只合并 OpenClash/fix_dot cron，不覆盖整个 root crontab。
- 不硬编码订阅文件名。
- 必须检测 OpenClash 服务和核心进程。
- 备份目录默认权限受 `umask 077` 保护并被 Git 忽略。

## 9. 本地验证结果

| 检查 | 结果 |
|---|---|
| `actionlint` | PASS |
| `yamllint` | PASS |
| 所有仓库 shell/uci-defaults `shellcheck -S warning` | PASS |
| `sh -n` / `bash -n` | PASS |
| `git diff --check` | PASS |
| 空 Git 仓库按真实完整 SHA 拉取源码 | PASS |
| ATH11K NSS 四条条件依赖 | PASS |
| 云端 STOCK 编译与 rootfs 校验 | PASS (`27798416475`) |
| mock SSH 备份流程 | PASS |
| mock SSH OpenClash 恢复流程 | PASS |
| stock/expand 配置差异 | 仅目标设备/profile |

## 10. 尚未完成的验证

| 优先级 | 项目 | 完成条件 |
|---|---|---|
| P0 | 测试分支 Artifact 整体工作流 | Artifact 上传成功且 workflow conclusion 为 success |
| P1 | main 正式 Release | PR 审核合并后由 main 构建创建 |
| P1 | built-in qca-nss 运行时 | 测试机 `nss-check -v` 无 FAIL |
| P1 | WiFi 2.4G IoT | 多设备完成关联、DHCP、联网和局域网发现 |
| P1 | VLAN | 802.1q 子接口实流量和 NSS VLAN 计数验证 |
| P1 | SQM | `nss-zk.qos` 实际限速和 NSS qdisc 状态 |
| P1 | ZeroTier/UPnP/OpenClash | 现场拓扑下运行时审计 |
| P2 | EXPAND 变体 | 仅在真实 256MB NAND 设备需求下构建和验证 |

## 11. 后续重构任务

### 11.1 VIKINGYFY `321f440d` 集成

必须在独立源码分支完成：

1. 解决 `ath.mk` 内存 profile 冲突。
2. 确认 mesh 默认不会重新启用。
3. 比较 pbuf 的 1GB/512MB 参数。
4. 重新生成 stock/expand defconfig。
5. 检查所有 qca-nss package 依赖和 Kconfig select。
6. 完成 STOCK 构建和 rootfs 校验。
7. 测试 ath11k NSS frame mode、pbuf、ECM 和 IRQ/RPS。

### 11.2 packages feed 升级

必须单独执行：

1. 审查被选中包是否涉及删除的 Python 包或 Go toolchain。
2. 更新 lock。
3. 运行 feeds install 和 defconfig 差异审计。
4. 完整构建。
5. 不与 VIKINGYFY 核心迁移同时进行，以便定位回归。

## 12. 不应执行的操作

1. 不要把卡住的 `#27774751677` 当作编译验证。
2. 不要继续使用短 SHA 判断锁文件正确性。
3. 不要直接合并 VIKINGYFY `321f440d`。
4. 不要同时升级核心源码和 packages feed。
5. 不要自动恢复完整 sysupgrade 备份到不同源码基线。
6. 不要把敏感备份目录加入 Git。
7. 不要自动刷写路由器。
8. 不要在 built-in qca-nss 新构建成功前称其为稳定 Release。

## 13. 下一步执行顺序

1. 提交并推送本轮仓库修复分支。
2. 取消已挂起超过一天的 `#27774751677`。
3. 触发新的 STOCK NSS 构建。
4. 检查完整日志和 rootfs `S28/S27`。
5. 确认新 Release 和 BUILD-LOCK。
6. 用户手动刷写测试机。
7. 执行 `nss-check -v` 与 `ax6-config-audit -v`。
8. 再开启 VIKINGYFY `321f440d` 独立重构。

## 14. 后续全量静态审计补充

本节覆盖原清单未识别的问题。以下修复只修改仓库，未连接、重启或刷写路由器。

### 14.1 新确认并修复的问题

| 优先级 | 问题 | 根因与影响 | 修复与验证 |
|---|---|---|---|
| P1 | ATH11K 配置引用已删除符号 | `NSS_TX_SUPPORT`、1G profile、NAPI weight 等已不在当前 `ath.mk`；defconfig 会静默丢弃，实际选择与文件声明不一致 | 删除旧符号，明确 `ATH11K_MEM_PROFILE_512M=y`，lint 防回归 |
| P1 | NSS 配置仍含大量未知符号 | built-in `qca-nss-drv/Config.in` 已不定义 IPSEC、CLMAP、TLS、WDS、旧 memory profile 等条目 | stock/expand/nss-extra 同步清理，只保留当前源树定义项 |
| P1 | ZRAM 配置未生效 | 使用旧 `CONFIG_ZRAM_*` 和不存在的 `CONFIG_ZRAM_SIZE`；实际会退回 RAM/2 与 lzo | 改用 `CONFIG_KERNEL_ZRAM_BACKEND_ZSTD`/`DEF_COMP_ZSTD`，新增首次启动 UCI 256MB/zstd 策略和运行时校验 |
| P0 | VLAN 默认暴露路由器服务 | 新 zone 使用 `input=ACCEPT`，IoT/访客设备可访问 LuCI、SSH 等本机服务 | 默认 `REJECT`，仅放行 DHCP/DNS，保留 WAN forwarding |
| P1 | VLAN 脚本可留下半套配置 | network/firewall/dhcp 分次 commit，无失败回滚 | 检查未提交 UCI、更名长度和端口冲突；三配置统一暂存、备份和失败恢复 |
| P1 | VLAN DHCP 池与 CIDR 不匹配 | 任意 CIDR 都固定 `100-249`，小子网会产生无效池 | 要求网关为首个可用地址，并按 CIDR 计算合法 start/limit |
| P1 | 软件源覆盖构建生成结果 | overlay 固定 24.10-SNAPSHOT，和自定义 6.18/NSS 内核不匹配 | 删除 overlay distfeeds，让锁定源码生成目标/架构一致的软件源；文档禁止混装 kmod |
| P2 | SSH 状态栏 ECM 计数错误 | 将 `tcp N udp M ... total T` 整串传给 `%d` | 提取最后一个数字并增加空值回退 |
| P1 | NSS 模块黑名单只在首次启动动态生成 | 静态镜像中缺文件，恢复/脚本异常时防护不稳定 | 黑名单直接进入 `/etc/modprobe.d`，首次启动脚本只清理已加载模块 |
| P1 | OpenClash 禁用状态被误判为恢复失败 | 恢复脚本无条件要求 clash 进程运行 | 仅在 restored `enable=1` 时等待核心；禁用时报告正常 |
| P1 | OpenClash 归档可解出非预期路径 | 恢复前未检查 tar 成员 | 添加路径 allowlist 和 `..` 拒绝检查 |
| P2 | ZRAM 自检可被非法 UCI 值中断 | 对非数字 `zram_size_mb` 直接算术展开 | 先校验数值，并从 `/proc/swaps` 获取实际 zram 设备 |
| P2 | 监控 cron 退出码表达含糊 | 依赖 `||` 后即时 `$?` | 显式保存 `rc` 后记录 |
| P1 | 配置尾部仍有旧 IPQ/内核符号 | 旧源码的 memory profile、minstrel、bridge、CPU freq 等 Buildroot 条目已无定义 | 删除失效与重复条目；直接内核值由 `qualcommax/config-6.18` 管理 |
| P1 | 启用了 SFE 专用 64MB SKB 预分配 | 当前 Kconfig 明确说明 PREALLOC 面向 SFE 而非 NSS | 保留 SKB recycler，关闭 `KERNEL_SKB_RECYCLER_PREALLOC` |

### 14.2 新增或重点修改文件

| 文件 | 作用 |
|---|---|
| `AX6-IPQ/.config-stock` / `.config-expand` | 清理未知符号，修正 ATH11K、ZRAM 与 SKB recycler |
| `AX6-IPQ/nss-extra.config` | 仅保留当前 Kconfig 可表达的 NSS 安全项 |
| `AX6-IPQ/files/etc/uci-defaults/95-ax6-zram-defaults` | 保守设置 256MB/zstd，不覆盖已有管理员选择 |
| `AX6-IPQ/files/etc/modprobe.d/nss-no-flow.conf` | 静态阻止 generic flow offload 与 NSS ECM 争用 |
| `AX6-IPQ/files/sbin/vlan-add` | 安全默认、CIDR 地址池、冲突检查和事务回滚 |
| `AX6-IPQ/files/sbin/nss-check` | ZRAM 大小/算法与非法配置检查 |
| `deploy-openclash-runtime.sh` | 归档 allowlist、禁用状态处理、启用状态等待 |
| `tests/test-vlan-add.sh` | 验证 VLAN 成功路径和 commit 失败回滚 |
| `tests/test-openclash-archive.sh` | 验证非 allowlist 归档在 SSH 前被拒绝 |
| `.github/workflows/lint.yml` | 对旧符号、重复配置、ZRAM、VLAN、软件源和恢复安全做防回归 |

### 14.3 本轮本地验证

| 检查 | 结果 |
|---|---|
| `shellcheck -S error`（全部 shell/uci-defaults） | PASS |
| `actionlint` | PASS |
| `yamllint -d relaxed` | PASS |
| `git diff --check` | PASS |
| stock/expand 除目标 profile 外的一致性 | PASS |
| active `CONFIG_*` 重复键检查 | PASS |
| VLAN mock 成功提交 | PASS |
| VLAN firewall commit 失败回滚 | PASS |
| OpenClash 非法归档拒绝 | PASS |

### 14.4 仍未完成或不能静态证明

| 优先级 | 项目 | 当前状态 |
|---|---|---|
| P0 | 包含本节全部修改的全量云端构建 | 尚未触发；旧 run `27801325559` 不包含这些未提交修改 |
| P1 | `VIKINGYFY/main@321f440d...` 详细差异集成 | 仅确认远端 HEAD；应在独立源码分支抓取并审查，不能直接改当前锁 |
| P1 | 真实 NSS/WiFi/VLAN/ZRAM/SQM 运行时 | 必须等待用户确认后在路由器执行 |
| P1 | 2.4G IoT 多芯片关联矩阵 | 必须在真实射频环境验证 WPA、PMF、RSSI、DHCP 和发现协议 |
| P2 | 备用 IPQ/IMM/LEDE 工作流完全可复现 | 仍跟踪移动分支/feeds；它们不是当前主 NSS 发布基线 |

因此，仓库级确定问题已继续修复并通过静态与隔离测试，但在新提交完成云端构建、
并经用户确认完成实机验证之前，仍不能声称“完全没有故障”。
