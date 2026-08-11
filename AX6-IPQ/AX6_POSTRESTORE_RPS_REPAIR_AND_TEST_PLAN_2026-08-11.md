# AX6 配置恢复、RPS/RFS 修复与后续测试方案（2026-08-11）

## 1. 结论

本轮配置恢复、核心驱动审计和定点吞吐 A/B 已完成。已确认一个此前被错误
归类为“避免 NSS 冲突”的配置问题：构建仓的同名 overlay 覆盖了锁定源码中的
`set-irq-affinity`，默认跳过 Linux RPS/RFS/XPS；同时锁定源码原脚本只枚举
`board.json` 的 `network.*.device`，未枚举 AX6 LAN 所在的
`network.*.ports[]`。结果是 LAN 本机终结流量集中在 CPU0。

修复前四流同时双向 iperf3 为 607/774 Mbit/s；仅临时给 LAN2 启用 RPS 后为
919/927 Mbit/s；完成源码修复并应用到实机后，15 秒最终回归为
908/930 Mbit/s，测试区间重传为 0，LAN2 错误和丢包增量为 0，NSS EDMA
分配失败增量为 0。

这证明本轮异常不是 PHY、网线、交换端口丢包、ECM 包损坏或 NSS EDMA 分配
失败，而是 host-path 的 CPU/RPS 配置缺口。

## 2. 配置恢复范围

| 项目 | 处理 | 结果 |
|---|---|---|
| 登录密码 | 不恢复 | root 密码仍为空，按用户要求由用户手动设置 |
| DHCP/DNS | 按字段迁移，不整文件覆盖 | 恢复本地域、AAAA 过滤、LAN IPv6 服务关闭和 ZeroTier ignore 段；保留新版本安全字段 |
| OpenClash | 不修改订阅和覆写 | 保留 127.0.0.1#7874、自动 GeoIP/GeoSite/GeoASN/CHNR 更新和现有运行模式 |
| ZeroTier | 恢复身份和配置并运行健康探针 | daemon、接口、地址、动态 nft include 和端口规则通过 |
| Wi-Fi | 保持现有已验证配置 | US 国家码；2.4G HE40+20/40 coexistence；5G HE80；未改 SSID/密钥 |
| NSS/ECM/EDMA | 保持分层 offload 策略 | ECM host-path 防护、NSS firmware RPS、pbuf/N2H、Wi-Fi NSS 均通过 |
| OpenVPN | 保持关闭 | 配置与证书保留，进程/接口/监听/转发均未启用 |
| macOS AppleDouble | 清理 `/etc/openvpn`、`/etc/easy-rsa` 下 37 个 `._*` | 清理后为 0，不影响真实证书和私钥 |

配置迁移前备份：

- 本地：`AX6-BACKUPS/POSTRESTORE-PRE-TUNING-20260811-2200/ax6-pre-config-migration.tar.gz`
- SHA256：`5627bd6110f2b60d3132254d5470f46cb61f0b0b04d31858f7de757c81b0e94a`
- 154 个成员，不包含 `/etc/shadow`

## 3. 根因链路

1. `qca-nss-ecm` 关闭的是 OpenWrt 通用 `packet_steering`，用于避免其自动策略
   覆盖 NSS 平台策略。
2. qualcommax 的 `set-irq-affinity` 随后应独立建立物理网口的 RPS/RFS/XPS
   flow table；这不是 NSS firmware RPS 的重复配置。
3. 构建仓原 `AX6-IPQ/files/etc/init.d/set-irq-affinity` 又增加
   `network.globals.rps` opt-in，默认直接返回，导致全局
   `rps_sock_flow_entries=0`、LAN 队列 `rps_cpus=0`、`rps_flow_cnt=0`。
4. 负载证据显示修复前 CPU0 为 99.5%，其余核心约 22%-29%，热点集中在
   `nss_empty_buf_queue` 和 `nss_queue0`。
5. 锁定源码原脚本进一步只读 `network.*.device`。AX6 的 board.json 中 WAN 是
   `device=wan`，LAN1-3 位于 `network.lan.ports[]`，因此简单恢复上游脚本仍只
   配置 WAN。
6. 修复后同时枚举 `device` 与 `ports[]`，去重后覆盖 wan、lan1、lan2、lan3；
   四核在双向负载中均参与处理。

