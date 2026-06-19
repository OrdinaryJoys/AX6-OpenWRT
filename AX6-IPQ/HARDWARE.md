# AX6 硬件参考(实测)

## 1. 设备信息(实机读取)

```
model:       Redmi AX6 (stock layout)
compatible:  redmi,ax6-stock, qcom,ipq8074
SoC:         IPQ8074 (4 × ARMv8 Cortex-A53 @1.4GHz)
RAM:         916 MB ≈ 1 GB DDR3
NAND:        128 MB(stock 出厂)/ 256 MB(硬件改后)
WiFi:        ath11k Wi-Fi 6, 4×4 MU-MIMO
NSS:         qca-nss-drv + qca-nss-dp + qca-nss-ecm
```

## 2. 两种构建变体

| 变体 | 适用硬件 | rootfs 容量 | 选哪个? | 变砖风险 |
|---|---|---|---|---|
| **STOCK** | 标准 1G+128M(出厂) | 双槽,每槽 35.75 MiB | **绝大多数人选这个** | 较低,刷写前仍须备份并核对硬件 |
| **EXPAND** | 1G+256M(改 NAND 颗粒后) | ~192 MB(DT 写死,留 18MB UBI 坏块 reserve)| 只有亲手换过 NAND 才能选 | **极高**(刷错变砖)|

### 怎么知道我是哪种?

```bash
# 已经能进 OpenWrt 的话
ssh root@192.168.5.1 'cat /proc/mtd | grep -E "\"rootfs(_1)?\"|\"overlay\""'
# STOCK: rootfs=023c0000, rootfs_1=023c0000, overlay=01ec0000
# EXPAND: rootfs=0c000000
```

如果不能进系统 / 不知道:**默认选 STOCK,不要冒险**。

`06640000` 是第三方合并分区后的 102.25 MiB 单槽布局,不是 Xiaomi 原厂
STOCK SMEM,不能作为 `redmi_ax6-stock` 的识别依据。

### EXPAND 前置确认清单

只有同时满足以下全部条件才能选 EXPAND:

- [ ] 你**亲手或店家换过** NAND 芯片(从 128MB 颗粒改到 ≥256MB 颗粒)
- [ ] 设备能进 ImmortalWrt SSH,`cat /proc/mtd` 看到 mtd12 ≥ 0x0C000000
- [ ] 你有 USB-TTL 串口和 fastboot 救机经验
- [ ] 你能接受刷错变砖的 1% 概率

任何一项打不上勾 → STOCK。

## 3. NAND 分区(stock SMEM 实测)

```
mtd0:  0:sbl1         1MB    一级 bootloader
mtd1:  0:mibib        1MB    mtd 索引
mtd2:  0:qsee         3MB    TrustZone OS
mtd3:  0:devcfg       0.5MB  TZ 设备配置
mtd4:  0:rpm          0.5MB  RPM firmware
mtd5:  0:cdt          0.5MB  Config data
mtd6:  0:appsblenv    0.5MB  u-boot env  ★
mtd7:  0:appsbl       1MB    u-boot      ★
mtd8:  0:art          0.5MB  WiFi cal (board-2.bin) ★
mtd9:  bdata          0.5MB  Xiaomi 设备数据
mtd10: crash          0.5MB
mtd11: crash_syslog   0.5MB
mtd12: rootfs         35.75MB ★ 启动槽 0
mtd13: rootfs_1       35.75MB ★ 启动槽 1
mtd14: overlay        30.75MB 原厂数据分区
mtd15: rsvd0          0.5MB
```

内核与 squashfs 共同装入当前 UBI 槽。构建必须按完整 UBI 镜像校验,
不能只比较 rootfs 文件大小。

★ 标记的分区**永远不要乱刷**:
- mtd7 appsbl(u-boot)被破坏 → 必须串口 + USB-Flash 救
- mtd8 art(WiFi 校准)被破坏 → WiFi 永久坏,要从他人备份恢复
- mtd6 appsblenv 被乱改 → bootcmd 错误,无法启动

## 4. 刷机前 — 强制备份(避免无限恢复)

**首次刷我们固件前**,必须从原厂或现 ImmortalWrt 备份关键分区:

