# AX6 全量测试与修复报告（2026-08-01）

## 结论

当前实机的 NSS、ECM、SSDK/EDMA、ath11k、VLAN、IRQ/RPS、ZRAM、
OpenClash、ZeroTier 和 OpenVPN 状态均未发现确定的驱动冲突或配置故障：

- `nss-check -v`：`PASS=45 WARN=4 FAIL=0`
- `ax6-config-audit -v`：`PASS=29 WARN=2 FAIL=0`
- 物理口：千兆全双工，CRC/FCS/align/overflow/underrun/collision 均为 0
- 内核：无 BUG、Oops、panic、NSS/ath11k fatal 或 crash
- DNS：Mihomo 直连探针 50/50、dnsmasq 50/50
- LAN 到路由：0% 丢包，平均 0.848 ms
- 公网 1.1.1.1：0% 丢包，平均 68.863 ms，标准差 0.867 ms

本轮没有刷写固件。实机只安装了下述已验证的健康检查脚本、执行了精确的
OpenVPN 旧模板迁移，并做了可回滚运行态测试；订阅、覆写、OpenClash
配置文件和 ZeroTier 网络配置均未改动。

## 实机与构建基线

| 项目 | 当前值 |
|---|---|
| 设备 | Redmi AX6，stock DTS + custom U-Boot/SMEM 合并 rootfs |
| 源码 | `OrdinaryJoys/immortalwrt-nss@0ea848641f0` |
| 构建仓库 | `OrdinaryJoys/AX6-OpenWRT@2c55d5d` |
| 内核 | 6.18.38 |
| ZeroTier | 1.16.2 |
| OpenClash | 0.47.116，Meta core AArch64 |
| Overlay | 41 MiB，总使用 16 MiB，可用 22.8 MiB |
| ZRAM | 256 MiB，zstd，测试时未发生换页 |

备份：

| 文件 | SHA256 |
|---|---|
| `router-backups/Redmi-AX6-20260801-fulltest/ax6-pre-fulltest-20260801-182643.tar.gz` | `7dba2885cb786e651bc60af5dbb5ecf7fd53625f2b3919d7b7e6de3316e11a3c` |
| `router-backups/Redmi-AX6-20260801-fulltest/ax6-pre-health-repair-20260801-190608.tar.gz` | `2218e09ad44ab8c8daa1237c09a9b7f3f732811aab05e715803a03bd1ee9211a` |

## 已确认并修复

| 优先级 | 问题 | 根因 | 完整修复 | 验证 |
|---|---|---|---|---|
| P0 | OpenClash 进程存活但 DNS 停止响应时，官方进程 watchdog 不会恢复 | 仅检查 PID，不能识别活锁/SIGSTOP | 新增直接查询 `127.0.0.1:7874` 的守护；仅在 OpenClash 实际拥有 dnsmasq 上游时启用；连续 3 次失败后受 300 秒冷却保护地重启 | SIGSTOP Meta core 后 26 秒恢复，新 PID 正常，配置与覆写目录哈希不变 |
| P0 | ZeroTier 控制面 `OK`，但内核接口偶发缺少已分配地址 | procd/控制面和内核 L3 收敛存在时序分离 | 新增 L3 所有权守护；只在 online、network `OK`、`allowManaged=true` 且明确缺地址时恢复；不手工写地址/路由，不对 OFFLINE/REQUESTING 重启 | 故障注入和真实 `network restart` 均在 3 次阈值后自动恢复 |
| P1 | ZeroTier init 返回非零，但新 daemon 实际已 ONLINE | 上游 `service_started()` 防火墙钩子的返回值可覆盖已成功的 procd 生命周期 | restart 非零后核对 PID 已更换且 CLI online，再决定是否失败 | 实机日志为 `replacement daemon is ONLINE`，第三次触发返回 0 |
| P1 | ZeroTier 高速上行出现 UDP socket receive drops | ZeroTier 明确调用 `SO_RCVBUF`，全局 `rmem_default` 无法覆盖；上游常量为 1 MiB | 构建层精确补丁改为 4 MiB；Linux 会在 8 MiB `rmem_max` 下提供相应加倍后的有效队列；不改全局 sysctl | 补丁应用测试和 prepared-source 门禁已通过；需新固件后做最终吞吐验证 |
| P1 | OpenVPN 关闭后仍可能残留旧 `myvpn/vpn0` 和 zone/forwarding | 旧镜像模板跨恢复保留 | 仅在服务关闭且每个旧字段完全匹配时删除；任何用户自定义字段均不匹配、不删除 | 实机迁移前后当前配置哈希不变；审计确认无进程、tun0、1194、WAN 规则和旧转发 |
| P2 | 审计未识别上述 OpenVPN、ZeroTier L3 和 OpenClash DNS 活锁 | 只检查静态 UCI 或进程存在 | 将直接健康探针和完整禁用态检查接入 `ax6-config-audit` | 实机 `PASS=29 WARN=2 FAIL=0`，故障夹具均能拒绝错误状态 |
| P2 | 审计测试场景变量可能泄漏到后续 VLMCS 用例 | shell 对函数前置赋值的恢复行为存在差异 | 在跨场景前显式清除故障注入变量 | 全部 13 个可执行测试通过 |

## 吞吐与链路验证

### 路由器本机终结流量

| 方向 | 结果 |
|---|---:|
| Mac -> AX6，4 流 | 940 Mbps |
| AX6 -> Mac，4 流 | 922 Mbps |
| 同时双向 | 约 642-829 Mbps + 514-745 Mbps，随本机 TCP/软中断调度波动 |

