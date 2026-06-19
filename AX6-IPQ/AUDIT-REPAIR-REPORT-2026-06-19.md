# AX6 OpenWrt/NSS 全量审计、修复与重构报告

> **历史报告提示：** 本文件采用追加方式记录 2026-06-19 多轮审计，页首基线和
> 中间结论已经被后续提交推翻。当前状态、有效问题和验证边界必须以
> [`CURRENT-STATUS-2026-06-19.md`](CURRENT-STATUS-2026-06-19.md) 为准。

> 审计日期：2026-06-19（Asia/Shanghai）
> 仓库：`OrdinaryJoys/AX6-OpenWRT`
> 审计基线：`main@878c97d79bd2e999185cf8066c9c6ea348917228`
> 修复分支：`codex/full-audit-20260619`
> 源码仓库：`OrdinaryJoys/immortalwrt-nss`
> 原源码基线：`3e7a3febdd3fba88a8ca248afd3cc946f9853ee9`
> 修复源码：`9b711aebd554e861406eed91ab5ea6c5c9bc3707`
> 用户提供清单：`FIX_CHECKLIST_2026-06-19.md`

> **P0 二次更正（2026-06-19 严格复审）：**`redmi_ax6-stock` DTS 使用
> `qcom,smem-part`，同一 compatible 会读取原厂双槽或 custom U-Boot
> 合并 MIBIB。当前路由快照 `/rom=51.3M`、UBI overlay=34.6M，排除了
> 35.75 MiB 原厂单槽，指向 `rootfs=0x06640000` 合并布局。此前把共享
> profile 固定为 `36608k` 是错误修复，现已撤销并改为实机 MTD 容量预检。

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
| VIKINGYFY 最新更新 | 远端 `main` 已移动到 `5f520e5c...`；当前锁定源码未盲目跟随 |
| packages feed | 落后 51 个提交；变化广泛，不应在本轮盲目升级 |
| 实机验证 | 尚未完成；本轮不刷写路由器 |

当前状态不能表述为“所有问题已修复”。准确表述应为：

> **确定性仓库问题已继续修正并通过本地检查；较早提交已完成 STOCK 编译、
> rootfs 校验和 Artifact 上传。最新严格复审又发现 ath11k 无效模块参数等问题，
> 因此仍需对最新修复 HEAD 重新执行云端构建。实机验证必须等待用户确认。**

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
| STOCK 与 EXPAND 配置软件部分一致 | 属实；两者仅应存在目标 profile/设备差异 |

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
| 上游落后为 0 | VIKINGYFY 随后继续移动，2026-06-19 已到 `5f520e5c...` | 当前源码与上游再次分叉 |

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
| OrdinaryJoys `codex/fix-ath11k-nss-depends` | `9b711aebd554...` | ATH11K NSS 依赖与动态 SMEM 升级预检源码 |
| OrdinaryJoys `codex/p0-nss-sync` | `3e7a3febdd3f...` | 与 OrdinaryJoys main 一致 |
| OrdinaryJoys `main` | `3e7a3febdd3f...` | 原始审计基线，尚未包含 ATH11K 依赖修复 |
| VIKINGYFY `main` | `5f520e5c2b...` | 2026-06-19 远端 HEAD；未在本轮直接合并 |
| VIKINGYFY `owrt` | `dfe9c76b658c...` | 非当前 NSS 构建基线 |
| qosmio/openwrt-ipq `main-nss` | `92a2d104145c...` | 与前次检查一致 |
| qosmio/nss-packages `NSS-12.5-K6.x` | `0d970dbf0185...` | 参考 feed 已继续更新 |

