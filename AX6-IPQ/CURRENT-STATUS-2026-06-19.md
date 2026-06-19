# AX6 NSS 当前状态与遗留问题

> 更新时间：2026-06-20（Asia/Shanghai）
>
> 本文件是当前唯一有效的状态清单。历史报告只用于追溯，不应用于判断当前
> 仓库、构建或路由器状态。

## 1. 当前证据基线

| 对象 | 当前基线 | 状态 |
|---|---|---|
| 编译仓库 | `OrdinaryJoys-AX6-OpenWRT/main@1fb8d078304b1be1bbd876102dd26207281f51c7` | 与 `origin/main` 一致；本轮修正尚未提交 |
| 源码仓库 | `immortalwrt-nss/main@9b711aebd554e861406eed91ab5ea6c5c9bc3707` | 审计开始时干净，与 `origin/main` 一致 |
| 锁定源码候选 | `61c945c14edd340379821d6dbd5965b029cc5bb2` | 修复 ath11k NSS Kconfig 递归依赖，等待云端构建 |
| packages feed | `8ed3556d174d9c04d3f97708d89c1c2ded236033` | 已由 `d461ce4` 完整 STOCK 构建覆盖 |
| 最新完整 STOCK 构建 | run `27832307023`，提交 `d461ce4` | 编译、rootfs、制品和 Release 全部成功 |
| 最新 Release | `AX6_NSS_STOCK_20260620003348` | 指向 `d461ce4`，SHA256 和 BUILD-LOCK 已复核 |
| 最新 main lint | run `27832487945`，提交 `1fb8d07` | 成功；本轮发现并修正一项无效推荐检查 |
| 实机固件 | `r39801-16b6a4fd78`，内核 `6.18.28` | 早于当前目标源码，不能代表新镜像运行状态 |

工作区另有旧副本 `../AX6-OpenWRT@689267f`。它不是当前有效仓库，后续检查、
修改和构建必须使用本文件所在的 `OrdinaryJoys-AX6-OpenWRT`。

## 2. 已由当前代码确认完成

| 项目 | 结论 | 证据边界 |
|---|---|---|
| qca-nss 来源 | 已迁移到源码树 `package/qca-nss` | 不再依赖已废弃的外部 NSS feed |
| ath11k NSS 包依赖 | 已恢复 | `ath.mk` 包含 drv、WIFIOFFLOAD 和 EXT_VDEV 条件依赖 |
| STOCK 升级目标选择 | 已按实际 `rootfs/rootfs_1` 存在情况动态选择 | 单 rootfs 合并布局不会因残留 boot flag 选择不存在的槽 |
| STOCK 容量预检 | 已加入 `platform_check_image` | 按实机 MTD 几何、坏块和 UBI 预留检查 |
| STOCK 构建容量门禁 | 已按 `0x06640000` 合并布局检查 | factory UBI 上限为 `0x06340000` |
| STOCK/EXPAND 配置差异 | 仅设备 profile 不同 | 软件配置当前一致 |
| ZRAM 构建配置 | 已启用 SWAP、zram、zstd 和 256MB 首次启动策略 | 尚未由最新镜像实机启动证明 |
| WiFi 默认策略 | US、2.4G HE40、20/40 共存、禁止 `noscan` | 不强制 SSID 隔离、PMF 或场景策略 |
| VLAN 助手 | 默认拒绝访问路由器，仅放行 DHCP/DNS，并支持失败回滚 | mock 成功与回滚测试通过 |
| OpenClash 恢复 | 已校验归档路径、成员类型并支持失败回滚 | mock 测试通过，未在新固件实机恢复 |
| Release 边界 | sysupgrade 与 recovery 文件分离 | factory UBI/initramfs 不再作为普通 Release 升级文件 |

## 3. 已完成验证

| 验证 | 当前结果 |
|---|---|
| `git diff --check` | PASS |
| 仓库 Shell 语法检查 | PASS |
| `tests/test-vlan-add.sh` | PASS |
| `tests/test-openclash-archive.sh` | PASS |
| 最新 main lint | PASS，run `27832487945` |
| `d461ce4` STOCK 编译、rootfs 校验和 Release 流程 | PASS，run `27832307023` |
| Release SHA256 与 GitHub 资产摘要 | PASS |
| 197 个内核模块 vermagic | 全部为 `6.18.35 SMP mod_unload aarch64` |
| NSS/ath11k 模块依赖链 | PASS：ath11k→NSS drv→NSS DP/SSDK |

以上结果证明 `d461ce4` 的 STOCK 产物在构建和静态内容层面完整，但不能替代
新镜像实机运行验证。

## 4. 当前仍存在的确定问题

### P0：实机运行闭环

1. 最新 Release 尚未在目标 AX6 上执行 `sysupgrade -T`。
2. 新内核 `6.18.35`、ZRAM、完整 S26-S29 NSS 启动链、WiFi/IoT、VLAN 和
   SQM 尚未由新镜像实机证明。
3. 未经用户再次确认，不上传镜像、不修改配置、不刷写。

### P1：EXPAND 安全验证不完整

1. `platform_check_image` 只对 `*-stock` 调用容量预检，`redmi,ax6`
   EXPAND 路径仍直接返回成功。
2. EXPAND 运行时使用独立 `ubi_kernel` 和 `rootfs` UBI，当前 CI 主要检查
   factory UBI 总体大小，没有分别证明 sysupgrade kernel/root 能装入对应分区。
