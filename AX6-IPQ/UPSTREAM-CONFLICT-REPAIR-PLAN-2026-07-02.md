# AX6 NSS 上游冲突审查与修复方案

日期: 2026-07-02

## 检查范围

| 仓库 | 最新检查点 | 结论 |
|---|---:|---|
| OrdinaryJoys/immortalwrt-nss | `1cf19f9724` | 当前构建锁定源, 已包含 S19 pbuf 早启动修复 |
| VIKINGYFY/immortalwrt | `ec6ea46cf1` | 有 qca-nss 新补丁, 但部分脚本会覆盖本仓稳定策略 |
| qosmio/openwrt-ipq | `92a2d10414` | AP_VLAN/dynamic VLAN 修复已在本仓语义覆盖, 6.12 rebase 不适用于当前 6.18 树 |
| vernesong/OpenClash | `23896d2662` | 当前 `master` 与 `v0.47.110` 一致, 构建应跟随 master 而不是固定插件版本 |

## 核心边界

| 子系统 | 必须保持的边界 | 原因 |
|---|---|---|
| NSS/ECM | OpenWrt packet steering、software/hardware flow offload 均关闭 | qosmio 说明 NSS 与 OpenWrt 通用 offload 路径冲突 |
| ECM netdev offload | 保留 `ecm.general.disable_offloads=1` 与 `disable_gro_list=1` | IPQ807x 本机终结流量在 checksum/GRO/GSO/TSO 开启时会出现丢包/重传/Web 卡顿 |
| pbuf/N2H | 最终 rootfs 必须是 `S19qca-nss-pbuf` | pbuf/N2H 需要在 WiFi AP 接口创建前应用 |
| VLAN | 不使用 `option vlan_filtering 1`、`config bridge-vlan`、`lan1:u*` DSA bridge VLAN filtering | qosmio 明确说明 bridge VLAN filtering 不兼容 NSS WiFi offload |
| WiFi | `ath11k frame_mode=2`、`nss_offload=1`, 不使用无效 `rx_hash` 参数 | 确保 WiFi NSS redirect 入口正确 |
| IRQ | 保留上游 `S93smp_affinity` 与 `S99set-irq-affinity`, 自定义 `ax6-irq-affinity` 只手动执行 | 避免多个脚本互相覆盖 IRQ/RPS/XPS 策略 |

## 上游代码冲突结论

| 上游提交/区域 | 状态 | 处理 |
|---|---|---|
| qosmio `7deb71dacb` dynamic VLAN initialization | 已语义覆盖 | 不重复 cherry-pick; 当前补丁已有 AP_VLAN `drv_set_key` NSS 判断和 AP_VLAN open 初始化 |
| qosmio `819196f2be` AP_VLAN ext_vdev cleanup | 已语义覆盖 | 不重复 cherry-pick; 当前补丁已有 ext_vdev up 时先 down, 失败路径走 `err_stop` |
| qosmio `823027c8b7` NSS mesh tx flags | 低优先级 | AX6 默认不启用 mesh NSS, 后续仅在需要 mesh 时手工评估 |
| qosmio `70e395a3e0` backports 6.18.26 rebase | 不直接合并 | 涉及整套 mac80211 patch stack 重排, 需要完整编译验证 |
| qosmio `92a2d10414` kernel 6.12.92 rebase | 不适用 | 当前仓库是 6.18 patch tree, 6.12 路径不匹配 |
| VIKING `bcc56131b8` qca-nss stability patches | 可合并候选 | 已本地 cherry-pick 验证, 仅新增 9 个 qca-nss patch, 不覆盖运行策略 |
| VIKING `2e496928a9` qca-nss wifi-no | 暂不合并 | 会把 `qca-nss-pbuf` 从 S19 改回 S27 并改变检测/重启时序 |
| VIKING ECM `disable_offloads.sh` 简化 | 必须拒绝 | 会移除本仓依赖的 `disable_offloads=1` 完整 netdev offload 关闭逻辑 |
| VIKING `991_set-network.sh` | 必须拒绝 | 会移除首次启动无条件关闭 packet steering/flow offload 的保护 |
| VIKING IRQ 启动顺序调整 | 暂不合并 | 会改变 `smp_affinity` 启动顺序和 UCI 开关语义 |

## 已执行修复

| 仓库 | 文件 | 修复 |
|---|---|---|
| AX6-OpenWRT | `.github/workflows/build-AX6-IPQ.yml` | 最终 rootfs 校验收紧到 `S19qca-nss-pbuf`, 并检查 pbuf 脚本关键逻辑 |
| AX6-OpenWRT | `AX6-IPQ/HARDWARE.md` | 文档明确最终镜像必须使用 S19 pbuf |
| AX6-OpenWRT | `CHANGELOG.md` | 记录 S19 pbuf 防回归校验 |
| immortalwrt-nss | `package/qca-nss/**/patches/020-025*.patch` | 本地合入 VIKING `bcc56131b8` 的 qca-nss 稳定性补丁组 |

## 修复顺序

1. 保留并验证现有 NSS 安全边界: `packet_steering=0`、`flow_offloading=0`、`disable_offloads=1`、`disable_gro_list=1`、`S19qca-nss-pbuf`。
2. 只合入不覆盖运行策略的 qca-nss 稳定性补丁组。
3. 不重复移植已经语义覆盖的 AP_VLAN/dynamic VLAN 修复。
4. 构建前更新 AX6 构建锁定提交到新的 `immortalwrt-nss` commit。
5. 构建后必须解包 rootfs 验证 NSS 模块、启动链、ath11k 参数、ECM offload 配置、VLAN 禁用项和 OpenClash overlay 审计工具。
6. 实机只做只读检查和用户确认后的临时验证; 不自动刷写。

## 必须通过的验证

| 阶段 | 命令/检查 | 通过标准 |
|---|---|---|
| 本地静态 | `git diff --check` | 无空白/patch 格式错误 |
| CI 静态 | `yamllint`, `actionlint`, `shellcheck` | 全部通过 |
| 源码补丁 | qca-nss patch 文件只新增, 不改 ECM/pbuf/IRQ 脚本 | 无策略覆盖 |
| 最终 rootfs | `S19qca-nss-pbuf`, `START=19`, ath11k `frame_mode=2/nss_offload=1` | 全部存在 |
| 运行审计 | `nss-check`, `ax6-config-audit` | 不出现 NSS/WiFi/ECM/VLAN P0/P1 FAIL |
| 实机网络 | ping/丢包、LuCI 大页面、OpenClash XHR、LAN SMB 单文件/多文件 | 无持续丢包/重传/明显卡顿 |

## 仍需注意

| 问题 | 当前状态 | 后续动作 |
|---|---|---|
| `/overlay` 空间满 | 实机已确认主要来自 OpenClash Geo 数据和 overlay UI | 不在仓库预设小空间配置; 仓库只新增审计, 实机清理需单独确认 |
| OpenClash DNS 单点依赖 | Redirect 模式依赖本地 core | 不改订阅/覆写; 使用官方 UCI DNS 生成路径并保留审计 |
| AP_VLAN | qosmio 仍标注 ath11k broken/risky | 不作为默认功能启用, 仅保留崩溃/资源泄漏修复 |
| VIKING 大规模 patch reorder | 直接合并风险高 | 只按文件/功能选择性移植, 不做整分支 merge |
