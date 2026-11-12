# AX6 028/029 根入口宿主事务与 stock 云验证说明

更新：2026-11-12。状态：**上次完整目标编译成功，最终 rootfs 验收失败；验收器修正待新提交云验证，不放行部署。**
本说明供 source/build 两仓同步使用，不改变既有 frozen 合同，也不是 Release 说明。

## 当前结论与修正

**11月12日派发阻塞：** 下述CI修正已提交推送为
`b7828de8b930143da7cc38dd99b46fb934775b27`。对该候选仅尝试一次完整Lint派发，
GitHub返回HTTP422：`Actions has been disabled for this repository.`，没有新run。
随后只读核对却显示仓库Actions `enabled=true`、Lint与NSS构建均`active`、
仓库`archived=false/disabled=false`，两候选远端也未漂移。
目前不能确认是账户限制、GitHub服务状态或其他原因；没有证据支持改权限、
改预算或绕过门禁，也没有再次派发或改用其他仓库。完整固件替代构建尚未启动。
先排清GitHub可执行性，再对届时确认的精确候选HEAD依次Lint和单次stock；
以下旧run结果不能冒充新提交已通过。

唯一已执行的本批完整 stock 构建为
[42387007623](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/42387007623)，
build `64990dd4729f7e6a0413614347de3d5780c18f24`、source
`5e5ccf0bb7b31a0f5890c98a37ca5b256a2749d8`、attempt1、`ssh=false`。
同 build 的完整 [Lint 42386195734](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/42386195734)
成功。完整固件 run 的 `Compile firmware` 和 compiled stock DTB 检查成功，
但第44步 `Validate final rootfs contents` 失败，不能将整个 run 描述为成功。

准确首错为 ncurses 证据保留函数复制所选 IPK/index 后，仍固定按 `vlmcsd`
回读。实际命令是 `verify-ncurses-rootfs.py`，报错
`expected exactly one actual vlmcsd IPK`，exit1。原有12项 ncurses 测试
只验证包体比对，没有覆盖实际 main -> retain -> 严格回读入口。
这是验收辅助函数的包身份错误，不是已证实的目标 NSS/Wi-Fi 驱动故障或缺包。

本次只给共享 `retain` 增加 keyword-only `package_name`（默认仍为 vlmcsd），
在创建目录前检查名称和实际 control 身份，再以该显式名称执行原严格回读。
ncurses 固定两个包逐一传名。原 IPK/index/hash、架构、版本、依赖、rootfs
字节/模式/链接和独占写入条件不放宽；源码、配方、版本锁、性能开关未改。

修正测试覆盖实际 main 路径、原始 IPK/Packages/Packages.gz 保留、默认 vlmcsd
调用、身份错配、输入变动和旧目录拒绝。旧硬编码负控只恢复回读语句，保持新
签名，必须重现原错误且尚未调用 unsquashfs，不能以 TypeError 假充故障复现。
当前本地组合21套通过；ncurses 29项、vlmcsd 31项是其中的两套，不能重复累加。
此前非作者21项控制与当前复核的资格仅限这四个修正文件，不等于整机验证。
11月12日非作者重新核对四文件完全相同的摘要，29+31及额外11项控制通过，
未发现本次提交的阻断问题；原ncurses顶层报告可覆盖既有文件的行为未改变，
不能将独占IPK证据目录的保证误述为所有报告均不可覆盖。

11月12日另一路独立复验了本run的实际诊断输入：原硬编码错误精确复现，
修正后libncurses6的IPK/index保留与严格回读通过，实际control、4个库文件、
12个符号链接和2个目录类型与rootfs一致，默认vlmcsd入口亦通过。
八个诊断ZIP中没有terminfo原始IPK，故完整双包门不可在本地独立复跑；
这是旧失败时的证据保留边界，不据此宣称固件缺包，也不使用旧run包体补齐。

前序 rpcd OFF、Vim、vlmcsd 验收已执行；后续完整产物绑定、staging、
sysupgrade/recovery/kmod 上传未执行。已保留本 run 的诊断 artifact，
不是已合格固件。完整日志83583971 bytes，SHA256
`456cbcfa6302f57a3793b185ee32c36c92eb1807cd235723656eaa2a7aab770e`。
后继流程为独立复核、推送修正、相同新提交的完整 Lint，再单次 stock 构建；
不重跑旧 SHA，不自动放行 Release、刷写或运行态结论。新 run 身份以本分支
Actions 记录和后续动态为准，不借旧成功构建代替。

## 历史 CI 修正

本节记录前两次 Lint 的当时状态；其中“固件未派发”不描述当前状态。