```bash
ssh root@<router>
# 必备 4 块
dd if=/dev/mtd7  of=/tmp/appsbl.bin
dd if=/dev/mtd6  of=/tmp/appsblenv.bin
dd if=/dev/mtd8  of=/tmp/art.bin
dd if=/dev/mtd9  of=/tmp/bdata.bin

# 拷出来
scp root@<router>:/tmp/{appsbl,appsblenv,art,bdata}.bin ~/ax6-backup/
```

把 `~/ax6-backup/` 备份到 U 盘,**永远保留**。变砖恢复要用。

## 5. 刷机步骤

### STOCK(标准 SMEM 分区)

```bash
# 1. 仅从已支持 redmi,ax6-stock 的 OpenWrt/ImmortalWrt 进入
ssh root@192.168.5.1

# 2. 再次确认是双 0x023c0000 槽
cat /proc/mtd | grep -E '"rootfs(_1)?"'

# 3. 校验 SHA256 后,只上传 Release 中的 sysupgrade 镜像
scp downloads/openwrt-qualcommax-ipq807x-redmi_ax6-stock-squashfs-sysupgrade.bin root@192.168.5.1:/tmp/

# 4. 使用 sysupgrade 正常升级
sysupgrade -v /tmp/openwrt-*.bin
# 或不保留:sysupgrade -n
```

不能从 Xiaomi 原厂 Web 升级页直接刷 `sysupgrade.bin`。`factory.ubi` 与
initramfs ITB 也不是 LuCI/sysupgrade 的替代文件。

### EXPAND(高风险)

只允许从已经使用相同 `redmi,ax6` EXPAND 分区布局的系统升级。先确认
物理 NAND 已改为至少 256 MiB,并且当前 `rootfs` 确实为 `0c000000`:

```bash
cat /proc/mtd | grep '"rootfs"'
scp downloads/openwrt-qualcommax-ipq807x-redmi_ax6-squashfs-sysupgrade.bin root@192.168.5.1:/tmp/
sysupgrade -n /tmp/openwrt-*.bin
```

从 STOCK 转换到 EXPAND 会改写 MIBIB/bootloader/分区表,不能靠
`sysupgrade` 启动 initramfs ITB 或手工 `ubiformat /dev/mtd12` 通用完成。
转换流程必须针对实机现有 bootloader 和备份单独确认,本仓库不自动执行。

## 6. 变砖恢复(救命方案)

### A. 软变砖(能进 fastboot)

```bash
# 1. 长按 reset 10 秒进 fastboot
fastboot devices
# 后续命令取决于当前 bootloader、MIBIB 和事先备份。
# 未确认分区布局前不要执行 fastboot flash 或 raw NAND 写入。
```

### B. 硬变砖(进不了 fastboot)

需要 USB-TTL 串口(GND/TX/RX 焊在主板 J1 排针):

```
1. 接串口,115200 8N1
2. 按住 reset 加电进 u-boot 命令模式
3. 核对串口输出中的 NAND/MIBIB 分区表与备份清单。
4. 只使用设备自身备份和与当前 bootloader 明确匹配的恢复流程。
5. `sysupgrade.bin` 是 tar 容器,不能用 `nand write` 当作 raw 分区镜像。
```

恢复 APPSBL/MIBIB/ART 属于高风险实机操作,必须在确认具体硬件和备份后单独制定命令。

## 7. NSS / WiFi 验证清单(刷完跑这套确认正常)

```bash
# 内存检测正确(应 ~916 MB)
cat /proc/meminfo | grep MemTotal

# NSS 模块加载数(应 ≥ 15)
lsmod | grep -E '^qca_nss|^ath11k' | wc -l

# NSS Core 启动
dmesg | grep -i 'NSS Core'                    # "NSS Core 0/1 booted"

# ath11k WiFi 校准变体加载
dmesg | grep -i ath11k | grep -i variant      # "Redmi-AX6"

# ath11k fw memory mode(AX6 应该是 1 = MID,匹配 DTS qcom,ath11k-fw-memory-mode=<1>)
# FULL/HIGH (0) 需要 ~100MB CMA,小心 panic;MID (1) ~32MB,稳定足用
dmesg | grep -i 'fw_mem_mode\|memory_mode'

# NSS 时钟锁定(我们的 sysctl 写入)
sysctl dev.nss.clock.auto_scale               # 期望 0

# NSS 实际跑流量中(开 iperf 或下载时观察)
watch -n1 'cat /sys/kernel/debug/qca-nss-drv/stats/cpu_load_ubi'

# ECM 接管的连接数(NSS 卸载工作中)
cat /sys/kernel/debug/ecm/ecm_db/connection_count_simple

# WiFi HE80
iw dev | grep -E "channel|center|width"       # 期望 80 MHz

# 防火墙无冲突 flow_offload 内核模块 (NSS ECM 处理硬件卸载)
lsmod | grep -E '^(nf_flow_table|nft_flow_offload) ' || echo "no conflict (OK)"

# Country code
iw reg get | head -3                          # US (FCC)
```