Linux 内核文档说明：`rps_cpus=0` 表示 RPS 关闭，数据会留在中断 CPU；RFS 需要
同时配置全局 `rps_sock_flow_entries` 和每队列 `rps_flow_cnt`，数值会向上取整到
2 的幂。参见 [Linux networking scaling](https://docs.kernel.org/networking/scaling.html)。

## 4. 仓库修复

### OrdinaryJoys/immortalwrt-nss

- 分支：`codex/ax6-apcs-regmap-boundary-20260803`
- 修复提交：`8762b2fbd2c7c315ca4dab00917cf579db237d97`
- 文件：`target/linux/qualcommax/base-files/etc/init.d/set-irq-affinity`
- 修改：新增 `get_board_devices()`，同时枚举 `network.*.device` 和
  `network.*.ports[]`。

### OrdinaryJoys/AX6-OpenWRT

- 删除错误同名 overlay，让锁定源码重新拥有 IRQ/RPS 启动策略。
- 更新 `SOURCE_COMMIT` 和完整 source patchset SHA256 清单。
- `nss-check` 新增 Linux RPS/RFS/XPS 实际运行态门禁，不再只检查启动链接和
  NSS firmware RPS。
- lint 禁止重新添加 `AX6-IPQ/files/etc/init.d/set-irq-affinity`。
- STOCK/IPQ 最终 rootfs 门禁要求脚本包含 RPS、RFS、XPS 和 bridge ports 枚举，
  并拒绝旧 `network.globals.rps` opt-in。

## 5. 实机变更与回滚点

实机已应用源码提交对应脚本：

- `/etc/init.d/set-irq-affinity` SHA256：
  `ed62e1c5cd952b57c96e015ffc2ba3551200e4136175aab20cd35372631bd8ce`
- `/sbin/nss-check` SHA256：
  `d9cb5ddb3ab24162bb534d999469a1353b1457541674053fd92dc1462e28617d`
- 当前 wan/lan1/lan2/lan3：`rps=f`、`rps_flow_cnt=8192`、`xps=f`
- 内核全局 RFS 表：写入 65535，运行值按内核规则取整为 65536

回滚副本：

- `/root/set-irq-affinity.pre-rps-fix-20260811`
- `/root/set-irq-affinity.device-only-20260811`
- `/root/nss-check.pre-rps-gate-20260811`

## 6. 实机测试结果

| 检查 | 结果 |
|---|---|
| `nss-check -v` | 46 PASS / 4 WARN / 0 FAIL |
| `ax6-config-audit -v` | 30 PASS / 3 WARN / 0 FAIL |
| AX6 到上级网关 | 30/30，0% 丢包，平均 1.021 ms |
| AX6 到 223.5.5.5 | 30/30，0% 丢包，平均 7.577 ms |
| 有线 Mac 到 AX6 | 30/30，0% 丢包，平均 0.880 ms |
| DNS 经 dnsmasq/OpenClash | 50/50 成功 |
| OpenClash 7874 直连探针 | 通过 |
| ZeroTier `--probe` | 通过 |
| LuCI 未登录响应 | 10 次总耗时 78-101 ms；403 为未认证预期状态 |
| fw4/nftables | 语法和已加载规则集通过 |
| 单向 AX6→Mac | 约 918 Mbit/s，0 重传 |
| 单向 Mac→AX6 | 约 936 Mbit/s，测试区间 0 重传 |
| 修复前四流双向 | 607/774 Mbit/s |
| 修复后四流双向 | 908/930 Mbit/s，0 重传 |
| 双向期间 LAN2 | RX/TX error=0，drop=0 |
| 双向期间 NSS EDMA | alloc-fail 增量 0 |

LAN IPv6 RA/DHCPv6/NDP 已明确设为 disabled；odhcpd 重启后的新 PID 没有继续
产生旧的“无公网前缀”警告。该语义与
[OpenWrt odhcpd 文档](https://openwrt.org/docs/techref/odhcpd)一致。

## 7. 当前非故障警告与未验证边界

1. OpenClash overlay 仍有一个与 ROM 完全相同的约 10.5 MiB core。在线直接删除
   overlay upperdir 风险高，继续留到下一次干净刷写或离线 overlay 清理。
2. Geo 数据约 10.5 MiB，自动更新按用户要求保持启用。overlay 当前使用 33%，
   可用约 25 MiB，需要继续监控，不改成小空间构建。
3. EasyRSA `certs_by_serial` 有两个未被 `index.txt` 引用的证书文件。当前没有
   服务故障证据，未在不明来源时删除。
4. 本轮双向测试以“AX6 本机 ↔ 有线 Mac”为端点，已经覆盖 host-path；它不能
   代替两个独立有线端点之间的 LAN-LAN switching 或 WAN-LAN NSS routed test。
5. 修复脚本已写入实机并由 S99 启动链接管理，但本轮未为此再次重启。重启持久性
   仍需在用户允许的维护窗口验证。
6. root 密码仍为空。这是恢复排除策略，不是安全推荐状态；由用户手动设置后再做
   SSH/LuCI 登录回归。

## 8. 下一阶段顺序

### P0：云端闭环

1. 新构建仓提交锁定源码 `8762b2fb...`。
2. 云端 lint 必须通过，包括 DTB fixture、source patchset、workflow 和 shellcheck。
3. 触发一次 STOCK、SSH debug=false 构建。
4. 下载 artifact，独立核对 DTB、NSS/ECM/EDMA/ath11k、最终 rootfs
   `set-irq-affinity`、OpenClash core、manifest、kmod、sysupgrade、recovery 和
   SHA256。

### P1：维护窗口实机验证

1. 用户手动设置 root 密码后确认 SSH key 和 LuCI 登录。
2. 受控重启，确认四个物理端口 RPS/RFS/XPS 自动恢复，审计仍为 0 FAIL。
3. 使用两个独立有线端点分别做 LAN-LAN switching 和 WAN-LAN routed 双向测试，
   同时采集 ECM connection、NSS IRQ、CPU、softnet、端口和 EDMA 增量。
4. 进行 30-60 分钟混合负载：双向 TCP、UDP 有损门限、DNS、LuCI、ZeroTier、
   2.4G/5G 客户端稳定性。

### P2：非阻塞清理

1. 在干净刷写或离线维护时移除 ROM-identical OpenClash upperdir core。
2. 追溯两个 EasyRSA orphan cert 的用途后再决定删除或归档。
3. 持续记录 Geo 更新后的 overlay 水位；低于安全余量时先审计内容来源，不关闭
   用户要求保留的自动更新。

## 9. 禁止项

- 不把 OpenWrt 通用软件/硬件 flow offload 与 NSS ECM 同时打开。
- 不再次以“NSS 已有 firmware RPS”为理由关闭 qca-nss-dp host-path 的 Linux
  RPS/RFS。
- 不修改 OpenClash 订阅文件和覆写内容。
- 不关闭 GeoIP/GeoSite/GeoASN/CHNR 自动更新。
- 不删除来源未确认的证书、overlay upperdir 或分区内容。
- 未完成 artifact 独立验证前，不发布新固件，不再次刷写实机。
