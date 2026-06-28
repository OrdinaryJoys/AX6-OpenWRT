# AX6 Runtime Audit and Repair Notes - 2026-06-28

本文记录 2026-06-28 对 AX6 实机与构建仓库进行的 OpenClash DNS、NSS、WiFi、交换/VLAN、ZeroTier、UPnP、ZRAM/IRQ 相关检查、修复和遗留风险。内容用于后续复盘和升级前核对。

## 边界

- 未刷写路由器固件。
- 未改订阅 YAML 文件。
- 未把实机订阅内容、节点地址、密码、token 或订阅 URL 写入仓库。
- 未新增启动脚本强制修改 OpenClash、WiFi、ZeroTier、UPnP 或 VLAN 场景策略。
- 未改 NSS、ath11k、SSDK/EDMA 驱动配置。
- 实机 OpenClash 修复只使用官方 UCI 配置路径。

## 已发现问题

| 类别 | 问题 | 根因/证据 | 影响 |
| --- | --- | --- | --- |
| OpenClash DNS | `dnsmasq` 只转发到 `127.0.0.1#7874` | `dhcp.@dnsmasq[0].server='127.0.0.1#7874'` 且 `noresolv=1` | OpenClash core 重启或卡住时 DNS 会短暂停顿 |
| OpenClash fake-ip | 原先 `store_fakeip=0` | OpenClash UCI 中 fake-ip 持久化未开启 | core 重启后 fake-ip 映射可能丢失,客户端缓存旧 fake-ip 时可能断流 |
| OpenClash default DNS | IPv6 DNS 混入 IPv6 关闭场景 | 生成 YAML 中曾有 `2400:3200::1`,而设备无 IPv6 默认路由 | 不是当前故障,但不是高效/干净配置 |
| OpenClash 修复边界 | 订阅 YAML/自定义覆写不适合作为默认修复点 | 订阅会更新,自定义覆写会与插件生成逻辑叠加 | 易造成隐藏冲突或修复被覆盖 |
| LuCI/OpenClash 页面慢 | 浏览器侧曾见 20s+ 加载,实机本机 curl 多次为 60-105ms | uhttpd/LuCI 后端没有持续卡死证据 | 更像 OpenClash 页面 XHR、浏览器侧状态或 DNS/core 瞬态卡顿 |
| 2.4G IoT | 个别客户端 `tx failed` 很高、速率降到 1 Mbps | station dump 显示若干 IoT MAC 高失败计数; hostapd 无持续 deauth/disassoc | 可能导致部分智能家居断流,需按设备继续跟踪 |
| 2.4G HE40 | 配置 HE40 但实际 fallback 20MHz | hostapd 报 `20/40 MHz operation not permitted... Fallback to 20 MHz` | 正常 20/40 共存行为,不是故障 |
| Overlay 空间 | `/overlay` 使用率约 89% | `df -h /overlay` | 后续 OpenClash 更新或包更新可能失败 |
| 实机 pbuf 启动顺序 | 实机仍是旧固件 `S27qca-nss-pbuf` | 当前运行固件不是仓库最新 S19 修复产物 | 当前 pbuf 已应用成功,但新 S19 需随下一版固件验证 |

## 已完成的实机修复

| 项目 | 修复方式 | 结果 |
| --- | --- | --- |
| fake-ip 映射持久化 | `openclash.config.store_fakeip=1` | 生成 YAML 已为 `profile.store-fake-ip=true` |
| OpenClash 官方 DNS 生成路径 | 启用 `enable_custom_dns=1`,新增官方 `dns_servers` 的 `nameserver` 与 `default` 组 | 不改订阅 YAML,不改自定义覆写 |
| IPv6 default DNS 残留 | `default` 组使用 IPv4 DNS,并设置 `disable_ipv6=1` | 生成 YAML 中 `ipv6_default_ns_left=[]` |
| 自定义覆写回退 | 曾临时验证自定义覆写可行,随后按边界恢复 | 自定义覆写脚本没有保留新增 DNS 修复逻辑 |

实机 OpenClash 备份:

- `/etc/config/openclash.bak-codex-dns-20260628-125740`
- `/etc/openclash/custom/openclash_custom_overwrite.rb.bak-codex-20260628-124402`

当前有效 OpenClash DNS 关键状态:

```text
profile.store-fake-ip=true
dns.ipv6=false
dns.enhanced-mode="fake-ip"
nameserver=["223.5.5.5", "119.29.29.29"]
default-nameserver=["223.5.5.5#disable-ipv6=true", "119.29.29.29#disable-ipv6=true"]
fake-ip-filter-size=79
proxy-server-nameserver-size=6
```

## 已完成的仓库修复

