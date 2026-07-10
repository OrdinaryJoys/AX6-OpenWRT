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
| ath11k shadow timer 下标 | 源仓 clean 候选 `codex/ax6-32b5-ath11k-shadow-timer-index-clean@604bf6b4ea9`;构建锁候选 `codex/ax6-32b5-ath11k-shadow-timer-build-test@bd43ed8` | `244-ath11k-dp-tx-perf.patch` 错用叠加 RBM 基值后的 `ti.buf_id` 索引按 TCL ring 数量分配的 timer 数组,存在越界风险;候选只改为 `tcl_ring_id`,与 VIKING 最新修正一致 |
| ath11k recovery 32b5 v2 候选 | 源仓 `codex/ax6-32b5-ath11k-recovery-v2-clean@f23b96be139`;构建仓 `codex/ax6-32b5-ath11k-recovery-v2-build-test@6ea19ab` | 在 timer 修正上原样叠加 VIKING `999-926` 到 `999-931`;六个文件逐字匹配上游。旧 `af8b2e1f1c6`/`a19b5d9` 组合缺少 timer 修正,已被替代 |
| ath11k/mac80211 TX teardown v2 候选 | 源仓 `codex/ax6-32b5-tx-teardown-v2-clean@d98e7d00d5d`;构建仓 `codex/ax6-32b5-tx-teardown-v2-build-test@be1f2ca` | 在 timer 修正上删除旧 `909`,新增 `911`、`912`、`658`;新增/删除边界与 VIKING 一致 |
| SSDK NSS-DP MAC sync 候选 | 源仓 `codex/ax6-32b5-ssdk-mac-sync-clean@a1829542ddb`;构建仓 `codex/ax6-32b5-ssdk-mac-sync-build-test@6666ca7` | 在 timer 修正上单独加入 VIKING `009`;与现有 `008` mutex unwind、`010` phylib 状态读取修正互补,但属于 downstream 修复,仍需独立编译和端口/FDB/SMB 实机验证 |
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
| runtime-audit Actions run `29060343662` | `7c2602a`;compile、final rootfs validation、sysupgrade/recovery/kmod artifact upload | PASS |
| runtime-audit 真实产物 | 三组 artifact 全部下载;sysupgrade/factory/initramfs/kmod SHA256 全通过;BOARD=`redmi_ax6-stock`;SquashFS XZ 44.19 MiB;kernel DTB 5,831,272 bytes | PASS |
| runtime-audit rootfs 内容 | 仓库 overlay 的 geodata、`nss-check`、配置审计、ECM boot guard、br-lan helper、VLAN、ZeroTier 和 WiFi 脚本逐字匹配;S19/S26/S28/S29 启动链正确 | PASS |
| runtime-audit 插件/冲突组件 | OpenClash 0.47.116 + ARM64 static `clash_meta`;ZeroTier 1.16.2;miniupnpd 2.3.9;无 sing-box/xray/WireGuard kmod 和 generic flow-offload 模块 | PASS |
| shadow timer clean 候选 | 相对 NSS core 只改 `244-ath11k-dp-tx-perf.patch` 一行;`git diff --check`;与 VIKING `tcl_ring_id` 语义交叉验证 | PASS |
| recovery v2 clean 候选 | 相对 NSS core 仅 1 行 timer 修正 + `999-926..931`;六个 recovery 文件逐字比较 VIKING | PASS |
| TX teardown v2 clean 候选 | 相对 NSS core 仅 1 行 timer 修正、删除 `909`、新增 `911/912/658`;三个新增文件逐字比较 VIKING | PASS |
| SSDK MAC sync clean 候选 | 相对 shadow timer 基线只新增 `009-feature-nss-dp-netdev-mac-sync.patch`;文件逐字比较 VIKING | PASS |
| 四个新构建锁候选 | 40 位源码 SHA、分支名、`test-vlan-add`、`test-openclash-geodata-defaults`、`test-openclash-archive` | PASS;shadow timer 源码和构建分支已推送并触发 run `29083106377`,其余三组继续等待 |

## 明确不能直接合并的上游项

