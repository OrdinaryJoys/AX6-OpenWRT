# AX6 32b5 上游拆解与下一轮验证状态

> 日期: 2026-07-10
> 范围: OrdinaryJoys/AX6-OpenWRT 构建仓、OrdinaryJoys/immortalwrt-nss 源仓、VIKINGYFY/immortalwrt 本地已抓取上游状态。
> 边界: 不刷写实机;不合并主线;不修改 OpenClash 订阅和覆写文件;不关闭 geoip/geosite/geoasn/chnr 自动更新。

## 当前已完成

| 项目 | 状态 | 结论 |
| --- | --- | --- |
| NSS core 32b5 候选 | 已拆分源仓分支 `codex/ax6-32b5-nss-core-candidate`;构建仓分支 `codex/ax6-32b5-nss-core-build-test` 已触发云端构建 | 只包含 qca-nss-clients/qca-nss-drv 的 5 个核心稳定补丁,未混入 pbuf/ECM/VLAN/IRQ 策略 |
| `nss-check` 多 SKU RAM 检查 | 已修复并整合到本地 `codex/ax6-runtime-audit-integration` | 1GB/512MB/256MB-class 设备不再被 1GB 专用阈值误判;低于 NSS/WiFi 安全范围仍 fail |
| fullcone NAT 审计 | 已修复并整合到本地 `codex/ax6-runtime-audit-integration` | 只在 fullcone 与已启用 UPnP/OpenClash/ZeroTier 重叠时 warn;不误报默认禁用的 ZeroTier 网络段 |
| ath11k recovery 32b5 候选 | 源仓本地分支 `codex/ax6-32b5-ath11k-recovery-candidate`, commit `f727574377c` | 仅原样引入 VIKING `999-926` 到 `999-931` 六个 WiFi recovery 补丁;边界检查无额外文件 |
| ath11k/mac80211 TX teardown 候选 | 源仓本地分支 `codex/ax6-32b5-tx-teardown-candidate`, commit `d6a2fa9cebc` | 只包含 `911` pending TX cleanup、`658` stopping iface status-frame cleanup、以及旧 `909` 到新 `912` 的 HTT 0x30 日志补丁替换 |
| pbuf/N2H 上游差异 | 已拆解 | 拒绝直接合并 VIKING `START=27`/启动后 `wifi up`/删除 UCI profile 的版本;当前继续保持 `S19` 早启动 |
| VLAN-over-bridge ECM 补丁 | 已拆解 | 该补丁修 DSA bridge VLAN filtering 下的 untagged/pvid 加速黑洞;但本仓按 qosmio 说明禁止 bridge VLAN filtering,默认使用 802.1q 子接口,因此不得作为主线修复混入 |
| `qualcommbe` EDMA/PPE 补丁 | 已拆解 | 属于 IPQ5332/IPQ9574/qualcommbe 路径,非 AX6 `qualcommax/ipq807x` 当前目标 |
| generic fitblk 补丁 | 已拆解 | 修 `/dev/fit0`/`fitrw` inline FIT 块设备映射;AX6 当前是 NAND/UBI/sysupgrade 路径,不是本轮 AX6 分区修复项 |

## 本地验证结果

| 分支/文件 | 验证 | 结果 |
| --- | --- | --- |
| `codex/ax6-runtime-audit-integration` | `git diff --check main..HEAD` | PASS |
| `codex/ax6-runtime-audit-integration` | `shellcheck -S error AX6-IPQ/files/sbin/nss-check AX6-IPQ/files/sbin/ax6-config-audit AX6-IPQ/files/usr/bin/zerotier-fw4 AX6-IPQ/files/sbin/vlan-add` | PASS |
| `codex/ax6-runtime-audit-integration` | `actionlint` | PASS |
| `codex/ax6-runtime-audit-integration` | `yamllint -d relaxed .github/workflows/lint.yml` | PASS |
| `codex/ax6-runtime-audit-integration` | `sh tests/test-vlan-add.sh` | PASS |
| `codex/ax6-runtime-audit-integration` | `sh tests/test-openclash-archive.sh` | PASS |
| `qca-nss-pbuf.init` | `shellcheck -S error` 和 `sh -n` | PASS |
| 构建 workflow | `S19qca-nss-pbuf`、`START=19`、`wait_for_ath11k_nss_offload` 防回归扫描 | PASS |

## 明确不能直接合并的上游项

