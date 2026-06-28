# AX6-OpenWRT

[![Lint](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/lint.yml/badge.svg)](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/lint.yml)

Redmi AX6 一键编译脚本 — 完整 NSS 加速 + WiFi 6 满血 + 分区布局门禁。

## 主仓输出:`Build OpenWRT for AX6-NSS`

基于 [OrdinaryJoys/immortalwrt-nss](https://github.com/OrdinaryJoys/immortalwrt-nss)
(VIKINGYFY 上游 + 本仓 NSS 修复)编译,带满血 NSS 加速,500 Mbps NAT 流量 CPU 占用 < 5%。

### 支持的构建目标

| 变体 | 适用布局 | rootfs | 变砖风险 |
|---|---|---|---|
| **STOCK** | 128MB NAND + custom U-Boot/SMEM 合并布局 | 单 `rootfs=0x06640000` | 中,必须核对 `/proc/mtd` |
| **EXPAND** | 1GB RAM + 256MB NAND(已硬件改装 NAND)| ~192 MB | 高(刷错变砖) |

Xiaomi 原厂双 `0x023c0000` 槽与合并布局共享 `redmi,ax6-stock`
兼容标识，但本仓完整 STOCK 镜像面向合并布局。布局不明确时不要刷写。
详见 [`AX6-IPQ/HARDWARE.md`](AX6-IPQ/HARDWARE.md)。

当前有效状态、验证证据和遗留问题见
[`AX6-IPQ/CURRENT-STATUS-2026-06-19.md`](AX6-IPQ/CURRENT-STATUS-2026-06-19.md)。
追加式历史审计记录保留在
[`AX6-IPQ/AUDIT-REPAIR-REPORT-2026-06-19.md`](AX6-IPQ/AUDIT-REPAIR-REPORT-2026-06-19.md)。

> **供应链已恢复（2026-06-18）**：
> qca-nss 已迁移到源码树内置 (`package/qca-nss/`, 10 包 73 文件)。
> 锁文件指向 `main` 分支，包含 ath11k NSS Kconfig 修复、ECM 风格统一和 stock 升级容量回归测试。
> 外部 feed `VIKINGYFY/nss-packages-618` 已废弃。
> VIKINGYFY 后续 `38e28da...`、`5f520e5...` 涉及 qca-nss/mac80211
> 重构，尚未合并。

### 触发编译

GitHub UI → Actions → `Build OpenWRT for AX6-NSS` → Run workflow → 选 variant。

## 特性

- **WiFi 6**:5G HE80;2.4G HE40 + 标准 20/40MHz 共存自动回退
- **NSS 完整卸载**:`frame_mode=2`,数据通路绕过 SoftIRQ,实测 NAT 速率单核占用 < 1%
- **23 个 NSS kmod**:bridge / vlan / pppoe / pptp / l2tp / gre / vxlan / shaper / crypto / ecm 全开 (mesh 需 FW 11.4，当前 12.5 不支持)
- **IRQ/RPS 策略**:由上游 qualcommax 脚本统一管理,避免多个脚本互相覆盖
- **WPA3 + IPv6 + 漫游支持**(11k/v + bss_transition)
- **分层检查**:`nss-check` 检查硬件/NSS 确定性故障,`ax6-config-audit` 只读审计场景配置
- **双重容量门禁**:CI 按合并分区和坏块预留校验；sysupgrade 按实机 MTD 几何再次拒绝超限镜像
- **完整软件集**:合并布局保留 OpenClash、sing-box、xray-core 与 DDNS 组件

## 默认登录

| 项 | 值 |
|---|---|
| IP | 192.168.5.1 |
| 用户 | root |
| 密码 | **首次登录通过 LuCI Web 或 SSH `passwd` 设置** |

## 目录结构

```
.
├── .github/
│   ├── depends-ubuntu-2204.txt    # 固化构建依赖(替代 curl|apt)
│   └── workflows/
│       ├── build-AX6-NSS.yml      # 主固件 (合并 SMEM / 256M 扩容)
│       ├── build-AX6-IPQ.yml      # 备用:基于 LiBwrt(原 LiBwrt-op 已改名)
│       ├── build-IMM.yml          # 无 NSS,基于 official ImmortalWrt 23.05
│       ├── build-LEDE.yml         # 基于 coolsnowwolf/lede
│       └── lint.yml               # 增量检查 (shellcheck/actionlint/yamllint + NSS 冲突)
├── AX6-IPQ/                        # 主目录
│   ├── .config-stock               # 1G+128M custom SMEM 合并布局
│   ├── .config-expand              # 1G+256M 改装 SKU
│   ├── nss-extra.config            # NSS / WiFi 增量(workflow 自动追加)
│   ├── diy.sh                      # 构建时 DIY(变体感知 DT patch)
│   ├── HARDWARE.md                 # 硬件参考 + 救机文档
│   └── files/                      # rootfs 注入文件
│       ├── etc/banner
│       ├── usr/sbin/ax6-irq-affinity
│       ├── etc/modprobe.d/ath11k.conf
│       ├── etc/profile.d/00-ax6-status.sh
│       ├── etc/sysctl.d/99-ax6-tune.conf
│       ├── etc/uci-defaults/9?-ax6-*
│       └── sbin/{nss-check,ax6-config-audit}
├── AX6-IMM/                        # ImmortalWrt 23.05 备用
├── AX6-lEDE/                       # LEDE 备用
├── LuCI应用说明.md                  # 插件说明
└── 备用源.md                        # 软件源
```

## 安全 & 合规

- 所有 GitHub Actions 已 pin 到 SHA(防 supply chain)
- 依赖清单固化在仓内(无 `curl | apt install`)
- WiFi 默认 country=US (FCC 最大功率; 覆盖: `echo CN > /etc/config/ax6_wifi_country && reboot`)
- Release 只发布正常升级用 `sysupgrade.bin`,并自带 SHA256SUMS-AX6.txt 校验
- `factory.ubi`/initramfs ITB 位于独立 RECOVERY artifact,不能用于 LuCI 正常升级

## 实机验证

刷机后 SSH 进设备运行:
```bash
nss-check -v
```

`nss-check` 输出硬件和 NSS 的 PASS/FAIL。继续运行:

```bash
ax6-config-audit -v
```

该工具只读检查 WiFi、NSS SQM、ZeroTier、UPnP 和 OpenClash。访客隔离、ZeroTier
转发/NAT、双 NAT 下 UPnP 等场景配置只会给出说明或告警，不会被启动脚本自动修改。
OpenClash fake-ip 场景会额外审计官方 UCI DNS 生成路径:建议使用
`store_fakeip=1`、`enable_custom_dns=1`、显式 `nameserver`/`default`
DNS 组和 `disable_ipv6=1` 的 IPv4 default DNS。不要把订阅 YAML 或自定义覆写脚本
当作默认修复位置,订阅更新和插件生成流程可能覆盖或叠加这些文件。

## 配置所有权

- Boot Guard 只纠正会直接冲突 NSS 数据路径的 packet steering/flow offload。
- WiFi 首次启动脚本只设置 radio 级默认值，不覆盖 SSID 隔离、PMF、漫游或 IoT 策略。
- VLAN、ZeroTier、UPnP 和 OpenClash 由管理员按网络拓扑配置，仓库工具只读审计。
- 主构建的源码、全部 feeds、Argon 和 OpenClash 都固定到完整提交 SHA。
- AX6-IPQ/IMM/LEDE 备用构建跟随移动分支或 feeds,只上传 7 天
  `UNVALIDATED` Actions artifact,不创建 Release。它们没有主构建级别的锁定、
  容量和最终产物验证,不得当作已验证固件发布。

## 关联仓库矩阵(实测可达性 + 引用关系)

| 仓库 | 类型 | 我们引用 | 实测 |
|---|---|---|---|
| [OrdinaryJoys/immortalwrt-nss](https://github.com/OrdinaryJoys/immortalwrt-nss) | **AX6-NSS workflow 直接构建源** | `main` 上的完整 SHA | ✓ |
| [LiBwrt/openwrt-6.x](https://github.com/LiBwrt/openwrt-6.x) | AX6-IPQ 备用源(原 `LiBwrt-op` 已改名) | branch `main-nss` | ✓ |
| [immortalwrt/immortalwrt](https://github.com/immortalwrt/immortalwrt) | AX6-IMM 备用源(无 NSS) | branch `openwrt-23.05` | ✓ |
| [coolsnowwolf/lede](https://github.com/coolsnowwolf/lede) | AX6-LEDE 备用源 | branch `master` | ✓ |
| [qosmio/nss-packages](https://github.com/qosmio/nss-packages) | OpenWrt feed 参考源(间接,未直接使用) | branch `main-nss` | ✓ |
| ~~`VIKINGYFY/nss-packages-618`~~ | 已废弃 — qca-nss 已迁移到源码树 `package/qca-nss/` | — | ✅ 已修复（2026-06-18） |
| `VIKINGYFY/nss-packages` | 历史 OpenWrt feed 参考源 | `HEAD` | **公开仓库列表中不存在（2026-06-18）** |
| [openwrt/qca-nss-dp](https://github.com/openwrt/qca-nss-dp) | NSS 数据路径间接上游,sync-check 监控 | branch `openwrt` | ✓ |
| [qosmio/sqm-scripts-nss](https://github.com/qosmio/sqm-scripts-nss) | NSS SQM feed | 完整 SHA 锁定 | ✓ |
| [OrdinaryJoys/luci](https://github.com/OrdinaryJoys/luci) | OpenWrt feed (LuCI Web UI) | 完整 SHA 锁定 | ✓ |
| [VIKINGYFY/immortalwrt](https://github.com/VIKINGYFY/immortalwrt) | nss-fork 的上游(间接) | 通过 nss-fork | ✓ |
| [Openwrt-Passwall/openwrt-passwall](https://github.com/Openwrt-Passwall/openwrt-passwall) | LEDE 科学上网包(原 `xiaorouji` 已迁移) | tip | ✓ |
| [Openwrt-Passwall/openwrt-passwall-packages](https://github.com/Openwrt-Passwall/openwrt-passwall-packages) | LEDE 科学上网依赖 | tip | ✓ |
| [jerrykuku/luci-theme-argon](https://github.com/jerrykuku/luci-theme-argon) | LuCI 主题 | 完整 SHA 锁定 | ✓ |
| [jerrykuku/luci-app-argon-config](https://github.com/jerrykuku/luci-app-argon-config) | Argon 主题配置 | 完整 SHA 锁定 | ✓ |
| [vernesong/OpenClash](https://github.com/vernesong/OpenClash) | OpenClash 独立锁定覆盖源 | `0.47.097` + 完整 SHA | ✓ |

### 已 release 版本与上游 commit 的对应

| Release tag | 构建源 commit (nss-fork) | qosmio nss-packages | 备注 |
|---|---|---|---|
| `AX6_NSS_STOCK_20260426145026` | `3138df48` | `NSS-12.5-K6.x` HEAD | 历史首次 success build |
| `AX6_NSS_*` 之前 (2026-04-19~25) | (legacy,直接拉 VIKINGYFY) | 同上 | 已被新 release 覆盖 |

> sync-check workflow 每周一 09:00 (CST) 比较主构建的 11 个锁定输入与当前远端，
> 并额外探测 6 个备用/间接上游。锁定分支发生漂移或仓库不可达时 workflow 会失败并在
> Actions Summary 标出原因；更新锁定值前仍需审查差异并完成构建验证。

### 同行项目对比

| 项目 | 优势 | 不足 |
|---|---|---|
| [LiBwrt/openwrt-6.x](https://github.com/LiBwrt/openwrt-6.x) | NSS 完整 | 部分版本启动失败 |
| [JiaY-shi/openwrt](https://github.com/JiaY-shi/openwrt) | 带 NSS | 仅官方分区 |
| [qosmio/openwrt-ipq](https://github.com/qosmio/openwrt-ipq) | NSS 数据源头(`main-nss` 分支) | 仅官方分区 |
| **本仓 + immortalwrt-nss** | NSS + 双变体 + 防变砖 + 自动检查 + 实测验证 | — |

## License & 致谢

GPL-2.0(继承自 OpenWrt)。

感谢 [@VIKINGYFY](https://github.com/VIKINGYFY) [@qosmio](https://github.com/qosmio) [@LiBwrt](https://github.com/LiBwrt) 的工作。