| 上游项 | 原因 | 正确处理 |
| --- | --- | --- |
| `qca-nss-pbuf.init` 整体替换 | 会把 `START=19` 回退为 `START=27`,并在应用 pbuf 后主动 `wifi up`;这与 AX6 当前 NSS/WiFi 稳定边界冲突 | 保持现有 S19;如需要,只单独拆 `read_sysctl/write_sysctl` 这类无策略变化的小函数 |
| `qca-nss-ecm/files/disable_offloads.sh` 缩减版本 | 上游版本只处理 `rx-gro-list`,会重新暴露 IPQ807x 本机终结流量 GRO/GSO/checksum 丢包/重传风险 | 保持 `ecm.general.disable_offloads=1`、`disable_gro_list=1` 和 br-lan hotplug helper |
| `package/kernel/mac80211/ath.mk` 整体替换 | 会删除 `/etc/config/pbuf` conffiles,并折叠 `ATH11K_NSS_MESH_SUPPORT`/`ATH11K_MEM_PROFILE_512M` 选择项;与当前多 SKU pbuf/NSS 配置边界冲突 | 不整合;如后续需要,只逐项审 Kconfig 依赖,不能影响 pbuf UCI 和 rootfs 防回归 |
| `015-frontends-nss-respect-bridge-port-vlan-tagging-for-vlan-over-bridge.patch` 直接进入主线 | 它服务于 DSA bridge VLAN filtering;本仓默认拓扑禁止该配置 | 如用户要 bridge VLAN filtering 专项实验,必须单独分支、单独构建、单独实机验证 |
| `qualcommbe` EDMA/PPE 补丁 | 非 AX6 目标平台 | 仅记录上游动态,不进入 AX6 构建 |
| fitblk inline FIT 补丁 | AX6 当前不是 FIT block root 路径 | 仅记录上游动态,不用于 AX6 分区修复 |
| `999-921` NSS peer debugfs 统计 | 当前构建关闭 ath11k/mac80211 debugfs,不会提供读出接口,但仍增加计数和内存开销 | 不进性能主线;仅在单独 observability/debug 构建中评估 |
| `999-925` per-CPU WiFi TX queues | 在 NSS 构建下把所有 mac80211 vif 的 TX queue 数改为 `num_possible_cpus()`,影响面不只运行时 NSS 接口 | 只建性能实验分支;必须做吞吐、延迟、丢包和内存对照 |
| `390` airtime weight driver op 单独回移 | 通用 mac80211 op 已进入 official ImmortalWrt,但当前 ath11k/NSS 未发现消费者实现 | 等正式源树 rebase 自然带入;不把无消费者接口当作 AX6 故障修复 |

## 仍在持续跟踪/待验证