第二次完整 Lint [42384556367](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/42384556367)
在 `fe684a7f58697d013314bf730a1d636fe91c6385` 上通过旧失败阶段，随后因官方
ncurses镜像低速而失败：90秒收到1703683/2247939 bytes（约75%），curl exit28。
完整归档哈希校验器尚未执行，不能误称哈希不匹配或驱动编译故障，固件仍未派发。
只将该次传输上限90秒调整为240秒、步骤上限3分钟调整为5分钟；连接上限15秒、
HTTPS/TLS验证、URL、archive/hash/source验证器与整个Lint20分钟上限均不变。
不增加盲目工作流重跑，也不接受半包、改哈希、关闭门禁或切未知镜像。
该参数是单次传输总时限，不是免校验或重试开关；定义参见
[curl 官方手册](https://curl.se/docs/manpage.html#-m)。

首个完整 Lint [42383523549](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/42383523549)
在 `aae2270a9f2893b908c0f4d643083504013785f6` 上失败；固件未派发。
准确首错为 `tests/test-current-layer-integration.py` 仍要求把当前DRIVER目录
直接传给历史命令门，未同步已审的“实际DRV27准入 -> 精确还原DRV25前缀”接线。
不是ShellCheck告警或目标驱动编译失败；步骤名包含大量测试，必须按实际trace归因。
原105命令门与新8门在该run均通过，原组合测试67项中的该1项失败。
修正只更新这条过时断言，并额外要求唯一新门、严格顺序及禁止旧直传路径；
原 frozen 合同、生产源码与构建锁不变。验证后只派发新提交，不重跑同SHA。
扩展本地20套构建门复核又提前检出两条同类旧接线断言（SSDK39与MDIO），
也已按真实SSDK41 ->40 ->39继承链更新，保留旧门及精确reverse合同；
这两条在本地修正，不消耗额外云构建试错。

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
- build 分支：`codex/ax6-root-host-build-20261107`；上次已运行 build 为 `64990dd4729f7e6a0413614347de3d5780c18f24`，本次修正保持同一 source 锁。
- 历史 b3 基础锁指向 `fce57df4d7828fa9e9c7a45975f37f09a77fa101` / driver25 / SSDK30，**未包含 028/029**；不得拿该旧固件替代本批。
- 用户允许核验后的修正提交推送和 stock 云验证；仍禁止 main/Release 和任何实机操作。

## 028/029 固定 Scope

`028-meminfo-cold-init-transaction.patch` 只处理初始未持有资源的 cold meminfo 取得事务：局部暂存、验证、成功提交及失败时仅回退本次取得项，包含局部 DMA 配对与边界检查。不将此扩展为已提交 meminfo 的完整释放、后续外层 probe 失败回退或 FW/DMA 退休证明。

`029-root-producer-diagnostic-host-transaction.patch` 是 root 控制、生产者和诊断入口的依赖组，不可任意拆取。范围包括根状态/取得位图与失败前缀逆序回退、sysctl/debugfs 撤入口与受保护操作排空、frequency/coredump 宿主生产者准入及排空、冷控制检查，以及仅属本 root 的 PPE HLOS 诊断映射凭据与清理。映射存在/ready 检查不构成 provider lease；HLOS 寄存器视图清理不等于 FW backing 或 DMA buffer 退休。

本批边界是既定 IPQ807x 宿主事务，不是任意热重探测、所有 SoC/内核、完整模块退出或整机安全认证。源码与文本清单一致性、宿主测试、目标编译和实机运行是不同证据层级，不能相互替代。

## 仍为 OPEN

- 完整 FW/DMA 退休，TX/callback/provider 的阻止新准入与所有在途访问排空，以及 committed meminfo、connection、QGIC、借用 provider 等生命周期。
- 全采样状态机互斥、RX/ACK/sample 写者竞争、FINISHED/晚 ACK 代际匹配、控制交叠、硬件最终频率和错误反馈；本批排队事务不是这些问题的闭合。
- late-probe、每核晚初始化失败及 timeout/晚回调的完整资源寿命；冷态 state/magic 检查不是其解决方案。
- SSDK 的 root/module UK/SD/PHY provider/reader 退休、嵌套 void GCC clock/reset 的真实成功判定与错误传播。
- 完整产物级 ABI/包体/manifest/FIT/UBI/stock 布局的一致性和独立验收；目标编译成功不替代这些未执行的门。
- 真实设备、RCU/NAPI/IRQ/DMA/HW/FW、吞吐/丢包/时延及性能。即使云编译成功，运行安全与性能仍未验。

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

## 历史接线复核与批准边界

最初的 b3 基础为旧锁。当时新增接线先独审、再协调 source 身份及 release/manifest/锁，之后已执行上述新 run；不能继续把这些已完成步骤记为未派发。后续镜像门和真实运行风险仍须独立验证，编译不证明没有其他故障。

最初接线独审发现 frozen40 sanitizer preflight 误传 `--source-root openwrt`，而原门强制 HEAD 为 fce40。该问题已在派发前修正为独立固定 fce40 test-only checkout，保留实际 SSDK41 prepared 的后段验证，未放宽 frozen 门。此处是已修历史问题，不是本次 ncurses 首错。

本次许可仅 **stock**；产物只能标记 **NOT-FLASHED**，**不创建或更新 Release，不向 main 发布**。不能把云编译或宿主 PASS 描述为 boot、flash、实机回归、FW 退休完成或部署批准。本任务不执行封存 runner/binary，不访问路由器，不运行 SSH、流量、配置、reload、reboot、恢复或刷写。

## 已执行 Run 身份

- 新 source 完整 commit：`5e5ccf0bb7b31a0f5890c98a37ca5b256a2749d8`；source manifest：`d2803aaed4c9a8ab4ddf8764438448126c51bdb18559cdaae22047a30792267a`。
- build commit：`64990dd4729f7e6a0413614347de3d5780c18f24`，本次待验修正不改变源码锁。
- stock run / attempt / job：`42387007623` / `1` / `128446412066`。
- 首个失败点：step44 ncurses retained-copy 包身份错误；完整日志及实际诊断数据已保留。
- 编译与 compiled DTB 步骤成功；最终 FIT/模块/manifest/恢复镜像等完整验收未完成，无正式合格 artifact。
- 实机状态：`NOT-FLASHED`；运行/性能：`UNVERIFIED`；Release：`NONE`。

早期 frozen40 sanitizer 预检已改用固定 fce40 test-only checkout，不再误把
新固件源码传给强制旧 HEAD 的门。实际新 SSDK41 仍走后续完整 prepared 门。
本次只修接线，原 frozen40/41 与 NSS command 合同不放宽。

后继 actual run 的身份与原始证据单独记录，不改写前次失败历史；FW 退休、采样、late-probe 等 OPEN 项不随编译成功自动关闭。
