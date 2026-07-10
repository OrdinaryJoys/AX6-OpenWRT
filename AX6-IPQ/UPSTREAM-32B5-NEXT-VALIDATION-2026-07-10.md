# AX6 32b5 上游拆解与下一轮验证状态

> 日期: 2026-07-10
> 范围: OrdinaryJoys/AX6-OpenWRT 构建仓、OrdinaryJoys/immortalwrt-nss 源仓、VIKINGYFY/immortalwrt 本地已抓取上游状态。
> 边界: 不刷写实机;不合并主线;不修改 OpenClash 订阅和覆写文件;不关闭 geoip/geosite/geoasn/chnr 自动更新。

## 当前已完成

| 项目 | 状态 | 结论 |
| --- | --- | --- |
| NSS core 32b5 候选 | 源仓分支 `codex/ax6-32b5-nss-core-candidate`;构建仓分支 `codex/ax6-32b5-nss-core-build-test`;Actions run `29036509737` 已成功 | 只包含 qca-nss-clients/qca-nss-drv 的 5 个核心稳定补丁,未混入 pbuf/ECM/VLAN/IRQ 策略;编译、最终 rootfs 校验和产物上传全部通过 |
| `nss-check` 多 SKU RAM 检查 | 已修复并整合到本地 `codex/ax6-runtime-audit-integration` | 1GB/512MB/256MB-class 设备不再被 1GB 专用阈值误判;低于 NSS/WiFi 安全范围仍 fail |
| fullcone NAT 审计 | 已修复并整合到本地 `codex/ax6-runtime-audit-integration` | 只在 fullcone 与已启用 UPnP/OpenClash/ZeroTier 重叠时 warn;不误报默认禁用的 ZeroTier 网络段 |
| OpenClash geodata 自动更新 | 真实产物发现 0.47.116 缺少五个自动更新 UCI 项,上游 LuCI 缺省值为 `0`;已在本地集成分支补修 | 新装仅为缺失项启用 Country MMDB/GeoIP.dat/GeoSite/GeoASN/chnroute 自动更新并错峰到工作日凌晨;显式 `0/1` 和自定义时间保持不变;不接触订阅、覆写或 YAML |
| ath11k recovery 32b5 干净候选 | 源仓分支 `codex/ax6-32b5-ath11k-recovery-clean`, commit `af8b2e1f1c6` | 以已成功构建的 NSS core `ccf777645f4` 为父提交,相对父提交恰好 6 个 VIKING `999-926` 到 `999-931` recovery 补丁 |
| ath11k/mac80211 TX teardown 干净候选 | 源仓分支 `codex/ax6-32b5-tx-teardown-clean`, commit `440f90246cb` | 同样以 `ccf777645f4` 为父提交,相对父提交恰好 4 个路径:`911`、`912`、`658` 和删除旧 `909` |
| 旧 WiFi 候选分支 | `codex/ax6-32b5-ath11k-recovery-candidate` 与 `codex/ax6-32b5-tx-teardown-candidate` | 禁止构建或合并:二者基于 `a706a46e462`,相对 `main` 额外混入 24 个 hostapd/WiFi v2 文件;仅保留作审计记录 |
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
| NSS core Actions run `29036509737` | compile、final rootfs validation、artifact checksums | PASS |
| NSS core sysupgrade rootfs | SquashFS superblock、BOARD、NSS/ECM/ath11k/SSDK/ZRAM/ZeroTier/OpenClash 文件与启动链接 | PASS |
| NSS core 产物校验 | sysupgrade、factory UBI、initramfs ITB、离线 kmod `SHA256SUMS` | PASS |
| OpenClash geodata defaults | `shellcheck`、`actionlint`、`yamllint`、模拟 UCI 幂等/保留显式值测试 | PASS |

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
| P0 | NSS core 32b5 云端构建 | run `29036509737` 已成功;产物已下载到临时目录并完成 SHA256、sysupgrade 容器和 rootfs 内容检查 | 源码/构建级候选可进入下一阶段;仍未授权刷写或实机验证 |
| P0 | runtime audit + OpenClash geodata 整合构建 | 分支 `codex/ax6-runtime-audit-integration`,commit `7c2602a`;Actions run `29060343662` 已进入 `Compile firmware` | 等编译和 final rootfs validation;成功后下载产物验证多 SKU 审计和 geodata 缺省策略 |
| P0 | 实机运行态 | 本轮未进行 SSH 修改或刷写 | 只有在用户确认后再做只读 SSH 检查或临时验证 |
| P1 | ath11k recovery 32b5 六补丁 | 干净源分支已推送;构建仓分支 `codex/ax6-32b5-ath11k-recovery-clean-build-test`,commit `a19b5d9`,已锁定远端 SHA 并推送 | runtime-audit run 成功后按顺序触发 STOCK 构建 |
| P1 | ath11k/mac80211 TX teardown 三项 | 干净源分支已推送;尚未建立干净构建锁分支 | recovery 构建与 rootfs 通过后再单独准备和触发,不与 per-CPU TX queue/debugfs 统计混合 |
| P1 | runtime audit 整合分支 | 已推送并通过本地静态/模拟测试 | 以 Actions run `29060343662` 的结果作为后续 WiFi 构建仓基线 |
| P2 | VLAN-over-bridge ECM 补丁 | 已判定不进默认主线 | 如后续确有 bridge VLAN filtering 需求,建立独立实验分支 |
| P2 | DP/SSDK/FDB/STP/MAC sync | 本轮未合并 | 继续沿用旧计划:每个补丁组单独分支、单独构建、端口/FDB/SMB 实机验证 |
| P2 | `999-921` debugfs NSS peer stats | 已拆解,未合并 | 仅提供观测能力;需确认 `peer->nss.nss_stats` 生命周期和 debugfs 读取路径后再单独验证 |
| P2 | `999-925` per-CPU vif transmit queues | 已拆解,未合并 | 性能路径改动,影响本机到 WiFi 的 NSS redirect 发送锁竞争;必须单独吞吐/延迟/丢包验证 |
| P2 | `390` airtime weight driver op | 已拆解,未合并 | 需要先确认 ath11k/NSS 是否实际实现该 op;没有消费者时不作为 AX6 故障修复项 |

## 下一步顺序

1. 跟踪 runtime-audit run `29060343662`;成功后下载并解包产物,确认新增 OpenClash geodata defaults 与多 SKU 审计真实进入 rootfs。
2. 触发 `codex/ax6-32b5-ath11k-recovery-clean-build-test` 的 STOCK 构建,验证 6 个 WiFi recovery 补丁。
3. recovery 构建通过后,从 `7c2602a` 建立只锁定 `codex/ax6-32b5-tx-teardown-clean` 的构建分支,再单独验证 TX teardown。
4. 对上述两个 WiFi 分支分别做源码边界、编译、rootfs 检查;不得在同一构建中混入 `999-921`、`999-925` 或 airtime weight。
5. 只有用户明确确认后,才对通过构建的单一候选做实机临时验证;不自动刷写、不直接合并主线。
6. 继续拆 mac80211/NSS 统计、per-cpu vif 队列、airtime weight 等 WiFi/NSS 项;`ath.mk` 只允许逐项审依赖,不得整体替换。
