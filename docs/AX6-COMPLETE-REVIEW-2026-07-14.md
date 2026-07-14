# AX6 完整修复审查与构建验证报告（2026-07-14）

## 1. 最终状态

本轮已经完成源码差异审查、遗漏修复、补丁严格重放、构建锁定、云端静态检查、AX6 STOCK 完整编译和 artifact 独立复核。

| 项目 | 最终证据 | 状态 |
|---|---|---|
| 源码主线基线 | `OrdinaryJoys/immortalwrt-nss@56807d9661dbe7df421d1fd31feba76677b5703d` | 已锁定 |
| 源码候选 | `codex/ax6-upstream-gap-complete@991f215ffb3aeeaf65e3e4703d8e1fb696065faf` | 已推送，工作区干净 |
| 构建仓主线 | `OrdinaryJoys/AX6-OpenWRT@099556aae4c0449a23e157fd95d061fc7537f59a` | 未修改 |
| 构建候选代码提交 | `codex/ax6-upstream-gap-complete-build@a3d6d58669e767e5d7ae82787ddfe7615f5bf1ee` | 已推送；其后只追加本文档 |
| 云端 Lint | Actions `29345426186`，提交 `a3d6d58` | 全部通过 |
| 完整 STOCK 构建 | Actions `29345081914`，提交 `8505d7d` | 成功 |
| 构建源码锁 | `991f215`，基线 `56807d9`，清单 SHA256 `d2ebf619...738c9` | 产物内一致 |
| 发布/实机 | 未合并主分支、未发布、未 SSH、未刷写 | 保持安全边界 |

完整构建使用 `8505d7d`。其后的 `a3d6d58` 只把 Lint 中不可靠的 `A && B || C` 改成显式 `if`，不改变源码锁、配置、固件构成或编译路径；该提交已由独立云端 Lint 完整验证。

## 2. 本轮补齐的遗漏和错误

| 范围 | 原问题 | 完整修复 | 验证 |
|---|---|---|---|
| hostapd | 缺少 2026-1 安全公告的完整 MLE/MLD 边界修复 | 纳入 8 个安全补丁，`PKG_RELEASE=2` | 70/70 补丁严格重放；云端编译通过 |
| netifd/libubox/ubus | 基础网络组件落后于上游修复 | 按 ABI 关系同步锁定版本 | 构建、bridge/VLAN 相关脚本与 Lint 通过 |
| WiFi scripts | disabled VIF、antenna、mesh probe、GCMP-256、SAE-EXT-KEY、EAP/cert/私钥别名和 iwinfo 信息缺失 | 合并完整上游逻辑并保留 AX6 的 US/HE40/coexistence 策略 | schema、ucode、hostapd/supplicant 路径和完整构建通过 |
| hostapd ubus | radar-detected 通知位置错误 | 对齐上游通知路径 | hostapd 补丁重放与编译通过 |
| ECM VLAN | VLAN-over-bridge 加速规则只看上层 VLAN，可能与 bridge port 线侧 tagged/untagged 状态不一致 | 新增 bridge port on-wire tag 判断，无法确定时回退 host path | ECM 15/15 补丁重放，`kmod-qca-nss-ecm ...-r8` 构建成功 |
| ath11k NSS recovery | Q6 恢复期间仍存在 monitor/CE/TX/ring 生命周期窗口 | 对齐完整 recovery guard 组并保留本地 999-932 IRQ/NAPI quiesce | mac80211/backports 278/278 严格重放；ath11k/ath11k-ahb 产物存在 |
| SSDK | NSS-DP netdev carrier 变化后 MAC software sync 可能未重新调度 | 新增 `ssdk_netdev_refresh_mac_sw_sync()` 和端口边界检查 | SSDK 8/8 补丁重放；`kmod-qca-ssdk` 构建成功 |
| AX3600 stock DTS | 上游同步时 ART fixed-layout NVMEM 状态不完整 | 恢复 stock ART NVMEM，保留尚需实机确认的 ethernet aliases | DTS 进入锁定差异和 AX6 构建 |
| Linux 6.18 | 仍为 6.18.35，且直接同步会引入重复/已上游补丁 | 完整升级到 6.18.38，刷新 generic/qualcommax/NSS 栈，删除已内建 MIPS 与重复 flowtable 补丁 | 精确版本/hash 门禁；Linux 云端全构建通过 |
| 构建溯源 | 只校验已列文件，不能证明清单覆盖全部 Git 差异 | 锁定基线提交，自动集合比对现存、删除和重命名路径 | 169 个现存变化 + 14 个旧路径完全一致；负向测试通过 |
| absent 清单 | 只记录 9 个纯删除路径，遗漏 5 个重命名旧路径 | 将全部 5 个迁移源路径加入缺席门禁 | 故意删除一项时 verifier 正确失败 |
| 云端 Lint | OpenClash 提交捕获顺序检查使用 `&& ... ||` | 改为显式 `if` | Actions `29345426186` 全部通过 |