当前锁定源码相对 VIKINGYFY `5f520e5c...` 为 `43 left / 2 right`。
两边均有独立修改,不能据此直接 rebase。

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
| `27801325559` | `0ed2e88...` | success | Compile、rootfs 校验、制品整理和 Artifact 上传全部成功 |
| `27809022908` | `20e27a6...` | success | 最新已推送 HEAD 的 lint 成功 |
| `27809077890` | `20e27a6...` | in progress | 仍在编译，但不包含随后发现的 ath11k/恢复安全修复，不能作为最终验证 |

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
| P0 | 最新修复 HEAD 的 Artifact 整体工作流 | lint、编译、rootfs 校验和 Artifact 上传均成功 |
| P1 | main 正式 Release | PR 审核合并后由 main 构建创建 |
| P1 | built-in qca-nss 运行时 | 测试机 `nss-check -v` 无 FAIL |
| P1 | WiFi 2.4G IoT | 多设备完成关联、DHCP、联网和局域网发现 |
| P1 | VLAN | 802.1q 子接口实流量和 NSS VLAN 计数验证 |
| P1 | SQM | `nss-zk.qos` 实际限速和 NSS qdisc 状态 |
| P1 | ZeroTier/UPnP/OpenClash | 现场拓扑下运行时审计 |
| P2 | EXPAND 变体 | 仅在真实 256MB NAND 设备需求下构建和验证 |

## 11. 后续重构任务

### 11.1 VIKINGYFY `5f520e5c` 集成

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
3. 不要直接合并 VIKINGYFY `5f520e5c`。
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
8. 再开启 VIKINGYFY `5f520e5c` 独立重构。

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
| stock/expand 核心 NSS/WiFi/ZRAM 配置一致,体积差异符合 allowlist | PASS |
| active `CONFIG_*` 重复键检查 | PASS |
| VLAN mock 成功提交 | PASS |
| VLAN firewall commit 失败回滚 | PASS |
| OpenClash 非法归档拒绝 | PASS |

### 14.4 仍未完成或不能静态证明

| 优先级 | 项目 | 当前状态 |
|---|---|---|
| P0 | 包含本节全部修改的全量云端构建 | 尚未触发；旧 run `27801325559` 不包含这些未提交修改 |
| P1 | `VIKINGYFY/main@5f520e5c...` 详细差异集成 | 已抓取并确认存在两提交重构；应在独立源码分支继续审查，不能直接改当前锁 |
| P1 | 真实 NSS/WiFi/VLAN/ZRAM/SQM 运行时 | 必须等待用户确认后在路由器执行 |
| P1 | 2.4G IoT 多芯片关联矩阵 | 必须在真实射频环境验证 WPA、PMF、RSSI、DHCP 和发现协议 |
| P2 | 备用 IPQ/IMM/LEDE 工作流完全可复现 | 仍跟踪移动分支/feeds；它们不是当前主 NSS 发布基线 |

因此，仓库级确定问题已继续修复并通过静态与隔离测试，但在新提交完成云端构建、
并经用户确认完成实机验证之前，仍不能声称“完全没有故障”。

## 15. 严格复审补充

本节通过锁定源码、哈希匹配的官方 backports 6.18.26、当前上游说明和隔离测试，
纠正“已构建即无问题”的过度结论。

### 15.1 新确认并修复

| 优先级 | 问题 | 交叉验证 | 修复 |
|---|---|---|---|
| P0 | `options ath11k rx_hash=1` 引用不存在的参数 | 官方 backports 只有 `crypto_mode`/`frame_mode`；NSS 补丁只新增 `nss_offload` | 删除该项，lint 和最终 squashfs 内容检查防回归 |
| P1 | `nss-check` 写反 `frame_mode=0/1` | 驱动定义为 `0=raw, 1=native WiFi, 2=ethernet` | 修正诊断，只有 2 判为 NSS WiFi 正常 |
| P1 | radio 上的 `dtim_period=1` 无效 | wifi-scripts schema 将 DTIM 定义为 `wifi-iface` 选项 | 删除无效项，保留 hostapd 标准默认，不强制所有 SSID |
| P1 | stock/expand 同时声明 `kmod-sched-core=n` 和 `=y` | 全量 Kconfig 赋值冲突扫描 | 删除旧否定项，CI 通用拒绝冲突赋值 |
| P1 | ZRAM uci-defaults 文件无 Git 执行位 | 原先依赖 DIY 批量 chmod 才可执行 | 文件模式改为 `100755` |
| P1 | OpenClash allowlist 不检查 tar 成员类型 | 允许路径内的链接仍可逃逸恢复边界 | 只接受普通文件和目录，拒绝目标端现有链接 |
| P1 | OpenClash “回滚包”不会自动回滚 | 恢复、cron 或启动失败会留下半恢复状态 | 保存原文件/crontab，失败自动恢复并增加 mock 测试 |

