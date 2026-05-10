# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
版本号采用 release tag(`AX6_NSS_<VARIANT>_<TIMESTAMP>`)。

## [AX6_NSS_STOCK_20260426145026] — 2026-04-26 (✅ 首个 e2e success)

### 重大变更

- **构建源切换**:`VIKINGYFY/immortalwrt` → `OrdinaryJoys/immortalwrt-nss`
  (本仓 fork,在 viking 之上加了 NSS 启动脚本修复)
- **mac80211 patches 集替换**:从 NSS-deep hack 集(68 个,与 backports-6.18.7
  不兼容)换为 `qosmio/openwrt-ipq main-nss` 分支的 20 个 ath11k patches。NSS
  WiFi 加速通过 `nss_packages` feed 实现,不再依赖 mac80211 patch。
  (commit `3138df48` in nss-fork)

### 新增

- 双变体构建:`stock`(1G+128M)/ `expand`(1G+256M HW-modded),通过
  `workflow_dispatch.inputs.variant` 选择,带 Pre-flight Python 校验
- 完整 `AX6-IPQ/HARDWARE.md` 含实测分区表 + 救机流程
- `AX6-IPQ/files/sbin/nss-check`:13 项健康自检 + cron 监控
- `.github/workflows/lint.yml`:shellcheck + actionlint + yamllint + Kconfig 冲突
- `.github/workflows/sync-check.yml`:每周一探测三个上游 HEAD
- `.github/depends-ubuntu-2204.txt`:固化构建依赖,杜绝 `curl|apt`
- WiFi 极致调优:HE80 + 4×4 MU-MIMO + LDPC + STBC + Beamforming + OBSS PD
  + IRQ 智能绑核

### 修复(本会话累计 25+ 个 commits)

| Commit | 修复 |
|---|---|
| `feb26c7` | pin actions 到真实可达 SHA(之前 3 个被编造)|
| `6c7a3e9` | Pre-flight Python 跨 step `$GITHUB_ENV` 不可见 |
| `81f36b6` | wifi-tune 不强制改 `network=lan` / `encryption=sae-mixed`(破坏多 SSID)|
| `feb26c7` | actions 中 3 个不可达 SHA 修正 |
| `dbea1d8` | 撤销错误的 466MB rootfs(超 NAND 物理大小,会变砖) |
| `6c895b7` | LiBwrt-op→LiBwrt(repo 改名);jlumbroso pin v1.3.1 SHA;feed 显式 branch |

### 安全

- 所有 GitHub Actions 已 pin 到 40-char SHA(防 supply chain)
- Release body 不再含默认密码 `password`
- WiFi country 默认 `US` (FCC 最大功率; 可通过 `/etc/config/ax6_wifi_country` 覆盖为 CN)
- Release artifact 自带 SHA256SUMS-AX6.txt + nss-check 工具

### 关联仓库

| 仓库 | 分支 / commit |
|---|---|
| OrdinaryJoys/immortalwrt-nss | `main` HEAD |
| VIKINGYFY/nss-packages | `NSS-12.5-K6.x` pin `8a93f51` (immortalwrt-nss feeds) |
| VIKINGYFY/nss-packages-618 | `NSS-12.5-K6.x` pin `1306d122` (NSS workflow override) |
| OrdinaryJoys/luci | `master` (NSS workflow luci feed override) |

### 实测产物

- `immortalwrt-qualcommax-ipq807x-redmi_ax6-stock-squashfs-sysupgrade.bin` 50.2 MB
- `immortalwrt-qualcommax-ipq807x-redmi_ax6-stock-squashfs-factory.ubi` 52.1 MB
- `immortalwrt-qualcommax-ipq807x-redmi_ax6-stock-initramfs-uImage.itb` 51.8 MB

---

## [AX6_NSS_*] — 2026-04-19 ~ 2026-04-25 (legacy)

直接基于 VIKINGYFY/immortalwrt 构建,无本仓 NSS 启动脚本修复。
镜像产物只有 `factory.ubi` 和 `sysupgrade.bin`(2 个 asset)。
**已被 AX6_NSS_STOCK_20260426145026 取代**,建议刷新版。

---

[AX6_NSS_STOCK_20260426145026]: https://github.com/OrdinaryJoys/AX6-OpenWRT/releases/tag/AX6_NSS_STOCK_20260426145026
[AX6_NSS_*]: https://github.com/OrdinaryJoys/AX6-OpenWRT/releases?q=AX6_NSS_2026
