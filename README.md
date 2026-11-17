# Redmi AX6 / OpenWrt NSS 构建仓

本仓定义 Redmi AX6（IPQ807x）的构建、软件包覆盖、来源校验和固件验收。实际驱动和用户态源码位于 [OrdinaryJoys/immortalwrt-nss](https://github.com/OrdinaryJoys/immortalwrt-nss)，由本分支的 [构建锁](.github/ax6-nss-lock.env) 指向确切提交。Actions 脚本仓的提交不是固件源码提交。

## 本分支：上游修复隔离候选

候选从已离线验收的 `828c21b4` / DRV29 派生。对照是 [stock run 44006853715](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/44006853715)，其 Linux 6.18.38、NSS、ECM、DP、SSDK、ath11k 和 rpcd OFF 基线保持不变。旧 run 的成功不代表本候选已构建、已验包或已运行。

| 独立变更 | 来源和适配 | 候选包修订 |
| --- | --- | --- |
| dnsmasq | OpenWrt [慢重载](https://github.com/openwrt/openwrt/commit/514fad5218edaa4a36af7c15c0f46cdff0139309)及[安全修补](https://github.com/openwrt/openwrt/commit/6db25ee835eb55af521125c84b12ffd0495f671b)。保留 2.93 源码、现有 init 和 LAN-only DNS 策略。 | `dnsmasq-full 2.93-r6` |
| odhcpd | 保留 `c6792bac`，组合修复 DHCPv6 IA 越界、AUTH 偏移、租约寿命、空 relay、IA 类型、recvmsg 错误和客户端主机名转义，不能仅移植初始 [越界修补](https://github.com/openwrt/odhcpd/commit/0320032ae313452f3c8cb8725c621dd06c36dc03)。 | `odhcpd-ipv6only r2` |
| hostapd | [5b240697](https://github.com/openwrt/openwrt/commit/5b240697987858c59d9798c3d46f2bc3db1de994) 的 BSS 空指针检查；保留本地 reload、无线配置和驱动适配。 | `wpad-openssl` / `hostapd-common r4` |
| netifd | 保留 `6088f7b3`，移植 [VID 拒绝](https://github.com/openwrt/netifd/commit/625425e086997ccb141ccfdc90527fc0847004d9)、失败回滚、引用寿命和 external bridge 修复；额外拒绝显式空 VID，保留合法 0 与未配置时的默认值。 | `netifd r2` |
| libubox | [20bea2b](https://github.com/openwrt/libubox/commit/20bea2ba777dec6e62e15415ded5ffd8be1a5f18) 修 JSON 越界；补齐无名对象成员跳过，不留下逗号或改变数组，ABI 名称不变。 | `libubox20260708 r2` |

[上游移植审查](docs/AX6_UPSTREAM_PORT_2026-11-17.md)说明审查覆盖、分级、验证边界和后续批次。本批不包含 054–073，不改变 VLAN 拓扑、NSS/FW、IRQ/RPS/PBUF、OpenClash 订阅/覆写/Geo、ZeroTier、UPnP、配置还原或默认启动策略。

## 来源和适配关系

- **实际固件线：** OrdinaryJoys 源码和 [构建锁](.github/ax6-nss-lock.env)；厂商传统 DP/EDMA v1、ECM、SSDK/HPPE、NSS DRV/clients/MCS/crypto 与 ath11k 适配保存在源码树。CodeLinaro 的分支相似命名不保证提交是同线后继。
- **上游参考：** [VIKINGYFY/immortalwrt](https://github.com/VIKINGYFY/immortalwrt) 旧 `main` 与现默认 `owrt` 数据面不同；`owrt` 的原生 PPE/EDMA + 新 NSS Wi-Fi 不是本仓传统 NSS 的替换包。[qosmio/openwrt-ipq](https://github.com/qosmio/openwrt-ipq) 用于比对 NSS 适配合同。[ImmortalWrt](https://github.com/immortalwrt/immortalwrt) 和 [OpenWrt](https://github.com/openwrt/openwrt) 用于独立回移。LiBwrt、JiaY、Julius、pbs05、perceival 是评审来源，不是构建 feeds。
- **组件输入：** LuCI、Packages、Routing、Telephony、Video、Argon、NSS SQM 直接按锁；OpenClash 跟随官方 `master`，构建记录实际插件提交、版本与 core 摘要，不把 `package/dev` 当作稳定源码更新。当前不换 feeds 和 Argon。
- **备用工作流：** AX6-IPQ、IMM 和 LEDE 与锁定主构建分开，上传 `UNVALIDATED` artifact。LiBwrt 旧 URL 指向 [LibWrt](https://github.com/LiBwrt/LibWrt)，巡检当前用 `25.12-nss`；不要把巡检状态当作该备用工作流已验证。

## 布局和安全边界

[硬件与分区说明](AX6-IPQ/HARDWARE.md)优先于镜像名称。

| 配置 | 布局 | 本分支是否验证 |
| --- | --- | --- |
| STOCK | 128 MiB NAND，自定义 U-Boot/SMEM 合并布局，单 rootfs `0x06640000` | 仅用于离线候选；不适用于同兼容标识的原厂双槽 |
| EXPAND | 256 MiB 改装 NAND，单独 DT/布局和配置 | 此候选工作流拒绝，不属于本批 |

仅凭设备名或 `redmi,ax6-stock` 兼容标识不能判断布局。sysupgrade、initramfs 和 factory UBI 用途不同；不要把 recovery 文件用于正常 LuCI 升级。候选无 Release、不提供刷机批准，未访问设备、未运行 `sysupgrade -T`、未测启动、坏块、性能或回滚。既有设备配置和实际硬件状态不由静态文档推断。

## 构建与核验

1. 固定源码提交，生成完整 [差异哈希清单](.github/ax6-source-patchset.sha256) 与 [缺席清单](.github/ax6-source-patchset.absent)。校验包修订和目标选择，不可通过关闭门禁解决。
2. 先对候选分支触发 [Lint](.github/workflows/lint.yml)，不选仅 PHY 测试。通过后再触发 [Build OpenWRT for AX6-NSS](.github/workflows/build-AX6-NSS.yml)：非 main，`variant=stock`，`ssh=false`。此工作流只读权限，候选不执行 Release。
3. 构建中验证目标工具链、rpcd ON/clean/OFF、NSS/MDIO/驱动回归、最终 DTB/rootfs 和构建输入。成功以后仍要按同一 run 的 ID 和 ZIP 摘要独立验包。检查 `BUILD-LOCK-AX6.txt`、设备 manifest 对整个 rootfs 已安装集合、kmod/IPK/ELF 与 vermagic、最终 rpcd OFF、OpenClash ELF 与 SHA256、FIT/DTB/UBI 以及完整校验清单。失败先归因，不盲目重跑。
4. 未来的实机验证需要另行确认。只读工具 `nss-check -v`、`ax6-config-audit -v` 只反映检查项目；不能由一次输出推导无丢包或满速。性能应以明确拓扑、同条件同版工具和多轮基线复核。

## 目录和历史

- `.github/`：构建锁、变更清单、校验脚本、Actions。
- `AX6-IPQ/`：stock/expand 配置、`diy.sh`、镜像覆盖、硬件文档。默认管理入口见现有配置，旧环境不保证与新构建一致；首次登录应设置本机密钥及密码。
- `tests/`：构建和集成回归；`docs/`：批次、故障证据与边界。
- [历史变更](CHANGELOG.md)、[LuCI 应用说明](LuCI应用说明.md)、[此前 SFP/stock 批次](docs/AX6_REPAIR_STATUS_2026-11-17.md)。

继承 OpenWrt 的 GPL-2.0 和各组件原许可。感谢 Qualcomm/CodeLinaro、OpenWrt、ImmortalWrt、VIKINGYFY、qosmio 与各上游维护者；每份补丁保留来源和作者信息。