### 15.2 锁定依赖源码核对

| 子系统 | 锁定来源 | 结果 |
|---|---|---|
| OpenClash | `a86fb847...` | `enable`、DNS 字段、`pidof clash` 和 nft 链名称匹配 |
| ZeroTier | packages `a53af9bb...` | `fw_allow_*`、动态 nft include 名称/路径匹配 |
| UPnP | packages `a53af9bb...` | `secure_mode` 和末尾完整 default-deny 规则匹配 |
| SQM NSS | `4b4ed863...` | 依赖普通 SQM 框架、qdisc/IGS；脚本为 `nss-zk.qos` |
| ZRAM | 当前源码树 | `zram_size_mb`、`zram_comp_algo` 字段匹配 |
| WiFi | backports 6.18.26 + NSS 补丁 | `frame_mode=2`、`nss_offload=1` 有效；`rx_hash` 无效 |

### 15.3 最新上游结论

- `VIKINGYFY/main` 当前为 `5f520e5c2bc7ee41b0a3e25c0686be22d59af34f`。
- 该提交把普通 `ATH11K_NSS_SUPPORT` 合并为 mesh 语义，自动选择/加载
  `qca-nss-wifi-meshmgr`，并删除当前构建依赖的 NSS drv/ECM/WIFIOFFLOAD select。
- qosmio 当前说明仍明确 WDS/MESH 需要 NSS FW 11.4；本构建使用 FW 12.5。
- 因此 `5f520e5c` 不能直接合并，必须在独立分支重做配置模型并完整验证。
- `qosmio/openwrt-ipq main-nss` 仍为 `92a2d104...`。
- SQM、LuCI、routing、telephony、video、Argon 和 OpenClash 锁均未漂移。
- `immortalwrt/packages` 已从 `a53af9bb...` 漂移到 `8ed3556d...`，继续保持锁定，
  不与 NSS/WiFi 核心迁移同时升级。

### 15.4 当前验证边界

已完成：

- 锁定依赖和上游 HEAD 实时核对。
- ShellCheck、Actionlint、Yamllint、`git diff --check`。
- VLAN 成功与失败回滚测试。
- OpenClash 非法路径、链接成员和恢复失败自动回滚测试。
- Kconfig 冲突扫描和 NSS WiFi 配置策略检查。

未完成：

- `27809077890` 不包含本节修复，不能作为最新 HEAD 的最终验证。
- 最新修复 HEAD 尚未完成云端 lint、STOCK 编译、rootfs 和 Artifact 验证。
- 未进行任何路由器重启、配置修改、刷写或射频实测。

## 16. 最终产物与 STOCK 分区闭环复审

### 16.1 新确认的 P0 根因

| 问题 | 证据 | 影响 |
|---|---|---|
| 一个 profile 对应多种 MIBIB | stock DTS 使用 `qcom,smem-part`; `DEVICE_ALT0` 仅是显示标题 | 不能在共享源码 profile 写死 35.75 MiB |
| 实机目标曾被误判 | 快照 `/rom=51.3M` 且 UBI overlay=34.6M | 当前系统不可能位于 35.75 MiB 槽,应按合并布局审查 |
| 升级脚本不验证目标存在 | 旧逻辑只看 `flag_boot_rootfs` | 合并布局若残留 flag=1 会选择不存在的 `rootfs_1` |
| 升级前没有容量预检 | UBI 卷删除后才由 `ubimkvol` 发现空间不足 | 原厂双槽误刷完整镜像可能先破坏当前 UBI |
| 构建名称含义模糊 | workflow 的 STOCK 被描述成 Xiaomi 原厂布局 | 用户可能把合并布局镜像用于原厂双槽 |
| 发布物用途混杂 | 同一 artifact/release 包含 sysupgrade、factory UBI、initramfs ITB | 用户容易把恢复镜像用于 LuCI 或 raw NAND |
| 恢复命令不安全 | Release 使用未定义 `stock.bin` 的通用 `nand erase/write rootfs` 示例 | sysupgrade tar 或错误布局镜像可能被直接写入 NAND |
| 备用工作流直接发布未锁定产物 | IPQ/IMM/LEDE 跟随移动源码/feeds,后两者没有最终镜像验证 | 未验证镜像会被误认为正式 Release |