| 上游项 | 原因 | 正确处理 |
| --- | --- | --- |
| `qca-nss-pbuf.init` 整体替换 | 会把 `START=19` 回退为 `START=27`,并在应用 pbuf 后主动 `wifi up`;这与 AX6 当前 NSS/WiFi 稳定边界冲突 | 保持现有 S19;如需要,只单独拆 `read_sysctl/write_sysctl` 这类无策略变化的小函数 |
| `qca-nss-ecm/files/disable_offloads.sh` 缩减版本 | 上游版本只处理 `rx-gro-list`,会重新暴露 IPQ807x 本机终结流量 GRO/GSO/checksum 丢包/重传风险 | 保持 `ecm.general.disable_offloads=1`、`disable_gro_list=1` 和 br-lan hotplug helper |
| `package/kernel/mac80211/ath.mk` 整体替换 | 会删除 `/etc/config/pbuf` conffiles,并折叠 `ATH11K_NSS_MESH_SUPPORT`/`ATH11K_MEM_PROFILE_512M` 选择项;与当前多 SKU pbuf/NSS 配置边界冲突 | 不整合;如后续需要,只逐项审 Kconfig 依赖,不能影响 pbuf UCI 和 rootfs 防回归 |
| `015-frontends-nss-respect-bridge-port-vlan-tagging-for-vlan-over-bridge.patch` 直接进入主线 | 它服务于 DSA bridge VLAN filtering;本仓默认拓扑禁止该配置 | 如用户要 bridge VLAN filtering 专项实验,必须单独分支、单独构建、单独实机验证 |
| `qualcommbe` EDMA/PPE 补丁 | 非 AX6 目标平台 | 仅记录上游动态,不进入 AX6 构建 |
| fitblk inline FIT 补丁 | AX6 当前不是 FIT block root 路径 | 仅记录上游动态,不用于 AX6 分区修复 |

## 仍在持续跟踪/待验证

| 优先级 | 项目 | 当前状态 | 下一步 |
| --- | --- | --- | --- |
| P0 | NSS core 32b5 云端构建 | 已触发 run `29036509737`;GitHub 查询因当前环境网络/用量限制暂时不可继续 | 等 GitHub 可用后查看 run;失败则拉失败日志定位;成功则下载 artifact 解包 rootfs |
| P0 | 实机运行态 | 本轮未进行 SSH 修改或刷写 | 只有在用户确认后再做只读 SSH 检查或临时验证 |
| P1 | ath11k recovery 32b5 六补丁 | 本地候选 commit `f727574377c`;尚未推送/构建 | GitHub 可用后推送源仓候选;等待 NSS core 构建结论后再建构建锁分支 |
| P1 | ath11k/mac80211 TX teardown 三项 | 本地候选 commit `d6a2fa9cebc`;尚未推送/构建 | GitHub 可用后推送源仓候选;单独构建验证,不与 per-CPU TX queue/debugfs 统计混合 |
| P1 | runtime audit 整合分支 | 本地 `codex/ax6-runtime-audit-integration` 已通过静态验证 | GitHub 可用后推送;可作为后续构建仓基线 |
| P2 | VLAN-over-bridge ECM 补丁 | 已判定不进默认主线 | 如后续确有 bridge VLAN filtering 需求,建立独立实验分支 |
| P2 | DP/SSDK/FDB/STP/MAC sync | 本轮未合并 | 继续沿用旧计划:每个补丁组单独分支、单独构建、端口/FDB/SMB 实机验证 |
| P2 | `999-921` debugfs NSS peer stats | 已拆解,未合并 | 仅提供观测能力;需确认 `peer->nss.nss_stats` 生命周期和 debugfs 读取路径后再单独验证 |
| P2 | `999-925` per-CPU vif transmit queues | 已拆解,未合并 | 性能路径改动,影响本机到 WiFi 的 NSS redirect 发送锁竞争;必须单独吞吐/延迟/丢包验证 |
| P2 | `390` airtime weight driver op | 已拆解,未合并 | 需要先确认 ath11k/NSS 是否实际实现该 op;没有消费者时不作为 AX6 故障修复项 |

## 下一步顺序

1. GitHub 可用后先确认 NSS core run `29036509737` 的 `Compile firmware` 和 rootfs validation 结果。
2. 若 NSS core 成功,解包 artifact 检查 rootfs: ECM offload 禁止项、`S19qca-nss-pbuf`、OpenClash 自动更新、VLAN 禁止项、插件构成和空间。
3. 推送 `codex/ax6-runtime-audit-integration`,作为 nss-check/fullcone 审计整合基线。
4. 推送 `codex/ax6-32b5-ath11k-recovery-candidate`,再单独建立构建锁分支验证 WiFi recovery 补丁。
5. 推送 `codex/ax6-32b5-tx-teardown-candidate`,再单独建立构建锁分支验证 TX teardown 稳定性补丁。
6. 继续拆 mac80211/NSS 统计、per-cpu vif 队列、airtime weight 等 WiFi/NSS 项,每项都按“源码边界检查 -> 构建 -> rootfs -> 实机确认”推进;`ath.mk` 只允许逐项审依赖,不得整体替换。
