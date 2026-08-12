# AX6 Regmap 与 NSS 启动边界修复状态 (2026-08-12)

## 1. 本轮结论

本轮以实机 pstore、运行设备树资源、Linux v6.18/主线源码、CodeLinaro
锁定源码和 VIKINGYFY 集成补丁交叉核对。确认 2026-08-10 的内核 panic
直接根因是 `qcom_hwspinlock` 的 MMIO regmap 上限越过资源末端，而不是
APCS mailbox。APCS 存在同类边界风险，但故障地址和寄存器偏移不同。

修复保存在独立源码分支：

- 分支：`codex/ax6-regmap-pbuf-hardening-20260812`
- 提交：`3854ea2aa18e977240b194d0fb35c5007e2e9f3b`
- 构建候选分支：`codex/ax6-regmap-pbuf-build-validation-20260812`

没有合并主线、没有发布固件、没有修改或刷写实机。

## 2. 已确认并修复

| 优先级 | 问题 | 证据与根因 | 修复 |
|---|---|---|---|
| P0 | qcom hwspinlock regmap 越界 | pstore 中故障偏移为 `0x20000`；实机 `1905000.hwlock` 资源长度为 `0x20000`；Linux 驱动的包含式 `max_register` 也是 `0x20000` | 新增 `1002` 补丁；按 `min(驱动原上限, resource_size - reg_stride)` 限制，增加小资源下溢保护 |
| P0 | APCS 补丁可能扩大其他平台范围 | 原补丁直接覆盖 `max_register`，较大资源可能扩大驱动原有访问范围；小资源还可能发生无符号下溢 | `1001` 改为 clamp，并在资源小于 stride 时拒绝 probe |
| P0 | NSS PBUF 启动假成功 | 启动脚本吞掉 sysctl 返回码，重复写入代替确认，非零值不校验目标 profile | 按 CodeLinaro `ALIGN(size, PAGE_SIZE)` 语义回读；零值有限重试；部分或错误的一次性分配立即失败，不重复写 |
| P0 | NSS 频率初始化保护不完整 | 本仓 `017` 只保护 `auto_scale`，实际缺少 `current_freq` 和 workqueue 消费端保护 | 对齐 VIKINGYFY 完整 `017`：两个 sysctl 入口和 IPQ60xx/IPQ807x 消费端双层保护，IPQ807x 同时检查 `npu_reg` |
| P1 | ECM multicast 负数被转为大无符号数 | CodeLinaro 官方提交 `5ff84400cfc9de77f45e4b3da581bf803051a466`；四条路径把可返回负值的接口计数存为 `uint32_t`，导致 `< 0` 分支失效 | 精确移植四处 `int dst_if_cnt`，覆盖 NSS/SFE 与 IPv4/IPv6 |
| P1 | 其他 NSS 启动 sysctl 仍可静默失败 | `auto_scale`、queue limit、RPS bitmap 原来均未回读 | 统一使用有限重试的精确回读，并向 init 返回失败 |

受影响包 release 已递增：`mac80211` 1→2、`qca-nss-drv` 18→19、
`qca-nss-ecm` 9→10。

## 3. 已完成验证

| 验证 | 结果 |
|---|---|
| hwspinlock v6.18 fixture、四类资源矩阵、补丁应用 | 16/16 PASS |
| APCS IPQ8074/IPQ6018/SDX55 clamp 与下溢边界 | 22/22 PASS |
| PBUF 对齐回读、零值重试、部分分配、错误 profile、写入失败注入 | 8/8 PASS |
| 频率双入口/双消费端与 ECM 四路径静态门禁 | 13/13 PASS |
| EDMA F1-F6 既有正确性门禁 | PASS |
| stock sysupgrade 分区几何测试 | PASS |
| Shell 语法、ShellCheck error 级、`git diff --check` | PASS |
| 源码 base-to-target 完整差异清单 | 202 present / 15 absent，SHA256 provenance PASS |