| 仓库/文件 | 修复 | 目的 |
| --- | --- | --- |
| `OrdinaryJoys/immortalwrt-nss` | `qca-nss-pbuf` 已调整为早启动 `S19`,并移除启动时 reload WiFi 等不稳定行为 | 让 pbuf/N2H 在 WiFi AP 建立前应用 |
| `.github/ax6-nss-lock.env` | 构建锁定到已修复的 `immortalwrt-nss` 提交 | 避免云端构建使用旧启动链 |
| `AX6-IPQ/files/sbin/ax6-config-audit` | 新增 OpenClash fake-ip DNS 结构只读审计 | 防止订阅更新或手动恢复后重新引入隐藏 DNS 冲突 |
| `.github/workflows/lint.yml` | 增加 OpenClash DNS 审计项的 CI 防回归检查 | 防止后续删除关键审计逻辑 |
| `README.md` | 补充 OpenClash DNS 官方 UCI 路径说明 | 明确不要把订阅 YAML/自定义覆写当默认修复点 |
| `AX6-IPQ/HARDWARE.md` | 补充 OpenClash DNS 所有权边界和推荐配置 | 与 VLAN/NSS 边界一并记录 |

仓库侧 OpenClash 修复只做审计和说明,不预置订阅配置,不强制写运行策略。

## 验证结果

### 实机验证

| 检查 | 结果 |
| --- | --- |
| OpenClash 重启 | 成功 |
| `127.0.0.1:7874` DNS 查询 | 正常 |
| `dnsmasq 127.0.0.1:53` DNS 查询 | 正常 |
| 国内域名 | 返回真实 IP |
| `github.com` | 返回 fake-ip |
| NTP/Apple/connectivity check | 正常 |
| LuCI 本机响应 | 约 0.06-0.07s |
| `nss-check -v` | `PASS=41 WARN=2 FAIL=0` |
| `ax6-config-audit -v` | `PASS=10 WARN=1 FAIL=0` |
| 新版仓库 `ax6-config-audit` 临时实机运行 | `PASS=13 WARN=1 FAIL=0` |

新版审计新增 PASS:

```text
OpenClash: fake-ip cache persistence enabled
OpenClash: custom DNS nameserver group is configured
OpenClash: default DNS is IPv4-only with disable_ipv6=1
```

### 仓库验证

| 检查 | 结果 |
| --- | --- |
| `sh -n` / `bash -n` | 通过 |
| `shellcheck -S error` | 通过 |
| `tests/test-vlan-add.sh` | PASS |
| `tests/test-openclash-archive.sh` | PASS |
| `git diff --check` | 通过 |
| `yamllint .github/workflows` | 仅既有 workflow 风格 warning |

## 当前仍需注意的问题

| 优先级 | 项目 | 当前状态 | 建议 |
| --- | --- | --- | --- |
| P1 | OpenClash DNS 单点依赖 | fake-ip Redirect 仍依赖本地 core | 继续监控; 不建议直接把公共 DNS 加入 dnsmasq 并列上游 |
| P1 | Overlay 空间 | 约 89% | 清理旧备份、日志、缓存或减少可写层占用 |
| P1 | 2.4G IoT 高 `tx failed` | 个别设备持续高失败计数 | 按 MAC、位置、设备型号继续跟踪; 不要先归咎 HE40/HE20 |
| P2 | 实机 S27 pbuf | 当前运行固件未包含 S19 新修复 | 下一版固件手动更新后验证 `S19qca-nss-pbuf` 和 pbuf/N2H |
| P2 | 云端构建产物 | 需要继续以 Actions 和产物内容验证 | 不要直接刷写未确认产物 |

## 不建议的修复方式

- 不要修改订阅 YAML 作为默认修复。
- 不要把 OpenClash 自定义覆写脚本作为默认 DNS 修复点。
- 不要把公共 DNS 直接加到 dnsmasq 并列上游,除非明确接受绕过 fake-ip/rule 的降级行为。
- 不要关闭 NSS/ECM 作为排障捷径。
- 不要重新开启 firewall software/hardware flow offload。
- 不要将 VLAN 改成 DSA bridge VLAN filtering; NSS WiFi offload 场景继续使用 802.1q 子接口拓扑。
- 不要因为 2.4G fallback 20MHz 就关闭 HE40/HE20 自动兼容。

## 后续检查清单

升级或订阅更新后建议执行:

```sh
nss-check -v
ax6-config-audit -v
uci -q get openclash.config.store_fakeip
uci -q get openclash.config.enable_custom_dns
uci show openclash | grep "=dns_servers\\|\\.group=\\|\\.ip=\\|\\.disable_ipv6="
nslookup github.com 127.0.0.1
nslookup -port=7874 github.com 127.0.0.1
df -h /overlay
iw dev phy1-ap0 station dump
```

下一版固件更新后重点确认:

- `/etc/rc.d/S19qca-nss-pbuf` 是否存在。
- `nss-check -v` 是否仍为 `FAIL=0`。
- `ax6-config-audit -v` 是否仍只剩预期 warning。
- OpenClash 生成 YAML 是否保持 `store-fake-ip=true` 和 IPv4-only default DNS。
- 2.4G IoT `tx failed` 是否继续增长。
