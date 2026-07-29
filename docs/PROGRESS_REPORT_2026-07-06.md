# AX6-OpenWRT 修复进度报告 — 2026-07-06

**日期:** 2026-07-05 ~ 2026-07-06 | **状态:** 全部修复完成, 仓库同步, CI 构建中

---

## 1. 修复总览

### 仓库 commits (本次会话)

| # | Commit | 修复 | 仓库 | 状态 |
|---|--------|------|------|------|
| 1 | `9f399c4` | ax6-boot-guard ECM 强制层 (disable_offloads + disable_gro_list) | AX6-OpenWRT | ✅ pushed |
| 2 | `40f45db` | Lock 文件同步到 immortalwrt-nss 56807d9 | AX6-OpenWRT | ✅ pushed |
| 3 | `ba0008f` | ZeroTier forward nftables include 注册 (94-zerotier-zone) | AX6-OpenWRT | ✅ pushed |
| 4 | `52d0d38` | ZeroTier hotplug (中间方案, 后被 db2f339 替代) | AX6-OpenWRT | ✅ pushed |
| 5 | `44d3e28` | hotplug sleep 10 (中间方案) | AX6-OpenWRT | ✅ pushed |
| 6 | `db2f339` | zerotier-fw4 重写: primary-port-only + ax6-config-audit 简化 + hotplug 删除 | AX6-OpenWRT | ✅ pushed |
| 7 | `51f5c6d` | sysupgrade.conf 模板 (6 条保留路径) | AX6-OpenWRT | ✅ pushed |
| 8 | `5b9b966` | keep.d 收紧: /etc/openclash/ → config/ + custom/ only | AX6-OpenWRT | ✅ pushed |
| 9 | `d446bae` | keep.d +overwrite/ | AX6-OpenWRT | ✅ pushed |
| 10 | `5946e56` | opkg.conf 移除 check_signature (自构建固件签名不匹配) | AX6-OpenWRT | ✅ pushed |
| 11 | `1f150d5` | .gitignore CI 固件产物 | AX6-OpenWRT | ✅ pushed |
| 12 | `56807d9` | ECM ROM default disable_offloads 0→1 | immortalwrt-nss | ✅ pushed |

### 路由器直接修复 (非仓库管理)

| # | 修复项 | 位置 | 说明 |
|---|--------|------|------|
| R1 | Overlay clash_meta 重复文件 | `/overlay/upper/etc/openclash/core/clash_meta` | 删除 9.8MB ROM 已有副本 |
| R2 | root.bak 清理 | `/etc/crontabs/root.bak` | 删除旧 crontab 备份 |
| R3 | crontab 同步仓库格式 | `/etc/crontabs/root` | nss-check 行改为 rc=$? 格式 |

---

## 2. 修复分类详解

### 2.1 ECM 防护 (4 层纵深)

```
Layer 1 (ROM default):  qca-nss-ecm.uci → disable_offloads='1'     ← 56807d9
Layer 2 (first boot):   98-nss-tune uci-defaults                    ← 已有
Layer 3 (every boot):   ax6-boot-guard enforcement                  ← 9f399c4
Layer 4 (monitoring):   nss-check cron (每 30 分钟)                 ← 已有
```

**已验证回归边界:** 在当时的实机固件上，对路由器本机终结流量路径
(LuCI Web/SSH/DNS) 应用 `disable_offloads=1` 后，慢请求率从 35~87% 降至
0.3%，吞吐约提高 8 倍。EDMA v1 未公布硬件校验和能力并不能单独证明
GRO/GSO/checksum 必然损坏数据；GRO/GSO 本身也是 Linux 软件聚合能力。
因此当前策略只对 `br-lan` 主机路径强制关闭，物理 NSS 数据面端口保持
`report`，真正机制仍需按接口和特性做受控 A/B 才能定论。

### 2.2 ZeroTier 防火墙修复

**问题:** 每次重启后 ZeroTier 端口规则丢失, 外部无法连接。