如有任何一项不对,**别急着重刷**,先 `dmesg | tail -100` 看启动日志。

## 8. 常见 brick 模式 + 处理

| 症状 | 原因 | 处理 |
|---|---|---|
| 启动卡 ImmortalWrt logo,无法 SSH | rootfs 损坏 | 等 30 秒,长按 reset 入 fastboot,刷回备份 |
| WiFi 完全没了 | mtd8 art 损坏 | 串口 + TFTP 写回 art.bin 备份 |
| 网口灯都不亮 | u-boot 损坏 | 串口救机 |
| 启动循环 | bootcmd 错或 kernel mismatch | u-boot `setenv bootcmd ...` |
| sysupgrade 后变砖 | 刷错变体(stock vs expand) | fastboot 刷回正确变体 |

## 9. NSS 与 OpenWrt 功能不兼容清单(qosmio 官方说明)

来源: https://github.com/qosmio/openwrt-ipq#important-note

### ❌ 启用以下任一会破坏 NSS 加速

| 功能 | LuCI 位置 | UCI 检查命令 | 必须 |
|---|---|---|---|
| Flow offload 冲突模块 | 命令行 | `lsmod \| grep -E 'nf_flow_table\|nft_flow_offload'` | **空 (无输出)** |
| Modprobe blacklist | /etc/modprobe.d/ | `cat /etc/modprobe.d/nss-no-flow.conf` | **存在** |
| Packet steering | 网络 → 接口 → 常规设置 | `uci get network.globals.packet_steering` | **=0**(本 NSS 专用构建固定关闭) |
| Bridge VLAN filtering(DSA 语法) | LuCI Network → Devices → bridge → bridge VLAN tab | `uci show network \| grep bridge-vlan` | **不要使用**；qosmio 说明不兼容 NSS WiFi offload |

**IRQ/RPS 分层特别注意**:
- `packet_steering=0` 只关闭 OpenWrt netifd 的通用 packet steering。
- 本构建仍应保留上游 qualcommax/NSS 启动链: `S93smp_affinity`、`S28qca-nss-drv`、`S27qca-nss-pbuf`、`S99set-irq-affinity`。
- 这些脚本分别管理 EDMA IRQ、NSS IRQ/internal RPS、NSS pbuf/hash bitmap、Linux RPS/XPS；不要用自定义 `ax6-irq-affinity` 开机覆盖，除非是在单次基准测试中手动执行并记录结果。
- `nss-check -v` 会检查上述启动链是否存在，并提示 NSS internal RPS 状态。

**Bridge VLAN filtering** 特别注意:
- 以 qosmio 当前上游说明为准: `option vlan_filtering 1`、`config bridge-vlan` 和 `list ports 'lan1:u*'` 这类 DSA bridge VLAN filtering 写法不兼容 NSS WiFi offload。
- 请使用经典 802.1q 子接口(如 `lan1.20`) + 独立 bridge。
- 详见 https://github.com/qosmio/openwrt-ipq/blob/main-nss/nss-setup/example/README.md

### ⚠️ NSS Firmware 12.5 不支持的功能(用 11.4 才支持)

| 功能 | 12.5 | 11.4 |
|---|---|---|
| 普通 NAT/PPPOE/L2TP/PPTP/GRE/Bridge/VLAN | ✅ | ✅ |
| 802.11s mesh | ❌ | ✅ |
| WDS bridging | ❌ | ✅ |
| AP_VLAN 4-addr | ⚠️ broken in ath11k | ⚠️ broken in ath11k |

