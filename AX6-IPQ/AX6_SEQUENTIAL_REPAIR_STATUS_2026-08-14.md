# AX6 顺序修复与验证状态（2026-08-14）

## 1. 当前验证对象

| 项目 | 分支 / 提交 | 状态 |
|---|---|---|
| 源码仓库 | `codex/ax6-rps-device-discovery-20260814@14f713a2a1e623cdd40b0bb50030ad09a2cf6fb0` | 已推送，工作区干净 |
| CI 已验证代码 | `codex/ax6-runtime-hardening-build-20260814@cb97ca1346ee651d96a077a842f82aa15e683a27` | 已推送；仅在固件构建提交后增加 CI fixture 调用 |
| 云端 Lint | Actions `31768455987` | 最终分支全部通过 |
| stock 构建输入 | `5e2f64ca9d79c2d252ad78a0be760f8c5b9023f8` / Actions `31766669024` | feed、输入溯源、NSS fast gate 和回归断言已通过；完整编译进行中 |

本轮只修改独立候选分支。没有合并主线、创建 Release、刷写或修改实机。

## 2. 已按顺序完成的修复

| 顺序 | 问题 | 根因 | 修复 | 验证 |
|---|---|---|---|---|
| 1 | NSS PBUF 最终 profile 可能被中间阶段覆盖 | 启动写入顺序和回读只证明单次写入，不能证明最终状态 | 固定 `extra -> wifi -> high` 顺序，按 PAGE_SIZE 对齐并对最终值精确回读 | 源码 11/11；构建门禁通过 |
| 2 | 首次启动后 RPS 设备集合不完整 | 脚本在 board pivot 前依赖旧状态，且未完整解析 DSA `ports[]` | 使用临时 `board_detect` 结果、UCI shell API和受限 sysfs，解析 `device` 与 `ports[]` | 源码 5/5；构建 fixture 通过 |
| 3 | 性能工具可能对不完整数据给出伪 PASS | 缺轮次/时长、跳过阶段、双向重传与最终快照判定不严格 | 建立 `FAIL > INCOMPLETE > ENV-BLOCKED > PASS` 优先级，校验轮次、时长、长时双向和最终快照 | hardening fixture 28/28；其他性能 fixtures 全部通过 |
| 4 | `qca-nss-clients` 本地补丁与包 release 不一致 | 本地包含上游以外的 011-013 修复，但 release 仍低于应有值 | release 提升至 14，构建锁和 artifact provenance 同步 | 五组件语义门禁中的 clients=14 通过 |
| 5 | 未配置 Wi-Fi 接口的 MCS leave 事件污染内核日志 | qca-mcs 将预期的未配置路径用 `KERN_DEBUG printk` 输出 | 定向移植 VIKINGYFY `2e496928` 的四处 `pr_debug` 修复，release 提升至 3 | 独立源码测试 6/6；五组件语义门禁 mcs=3 通过 |

## 3. 完整性门禁结果

- 源码从基线 `56807d9661dbe7df421d1fd31feba76677b5703d` 到当前提交的差异已由清单覆盖：209 个应存在文件、15 个应缺失路径。
- hostapd=2、qca-nss-drv=20、qca-nss-ecm=10、qca-nss-clients=14、qca-mcs=3 与构建锁逐项一致。
- 构建仓库全部 AX6 测试通过；性能工具 hardening 为 28/28，source semantic lock 为 21/21，并强制构建工作流实际调用 qca-mcs 源码门禁。
- GitHub Actions Lint 的 shellcheck、actionlint、yamllint、ZRAM、ECM offload、Wi-Fi、IRQ、PBUF、NSS 配置冲突和固件安全门禁全部通过。
- 源码分支和构建分支分别对当前 `origin/main` 执行三方 `merge-tree`，均无文本冲突；这只证明可合并性，不替代编译、产物和实机验证。
- stock 构建已完成真实 patch prepare 和 007/008、012、018/019 回归断言；仍需完成 qca-mcs/NSS/ECM/ath11k 编译、DTB、最终 rootfs、manifest、kmod、镜像和 SHA256。

## 4. 已审查但本轮不直接合并