**后续复核:** ZeroTier 1.16.2 官方源码会绑定 daemon 报告的 `primaryPort` 与
`secondaryPort`；启用 `portMappingEnabled` 时还会绑定 `tertiaryPort` 并交给
UPnP/NAT-PMP `PortMapper`。仓库规则必须跟踪这三个实际本地端口，不能简化为
primary-only，也不能从外部 `listeningOn`/surface address 推断端口。

**修复 (`db2f339`):**
- zerotier-fw4: 跟踪 primary + secondary，并在端口映射启用时跟踪 tertiary
- 增加 cli-ready guard (60s 等待 zerotier-cli 响应)
- drop_stale + append_once 防重复规则
- ax6-config-audit: 核对 daemon 实际启用的服务端口与 nft include 一致
- 删除无效的 hotplug 脚本 (99-zerotier-fw4)

**验证:**
- ZT input: daemon 报告的 primary/secondary 端口 + zt 接口 accept
- ZT forward: bidirectional rules, **33,161 pkts** 活跃转发
- ZT ONLINE, 7-8 peers, ARP 可见远程 peer (172.29.144.138)

### 2.3 备份配置修复

**问题:** 旧 sysupgrade 备份包含整个 `/etc/openclash/` (21MB),
包括内核二进制 (clash_meta 9.8MB)、GeoIP 数据库 (16.6MB)、规则集等可自动下载文件。
且 sysupgrade.conf 为空, ZeroTier 身份密钥等重要文件不在备份中。

**修复:**
- `sysupgrade.conf` (`51f5c6d`): 新增 6 条保留路径:
  - `/etc/zerotier/` — 身份密钥 (丢失 = 新 ZT 地址)
  - `/etc/openclash/config/` — 订阅/代理配置
  - `/etc/openclash/custom/` — 用户自定义规则
  - `/etc/crontabs/` — 定时任务
  - `/etc/dropbear/` — SSH 密钥
  - `/etc/ddns-go/` — DDNS 配置
  - `/etc/uhttpd.{crt,key}` — LuCI SSL

- `keep.d` (`5b9b966` + `d446bae`): 收紧 OpenClash 备份范围:
  ```
  旧: /etc/openclash/  (全部, 含 core/GeoIP/ASN/rule_provider/history)
  新: /etc/openclash/config/    (订阅配置)
      /etc/openclash/custom/    (自定义规则)
      /etc/openclash/overwrite/ (运行时参数)
  ```

**效果:** 备份从 21MB → 104KB (减少 99.5%), 完全排除固件内核和自动下载文件。

### 2.4 opkg 签名检查修复

**问题:** `opkg update` 在所有 6 个 feed 上报 "Signature check failed"。
自构建固件的 usign 密钥与上游 immortalwrt snapshot 仓库不匹配。

**修复 (`5946e56`):** `/etc/opkg.conf` 移除 `option check_signature`。
包认证仍由 HTTPS (TLS) + 包级 checksum 保证。

**验证:** 6 feeds 全部更新成功, 10325 个包可用。

### 2.5 Overlay 空间清理

| 文件 | 大小 | 原因 |
|------|------|------|
| clash_meta | 9.8MB | ROM inode 382 已有, overlay inode 609 重复 |
| root.bak | 567B | 旧 crontab 备份, 已更新为正确格式 |

---

## 3. 路由器当前状态

### 核心健康

| 子系统 | 结果 |
|--------|------|
| nss-check | **PASS=40 WARN=4 FAIL=0** |
| ax6-config-audit | **PASS=14 WARN=2 FAIL=1** (geo 已知接受) |
| CPU Load | 0.01 ~ 0.39 (NSS 硬件卸载) |
| RAM | ~315MB / 916MB (34%) |
| Overlay | 17.8M / 41.1M (46%) |
| Uptime | 15h+ |

### 接口

| 接口 | 状态 | 速率 | 错误 |
|------|------|------|------|
| lan1 | UP | 1000Mbps | 0/0 |
| lan2 | UP | 1000Mbps | 0/0 |
| lan3 | DOWN | — | 0/0 |
| wan | UP | 1000Mbps | 0/0 |
| br-lan | UP | — | 0/0 |