## 3. 上游交叉检查结果

截至本轮 fetch，主要参照状态为：

| 仓库/分支 | HEAD | 处理结论 |
|---|---|---|
| OrdinaryJoys/immortalwrt-nss main | `56807d9661db` | 作为固定基线，修复保持候选分支 |
| VIKINGYFY/immortalwrt main | `30e28764598d` | 按文件和语义拆解，不整仓合并 |
| immortalwrt/immortalwrt master | `4cafb73e88b6` | hostapd、基础组件、WiFi scripts、kernel 通用修复参照 |
| qosmio/openwrt-ipq main-nss | `92a2d104145c` | NSS/ath11k 架构与限制参照；Linux 6.12 栈不直接合入 6.18 |
| qosmio/openwrt-ipq 25.12-nss | `d6848fa2ea00` | backports 6.18.26 参照 |
| Qualcomm CodeLinaro qca-ssdk | `d9a19649...` | 锁定所选 QSDK 分支 |
| Qualcomm CodeLinaro qca-nss-dp | `d8f802f0...` | 锁定所选 QSDK 分支 |
| Qualcomm CodeLinaro qca-nss-drv | `6aa14c7...` | 锁定所选 QSDK 分支 |
| Qualcomm CodeLinaro qca-nss-ecm | `8c7355b...` | 锁定所选 QSDK 分支 |
| Qualcomm CodeLinaro qca-nss-clients | `51be82d...` | 锁定所选 QSDK 分支 |

没有整合 VIKINGYFY 的 NSS cleanup 脚本，因为它会删除当前已验证的 ECM/pbuf 配置所有权并改变 `disable_offloads=1` 策略。没有整合 qca8084/qca81xx PHY 补丁，因为 AX6 使用 qca8075。没有删除 AX6/AX3600 ethernet aliases，因为缺少 stock/custom U-Boot 实机证据。

## 4. 源码和补丁验证

严格重放采用锁定上游源、`-F0`、零 fuzz、零 reject：

| 补丁栈 | 结果 |
|---|---:|
| mac80211/backports 6.18.26 | 278/278 |
| hostapd | 70/70 |
| qca-nss-ecm | 15/15 |
| qca-nss-dp | 5/5 |
| qca-ssdk | 8/8 |
| qca-nss-drv | 16/16 |
| qca-nss-clients | 13/13 |
| 合计 | 405/405 |

附加检查：

- 源码分支相对基线共有 42 个提交、169 个现存变化路径和 14 个删除/重命名旧路径。
- `git diff --check`、`git fsck`、冲突标记扫描、ShellCheck、schema/JSON 检查均通过。
- 本地 macOS 大小写不敏感文件系统无法同时展开 Linux 的 `xt_DSCP.c` 与 `xt_dscp.c`，因此 Linux 全补丁栈的最终结论以 Ubuntu Actions 完整构建为准；这不是源码 reject。
- 构建工作流直接检查 Linux 6.18.38/hash、hostapd 8 个补丁、ECM VLAN、SSDK MAC sync、WiFi EAP 映射、ath11k recovery 文件及 ucode 执行位。

## 5. 云端验证

### 5.1 Lint `29345426186`

以下检查全部通过：ShellCheck、Actionlint、Yamllint、构建锁、STOCK/EXPAND 差异、NSS 冲突、ZRAM 依赖、ECM offload、Kconfig 一致性、包归属、WiFi 默认值、IRQ 所有权、pbuf 和最终配置合并。

### 5.2 完整构建 `29345081914`

- 开始：2026-07-14 15:23:03 UTC
- 完成：2026-07-14 17:21:30 UTC
- `Clone locked source code`：完整差异与语义门禁通过
- `Compile firmware`：成功，Linux 6.18.38/NSS/SSDK/ECM/ath11k 全部编译
- `Validate final rootfs contents`：成功
- sysupgrade、recovery、kmod artifact：全部上传成功
- Release：按策略跳过，没有发布固件

## 6. Artifact 独立复核

artifact 下载到临时目录后重新校验，不依赖 Actions 步骤结论。

