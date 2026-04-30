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
| **STOCK** | 标准 1G+128M(出厂) | ~102 MB(SMEM 给的) | **绝大多数人选这个** | **0%** |
| **EXPAND** | 1G+256M(改 NAND 颗粒后) | ~192 MB(DT 写死,留 18MB UBI 坏块 reserve)| 只有亲手换过 NAND 才能选 | **极高**(刷错变砖)|

### 怎么知道我是哪种?

```bash
# 已经能进 OpenWrt 的话
ssh root@192.168.5.1 'cat /proc/mtd | grep rootfs'
# 输出 mtd12: 06640000 → 102MB,是 STOCK
# 输出 mtd12: 0C000000 → 192MB,是 EXPAND
```

如果不能进系统 / 不知道:**默认选 STOCK,不要冒险**。

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
mtd12: rootfs         102MB  ★ 本固件刷写位置
mtd13: rsvd0          0.5MB
```

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

### STOCK(零风险)

```bash
# 1. SSH 进入当前固件(stock 或之前刷的同变体)
ssh root@192.168.5.1

# 2. 上传我们的镜像
scp downloads/openwrt-qualcommax-ipq807x-redmi_ax6-stock-squashfs-sysupgrade.bin root@192.168.5.1:/tmp/

# 3. 直接 sysupgrade(保留配置)
sysupgrade -v /tmp/openwrt-*.bin
# 或不保留:sysupgrade -n
```

### EXPAND(高风险)

如果当前是 stock 镜像,先 sysupgrade 到 stock 的我们的镜像,再走以下流程切到 expand:

```bash
# 1. 上传 initramfs 镜像(不是 sysupgrade)
scp downloads/openwrt-qualcommax-ipq807x-redmi_ax6-initramfs-uImage.itb root@192.168.5.1:/tmp/

# 2. 启动 initramfs(机器进入 RAM 模式)
sysupgrade /tmp/openwrt-*-initramfs-uImage.itb
# 等设备重启后进入 initramfs RAM 模式

# 3. SSH 进 initramfs(IP 还是 192.168.5.1 但状态在内存)
ssh root@192.168.5.1

# 4. 重格 UBI 分区(危险点,一旦执行无回滚)
ubidetach -p /dev/mtd12 || true
ubiformat /dev/mtd12 -y

# 5. 上传 expand sysupgrade 镜像
scp downloads/openwrt-qualcommax-ipq807x-redmi_ax6-squashfs-sysupgrade.bin root@192.168.5.1:/tmp/

# 6. 写入
sysupgrade -n /tmp/openwrt-*.bin
```

## 6. 变砖恢复(救命方案)

### A. 软变砖(能进 fastboot)

```bash
# 1. 长按 reset 10 秒进 fastboot
fastboot devices                              # 看到 AX6 ID
fastboot flash rootfs stock-rootfs.bin        # 刷回备份的 rootfs
fastboot reboot
```

### B. 硬变砖(进不了 fastboot)

需要 USB-TTL 串口(GND/TX/RX 焊在主板 J1 排针):

```
1. 接串口,115200 8N1
2. 按住 reset 加电进 u-boot 命令模式
3. 通过 TFTP 恢复:
   ipq807x# tftpboot 0x44000000 appsbl.bin
   ipq807x# nand erase 0x600000 0x100000     # mtd7 offset
   ipq807x# nand write 0x44000000 0x600000 0x100000