家用单 AP **不需要** mesh / WDS / AP_VLAN,12.5 firmware 性能更优。

### ❌ NSS firmware 11.4-12.5 都不支持的(无论选哪个版本)

- IPSEC offload(VPN 走 CPU,不影响功能但占 CPU)
- CAPWAP(企业 AP 协议)
- TLS / DTLS offload
- PVXLAN
- CLMAP

这些不用就是了,不影响普通家用。

## 10. NSS-兼容的 VLAN 设置(802.1q)

### 唯一推荐拓扑

按 qosmio `main-nss` 当前说明，NSS WiFi offload 场景应使用经典 **802.1q
子接口**(如 `lan1.40`) + 独立 bridge。不要使用 DSA bridge VLAN filtering。

### 配置审计

本固件不会自动删除 VLAN 配置。`nss-check -v` 或 `ax6-config-audit -v`
发现 `vlan_filtering=1` 或 `config bridge-vlan` 时会报告确定性故障，
由管理员手动迁移到 802.1q 子接口拓扑。

### 🛠️ 命令行助手 `vlan-add`

```bash
# 添加 IoT VLAN 40,网关 192.168.40.1/24,在 lan1 lan2 上 tag
ssh root@192.168.5.1
vlan-add 40 iot 192.168.40.1/24 lan1 lan2

# 添加访客 VLAN 30,所有 LAN 口
vlan-add 30 guest 192.168.30.1/24 lan1 lan2 lan3 lan4

# 不带 ports 参数 = 默认所有 4 个 LAN
vlan-add 50 office 192.168.50.1/24
```

执行后会自动:
- 创建 `br-iot` bridge,用 `lan1.40 lan2.40` 作为 tagged port
- 创建 `interface iot` 静态 IP
- 创建 `firewall iot` zone，默认拒绝访问路由器本机、允许出站并转发到 `wan`
- 仅显式允许到路由器的 DHCP 与 DNS 请求
- 创建适配 CIDR 大小的 `dhcp iot` 地址池
- 任一步骤失败时恢复 network/firewall/dhcp 三个配置文件

后续只需按场景手动添加 WiFi SSID(SSID、密码、隔离策略不应由脚本猜测):
把新 SSID 的 `option network` 指向对应 VLAN 网络名,例如 `iot`。

### 📐 LuCI Web 操作步骤(等价手动)

1. **网络 → 接口**:确认现有网络使用经典 802.1q 子接口方案，而不是混用未知的 bridge VLAN 拓扑
2. **网络 → 设备 → 添加桥接设备**:
   - 名称: `br-iot`
   - 桥接接口: 留空(下一步加 vlan 子接口)
3. **网络 → 设备 → 编辑 lan1**(或物理口):保持该经典 802.1q 方案的端口设置一致
4. **网络 → 接口 → 添加新接口**:
   - 名称: `iot`
   - 协议: 静态地址
   - 设备: 自定义,填 `lan1.40`(关键!`.40` 是 8021q tag)
   - IP: 192.168.40.1/24
5. (如要多端口)在第 4 步前先创建 br-iot 包含 lan1.40 + lan2.40
6. **防火墙 → 新建 Zone** 把 iot 网络拉进去,转发到 wan
7. **DHCP**:启用 iot 接口的 DHCP

命令行助手会自动完成第 2-7 步的基础配置；LuCI 步骤主要用于人工审查或手动迁移已有网络。

### 🔬 验证 NSS VLAN offload 工作

```bash
# 1. VLAN manager 内核模块加载
lsmod | grep qca_nss_vlan
# 期望:qca_nss_vlan 32768 0

# 2. NSS 连接表带 VLAN 信息(跑流量后)
cat /sys/kernel/debug/ecm/ecm_db/connection_count_simple
# 期望 > 0

# 3. NSS VLAN debugfs(若内核暴露)
ls /sys/kernel/debug/qca-nss-drv/vlan/  2>/dev/null
```

### 完整 VLAN 范例(network/wireless/firewall)

参考 qosmio 官方:
<https://github.com/qosmio/openwrt-ipq/blob/main-nss/nss-setup/example/README.md#vlan>