该测试终结于路由器 CPU，不是 NSS 转发测试，不能用来判断 ECM/NSS 的
双向转发上限。

### 真正 LAN-LAN 端到端

Mac `192.168.5.190` 与 Windows `192.168.5.111` 位于不同有线 LAN 口：

| 测试 | 结果 |
|---|---:|
| Mac -> Windows，4 流 | 948 Mbps |
| Windows -> Mac，4 流 | 949 Mbps |
| iperf3 `--bidir` Windows -> Mac | 946 Mbps |
| iperf3 `--bidir` Mac -> Windows | 325-329 Mbps |

双向 TCP 存在明显公平性不对称，但尚无证据指向 NSS/SSDK：

1. 同网段 LAN-LAN 流量主要走交换/桥路径，不是 ECM 三层加速流。
2. 两个单向测试都达到千兆线速。
3. 全程没有物理错误、overflow、underrun 或内核异常。
4. 强制关闭 PAUSE 后，链路稳定后双向结果仍为约 325 + 946 Mbps，
   与 PAUSE on/on 基本一致，因此 PAUSE 不是根因。
5. Windows 端拒绝 iperf3 UDP `--bidir`，无法用同一端点排除 Windows
   iperf3/TCP 栈差异。ESnet 对 Windows 仅提供 best-effort 支持。

因此不能把该现象转化为路由默认配置。下一次定点测试应使用两台 Linux
有线端点，统一 iperf3 版本，并同时采集两端 CPU、NIC pause/drop、TCP
拥塞窗口与重传；若 Linux-Linux 仍复现，再进入 SSDK 端口队列和 buffer
水位检查。

### PAUSE A/B 边界

仓库继续保持 `ecm.general.disable_flow_control=0`。ECM 的该选项会执行
`ethtool -A <iface> autoneg off tx off rx off`，实测无双向收益，并在重新
协商的约 2 秒窗口产生大量重传。测试结束后 LAN1/LAN2 已恢复为 PAUSE
RX/TX on/on；未写 UCI。

Linux 文档也说明 PAUSE 的 RX/TX 值在 autoneg 开启时用于改变与链路伙伴
的协商参数，并可能触发重新协商，不能把它当作无中断性能开关：
[Linux ethtool netlink PAUSE 文档](https://docs.kernel.org/networking/ethtool-netlink.html)。

## Wi-Fi 验证

| 项目 | 结果 |
|---|---|
| 国家码 | US |
| 5 GHz | HE80，近距离实测上行 935 Mbps、下行 567 Mbps，无驱动 crash/drop |
| 2.4 GHz | 配置 HE40 + 20/40 coexistence；当前受共存机制降为 20 MHz，属于预期动态行为 |
| ath11k | `frame_mode=2`、`nss_offload=1`、`crypto_mode=0`、`fw_mem_mode=1` |

5 GHz 高负载时 `wifili_wbm_src_reo_code_inv` 会随流量增长，但目前没有
与丢包、崩溃或物理错误关联，保留为 P2 观察项，不据此改驱动。

## Web、DNS 与应用状态

- uhttpd 本机静态首页约 1.4 ms；未认证 LuCI 页面约 62-90 ms。
- Mihomo 直连 DNS 50/50 成功，dnsmasq 50/50 成功。
- OpenClash 配置、订阅、覆写、GeoIP/GeoSite/GeoASN/CHNR 自动更新保持原状。
- Mihomo UDP 端口 7895 累计 12 个 receive-buffer drops；ZeroTier 当前全部
  UDP sockets 为 0 drops。12 次/约 21 小时尚不足以证明持续故障，继续观察。
- 两条审计警告只表示 geodata 自动更新占用 overlay，用户已明确要求保留
  自动更新，因此不作为修复项。

## 仓库改动与门禁

新增/修正内容：

- `ax6-openclash-dns-health` 及 procd init
- `ax6-zerotier-health` 及 procd init
- ZeroTier 4 MiB UDP socket-buffer package patch
- OpenVPN 精确旧模板迁移
- `ax6-config-audit` 运行态检查
- build rootfs 内容门禁、ZeroTier prepared-source 门禁和 lint 测试

已通过：

- 13 个仓库可执行测试
- 所有可执行 shell 的 `sh -n`
- `git diff --check`
- 6 份 GitHub Actions YAML 解析
- 实机故障注入、真实 network restart、自恢复和文件 SHA256 一致性

## 尚未关闭的边界

| 状态 | 项目 | 下一步 |
|---|---|---|
| 待构建 | ZeroTier 4 MiB socket buffer 尚未进入当前实机二进制 | 触发独立分支 stock 构建，核对 prepared source、rootfs、manifest、kmod 和 SHA256 |
| 待端点交叉 | LAN-LAN TCP 双向不公平 | 两台 Linux 有线端点、同版 iperf3 复测；当前不得归因 NSS |
| 待新固件实机确认 | ZeroTier 高速上行 drops 是否归零 | 新固件后对齐 Mac/路由 ZeroTier 版本，再测双向吞吐和逐 socket drops |
| 观察 | Mihomo UDP 7895 累计 12 drops | 按时间差分，不用全局 UDP 计数直接归因 ZeroTier |
| 观察 | 5 GHz NSS Wi-Fi invalid REO counter 随负载增长 | 仅在与用户可见丢包/断流同步时再进入驱动级修复 |
| 测试条件缺失 | 2.4 GHz 独立吞吐/兼容矩阵 | 需要受控 2.4 GHz HE/legacy 客户端，不能用当前 IoT 设备做线速基准 |

在独立分支 CI 成功并下载产物完成离线核验前，不合并主分支、不发布、
不刷写实机。