4. 同样恢复 appsblenv / art / bdata 分区
5. reset
```

详细引脚和 TFTP 服务器 setup,Google "redmi ax6 ttl unbrick"。

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

# ath11k fw memory mode(应该是 0 = HIGH)
dmesg | grep -i 'fw_mem_mode\|memory_mode'

# NSS 时钟锁定(我们的 sysctl 写入)
sysctl dev.nss.clock.auto_scale               # 期望 0

# NSS 实际跑流量中(开 iperf 或下载时观察)
watch -n1 'cat /sys/kernel/debug/qca-nss-drv/stats/cpu_load_ubi'

# ECM 接管的连接数(NSS 卸载工作中)
cat /sys/kernel/debug/ecm/ecm_db/connection_count_simple

# WiFi HE80
iw dev | grep -E "channel|center|width"       # 期望 80 MHz

# 防火墙没打开 flow_offload(避免与 NSS 冲突)
uci -q get firewall.@defaults[0].flow_offloading   # 0
uci -q get firewall.@defaults[0].flow_offloading_hw  # 0

# Country code
iw reg get | head -3                          # CN
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
| Software flow offloading | 网络 → 防火墙 → 常规设置 | `uci get firewall.@defaults[0].flow_offloading` | **=0** |
| Hardware flow offloading | 同上 | `uci get firewall.@defaults[0].flow_offloading_hw` | **=0** |
| Packet steering | 网络 → 接口 → 常规设置 | `uci get network.globals.packet_steering` | **=0**(NSS 加载时,失败时回 1) |
| **Bridge VLAN filtering**(DSA 语法)| LuCI Network → Devices → bridge → bridge VLAN tab | `uci show network \| grep bridge-vlan` | **不能有** |

**Bridge VLAN filtering** 特别注意:
- ❌ 错误用法(会断 NSS):`config bridge-vlan` + `list ports 'lan1:u*'`
- ✅ 正确用法:用 `config device` 加 `option type 'bridge'` + 单独 vlan 接口 `lan1.20`
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

## 10. NSS-兼容的 VLAN 设置(完整支持)

### 核心规则

NSS 与 OpenWrt 的 **DSA bridge VLAN filtering** 不兼容(会断 WiFi NSS offload),
必须用经典 **8021q 子接口**(如 `lan1.40`)+ 独立 bridge 实现 VLAN。

### ✅ 自动防御

本固件每次 boot 自动跑 `/etc/uci-defaults/95-ax6-nss-vlan-guard`:
- 删除任何 `option vlan_filtering '1'`(LuCI 不小心打开过会被清掉)
- 删除 `config bridge-vlan` 段(DSA 语法,清掉)

清理动作会写到 syslog: `logread | grep nss-vlan-guard`

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

后续仍需手动加 firewall zone / DHCP / WiFi(脚本会提示具体 UCI 段落)。

### 📐 LuCI Web 操作步骤(等价手动)

1. **网络 → 接口**:不要在 device 上勾选 "VLAN filtering"!如果勾了赶紧取消
2. **网络 → 设备 → 添加桥接设备**:
   - 名称: `br-iot`
   - 桥接接口: 留空(下一步加 vlan 子接口)
3. **网络 → 设备 → 编辑 lan1**(或物理口):**不要**改"网桥 VLAN 过滤"
4. **网络 → 接口 → 添加新接口**:
   - 名称: `iot`
   - 协议: 静态地址
   - 设备: 自定义,填 `lan1.40`(关键!`.40` 是 8021q tag)
   - IP: 192.168.40.1/24
5. (如要多端口)在第 4 步前先创建 br-iot 包含 lan1.40 + lan2.40
6. **防火墙 → 新建 Zone** 把 iot 网络拉进去,转发到 wan
7. **DHCP**:启用 iot 接口的 DHCP

### 🔬 验证 NSS VLAN offload 工作

```bash
# 1. VLAN manager 内核模块加载
lsmod | grep qca_nss_vlan_mgr
# 期望:qca_nss_vlan_mgr 32768 0

# 2. NSS 连接表带 VLAN 信息(跑流量后)
cat /sys/kernel/debug/ecm/ecm_db/connection_count_simple
# 期望 > 0

# 3. NSS VLAN debugfs(若内核暴露)
ls /sys/kernel/debug/qca-nss-drv/vlan/  2>/dev/null
```

### ❌ 错误用法(会断 NSS WiFi 加速)

绝对不要做:
```
config device
    option type 'bridge'
    option name 'br-lan'
    option vlan_filtering '1'    ← 错!
config bridge-vlan
    option vlan '20'
    list ports 'lan1:t'           ← 错!
```

DSA 语法 = bridge_vlan_filtering = 与 NSS 不兼容。**95-ax6-nss-vlan-guard 会自动清掉**,你勾了 LuCI 也无效(下次 boot 被回滚)。

### 完整 VLAN 范例(network/wireless/firewall)

参考 qosmio 官方:
https://github.com/qosmio/openwrt-ipq/blob/main-nss/nss-setup/example/README.md#vlan