| 优先级 | 项目 | 当前状态 | 下一步 |
| --- | --- | --- | --- |
| P0 | NSS core 32b5 云端构建 | run `29036509737` 已成功;产物已下载到临时目录并完成 SHA256、sysupgrade 容器和 rootfs 内容检查 | 源码/构建级候选可进入下一阶段;仍未授权刷写或实机验证 |
| P0 | runtime audit + OpenClash geodata 整合构建 | run `29060343662` 已成功;真实产物 SHA、sysupgrade 结构、SquashFS、rootfs 关键文件、启动链和插件版本均已复核 | 仓库/产物级闭环;仍未授权刷写或实机验证 |
| P0 | 实机运行态 | 本轮未进行 SSH 修改或刷写 | 只有在用户确认后再做只读 SSH 检查或临时验证 |
| P0 | ath11k shadow timer 下标修正 | 源码 `604bf6b4ea9` 与构建锁 `bd43ed8` 已推送;远端 SHA 已精确核对;STOCK run `29083106377` 已触发 | 跟踪源码锁、compile、final rootfs 和 artifact;成功后下载产物再进入 recovery v2 |
| P1 | ath11k recovery v2 六补丁 | clean v2 源码和构建锁均已在本地提交;旧候选已废弃 | 只在 shadow timer 单独构建通过后推送/触发;再检查模块、rootfs 和 recovery 日志路径 |
| P1 | ath11k/mac80211 TX teardown v2 | clean v2 源码和构建锁均已在本地提交 | 在 recovery v2 之后单独构建;不与 recovery、per-CPU TX queue 或 debugfs 统计混合 |
| P1 | runtime audit 整合分支 | `7c2602a` 已完成云端构建和产物审查;后续本地提交只更新审查文档 | 文档更新可推送,不得因文档提交重复触发固件构建 |
| P2 | VLAN-over-bridge ECM 补丁 | 已判定不进默认主线 | 如后续确有 bridge VLAN filtering 需求,建立独立实验分支 |
| P2 | DP/SSDK/FDB/STP/MAC sync | DP `005`、SSDK `008/010` 职责无重叠;新增 SSDK009 clean 候选已完成 | 单独编译后,仅经用户确认才做 LAN 拔插、bridge FDB、MAC roaming、多文件/单文件 SMB 双向对照 |
| P2 | `999-921` debugfs NSS peer stats | 已拆解并判定不进当前性能构建 | 如需要观测,另建启用 debugfs 的诊断固件;默认固件不承担无读出接口的计数开销 |
| P2 | `999-925` per-CPU vif transmit queues | 已拆解,未合并 | 性能路径改动,影响本机到 WiFi 的 NSS redirect 发送锁竞争;必须单独吞吐/延迟/丢包验证 |
| P2 | `390` airtime weight driver op | official 已包含通用接口;当前未找到 ath11k/NSS 消费者 | 等未来 official 源树 rebase,不单独回移 |
| P1 运行态复核 | 2.4G IoT `tx-failed` 历史持续增长 | `COMPLETE_STATUS_2026-07-01.md` 记录 4 台设备在良好 RSSI 下累计和日增均异常;本轮未取得更新后的同口径采样,不能假定 recovery/TX 候选已解决 | 新固件实机验证时按 MAC/型号记录 `iw station dump`、重传/失败计数、省电状态和 NSS offload,分别对比 recovery v2 与 TX teardown v2;不把 HE20/HE40 自动兼容本身当作根因 |
| P1 运行态复核 | `nss-check -q` 历史偶发退出 1 | 旧文档记录约半数 cron 运行非零,但未固定具体 FAIL 项;当前脚本已修改多 SKU RAM 和审计逻辑,仍需新固件复测 | 只读保存 `nss-check -v` 的完整输出和退出码,区分瞬时计数器/接口状态与确定性配置错误;不得用自动写配置掩盖告警 |

## 文档时效边界

- `COMPLETE_STATUS_2026-07-01.md`、`FIX_HISTORY.md` 和 `docs/PROGRESS_REPORT_2026-07-06.md` 保留历史证据,其中旧 main HEAD、源码锁、RC、Actions `in_progress` 和“待提交锁文件”等状态不能用于当前执行。
- 本文件记录 2026-07-10 本地已抓取的 VIKING `32b5f4898f9`、official `4cafb73e88b` 和 qosmio `main-nss@92a2d104145` 交叉结果;不能据此声称覆盖后续新提交。
- 空间清理按用户要求不作为本轮仓库小空间配置项;但真实 overlay 若接近满载,仍会影响 OpenClash geodata 更新,属于实机运维条件而非驱动修复。

## 下一步顺序

1. 跟踪 shadow timer run `29083106377`;通过 compile、final rootfs、checksum 和源码锁检查后下载产物复核,失败则只按日志根因修复。
2. shadow timer 产物通过后,才推送并构建 recovery v2 `f23b96be139`/`6ea19ab`;旧 `af8b2e1f1c6`/`a19b5d9` 构建组合不得触发。
3. recovery v2 通过后,推送并构建 TX teardown v2 `d98e7d00d5d`/`be1f2ca`;与 recovery v2 保持独立。
4. TX teardown v2 通过后,推送并构建 SSDK MAC sync `a1829542ddb`/`6666ca7`;VLAN 继续使用 802.1q 子接口,不启用 bridge VLAN filtering。
5. `999-925` 如需继续,另建仅含 per-CPU TX queue 的性能分支;`999-921` 和 `390` 不进入当前默认候选。
6. 只有用户明确确认后,才对通过构建的单一候选做实机临时验证;不自动刷写、不直接合并主线。实机门槛包括 WiFi 重启/崩溃恢复、LAN 拔插、FDB、双向 SMB、Web/SSH 本机终结流量、TCP 重传和 NSS/ECM 计数。