本轮上游审查快照为：ImmortalWrt `bf1f49d07a93125882e50c4f33ca6b6a38c024dc`、
VIKINGYFY `1f9630750776197cda1269bf10a12fcdf16b7d42`、qosmio 25.12-nss
`d6848fa2ea00193b5b7d3973e3990da7f608027c`、LuCI 上游
`39dca4a5b097178fb69b1243b19e58ca1d6afefe`。移动分支仅用于差异审查，不直接进入构建锁。

| 候选 | 当前判断 | 原因 |
|---|---|---|
| Linux 6.18.41 | 独立候选 | 当前锁定 6.18.38；升级会同时改变 NSS、ath11k 和 qualcommax 补丁上下文，必须单独 refresh 和完整构建 |
| VIKINGYFY qualcommax/DTS 更新 | 逐项移植 | AX6 stock 有自定义 SMEM/nvmem 与分区约束，整目录覆盖可能破坏 stock layout |
| 官方 `qca_edma` stable MAC 更新 | 当前不适用 | 修改的是 DSA `qca_edma.c`，AX6 当前数据面是 `qca-nss-dp`，不能把同名 EDMA 直接视为同一路径 |
| CodeLinaro 默认分支 HEAD | 不跟随 | 默认 HEAD 对应较旧 11.4/13.0 分支；继续使用已验证的 13.1 锁定提交 |
| LuCI 上游 58 个提交 | 独立候选 | 含 luci-base dispatcher/security 和插件升级，需要与当前源码、OpenClash、UPnP 分别验证 |
| EDMA portable DMA/store 重构 | Track B | 属结构性修改，需要非 identity-DMA 平台、故障注入和完整吞吐测试，不夹入当前正确性修复 |

### 4.1 `package/qca-nss` 全目录复核

- qca-mcs 已与 VIKING 对齐为 release 3、9 个补丁；qca-nss-clients 因额外本地修复为 release 14，高于 VIKING 的 13。
- qca-nss-drv release 20、qca-nss-ecm release 10 高于 VIKING，来自本仓库已经独立验证的 correctness/backport 修复，不应降级覆盖。
- qca-ssdk 本地补丁数量为 8、VIKING 为 11，但本地 `004-platform-mht-init-guards.patch` 已合并覆盖 VIKING 004-007 的 package-private、DSA link polling、pinctrl 和清理语义；补丁数量不能直接作为缺失判断。
- VIKING 的 qca-ssdk 011 只处理可选 SFP MDIO-I2C bridge；AX6 stock DTS 没有该路径。本轮不引入额外模块依赖，转入多设备候选分支。
- VIKING 的 qca-nss-phy 001/002 针对 QCA8084 2.5G EEE 和 QCA81xx 10G 互操作，不是 AX6 的 QCA807x PHY 数据面；stock/expand 配置未选择 qca-nss-phy，AX6 DTS 也没有 QCA8084/QCA81xx/SFP-I2C 节点。为保持仓库多版本能力，应另建非 AX6 设备矩阵验证后再决定移植，不能借 AX6 stock 构建冒充验证。

## 5. 后续顺序

1. 等待 stock 构建越过 feed、fast gate、NSS prepare 和核心编译。
2. 构建成功后下载两个 artifact，独立核对 BUILD-LOCK、manifest、rootfs 包清单、OpenClash provenance、kmod 与全部 SHA256。
3. 只在离线产物审计通过后执行实机 `sysupgrade -T` 兼容性预检；未经再次确认不刷写、不重启。
4. 新固件获准刷写后，再执行冷启动、RPS/RFS/XPS、PBUF readback、ECM offload、ZeroTier、OpenClash DNS 和双端点吞吐矩阵。
5. 当前候选闭环后，再分别建立内核 6.18.41、LuCI 更新和 EDMA Track B 分支，不混合验证变量。

## 6. 尚未关闭的边界

- 当前 stock 构建尚未完成，因此不能宣称固件产物已经闭环。
- 本轮没有操作实机；新修复的冷启动持久性、Wi-Fi/MCS 日志、真实 routed NSS/ECM 吞吐仍待授权后的实机验证。
- Windows 接收方向双向不公平仍偏向端点/NIC，但缺第二个 Linux 有线端点，不能最终排除链路协商、PAUSE 或客户端驱动因素。
- ZeroTier 高速 UDP receive drops、IoT 长稳、24/72 小时稳定性和 recovery 演练仍需专门测试窗口。
