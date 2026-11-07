# AX6 028/029 根入口宿主事务与 stock 云验证说明

日期：2026-11-07。状态：**有限源码候选，目标构建与真实运行未验；不放行部署。**
本说明供 source/build 两仓同步使用，不改变既有 frozen 合同，也不是 Release 说明。

## 本批同步动态

源码候选已提交并推送：
[`5e5ccf0bb7b31a0f5890c98a37ca5b256a2749d8`](https://github.com/OrdinaryJoys/immortalwrt-nss/commit/5e5ccf0bb7b31a0f5890c98a37ca5b256a2749d8)，
恰为已审424基线的单父 child。构建锁现绑定该提交、driver27/SSDK31；
完整 base-to-source 清单为652项 present /21项 absent，摘要
`d2803aaed4c9a8ab4ddf8764438448126c51bdb18559cdaae22047a30792267a`。
清单覆盖全部实际差异，不能只用文件数量作源码或功能通过证明。

本批 Actions 动态入口（状态由云端更新，不用历史 run 代填）：

[![本批 Lint](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/lint.yml/badge.svg?branch=codex%2Fax6-root-host-build-20261107)](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/lint.yml?query=branch%3Acodex%2Fax6-root-host-build-20261107)
[![本批 stock 构建](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/build-AX6-NSS.yml/badge.svg?branch=codex%2Fax6-root-host-build-20261107)](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/workflows/build-AX6-NSS.yml?query=branch%3Acodex%2Fax6-root-host-build-20261107)

派发顺序为相同 build commit 的完整 Lint通过后，单次 stock/ssh=false 构建。
运行时以 Actions 的实际 `head_sha`、attempt、步骤原始日志和本批锁为准，
不能把分支 badge 或旧 run 的 success 当作固件/实机通过。

新增本地宿主验证为：DRV candidate-only37；受影响且重叠的23正例与12精确
SIGABRT负控；N2H417场景与8个实际 helper/handler 负控（ASan+UBSan）；
词法/CLI及构建门数据控制另计。两作者互为非作者复核，限定范围无 blocker。
417包含162原正常场景、31 ready helper、双核各112 cold场景，重复运行不累加。
这是实际选定C函数加宿主替代依赖，不是完整root/producer或内核并发执行。

## 当前身份与证据边界

- source 分支：`codex/ax6-root-host-source-20261107`。
- source 基础 HEAD：`4245760179a1fbf2a0ce35cc4e6f21fc49b642cc`；本批修复提交必须是它的直接单父 child。实际完整提交以本仓 `SOURCE_COMMIT` 与 Actions 记录为准，不能将基础 HEAD 单独称为已包含本批。
- 本批包版本：`qca-nss-drv` release27，`qca-ssdk` release31；厂商 driver pin 保持 `6aa14c78e097b29c493ff2fef87e4d35906b2b5a`。
- build 分支：`codex/ax6-root-host-build-20261107`；本次读回基础 HEAD：`b3d0caec10500e0a24c010003610c6352f0723f1`。
- 该 b3 基础锁仍指向 `fce57df4d7828fa9e9c7a45975f37f09a77fa101` / driver25 / SSDK30，**未包含 028/029**。旧云构建、旧固件及旧成功证据不包含本批，不可回填为本批通过。
- 本阶段仅允许由父层完成一次新的 stock 云编译/推送；本说明任务不执行 commit、push、dispatch、Release 或任何实机操作。

## 028/029 固定 Scope

`028-meminfo-cold-init-transaction.patch` 只处理初始未持有资源的 cold meminfo 取得事务：局部暂存、验证、成功提交及失败时仅回退本次取得项，包含局部 DMA 配对与边界检查。不将此扩展为已提交 meminfo 的完整释放、后续外层 probe 失败回退或 FW/DMA 退休证明。

`029-root-producer-diagnostic-host-transaction.patch` 是 root 控制、生产者和诊断入口的依赖组，不可任意拆取。范围包括根状态/取得位图与失败前缀逆序回退、sysctl/debugfs 撤入口与受保护操作排空、frequency/coredump 宿主生产者准入及排空、冷控制检查，以及仅属本 root 的 PPE HLOS 诊断映射凭据与清理。映射存在/ready 检查不构成 provider lease；HLOS 寄存器视图清理不等于 FW backing 或 DMA buffer 退休。

本批边界是既定 IPQ807x 宿主事务，不是任意热重探测、所有 SoC/内核、完整模块退出或整机安全认证。源码与文本清单一致性、宿主测试、目标编译和实机运行是不同证据层级，不能相互替代。

## 仍为 OPEN

- 完整 FW/DMA 退休，TX/callback/provider 的阻止新准入与所有在途访问排空，以及 committed meminfo、connection、QGIC、借用 provider 等生命周期。
- 全采样状态机互斥、RX/ACK/sample 写者竞争、FINISHED/晚 ACK 代际匹配、控制交叠、硬件最终频率和错误反馈；本批排队事务不是这些问题的闭合。
- late-probe、每核晚初始化失败及 timeout/晚回调的完整资源寿命；冷态 state/magic 检查不是其解决方案。
- SSDK 的 root/module UK/SD/PHY provider/reader 退休、嵌套 void GCC clock/reset 的真实成功判定与错误传播。
- Linux/GCC11 目标 ABI、完整目标内核/固件、真实设备、吞吐/丢包/时延及性能。即使将来云编译成功，运行安全与性能仍未验。

## 旧 Run 的首错与已有修复

本次直接复用既存 `cloud-review-worker/retrieval-02` 的 run/jobs JSON 与 job 日志，三份 SHA256 均与原 `CAPTURE-RECEIPT.json` 相符；没有重取同一 run。

[历史 run 41958787303](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/41958787303) 的 build HEAD 为 `c7fcbe7567cb3f8305a5237ed4b2b2a28adfc38e`，结论为 failure。NSS prepare、MDIO 与 frozen NSS command 步骤成功，失败步骤是 `Compile firmware`；其后 DTB/rootfs/产物绑定及 Release 步骤均 skipped。

直接致命首错发生于 2026-11-05 04:26:27 UTC：`package/libs/ncurses/host` 在准备 `ncurses-6.6.20260801` 时仍应用旧 `101-ncurses-5.6-20080628-kbs.patch`，6 个 hunk 中 4 个失败；单线程重试于 04:28:14 UTC 重现相同原因。不是 NSS command 失败，也不是本批新增生产故障。日志更早的 make 探测/卸载错误并未终止此前成功步骤，不能仅按第一个 `Error 1` 字符串归因。

b3 已包含 `f8d092d9ba159b3e8fc96e4189663e3f2c1fa440`：source 锁移到删除六个旧 ncurses 补丁的 `fce57df4d7828fa9e9c7a45975f37f09a77fa101`，新增完整 package 清单检查，并在目标 toolchain 前 prepare、核对固定归档与实际 host-prepared 源码。静态上覆盖上述首错；**不等于本次新 run 已通过，也不保证后续编译没有其他失败。**

## NSS Frozen 合同的 481/480 口径

原 command source profile 固定要求 driver **481** 文件。原始 driver25 重放主体为 **480**；已保存的历史 run 41771617912 与失败 run 41958787303 的 `PREPARED-driver.json` 均与这 480 个文件逐项同 SHA256，无缺失、无内容差异，唯一 extra 均是：

- 精确路径：`nss_init.c.orig`；大小：24079 bytes。
- 固定 SHA256：`f4c1b47f418282d49ff8ac7b1dd89dfdaef041f16442dbe3e5b4e9ec068ee020`。
- 两份保存的 aux 实际 payload 也已按该 SHA256 读回；完整 481 文件排序清单摘要均为 `8725c8ee568d698941659db9ac546c165b7817cb4787d8fe73ea163ecc19f4ce`，与 frozen profile 相符。

这是旧 prepare 辅助文件的身份差异，**不作为新生产故障，也不通配忽略任何 `.orig`**。历史 capture 的 484 项是 481 code + 3 recipe metadata，不是本批 484 文件源码主体。

父层新 root-host 门及 workflow 接线已落工作树，待限定范围非作者独审及 actual run。准入要求实际 prepared 的固定 **484 文件主体 + 必须存在的唯一固定路径/固定 SHA256 aux，共 485 项**，recipe metadata 单独依严格规则校验。随后按 **reverse029 -> reverse028** 严格还原旧 prefix：核完整路径与内容，不以宽松反打、刷新摘要或只数文件代替；还原后 481 项精确匹配旧摘要，继续调用原 command 门。不得修改、放宽或重新生成原 frozen 合同来接纳新代码。

新 profile 固定 SHA256 为 `f89e893bcc21b23be67c0d8afd5dae80c5bd4817b74ddb213569586e5890200c`，由封存 `669d...` 清单、pre-028 的原始 480 清单及旧 profile 比较固化，不从待验证的 prepared 刷新。新 source 拟为基础 `424576...` 的直接单父提交；新门读取该 commit 的原始 parent 头核对，不依赖 depth1 浅克隆中的 merge-base 历史，也不为此增加 fetch。

SSDK41 同样使用固定 `4245760179a1fbf2a0ce35cc4e6f21fc49b642cc` 的隔离 test-only source、真实固定 `fce57df4d7828fa9e9c7a45975f37f09a77fa101` accepted40 父检查，并核 actual prepared。test-only checkout 不得替代新固件源码锁，41/40 及更早 frozen 合同不改。

## 新构建风险与批准边界

当前 b3 基础仍是旧锁；新增工作树接线不等于新 run 已通过，不能直接宣称已验证 driver27/SSDK31。父层需完成新不可变 source 身份及 release/manifest/锁协调，并将 root-host 和 SSDK41 的实际 prepared 接线交非作者按限定 diff 独审。新头文件、目标回调 ABI、严格 patch reverse、GCC11/sanitizer 与目标编译均可能产生新的门失败；旧日志不能排除这些风险。

当前接线独审还发现一项需父层先修正的构建阻断：早期 frozen40 sanitizer preflight 仍传 `--source-root openwrt`，而原门在 preflight 分支前强制 HEAD 为 fce40。新固件锁改到424的直接 child 后将先在此失败，尚到不了后段 SSDK41/root-host 门。应将该旧控制预检绑定独立固定 fce40 test-only checkout，保持实际 SSDK41 prepared 的后段验证；不能放宽原 frozen 门来绕过。此项未修正并复核前，不将当前接线签为可 dispatch。

本次许可仅 **stock**；产物只能标记 **NOT-FLASHED**，**不创建或更新 Release，不向 main 发布**。不能把云编译或宿主 PASS 描述为 boot、flash、实机回归、FW 退休完成或部署批准。本任务不执行封存 runner/binary，不访问路由器，不运行 SSH、流量、配置、reload、reboot、恢复或刷写。

## Actual Run 待父层补录

- 新 source 完整 commit：`5e5ccf0bb7b31a0f5890c98a37ca5b256a2749d8`；source manifest：`d2803aaed4c9a8ab4ddf8764438448126c51bdb18559cdaae22047a30792267a`。
- 新 build 完整 commit / lock 摘要：`PENDING_PARENT`。
- 新 stock run ID / attempt / job ID：`PENDING_PARENT`；不得使用历史 `41958787303` 代填。
- actual prepared 与 root-host/SSDK41/原 command 门结果、首个实际失败点：`PENDING_PARENT`。
- 编译、DTB/rootfs/最终 FIT 与模块绑定及 artifact ID/SHA256：`PENDING_PARENT`。
- 实机状态：`NOT-FLASHED`；运行/性能：`UNVERIFIED`；Release：`NONE`。

早期 frozen40 sanitizer 预检已改用固定 fce40 test-only checkout，不再误把
新固件源码传给强制旧 HEAD 的门。实际新 SSDK41 仍走后续完整 prepared 门。
本次只修接线，原 frozen40/41 与 NSS command 合同不放宽。

只有父层在新 actual run 产生后补齐身份与原始证据，才可更新对应云验证结论；FW 退休、采样、late-probe 等 OPEN 项不随编译成功自动关闭。
