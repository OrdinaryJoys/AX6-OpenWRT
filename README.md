# AX6-OpenWRT

[![Lint](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/lint.yml/badge.svg)](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/lint.yml)

Redmi AX6 一键编译脚本 — 完整 NSS 加速 + WiFi 6 满血 + 双变体支持。

## 主仓输出:`Build OpenWRT for AX6-NSS`

基于 [OrdinaryJoys/immortalwrt-nss](https://github.com/OrdinaryJoys/immortalwrt-nss)
(VIKINGYFY 上游 + 本仓 NSS 修复)编译,带满血 NSS 加速,500 Mbps NAT 流量 CPU 占用 < 5%。

### 两个硬件变体

| 变体 | 适用 | rootfs | 变砖风险 |
|---|---|---|---|
| **STOCK**(默认)| 1GB RAM + 128MB NAND(Xiaomi 出厂) | ~102 MB | **0%** |
| **EXPAND** | 1GB RAM + 256MB NAND(已硬件改装 NAND)| ~210 MB | 高(刷错变砖) |

不知道选哪个 → **选 STOCK**。详见 [`AX6-IPQ/HARDWARE.md`](AX6-IPQ/HARDWARE.md)。

### 触发编译

GitHub UI → Actions → `Build OpenWRT for AX6-NSS` → Run workflow → 选 variant。

## 特性

- **WiFi 6 满血**:HE80 + 4×4 MU-MIMO + 1024-QAM + LDPC + STBC + Beamforming + OBSS PD
- **NSS 完整卸载**:`frame_mode=2`,数据通路绕过 SoftIRQ,实测 NAT 速率单核占用 < 1%
- **23 个 NSS kmod**:bridge / vlan / pppoe / pptp / l2tp / gre / vxlan / mesh / shaper 全开
- **IRQ 智能绑核**:eth/wifi/nss IRQ 分散到 4 个核
- **WPA3 + IPv6 + 漫游**(11k/v + bss_transition)
- **`nss-check`**:自带 13 项健康自检,cron 每 30 分钟自动跑

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
│       ├── build-AX6-NSS.yml      # 主固件 (双变体输入)
│       ├── build-AX6-IPQ.yml      # 备用:基于 LiBwrt(原 LiBwrt-op 已改名)
│       ├── build-IMM.yml          # 无 NSS,基于 official ImmortalWrt 23.05
│       ├── build-LEDE.yml         # 基于 coolsnowwolf/lede
│       └── lint.yml               # 增量检查 (shellcheck/actionlint/yamllint + NSS 冲突)
├── AX6-IPQ/                        # 主目录
│   ├── .config-stock               # 1G+128M 标准 SKU
│   ├── .config-expand              # 1G+256M 改装 SKU
│   ├── nss-extra.config            # NSS / WiFi 增量(workflow 自动追加)
│   ├── diy.sh                      # 构建时 DIY(变体感知 DT patch)
│   ├── HARDWARE.md                 # 硬件参考 + 救机文档
│   └── files/                      # rootfs 注入文件
│       ├── etc/banner
│       ├── etc/init.d/ax6-irq-affinity
│       ├── etc/modprobe.d/ath11k.conf
│       ├── etc/profile.d/00-ax6-status.sh
│       ├── etc/sysctl.d/99-ax6-tune.conf
│       ├── etc/uci-defaults/9?-ax6-*
│       └── sbin/nss-check
├── AX6-IMM/                        # ImmortalWrt 23.05 备用
├── AX6-lEDE/                       # LEDE 备用
├── LuCI应用说明.md                  # 插件说明
└── 备用源.md                        # 软件源
```

## 安全 & 合规

- 所有 GitHub Actions 已 pin 到 SHA(防 supply chain)
- 依赖清单固化在仓内(无 `curl | apt install`)
- WiFi 默认 country=CN(覆盖:`echo US > /etc/config/ax6_wifi_country`)
- Release artifact 自带 SHA256SUMS-AX6.txt 校验

## 实机验证

刷机后 SSH 进设备运行:
```bash
nss-check -v
```

13 项检查会输出 PASS/FAIL,失败项可贴到 issue 我帮你看。

## 关联仓库矩阵(实测可达性 + 引用关系)

| 仓库 | 类型 | 我们引用 | 实测 |
|---|---|---|---|
| [OrdinaryJoys/immortalwrt-nss](https://github.com/OrdinaryJoys/immortalwrt-nss) | **AX6-NSS workflow 直接构建源** | branch `main` | ✓ |
| [LiBwrt/openwrt-6.x](https://github.com/LiBwrt/openwrt-6.x) | AX6-IPQ 备用源(原 `LiBwrt-op` 已改名) | branch `main-nss` | ✓ |
| [immortalwrt/immortalwrt](https://github.com/immortalwrt/immortalwrt) | AX6-IMM 备用源(无 NSS) | branch `openwrt-23.05` | ✓ |
| [coolsnowwolf/lede](https://github.com/coolsnowwolf/lede) | AX6-LEDE 备用源 | branch `master` | ✓ |
| [qosmio/nss-packages](https://github.com/qosmio/nss-packages) | OpenWrt feed 参考源(间接,未直接使用) | branch `main-nss` | ✓ |
| [VIKINGYFY/nss-packages](https://github.com/VIKINGYFY/nss-packages) | OpenWrt feed (NSS 用户态包,immortalwrt-nss feeds 使用) | pin `8a93f51` | ✓ |
| [VIKINGYFY/nss-packages-618](https://github.com/VIKINGYFY/nss-packages-618) | OpenWrt feed (NSS 包 6.18 兼容版,NSS workflow 使用) | pin `0f3a7fb` | ✓ |
| [OrdinaryJoys/luci](https://github.com/OrdinaryJoys/luci) | OpenWrt feed (LuCI Web UI) | branch `master` | ✓ |
| [VIKINGYFY/immortalwrt](https://github.com/VIKINGYFY/immortalwrt) | nss-fork 的上游(间接) | 通过 nss-fork | ✓ |
| [Openwrt-Passwall/openwrt-passwall](https://github.com/Openwrt-Passwall/openwrt-passwall) | LEDE 科学上网包(原 `xiaorouji` 已迁移) | tip | ✓ |
| [Openwrt-Passwall/openwrt-passwall-packages](https://github.com/Openwrt-Passwall/openwrt-passwall-packages) | LEDE 科学上网依赖 | tip | ✓ |
| [jerrykuku/luci-theme-argon](https://github.com/jerrykuku/luci-theme-argon) | LuCI 主题 | tip / 18.06 | ✓ |
| [jerrykuku/luci-app-argon-config](https://github.com/jerrykuku/luci-app-argon-config) | Argon 主题配置 | tip / 18.06 | ✓ |

### 已 release 版本与上游 commit 的对应

| Release tag | 构建源 commit (nss-fork) | qosmio nss-packages | 备注 |
|---|---|---|---|
| `AX6_NSS_STOCK_20260426145026` | `3138df48` | `NSS-12.5-K6.x` HEAD | **当前推荐**,首次 success build |
| `AX6_NSS_*` 之前 (2026-04-19~25) | (legacy,直接拉 VIKINGYFY) | 同上 | 已被新 release 覆盖 |

> sync-check workflow 每周一 09:00 (CST) 自动探测 5 个上游(VIKINGYFY/immortalwrt、
> VIKINGYFY/nss-packages、VIKINGYFY/nss-packages-618、openwrt/qca-nss-dp、OrdinaryJoys/luci)
> HEAD,通过 issue 跟踪。如需手动同步:Actions → `Sync upstream check` → Run workflow。

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
