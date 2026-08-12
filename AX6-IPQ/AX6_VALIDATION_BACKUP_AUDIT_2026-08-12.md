# AX6 r0-4e35043 验证备份错误审查 (2026-08-12)

## 1. 审查范围与结论

审查对象：
`/Volumes/FX-MD87/Review/backups/r0-4e35043-validation-20260812/`。

结论：目录中的部分原始 iperf3 数据仍可用于有限分析，但“全量验证完成”不成立，
也不能用这些测试证明 NSS/ECM 转发路径或双向 WAN-LAN/LAN-LAN 满速。原验证脚本存在
输出格式、双向参数、错误传播、方向解析和测试拓扑错误；目录内的 hwspinlock 补丁草稿
也是损坏且不可应用的版本。

没有修改备份目录、路由器配置或实机状态。

## 2. 确定错误

| 严重度 | 问题 | 证据 | 影响 |
|---|---|---|---|
| P0 | P1 JSON 为空 | `P1.json` 为 0 字节；命令使用 `--logfile P1.log`，没有 `-J` | P1 自动 JSON 解析必然失败；只能人工读取文本日志 |
| P0 | 原 P2 不是双向测试 | `-d` 在 iperf3 3.21 是 debug，不是 bidirectional | 原“P2 双向”结论无效 |
| P0 | 原 P2 未完成 | `P2.log` 在 1155.76/1200 秒收到 SIGTERM，receiver 为 0 | 原 P2 不能作为完整 20 分钟结果 |
| P0 | 错误不会终止套件 | 主脚本只有 `set -u`；Python 解析、SSH snapshot 和 phase 失败不统一向上传播 | 可在阶段失败后继续，产生假完成或混合结果 |
| P0 | 测试没有穿越路由器 | 所有客户端连接 `192.168.5.1` 的路由器本机 iperf3 server | 只覆盖 host-terminated 流量，不能验证 NSS/ECM 转发、NAT 或 LAN-LAN |
| P0 | hwspinlock 草稿损坏 | `git apply --check` 报 `corrupt patch at line 87`；diff 后附带非补丁清单 | 不能用于构建 |
| P0 | hwspinlock 草稿返回类型错误 | 返回 `struct regmap *` 的函数中使用 `return -EINVAL` | 即使删除尾部文字，代码仍不正确；应返回 `ERR_PTR(-EINVAL)` |
| P1 | 后补 bidir 摘要只显示一个方向 | JSON 有 `sender=true/false` 两条 stream，脚本只读顶层 `sum_sent/sum_received` | P2 会被误报为 887/887 Mbps，实际约为 887/804 Mbps |
| P1 | S5 补测改变了并发条件 | 原 S5 计划 `-P 4`，后补 `--bidir` 没有 `-P 4` | 新旧 S5 不可直接比较 |
| P1 | P1 “60 秒窗口”描述错误 | 命令未设置 `-i 60`，默认 interval 是 1 秒 | 即使 JSON 正确，窗口数量和标签也不匹配 |
| P1 | S5/P2 文件被覆盖 | 17:49/17:50 的补测覆盖同名 JSON；旧文本 P2 仍保留 | 同名文件来自不同命令，缺少一一对应关系 |
| P1 | Wi-Fi 上下行标签反向 | `en1 -> router` 被写成下行，`-R` 的 `router -> en1` 被写成上行 | Wi-Fi 方向结论相反 |
| P1 | snapshot 覆盖不完整 | 后补 S5/P2/W1/W1R 没有阶段前后 snapshot；P3 四档只在最后采样一次 | 无法把计数器增量归因到具体方向或速率 |
| P1 | softnet 汇总不可依赖 | 同一 boot 中 `tsq` 从 339 降为 33；脚本直接用 awk 累加十六进制字段 | 计数出现不可能的回退，解析或采集方法错误 |
| P1 | UDP 断崖不可复现 | P3 900 Mbps 丢包 52.59%，随后 950 Mbps 仅 2.30% | 单轮顺序扫描受瞬态影响，不能确认稳定阈值 |
| P1 | SSH 身份校验不完整 | 脚本未设置 `IdentitiesOnly`、严格 host key 和固定 known_hosts | 测试对象身份和所用客户端密钥未被脚本强约束 |
| P2 | server 启动状态不明确 | `server.log` 只有 `Address in use` | 可能已有 server 正常运行，但该启动动作本身失败，缺少 PID/版本记录 |
| P2 | 无完整性清单 | 目录没有 SHA256、inventory 或 immutable run metadata | 无法检测后续覆盖或文件变化 |
| P2 | P4 隐藏错误 | 每轮 stderr 丢弃且不检查 iperf3 返回码；解析失败只表现为非零重传轮次 | “40/40”缺少运行成功数量门禁 |
| P2 | BB 不是 WAN bufferbloat | ping 和负载目标都是路由器本机 | 只能反映本机终结路径，不能评价 WAN/SQM 排队延迟 |

