# AX6-OpenWRT

[![Lint](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/lint.yml/badge.svg)](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/lint.yml)

Redmi AX6 一键编译脚本 — 完整 NSS 加速 + WiFi 6 满血 + 双变体支持。

## 主仓输出:`Build OpenWRT for AX6-NSS`

基于 [VIKINGYFY/immortalwrt](https://github.com/VIKINGYFY/immortalwrt) 编译,带满血 NSS 加速,
500 Mbps NAT 流量 CPU 占用 < 5%。

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
│       ├── build-AX6-IPQ.yml      # 备用:基于 LiBwrt
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

## 已知项目对比

| 项目 | 优势 | 不足 |
|---|---|---|
| [LiBwrt-op/openwrt-6.x](https://github.com/LiBwrt-op/openwrt-6.x) | NSS 完整 | 部分版本启动失败 |
| [VIKINGYFY/immortalwrt](https://github.com/VIKINGYFY/immortalwrt) | NSS 满血,本仓底座 | — |
| [JiaY-shi/openwrt](https://github.com/JiaY-shi/openwrt) | 带 NSS | 仅官方分区 |
| [qosmio/openwrt-ipq](https://github.com/qosmio/openwrt-ipq) | NSS 数据源头 | 仅官方分区 |
| 本仓 | NSS + 双变体 + 防变砖 + 自动检查 | — |

## License & 致谢

GPL-2.0(继承自 OpenWrt)。

感谢 [@VIKINGYFY](https://github.com/VIKINGYFY) [@qosmio](https://github.com/qosmio) [@LiBwrt](https://github.com/LiBwrt) 的工作。