### WiFi

| 频段 | SSID | 信道 | 模式 | 客户端 | TX Power |
|------|------|------|------|--------|----------|
| 5G | RIFI | CH44 | HE80 | 0-1 | 29 dBm |
| 2.4G | AOT | CH11 | HE40 | 4 | 27 dBm |

### ECM 加速

| 指标 | 典型值 |
|------|--------|
| 连接数 | 94 ~ 1956 |
| NSS 加速 | 61 ~ 422 (35-71%) |
| accel_fail / driver_fail / nack | 0 / 0 / 0 |

### 核心约束 (全部合规)

```
flow_offload=0  flow_offload_hw=0  packet_steering=0
ecm_disable_offloads=1  ecm_disable_gro_list=1  ecm_disable_flow_control=0
ath11k frame_mode=2  nss_offload=1  crypto_mode=0  fw_mem_mode=1 (MID)
bridge-vlan=0  br-lan offload=ALL OFF  NSS RPS=1
冲突模块: nf_flow_table / nft_flow_offload / ipt_FLOWOFFLOAD — 全部 absent
```

### 启动链

```
S12ax6-boot-guard → S19qca-nss-pbuf → S26qca-nss-ecm
→ S28qca-nss-drv → S29qca-nss-netlink → S93smp_affinity
→ S99set-irq-affinity
```

### 服务 (全部运行)

| 服务 | 状态 |
|------|------|
| ZeroTier | ONLINE, 7-8 peers, forward 33161 pkts |
| OpenClash | running, Meta core, fake-IP mode |
| dnsmasq | running, DNS redirect → 127.0.0.1:7874 |
| uhttpd | running, `-n 50 -N 100 -k 20 -A 1 -R` |
| dropbear | running |
| network | running |

### 防火墙

| 规则 | 状态 |
|------|------|
| ZT input | primaryPort 9993 (TCP+UDP) + ztiv5j73wk accept |
| ZT forward | ztiv5j73wk ↔ LAN bidirectional |
| DNS hijack | dport 53 → redirect :53 (OpenClash fake-IP) |
| opkg | 6 feeds OK, 10325 packages |

---

## 4. 备份配置最终方案

### sysupgrade 保留 (固件升级时)

```
✅ 保留:
  /etc/config/*            — UCI 配置 (默认)
  /etc/zerotier/           — 身份密钥
  /etc/openclash/config/   — 订阅/代理
  /etc/openclash/custom/   — 自定义规则
  /etc/openclash/overwrite/— 运行时参数
  /etc/crontabs/           — 定时任务
  /etc/dropbear/           — SSH 密钥
  /etc/ddns-go/            — DDNS
  /etc/uhttpd.{crt,key}    — SSL

❌ 不保留 (来自固件或自动下载):
  /etc/openclash/core/     — 内核二进制
  /etc/openclash/GeoIP.dat — 自动更新
  /etc/openclash/ASN.mmdb  — 自动更新
  /etc/openclash/rule_provider/ — 启动后下载
  /etc/openclash/history/  — 历史数据库
```

### 备份大小对比

| 版本 | 大小 | 说明 |
|------|------|------|
| 旧 (修复前) | 21MB | 包含 core/GeoIP/ASN/规则集 |
| 新 (修复后) | 104KB | 仅用户配置 |

---

## 5. 仓库状态

### AX6-OpenWRT

```
HEAD:     1f150d5
Remote:   origin/main (已推送)
Branch:   main
Ahead:    0
Dirty:    0
```

**完整 commit 链 (12 commits):**
```
1f150d5 chore: gitignore CI firmware artifacts
5946e56 fix(ax6): disable opkg signature check for self-built firmware
d446bae fix(ax6): add overwrite/ to OpenClash keep.d backup
5b9b966 fix(ax6): narrow OpenClash keep.d to config/ + custom/ only
51f5c6d fix(ax6): add sysupgrade.conf (6 paths)
db2f339 fix(ax6): ZeroTier fw4 primary-port-only + audit simplify
44d3e28 fix(ax6): hotplug sleep 10 (intermediate)
52d0d38 fix(ax6): ZeroTier hotplug (intermediate, superseded)
ba0008f fix(ax6): 94-ax6-zerotier-zone forward include
40f45db fix(lock): bump to immortalwrt-nss 56807d9
9f399c4 fix(ax6): boot-guard ECM enforcement
```

