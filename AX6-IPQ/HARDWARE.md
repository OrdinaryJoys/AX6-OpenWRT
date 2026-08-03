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

## 2. 三种不能混用的分区布局

| 布局 | `/proc/mtd` 特征 | 本仓构建 | 风险 |
|---|---|---|---|
| Xiaomi 原厂双槽 | `rootfs=023c0000`, `rootfs_1=023c0000`, `overlay=01ec0000` | 当前完整镜像不适用 | 镜像过大会在升级前被拒绝 |
| custom U-Boot/SMEM 合并 | 单 `rootfs=06640000` | **STOCK workflow 的实际目标** | 必须确认只有合并 rootfs |
| 256MB 扩容固定 DT | 单 `rootfs=0c000000` | EXPAND | 仅限已换 NAND 且布局一致 |

### 怎么知道我是哪种?

```bash
# 已经能进 OpenWrt 的话
ssh root@192.168.5.1 'cat /proc/mtd | grep -E "\"rootfs(_1)?\"|\"overlay\""'
# 原厂双槽: rootfs=023c0000, rootfs_1=023c0000, overlay=01ec0000
# 合并 SMEM: rootfs=06640000,通常没有 rootfs_1/overlay
# EXPAND: rootfs=0c000000
```

如果不能确认分区布局，不要依靠固件文件名中的 `stock` 猜测。上游
`redmi_ax6-stock` DTS 使用 `qcom,smem-part`，会读取当前 MIBIB/SMEM；
它既可能看到原厂双槽，也可能看到 custom U-Boot 合并布局。

### EXPAND 前置确认清单

只有同时满足以下全部条件才能选 EXPAND:

- [ ] 你**亲手或店家换过** NAND 芯片(从 128MB 颗粒改到 ≥256MB 颗粒)
- [ ] 设备能进 ImmortalWrt SSH,`/proc/mtd` 中名为 `rootfs` 的分区为 `0x0C000000`
- [ ] 你有 USB-TTL 串口和 fastboot 救机经验
- [ ] 你已准备与当前 MIBIB/分区布局匹配的完整备份和恢复方案

任何一项打不上勾都不能使用 EXPAND。

## 3. 128MB NAND 的两类 SMEM 布局

原厂双槽把 kernel、squashfs 和 `rootfs_data` 放入当前 35.75 MiB UBI
槽；完整功能镜像通常无法容纳。custom U-Boot 合并布局把后部空间合并为
`rootfs=0x06640000`，本机快照中的 `/rom=51.3M` 与 `/overlay=34.6M`
也只可能来自此类较大的 UBI，而不可能来自 35.75 MiB 单槽。

内核会按 MIBIB 动态生成 MTD，因此不能用固定 `mtd12/mtd13` 作为布局
判断或恢复依据，必须同时核对分区名称和大小。

以下关键分区**永远不要按固定 mtd 编号乱刷**:
- `0:appsbl` (U-Boot) 被破坏 → 通常需要串口和底层恢复工具
- `0:art` (WiFi 校准) 被破坏 → WiFi 校准数据丢失，必须使用本机备份恢复
- `0:appsblenv` 被误改 → bootcmd/启动变量可能导致设备无法启动

## 4. 刷机前 — 强制备份(避免无限恢复)

**首次刷我们固件前**,必须从原厂或现 ImmortalWrt 备份关键分区:

```bash
ssh root@<router>
# 按名称查找，禁止假设固定 mtd 编号
. /lib/functions.sh
. /lib/functions/system.sh
dd if="/dev/mtd$(find_mtd_index 0:appsbl)" of=/tmp/appsbl.bin
dd if="/dev/mtd$(find_mtd_index 0:appsblenv)" of=/tmp/appsblenv.bin
dd if="/dev/mtd$(find_mtd_index 0:art)" of=/tmp/art.bin
dd if="/dev/mtd$(find_mtd_index bdata)" of=/tmp/bdata.bin

# 拷出来
scp root@<router>:/tmp/{appsbl,appsblenv,art,bdata}.bin ~/ax6-backup/
```

把 `~/ax6-backup/` 备份到 U 盘,**永远保留**。变砖恢复要用。

## 5. 刷机步骤

### STOCK workflow(custom U-Boot/SMEM 合并布局)

```bash
# 1. 仅从已支持 redmi,ax6-stock 的 OpenWrt/ImmortalWrt 进入
ssh root@192.168.5.1

# 2. 必须确认是单 0x06640000 rootfs
cat /proc/mtd | grep -E '"rootfs(_1)?"|"overlay"'

# 3. 校验 SHA256 后,只上传 Release 中的 sysupgrade 镜像
scp downloads/openwrt-qualcommax-ipq807x-redmi_ax6-stock-squashfs-sysupgrade.bin root@192.168.5.1:/tmp/

# 4. 先执行只读验证；新版源码会按实际 MTD 几何检查镜像能否容纳
sysupgrade -T /tmp/openwrt-*.bin

# 5. 测试通过后才进行正常升级
sysupgrade -v /tmp/openwrt-*.bin
# 或不保留:sysupgrade -n
```

若看到双 `023c0000` 槽，本仓完整 STOCK 镜像不适用。不能从 Xiaomi
原厂 Web 升级页直接刷 `sysupgrade.bin`。`factory.ubi` 与 initramfs ITB
也不是 LuCI/sysupgrade 的替代文件。

### EXPAND(高风险)

只允许从已经使用相同 `redmi,ax6` EXPAND 分区布局的系统升级。先确认
物理 NAND 已改为至少 256 MiB,并且当前 `rootfs` 确实为 `0c000000`:

```bash
cat /proc/mtd | grep '"rootfs"'
scp downloads/openwrt-qualcommax-ipq807x-redmi_ax6-squashfs-sysupgrade.bin root@192.168.5.1:/tmp/
sysupgrade -n /tmp/openwrt-*.bin
```

从 STOCK 转换到 EXPAND 会改写 MIBIB/bootloader/分区表,不能靠
`sysupgrade` 启动 initramfs ITB 或对某个固定 `/dev/mtdX` 执行 `ubiformat`
来通用完成。
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

# ECM 数据库连接总数 (非 accelerated count, 用于粗略监控)
cat /sys/kernel/debug/ecm/ecm_db/connection_count_simple
# 主动验证 NSS 加速: nss-check -v 检查模块/参数, 然后生成流量对比计数

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
| WiFi 完全没了 | `0:art` 校准分区损坏 | 串口 + TFTP 写回本机 art.bin 备份 |
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
| ECM flow-control helper | 命令行 | `uci get ecm.general.disable_flow_control` | **=0 或 unset**；不要默认强制修改 Ethernet PAUSE/autoneg |

**IRQ/RPS 分层特别注意**:
- `packet_steering=0` 只关闭 OpenWrt netifd 的通用 packet steering。
- 本构建仍应保留上游 qualcommax/NSS 启动链: `S93smp_affinity`、`S28qca-nss-drv`、`S99set-irq-affinity`。最终镜像必须使用早启动 `S19qca-nss-pbuf`，确保 pbuf/N2H 在 WiFi AP 接口创建前应用；CI 会检查启动链接和脚本内容。
- 这些脚本分别管理 EDMA IRQ、NSS IRQ/internal RPS、NSS pbuf/hash bitmap、Linux RPS/XPS；不要用自定义 `ax6-irq-affinity` 开机覆盖，除非是在单次基准测试中手动执行并记录结果。
- `nss-check -v` 会检查上述启动链是否存在，并提示 NSS internal RPS 状态。
- `qca-nss-ecm` 的 `disable_flow_control` 会通过 ethtool 修改接口 PAUSE/autoneg。它不是本机终结流量卡顿的根因修复项，默认保持关闭；只有在单端口链路专项测试证明有收益时才临时开启验证。

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

OpenClash DNS 也遵循同样的所有权边界。固件不内置订阅配置,也不通过启动脚本改写
订阅 YAML 或 `/etc/openclash/custom/openclash_custom_overwrite.rb`。fake-ip 模式下建议
使用 OpenClash 官方 UCI 生成路径:

- `store_fakeip=1`,避免 core 重启后丢失 fake-ip 映射。
- `enable_custom_dns=1`,通过 `dns_servers` 配置 `nameserver` 与 `default` 组。
- IPv6 未启用时,`default` 组应使用 IPv4 DNS 并设置 `disable_ipv6=1`。
- 不建议把公共 DNS 直接加到 dnsmasq 并列上游,否则可能绕过 fake-ip/rule。

OpenClash 官方 `router_self_proxy=1` 会覆盖路由器本机 output 流量,而 ZeroTier 的
peer 传输并不只使用固定 UDP 9993。固件在 OpenClash 完成防火墙规则生成后读取
ZeroTier daemon 的 `primaryPort`、`secondaryPort`，并在端口映射启用时读取
`tertiaryPort`。WAN input 只允许 daemon 实际监听的三个 UDP 端口；TCP/9993 是
回环管理 API，不向 WAN 开放。OpenClash 本机 output 旁路则保留 primary 的 TCP/UDP
以及 secondary/tertiary 的 UDP。`ax6-zerotier-reconcile` 以 30 秒
间隔检查端口和规则，仅在变化时使用锁和 nft 事务同步 include 与 live 规则，不调用
`fw4 reload`，也不重启 OpenClash 或 ZeroTier。CLI 暂时不可用时保留最后有效规则。
该逻辑不固定随机端口，不修改 `local.conf`、LAN 代理、DNS 劫持、订阅 YAML、
覆写和 custom 文件。

`ax6-config-audit -v` 会只读检查以上配置边界；当两个服务同时启用且
`router_self_proxy=1` 时，会分别校验 include、live input 和 OpenClash 旁路规则，
拒绝缺失端口、陈旧端口、错误协议及 include/live 不一致。

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

> **维护安全边界：** 只读取下列已经确认的精确 debugfs 节点。禁止对
> `/sys/kernel/debug` 执行递归 `grep`/`cat`/内容采集。Linux 6.18 的
> IPQ807x APCS regmap 暴露范围可能超过实际 MMIO 资源，读取
> `regmap/b111000.mailbox/registers` 会触发内核 Oops/panic。

```bash
# 1. VLAN manager 内核模块加载
lsmod | grep qca_nss_vlan
# 期望:qca_nss_vlan 32768 0

# 2. ECM 连接总数 (跑流量后应增长, 但不等于 accelerated)
cat /sys/kernel/debug/ecm/ecm_db/connection_count_simple
# 主动验证: 生成受控流量, 比较前后 NSS frontend accelerated 计数

# 3. NSS VLAN debugfs(若内核暴露)
ls /sys/kernel/debug/qca-nss-drv/vlan/  2>/dev/null
```

### 完整 VLAN 范例(network/wireless/firewall)

参考 qosmio 官方:
<https://github.com/qosmio/openwrt-ipq/blob/main-nss/nss-setup/example/README.md#vlan>