## 3. 仍可采用的数据

| 数据 | 可采用结论 | 限制 |
|---|---|---|
| `P1.log` | 1500 秒约 937 Mbps，0 retrans | 文本结果；不是转发流量，自动 JSON 报告无效 |
| 当前 `P2.json` | 双向两条 stream 约 887/804 Mbps，retrans 1/2 | 后补 host-terminated 测试；脚本摘要漏掉第二方向 |
| 当前 `S5.json` | 双向约 785/862 Mbps，retrans 0/0 | 单 stream，不等于原计划的四并发 |
| P4 40 个 JSON | 935.46-938.83 Mbps，均值 937.76 Mbps，记录中总 retrans 0 | 脚本没有单独记录每轮退出码 |
| W1/W1R | 两个方向约 939/476 Mbps，均无 retrans | 标签反向；需先确认绑定 IP 确实属于目标 Wi-Fi 接口 |
| snapshots | boot ID 全程一致；`alloc_fail_cnt=4990` 在 11 次快照中未增长 | 后半段 `softnet dropped +28`、`lan2 rx_drop +654` 无法定位到单一测试 |

上述数据可以说明路由器本机 TCP 服务在部分负载下可运行，但不能证明核心转发链路、
NSS acceleration、ECM classifier 或 NAT 双向性能已经闭环。

## 4. hwspinlock 草稿处理

备份中的 `1002-hwspinlock-qcom-tcsr-mutex-bound-max_register-by-resource.patch` 不应继续
使用，也不应手工修剪后直接投入构建。它有三项问题：

1. diff 尾部混入 `*** 验证要点`，导致补丁格式损坏；
2. 小资源分支错误返回裸 `-EINVAL`；
3. 验证说明建议直接读取修复后的 regmap debugfs，仍会扩大实机风险。

可构建版本已经在源码仓提交 `3854ea2aa18e977240b194d0fb35c5007e2e9f3b` 中实现，并由
Linux v6.18 fixture、资源矩阵和补丁应用门禁验证。实机验证不得读取
`/sys/kernel/debug/regmap/1905000.hwlock/registers`。

## 5. 重测要求

1. 每次执行建立不可覆盖的时间戳 run 目录，并先写 boot ID、固件版本、命令行、客户端/
   服务端 iperf3 版本和 SHA256 inventory。
2. 脚本使用 `set -Eeuo pipefail` 和失败 trap；任何 iperf3、JSON、SSH 或 snapshot 失败都令
   phase 失败，只有全部阶段通过才写完成标记。
3. JSON 命令必须显式使用 `-J`；文本日志与 JSON 分开，不使用同一路径或同名覆盖。
4. 双向结果按 `end.streams[].sender.sender` 分辨本地发送和反向发送，分别输出吞吐、重传、
   RTT；保留 `-P` 参数，不能在修正双向参数时改变并发条件。
5. 使用第二台受控有线端点，让流量实际穿越 LAN-LAN 或 WAN-LAN；路由器本机 server 只作为
   control，不作为 NSS/ECM 转发验收。
6. 每个 phase 前后分别保存原始 `/proc/net/softnet_stat`、端口、EDMA、NSS、ECM 和中断计数；
   十六进制字段显式转换，不只保存错误的汇总值。
7. UDP 每个速率至少重复三次并随机化顺序；出现 900/950 Mbps 非单调结果时增加冷却时间并
   检查客户端发送能力、socket buffer 和服务端 CPU。
8. SSH 固定 `ax6_check`、`IdentitiesOnly=yes`、`BatchMode=yes`、严格主机密钥和专用
   known_hosts；不递归读取 debugfs。
9. server 启动前检查监听 PID、二进制版本和绑定地址；`Address in use` 必须被明确判为复用
   已验证实例或阶段失败。

## 6. 当前边界

这份备份可以保留为原始故障证据，但应标记为 `PARTIAL / SUPERSEDED`，不能继续作为“驱动、
链路、吞吐全绿”的发布依据。下一次重测应在新固件通过云端构建和离线产物审计后进行，且
需要第二个有线端点才能关闭双向转发问题。