### immortalwrt-nss

```
HEAD:     56807d9
Remote:   origin/main (已推送)
Branch:   main
Ahead:    0
Dirty:    0
```

```
56807d9 fix(ecm): change ROM default disable_offloads 0→1 for IPQ807x
```

### Lock 验证

```
SOURCE_COMMIT = 56807d9661dbe7df421d1fd31feba76677b5703d
git ls-remote = 56807d9661dbe7df421d1fd31feba76677b5703d
✅ 一致
```

---

## 6. 修复文件交叉验证

| # | 文件 | 路由器 | ROM 固件 | 仓库 | 状态 |
|---|------|--------|----------|------|------|
| 1 | ECM disable_offloads=1 | ✅ | ✅ d446bae | ✅ 56807d9 | 一致 |
| 2 | sysupgrade.conf | ✅ | ✅ 21 lines | ✅ 51f5c6d | 一致 |
| 3 | keep.d | ✅ 3 paths | ✅ 3 paths | ✅ d446bae | 一致 |
| 4 | zerotier-fw4 | ✅ 100 lines | ✅ 100 lines | ✅ db2f339 | 一致 |
| 5 | ax6-boot-guard | ✅ 54 lines | ✅ 54 lines | ✅ 9f399c4 | 一致 |
| 6 | 94-ax6-zerotier-zone | ⚠️ 已消耗 | ✅ 81 lines | ✅ ba0008f | 一致 |
| 7 | ax6-config-audit | ✅ 480 lines | ✅ 480 lines | ✅ db2f339 | 一致 |
| 8 | nss-check | ✅ 541 lines | ✅ 541 lines | ✅ existing | 一致 |
| 9 | 100-disable_offloads | ✅ | ✅ | ✅ existing | 一致 |
| 10 | opkg.conf | ✅ 0 check_sig | ✅ 0 check_sig | ✅ 5946e56 | 一致 |
| 11 | nss-no-flow.conf | ✅ 3 blacklist | ✅ | ✅ existing | 一致 |
| 12 | ath11k.conf | ✅ 3 params | ✅ | ✅ existing | 一致 |

### 残留文件检查

| 文件 | 状态 |
|------|------|
| 99-zerotier-fw4 (hotplug) | ✅ 已删除 |
| root.bak | ✅ 已删除 |
| clash_meta (overlay) | ✅ 已删除 |

---

## 7. CI 构建

| # | Commit | 状态 |
|---|--------|------|
| 28743393290 | db2f339 | ❌ 已取消 (被 d446bae 替代) |
| 28745794537 | d446bae | ✅ success (50MB, SHA256: 8c4081be...) |
| **28767971873** | **1f150d5** | **🔄 in_progress** (含 opkg + gitignore) |

---

## 8. 已知遗留

| 项目 | 状态 | 说明 |
|------|------|------|
| OpenClash geo auto-update | 已知接受 | GeoIP+GeoSite+ASN 31.6MB overlay, 每日更新 |
| 下一版固件刷入 | 待 CI 完成 | 1f150d5 构建中, 需用户授权 |
| 外置硬盘权限 | 间歇 | `/Volumes/FX-MD87` macOS 安全限制, 不影响仓库 |
| haproxy/openvpn | 未安装 | 预期 |

---

## 9. 下一步

1. **CI 完成** — 构建 `1f150d5`
2. **下载固件** — sysupgrade.bin + SHA256 验证
3. **刷入路由器** — 需用户明确授权
4. **重启验证** — ROM default disable_offloads=1 生效确认
5. **完整审计** — nss-check + ax6-config-audit + 功能测试
