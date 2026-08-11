# AX6 插件更新与合并方案（2026-08-11）

## 1. 目标与边界

本轮只更新已经完成源码差异、依赖合同和 AX6 运行边界审查的插件层输入，
不修改 NSS、ECM、EDMA、ath11k、内核、DTB、交换/VLAN、SQM、IRQ 或实机配置。
不写入 OpenClash 订阅、覆写文件和运行态数据库，不刷写或重启路由器。

基线：

- 构建仓库：`0f4a34f84324846d39d4ea3efdb23c83377c1748`
- 源码仓库：`4e350435cd9e38d8d0d1fbae2d6ad523a45e622e`
- 已通过的 stock 构建：GitHub Actions `31392093042`
- 本轮候选分支：`codex/ax6-plugin-update-integration-20260811`
- LuCI 候选分支：`codex/luci-upstream-linear-20260811`

## 2. 本轮更新组

| 组 | 原状态 | 更新状态 | 审查结论 |
|---|---|---|---|
| LuCI | `OrdinaryJoys/luci@48884afb` | `OrdinaryJoys/luci@1bd7a996` | 线性基于官方 `8c4171bc`；11 个由 LuCI 提供的已选应用仍存在且依赖合同未变化；有效主题定制改为独立 override |
| Argon | `e2935dc` | `86c3156` | 仅模板变量传递和浏览器标题修复；现有 `1.7rem` AX6 样式调整继续由 `diy.sh` 管理 |
| OpenClash 插件 | 构建时跟踪 `master` | 策略不变 | 不锁版本；先解析远端提交，再按不可变 SHA 检出，阻止移动分支在同一次构建中产生混合来源 |
| OpenClash core | 构建时解析 `core` | 策略不变 | 继续检查压缩包结构、AArch64 ELF 和最终 rootfs SHA256 |

LuCI 更新包含认证/转义、密码策略、无线信道与 WPA3 显示、网络状态、
firewall、UPnP 和 package-manager 等修正。新的 Switch/VLAN 页面属于高风险 UI
边界：构建通过并不授权其改写 AX6 当前 `802.1q` 子接口拓扑，实机验证阶段只允许
只读查看；任何保存操作必须另行确认。

原 fork 的唯一独有提交用未压缩的整份 `cascade.css` 覆盖生成文件。它与当前
Argon 源码同步产生整文件冲突，并会撤销当前 mwan3、文件选择按钮、折叠控件和
OpenClash 布局修复。LuCI 的正式检查同时禁止 merge commit，因此最终候选线性
基于官方提交，把仍有效的 `1.7rem` 品牌字号放入独立 `ordinaryjoys.css`，并由
普通页和登录页模板显式加载。旧提交及完整差异保留在原 fork `master` 和本审计
记录中，不把过期生成物重放到新代码。AX6 的实际主题来自独立锁定的 Argon
`86c3156`，`diy.sh` 继续应用相同字号。

## 3. 明确不合并的更新

| 输入 | 当前处理 | 原因 |
|---|---|---|
| `immortalwrt/packages` 整体 HEAD | 保持 `4db836e2` | 新 feed 仍会通过 trafficshaper/freeradius3 引入全局 Kconfig 递归依赖；不能用插件更新掩盖配置图错误 |
| OpenSSH/OpenVPN/zoneinfo 等后台包 | 后续精确回移植组 | 必须逐包核对补丁、ABI、init/procd、依赖闭包和镜像空间，不与 LuCI 更新捆绑 |
| NSS/ECM/EDMA/ath11k/WiFi/交换驱动 | 冻结 | 本轮没有上游驱动变更需求，也没有证据支持为了插件升级改动核心数据路径 |
| OpenClash 订阅和覆写 | 不修改 | 文件会被订阅更新覆盖，且属于用户运行配置，不应作为固件修复入口 |

## 4. 合并门禁

本候选只有全部满足以下条件，才可进入主线审查：

1. `actionlint`、`shellcheck`、仓库全部 fixture 测试通过。
2. LuCI 官方锁定提交和 Argon 锁定提交可达，feeds 安装与 `defconfig` 无递归依赖。
3. OpenClash `RESOLVED_COMMIT == ACTUAL_COMMIT`，版本为三段数字格式。
4. OpenClash ZeroTier hook 和 DNS runtime contract 对构建时实际插件源码继续通过。
5. stock 固件、sysupgrade、initramfs/factory、rootfs、kmod、设备 manifest 和全部 SHA256 完整。
6. 最终 rootfs 的 OpenClash 版本、Meta core 哈希、dashboard 溯源与 BUILD-LOCK 一致。
7. 最终 rootfs 包清单与设备 manifest 完全一致，且不出现 `nf_flow_table`/软件流卸载回流。

## 5. 后续实机验证边界

完成云端构建和离线解包只证明“可编译、产物内部一致”，不证明无线、VLAN 或代理
运行态无回归。实机阶段必须等待确认，并按以下顺序进行：

1. 先做 `sysupgrade -T`，不刷写。
2. 获得确认后全新刷写，不保留登录密码。
3. 验证 LuCI 登录、状态页、无线页和 Switch/VLAN 页面只读加载。
4. 验证 2.4G/5G、NSS/ECM、双向吞吐、延迟/丢包、ZeroTier、UPnP 和 OpenClash DNS。
5. 发现回归时回到本独立分支修复，不在实机上堆叠持久补丁。

## 6. 回滚方案

本轮没有改动源码仓库锁和核心驱动。回滚只需恢复 LuCI commit 和 Argon
commit；OpenClash 仍按原有动态更新策略工作。已验证构建
`31392093042` 保持为独立可复核基线，不被本候选覆盖。