构建 workflow 已增加上述三个新测试，并增加 `qca-nss-ecm/prepare`，用于在
正式编译前确认官方源码上的补丁可应用性。

## 4. 对旧问题清单的校正

1. OpenClash 已是 `0.47.156`，不是清单中的 `0.47.133`。按既定策略继续
   跟踪 `master`，由构建阶段记录实际插件提交和 Meta core SHA256；不改为
   固定旧插件版本，也不触碰订阅、覆写和 Geo 自动更新。
2. 设备 manifest 与最终 rootfs 包清单门禁在最近成功构建中已通过；旧清单
   的“Manifest V4 进行中”已过期。
3. 实机 EDMA `alloc_fail=4990` 是累计值，短窗无增长；不能据单点值判定当前
   故障，仍需 72 小时增量窗。
4. 2.4 GHz 配置为 HE40 + coexistence，运行时降至 20 MHz 是兼容行为，
   不是配置漂移。
5. UPnP 当前显式关闭且无映射实例，属于策略状态，不是服务故障。

## 5. 仍未闭环

| 项目 | 当前边界 | 下一步 |
|---|---|---|
| 云端完整构建 | 本轮外部执行额度阻止 GitHub 查询/推送；尚无新固件结果 | 恢复额度后先推两个独立分支，再运行一次 stock 构建，不盲目重跑 |
| 新固件产物 | 尚未生成 | 核对 kernel、DTB、rootfs、kmod、manifest、OpenClash provenance 和全部 SHA256 |
| 实机修复验证 | 本轮明确未改实机 | 新固件离线验证通过后，另行取得刷写授权；禁止直接读取危险 regmap debugfs registers |
| 双向转发满速 | 缺第二个受控有线端点 | 做 LAN-LAN 与 WAN-LAN TCP/UDP 双向测试，并同步采集 EDMA/NSS/ECM 增量计数 |
| 冷启动稳定性 | 未完成物理冷启动十轮 | 用户配合断电上电，逐轮检查 PBUF 回读、NSS core、ath11k 和 pstore |
| EDMA portable DMA | AX6 identity-DMA 当前可运行，但 RX 路径仍含 `phys_to_virt(dma_addr)` 假设 | 保持 Track B 独立实验分支，不并入当前 AX6 发布候选 |
| EDMA 多 ring | 当前实机 1/1/1/1，符合门禁 | 继续禁止在未完成 store 模型重构前扩大 ring 数 |
| 内核 6.18.40 | 独立候选，未和本轮核心修复混合 | 本轮候选通过后再单独构建/回归，避免扩大故障定位范围 |

## 6. 操作红线

- 禁止递归读取 `/sys/kernel/debug`，尤其不得读取
  `/sys/kernel/debug/regmap/1905000.hwlock/registers`。
- 不自动刷写、重启或恢复实机配置。
- 不整分支合并 qosmio、VIKINGYFY、QSDK 13.1.5/14；只移植已核对的提交。
- 不同时启用 OpenWrt software/hardware flow offload、packet steering 与 NSS
  自有加速策略。
- 不修改 OpenClash 订阅和覆写文件，不关闭 Geo 自动更新。

## 7. 上游依据

- Linux `drivers/hwspinlock/qcom_hwspinlock.c` v6.18 与主线：
  `tcsr_mutex_config.max_register = 0x20000`
- Linux IPQ8074 DTS：`hwlock@1905000` 资源长度 `0x20000`
- CodeLinaro qca-nss-drv 锁定提交：
  `6aa14c78e097b29c493ff2fef87e4d35906b2b5a`
- CodeLinaro qca-nss-ecm 修复：
  `5ff84400cfc9de77f45e4b3da581bf803051a466`
- VIKINGYFY 频率初始化保护：
  `package/qca-nss/qca-nss-drv/patches/017-fix-frequency-work-before-core-init.patch`
- qosmio 集成说明：NSS 场景关闭 OpenWrt packet steering 与软件/硬件 flow offload，
  避免用 DSA bridge-vlan 语法替代 NSS Wi-Fi offload 预期拓扑。
