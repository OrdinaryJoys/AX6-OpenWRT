# AX6 OpenWrt/NSS 全量审计、修复与重构报告

> 审计日期：2026-06-19（Asia/Shanghai）
> 仓库：`OrdinaryJoys/AX6-OpenWRT`
> 审计基线：`main@878c97d79bd2e999185cf8066c9c6ea348917228`
> 修复分支：`codex/full-audit-20260619`
> 源码仓库：`OrdinaryJoys/immortalwrt-nss`
> 源码基线：`3e7a3febdd3fba88a8ca248afd3cc946f9853ee9`
> 用户提供清单：`FIX_CHECKLIST_2026-06-19.md`

## 1. 最终结论

| 项目 | 审计结论 |
|---|---|
| 6 月 16 日旧源码 STOCK 固件 | 已成功构建并生成 Release |
| 迁移到 built-in `package/qca-nss` 后的新源码固件 | **尚未成功完成构建验证** |
| 清单中的 CI `#27774751677` | 不是“编译中”，而是超过一天卡在 `Initialize environment` |
| 清单中的 `SOURCE_COMMIT` | **错误**；写入了 GitHub 上不存在的完整 SHA |
| NSS init START 修正 | 代码已改为 `S28qca-nss-drv` / `S27qca-nss-pbuf`，仍需新构建验证 |
| 构建供应链 | 外部 NSS feed 已移除，但源码锁错误导致新构建必然失败 |
| 配置状态 | 存在 9 个当前源码未定义的陈旧 NSS 符号和 1 个无效依赖组合 |
| 路由器备份脚本 | 原实现不是完整备份，已重构 |
| OpenClash 恢复脚本 | 原实现未使用备份目录且硬编码订阅名，已重构 |
| VIKINGYFY 最新更新 | 新增 `38e28da... cleanup qca-nss config`，与当前本地修复有冲突 |
| packages feed | 落后 51 个提交；变化广泛，不应在本轮盲目升级 |
| 实机验证 | 尚未完成；本轮不刷写路由器 |

当前状态不能表述为“所有问题已修复”。准确表述应为：

> **确定性仓库问题已修正并通过本地检查；built-in qca-nss 新基线仍需新的
> GitHub Actions STOCK 构建、rootfs 校验和测试机运行时验证。**

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
| 上游落后为 0 | 审计时 VIKINGYFY 已 force-update 到 `38e28da...` | 当前源码与上游再次分叉 |

## 3. 本轮发现并修复的问题

| 优先级 | 问题 | 根因 | 修复 |
|---|---|---|---|
| P0 | 源码锁完整 SHA 不存在 | 只核对了短 SHA `3e7a3feb`，手工拼写完整 SHA | 改为真实 `3e7a3febdd3fba88a8ca248afd3cc946f9853ee9` |
| P0 | 构建按分支拉取后才比较 SHA | 分支移动会让历史锁定构建无故失败 | workflow 改为直接 `fetch $SOURCE_COMMIT` |
| P0 | 锁检查漏掉 3 个关键 commit | lint/build 只验证部分 feed SHA | 补充 SOURCE、SQM、LuCI 的 40 位 SHA 校验 |
| P1 | CI 可无限挂起 | jobs 未设置超时 | NSS/IPQ/IMM/LEDE 设 180 分钟，lint 20 分钟，sync 15 分钟 |
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
| OrdinaryJoys `codex/p0-nss-sync` | `3e7a3febdd3f...` | 与 OrdinaryJoys main 一致 |
| OrdinaryJoys `main` | `3e7a3febdd3f...` | 当前锁定源码 |
| VIKINGYFY `main` | `38e28da69292...` | 新增 1 个 qca-nss 清理提交并发生 force-update |
| VIKINGYFY `owrt` | `dfe9c76b658c...` | 非当前 NSS 构建基线 |
| qosmio/openwrt-ipq `main-nss` | `92a2d104145c...` | 与前次检查一致 |
| qosmio/nss-packages `NSS-12.5-K6.x` | `0d970dbf0185...` | 参考 feed 已继续更新 |

当前 OrdinaryJoys 分支相对 VIKINGYFY 最新 main 为 `42 left / 1 right`。这 42 个
left commits 主要是本仓历史修复和合并提交，并不表示可简单 rebase。

### 5.2 VIKINGYFY 最新提交影响

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

截至审计时，最新 Release 仍为：

`AX6_NSS_STOCK_20260616203522`

它不能证明 built-in qca-nss 新源码和 `S28/S27` 校验已经通过。

## 7. GitHub Actions 供应链修复

| Action | 原固定版本 | 新固定版本 | 验证 |
|---|---|---|---|
| `actions/checkout` | v4.1.1 / Node 20 | v7.0.0 / Node 24 | 官方 tag SHA `9c091bb...` |
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
| mock SSH 备份流程 | PASS |
| mock SSH OpenClash 恢复流程 | PASS |
| stock/expand 配置差异 | 仅目标设备/profile |

## 10. 尚未完成的验证

| 优先级 | 项目 | 完成条件 |
|---|---|---|
| P0 | 新源码 STOCK 云端构建 | Compile、rootfs validation、Release 全部成功 |
| P0 | `S28/S27` rootfs 链接 | 新镜像内实际存在 |
| P1 | built-in qca-nss 运行时 | 测试机 `nss-check -v` 无 FAIL |
| P1 | WiFi 2.4G IoT | 多设备完成关联、DHCP、联网和局域网发现 |
| P1 | VLAN | 802.1q 子接口实流量和 NSS VLAN 计数验证 |
| P1 | SQM | `nss-zk.qos` 实际限速和 NSS qdisc 状态 |
| P1 | ZeroTier/UPnP/OpenClash | 现场拓扑下运行时审计 |
| P2 | EXPAND 变体 | 仅在真实 256MB NAND 设备需求下构建和验证 |

## 11. 后续重构任务

### 11.1 VIKINGYFY `38e28da` 集成

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
3. 不要直接合并 VIKINGYFY `38e28da`。
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
8. 再开启 VIKINGYFY `38e28da` 独立重构。
