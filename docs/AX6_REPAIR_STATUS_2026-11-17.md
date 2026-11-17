# AX6 修复与验证状态｜2026-11-17

此分支只同步状态文档。源码锁、补丁清单、固件配置、CI 门禁、权限均未改变。
**不合主线、不发布 Release、不操作实机。**

| 状态 | 内容 | 证据与边界 |
| --- | --- | --- |
| 已编译并离线验包 | stock `r0-828c21b`，Linux 6.18.38，NSS DRV29，032/033 本机事务与 GCC 修正；DP、SSDK、ECM、ath11k；最终 rpcd r9 OFF；OpenClash 0.48.002 与锁匹配的 AArch64 core | [完整 Lint 43555788525](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/43555788525)、[stock 43556271166](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/43556271166)，build `e1a22c35018b4f1235ed06385e50a001ebda361b`，source `828c21b4d753328dce48e8c1a38530668cb246da`。旧固件 sysupgrade SHA256 `d82c19f1ba824936f553a00f353940bbe3a9ec5775530c6f67b32b25aab3aade`；未刷写、未验证实机。 |
| 离线候选，未入上述镜像 | SSDK 054–069：时钟/映射的本次失败配对、根层和 HPPE/PHY 局部事务、MDIO 路由拒绝、分设备 reader 和 MIB 唤醒；stock UK 根提交和 ioctl 在途排空、FDB 停排、旧 NAT/MTU 路径 | 修复了各自的局部路径，不代表根层清理失败、共享资源或解绑完整闭环。 |
| 离线优化，未入镜像 | DP 070：以 HAL 共享只读描述替换候选中的每实例 4 KiB 名称缓存，保留 ethtool 的名字布局、ndo 最后有效样本和拒绝不回退 | 已核五种布局；实际结构大小、吞吐和性能未测。DP remove 的 pdev 所有权与并发读取仍开放。 |
| 离线修复，未入镜像 | SFP 071：注册失败仅释放本次对象，保留同地址占用者；072：在私有数组发布前设置设备 ID，避免非零设备同步 probe 查设备 0 | 072 保留 071，只有一个 C 文件变化；严格重放、完整树对比、6 项源码负控和 48 项抽象场景通过；独立源码复核。不是目标编译。 |
| 仍未修完 | 可选 SFP port 6 的早期端口映射、QCA8111 退出过滤、MDIO-I²C 的其他 child 和引用、共享 SFP 驱动与 combo 的最后持有者、已注册后根失败、DP 跨 pdev reader | LIVE、独立解绑 HOLD。禁止在解绑通知内同步等待可能触发同一通知的 reader。 |
| 仍 HOLD 或未实测 | NSS 035 的 ESS/双核初态、FW 回传和 DMA 退休、017/018 完整 HW/FW/IRQ/NAPI 行为、延迟/丢包/双向吞吐、rpcd recover/LuCI checked 前端/恢复与真实重启、I²C 供应 ABI、mirror FRAG 与 MU-EDCA 编号 | 不关闭已使能共享时钟、不释放已发布资源、不扩大协议匹配；性能未宣称最优。现有 feed、Argon 与 OpenClash 更新策略未改，没有声称所有组件都是最新版。 |

## 云端检查范围

- [main 的 43824313446](https://github.com/OrdinaryJoys/AX6-OpenWRT/actions/runs/43824313446) 是上游巡检失败，不是 stock 编译失败：旧 LiBwrt 路径已跳转到 `LiBwrt/LibWrt`，旧 `main-nss` 不存在。此分支沿用的巡检已经改为观察 `LibWrt 25.12-nss`，不借此变更 main 或其他板型。
- 若本分支 Lint 放行，则单次 stock、SSH=false，用上述已验收源码基线复验当前构建环境和移动的 OpenClash core。已核该插件 master 仍是 `e553e82e`，core 分支从上次产物 `0c899b07` 变化到观察时的 `83506f91`；最终以本次产物实际提交、架构和散列为准。
- 本次 stock 不能验证 054–072。它们尚未形成同时满足冻结源码锁、清理失败/供应者放行和对应模块预检的最新候选。不得将这次 stock 通过等同于这些改动、可选 SFP 或实际性能通过。