| 产物 | 实际内容/大小 | 独立结果 |
|---|---:|---|
| sysupgrade | `52,194,082` B | SHA256 全部通过；唯一镜像 |
| factory UBI | `54,263,808` B | SHA256 通过 |
| initramfs ITB | `51,574,684` B | SHA256 通过 |
| kmod archive | `3,546,063` B | 143 个 ipk 与索引全部通过 |
| NSS 相关 kmod | 20 个 | drv/dp/ssdk/ecm/clients 等均存在 |
| device manifest | 12,096 B | sysupgrade/recovery 相同；与 rootfs opkg 完全一致 |

STOCK factory UBI 门禁上限为 `0x06340000`（99.25 MiB），当前 51.75 MiB，保留约 47.50 MiB 余量；这只证明适配仓库定义的 merged-layout STOCK profile，不代表可写入原厂双小 rootfs 槽。

最终 rootfs 关键版本：

| 组件 | 版本 |
|---|---|
| Linux | `6.18.38` |
| ath11k/backports | `6.18.26-r1` |
| qca-nss-drv | `...6aa14c7-r18` |
| qca-nss-dp | `...d8f802f0-r1` |
| qca-nss-ecm | `...8c7355b-r8` |
| qca-ssdk | `...d9a19649-r1` |
| OpenClash | `0.47.116` |
| ZeroTier | `1.16.2-r1` |
| zram-swap | `32` |

OpenClash 供应链证据：实际插件提交 `1c8e8cb8...`，Meta core 提交 `0657e71e...`，core SHA256 `8a5cd36a...d3765`；独立提取后确认是静态 AArch64 ELF。Metacubexd 与 Zashboard 的提交和归档哈希均写入 BUILD-LOCK。

rootfs 还通过以下边界：

- NSS/SSDK/DP/ECM/ath11k/ZRAM 模块、init 和启动链接存在；
- `ath11k frame_mode=2`、`nss_offload=1`，没有无效 `rx_hash`；
- ECM helper、br-lan hotplug、SQM NSS、ZeroTier fw4、OpenClash UI/core、审计脚本存在；
- sing-box、xray-core、WireGuard、HAProxy、microsocks 和未选 DNS 转发组件不在 manifest/rootfs；
- 手工 `ax6-irq-affinity` 未自动启用，官方 `set-irq-affinity` 与 `smp_affinity` 启动链保留。

## 7. 配置和运行逻辑结论

- NSS 与 firewall 软件 flow offload 的互斥门禁保持有效，未发现隐藏启用的 `kmod-nf-flow`/shortcut-fe 路径。
- ECM 继续使用仓库已验证的 `disable_offloads=1` 运行策略；本轮没有用上游 cleanup 覆盖它。
- 2.4 GHz 保持 US、HE40 与 coexistence，可与 HE20 客户端协商；没有为修复本轮源码问题强制降到 HE20。
- ECM VLAN 修复的是 routed VLAN-over-bridge 的线侧 tag 判断。qosmio 对 NSS WiFi offload + DSA bridge VLAN filtering 的限制仍然成立，不能把本次构建通过解释为该组合已全面支持。
- ZeroTier fw4、OpenClash DNS 只读审计、ZRAM 和 IRQ 所有权保持既有已验证设计，本轮没有修改订阅文件、覆写或实机配置。

## 8. 仍未消除的边界

1. 本轮没有实机运行验证。编译不能证明冷/热重启、ath11k firmware recovery、长时 ECM、本机终结流量、VLAN、ZeroTier、OpenClash DNS failover 和 2.4 GHz IoT 在真实环境完全无故障。
2. `act_nssmirred` create/replace/IDR/NSS/IFB 的全事务重构仍属于上游级工作；当前已修复已知 release 链表损坏，并保留 create-only 使用边界。
3. 仅完成 AX6 STOCK 统一构建；EXPAND、其他官方配置和非 AX6 target 没有在本次 run 中逐一生成固件。
4. OpenClash 按用户要求继续跟踪 master，不固定插件版本；可复现性由每次 BUILD-LOCK 记录实际插件/core/dashboard 提交和哈希保证。
5. 候选尚未合并主分支、未发布。任何实机测试必须再次取得用户确认，并先核对 `/proc/mtd`、SMEM/bootloader 布局和镜像用途。

## 9. 最终判断

在“源码一致性、补丁适配、构建配置、云端编译、rootfs 和 artifact”范围内，本轮发现的确定遗漏已经修复并通过验证，没有剩余已知编译错误、清单遗漏或产物结构错误。

不能据此承诺实机运行态不存在未知问题。下一阶段只能是经用户确认后的受控实机验证，不能自动刷写或直接合并发布。