3. EXPAND 升级会先写 U-Boot 环境变量，缺少与 STOCK 同等级的升级前布局和
   容量硬门禁。
4. 没有真实 256MB NAND 设备证据，因此 EXPAND 仍应视为未验证实验目标。

### P1：自动测试覆盖不足

当前只有 VLAN 和 OpenClash 两个行为测试。尚缺：

- `xiaomi_stock_get_upgrade_part` 的单槽、双槽和无槽测试。
- `xiaomi_stock_check_image_size` 的正常、超限、坏块和缺失 sysfs 测试。
- AX6/AX3600/AX9000 stock 布局回归测试。
- EXPAND `ubi_kernel/rootfs` 分区和容量测试。
- `nss-check`、`ax6-config-audit`、boot guard、WiFi 迁移和备份脚本测试。

### P1：本轮已修正但需 CI 验证

- 修复 `PACKAGE_kmod-ath11k → ATH11K_NSS_MESH_SUPPORT → ATH11K_NSS_SUPPORT
  → PACKAGE_kmod-ath11k` 递归依赖。
- `make defconfig` 发现递归依赖时现在会直接让构建失败。
- 移除 lint 对不存在的 `CONFIG_PACKAGE_MAC80211_NSS_SUPPORT` 的误导检查。
- rootfs 门禁补充 NSS DP、SSDK、ECM 和 S26/S29 启动链接。
- 将 stock/expand 的 CPU 优化统一为已成功构建实际使用的 `-Os`。
- 修正 workflow、README、HARDWARE 和 `diy.sh` 的过期分区/外部 feed 描述。

### P2：状态文档本身过时

`FIX_CHECKLIST_2026-06-19.md` 仍以 `878c97d/3e7a3feb` 为基线，并将 lint、
构建、rootfs 和实机验证混为一类。旧 `AUDIT-REPAIR-REPORT-2026-06-19.md`
也是追加式历史报告，前后存在已经被后续提交推翻的结论。

## 5. 当前实机状态

这些结论只描述当前运行的旧固件，不应倒推成最新仓库缺陷。

| 项目 | 实机结果 | 判断 |
|---|---|---|
| 分区 | 单 `rootfs=0x06640000`，无 `rootfs_1` | 确认是 custom U-Boot/SMEM 合并布局 |
| NAND | 128MiB，rootfs 有 1 个坏块 | 当前 STOCK 目标布局匹配 |
| UBI | kernel 46 LEB、root 422 LEB、rootfs_data 326 LEB | 现有布局可容纳当前运行系统 |
| Overlay | 约 90%，仅余约 3.3MB | 确定的运行风险，OpenClash 更新可能失败 |
| NSS | 两个 NSS core 正常，ECM 有活动连接 | 当前旧固件 NSS 正常工作 |
| WiFi | US；5G HE80；2.4G 配置 HE40、实际退回 20MHz | 20/40 共存表现正常 |
| IoT | 多个 2.4G 设备已长期关联 | 不能认定存在普遍关联失败 |
| WiFi 计数 | 多客户端 `tx failed` 很高 | 可能是累计/驱动统计，需丢包和吞吐交叉验证 |
| ZRAM | `/proc/swaps` 不存在，zram disksize=0 | 当前旧固件没有可用 swap |
| 启动链 | 缺目标镜像要求的部分 NSS rc.d 链接 | 当前旧固件与目标 rootfs 不同，不能证明新镜像缺失 |
| OpenClash | 正在运行，占用较多 overlay | 优先处理空间风险，不应先改 DNS 策略 |
| ZeroTier | 正在运行 | 当前未发现确定故障 |
| UPnP | 已禁用 | 当前未发现确定故障 |

## 6. 上游合并结论

- `VIKINGYFY/main@5f520e5c` 重构了 ath11k/NSS 配置模型，并把普通 NSS 支持
  与 mesh、512M profile、meshmgr 选择关系耦合。
- 当前 AX6 使用 NSS FW 12.5 且关闭 mesh，不能直接合并该变化。
- 应在独立源码分支解决 Kconfig、包依赖和内存 profile 差异，再执行完整
  STOCK 构建和实机 NSS/WiFi 验证。
- `qosmio/openwrt-ipq` 继续作为 NSS 数据路径和 VLAN 约束参考，但不直接提供
  当前 AX6 custom SMEM 发布配置。

## 7. 正确执行顺序

1. 修正文档和 workflow 中已经确认的错误描述。
2. 为 STOCK 升级预检补充可重复的 mock 测试。
3. 为 EXPAND 增加分区布局、kernel/root 分别容量预检；未完成前不发布。
4. 对本轮门禁和文档修正运行 lint；合并后再决定是否重新构建。
5. 经用户确认后，将已验证镜像上传到当前实机并只执行 `sysupgrade -T`。
6. 再次确认后才允许刷写。
7. 新镜像运行后检查 ZRAM、NSS 启动链、WiFi 丢包、VLAN、SQM、
   ZeroTier、UPnP 和 OpenClash。

## 8. 当前禁止结论

- 不能把构建成功表述为所有驱动已经完成实机验证。
- 不能把当前旧固件的运行状态当成 `d461ce4` Release 的运行结果。
- 不能把当前旧固件的 ZRAM/启动链状态当成最新仓库构建结果。
- 不能称 EXPAND 已安全适配或已完成实机验证。
- 不能仅凭 `tx failed` 计数认定 WiFi 驱动故障。
- 不能直接合并 VIKINGYFY 的 NSS/WiFi 重构。
- 不能在未确认前修改或刷写实机。
