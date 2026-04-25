# AX6 硬件参考(实测)

## 设备信息

```
model:       Redmi AX6 (stock layout)
compatible:  redmi,ax6-stock, qcom,ipq8074
SoC:         IPQ8074 (4 × ARMv8 Cortex-A53 @1.4GHz)
RAM:         916 MB (≈ 1 GB DDR3)
NAND:        128 MB total
WiFi:        ath11k (Wi-Fi 6, 4×4 MU-MIMO)
NSS:         qca-nss-drv + qca-nss-dp + qca-nss-ecm
```

## NAND 分区(stock SMEM)

| MTD | 名称 | 大小 | 备注 |
|---|---|---|---|
| mtd0 | 0:sbl1 | 1 MB | 一级 bootloader |
| mtd1 | 0:mibib | 1 MB | mtd 索引 |
| mtd2 | 0:qsee | 3 MB | TrustZone OS |
| mtd3 | 0:devcfg | 0.5 MB | TZ 设备配置 |
| mtd4 | 0:rpm | 0.5 MB | RPM firmware |
| mtd5 | 0:cdt | 0.5 MB | Config data |
| mtd6 | 0:appsblenv | 0.5 MB | u-boot env |
| mtd7 | 0:appsbl | 1 MB | u-boot |
| mtd8 | 0:art | 0.5 MB | WiFi calibration (board-2.bin)|
| mtd9 | bdata | 0.5 MB | Xiaomi 设备数据 |
| mtd10 | crash | 0.5 MB | crash dump |
| mtd11 | crash_syslog | 0.5 MB | crash syslog |
| **mtd12** | **rootfs** | **102 MiB** | **本固件实际可用空间** |
| mtd13 | rsvd0 | 0.5 MB | Reserved |

UBI 在 mtd12 上,典型布局:
- ubi0_0: kernel(~5 MB)
- ubi0_1: rootfs squashfs(~45 MB)
- ubi0_2: rootfs_data(UBIFS overlay,40 MB)

## 关于 1G + 512 SKU 说明

用户最初描述 "1G + 512 存储",但**实测 NAND 仅 128MB**,
未发现存在硬件层面 512MB NAND 的 AX6 SKU。可能是以下三种情况:

1. 你记错了规格(更可能)
2. 有人在闲鱼魔改换了 NAND 芯片(罕见)
3. 你看到的 "512" 是 **DDR** 不是 NAND(那种是 512MB DDR + 128MB NAND 的标准低配 SKU)

无论哪种,本固件的 nss-extra.config 已经按以下假设构建:
- DDR: 1024MB → `IPQ_MEM_PROFILE_1024`
- NAND: 128MB → 不修改 stock 分区,rootfs ≤ 102MB

如果你的 NAND 实际是 256MB(部分 AX6 批次),可以改用非 stock 变体
`redmi,ax6` 重新分区,但需要 initramfs 跑 ubidetach + ubiformat,**有变砖风险**,且非 stock 给的 rootfs 反而更小(82MB)。**保留 stock 是最优选**。

## 刷机检查清单(刷我们的固件后)

```bash
# 1. 内存 — 应 ~916 MB
cat /proc/meminfo | grep MemTotal

# 2. NSS 模块全加载
lsmod | grep -E '^qca_nss|^ath11k' | wc -l   # 期望 ≥ 15

# 3. NSS firmware 启动
dmesg | grep -i 'NSS Core'                    # 期望 "NSS Core 0/1 booted"

# 4. ath11k 加载(WiFi 6)
dmesg | grep -i ath11k | tail -5             # 期望 board-2.bin "Redmi-AX6"

# 5. fw memory mode(应为 0 = HIGH)
dmesg | grep "fw_mem_mode\|memory_mode"

# 6. NSS clock 锁定
sysctl dev.nss.clock.auto_scale               # 期望 0

# 7. NSS 实际跑流量(下载或 iperf 时观察)
watch -n1 'cat /sys/kernel/debug/qca-nss-drv/stats/cpu_load_ubi'

# 8. ECM 连接计数(NSS 接管的连接)
cat /sys/kernel/debug/ecm/ecm_db/connection_count_simple

# 9. WiFi HE 模式
iw dev | grep -E "channel|center"             # 期望 "width: 80 MHz"

# 10. 防火墙 flow_offload 应该是 0
uci -q get firewall.@defaults[0].flow_offloading        # 期望 0
```

## 当前已知风险点

| 风险 | 缓解 |
|---|---|
| 当前 ImmortalWrt SNAPSHOT 未应用本仓 nss-extra.config | 必须用 build-AX6-NSS 工作流构建,不要直接用上游 SNAPSHOT |
| rootfs_data 仅 40MB,装多了 LuCI app 会满 | LuCI 默认带,大插件改用 USB 外挂 |
| ath11k fw-memory-mode 改 0 是 build-time DT 修改 | 需要重新 sysupgrade(用我们工作流出的镜像) |
| nss-firmware 二进制没 hash 校验(`PKG_MIRROR_HASH:=skip`)| 信任 qosmio/nss-packages git commit |