### 16.2 已实施修正

- 撤销共享 stock profile 中错误的 `IMAGE_SIZE=36608k`/`NAND_SIZE=128m`。
- 源码新增 `xiaomi_stock_get_upgrade_part`：双槽沿用 boot flag，单 rootfs
  合并布局强制使用实际存在的 `rootfs`。
- 源码新增升级前容量检查：读取实际 MTD size/erase size/write size/
  bad blocks，按 UBI LEB、layout PEB 和坏块预留计算 kernel+root 是否可容纳。
- 容量或目标布局失败返回 74，`sysupgrade -F` 也不能绕过该硬故障。
- CI 明确把 STOCK workflow 定义为 `rootfs=0x06640000` 合并布局，并按
  `0x06340000` UBI 上限检查 factory 镜像；EXPAND 仍按 `0x0c000000`。
- 恢复 STOCK 的完整软件集和 OpenClash 静态资源，不再为错误的双槽假设删包。
- Release 只包含正常升级用 sysupgrade；factory UBI/initramfs ITB 移入
  独立 RECOVERY artifact 并附禁止误用说明。
- 删除通用 raw NAND 恢复命令和未经验证的 STOCK→EXPAND 转换步骤。
- `nss-check` 分别识别原厂双槽、custom U-Boot 合并和 256M 扩容布局。
- 文档和 lint 禁止“布局不明默认选 STOCK”，改为不明确就停止刷写。
- IPQ/IMM/LEDE 备用工作流取消 Release 与仓库写权限,仅保留 7 天、明确标记
  `UNVALIDATED` 的 Actions artifact。

### 16.3 上游状态

- `VIKINGYFY/main` 于 2026-06-19 更新到 `5f520e5c2b`,比当前锁定源码多
  `38e28da692`、`5f520e5c2b` 两个提交。
- 更新仍把 `ATH11K_NSS_SUPPORT` 同时绑定 mesh、512M profile 和
  `qca-nss-drv-wifi-meshmgr`,与 AX6 1GB、NSS FW 12.5、禁用 mesh 的配置
  模型冲突,本轮不直接合并。
- ImmortalWrt 官方与 VIKINGYFY 都保留动态 SMEM profile，且没有固定
  `IMAGE_SIZE`；这与一个 compatible 对应多种 MIBIB 的框架一致。
- qosmio `main-nss@92a2d104` 不提供 AX6 stock profile，但其 NSS VLAN
  文档继续要求使用 802.1q 子接口而非 bridge VLAN filtering。

### 16.4 当前验证边界

旧 run `27813375966` 的 62,521,344 字节 factory UBI 对原厂双槽不合格，
但对 `0x06640000` 合并布局在容量上可成立；它仍不包含新的运行时预检，
因此不能直接作为最终可刷产物。
新的源码提交和编译仓提交完成后,必须至少通过：

1. 合并布局与原厂双槽的升级容量 mock 测试。
2. CI 完整 UBI `0x06340000` 合并布局上限复核。
3. sysupgrade board/metadata、rootfs 内容与源码预检函数复核。
4. sysupgrade 与 RECOVERY artifact 分离检查。

在新的云端构建通过这些门禁前，不能发布或刷写新固件；实机读取和刷写
仍需用户另行确认。
