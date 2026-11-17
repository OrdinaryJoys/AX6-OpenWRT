# AX6 2026-11-17 上游移植与验收范围

这是现有 stock 验收基线的单独用户态候选，不是上游默认分支的整树合并。目标是吸收经验证适用的修复，不替换 NSS 数据面，未更改 main、运行参数、发布权限或实机。

## 覆盖与变动

全树基线冻结时，OpenWrt main 的月度范围为 1,140 个提交，ImmortalWrt master 为 1,157 个。相对已验收 AX6 源码的虚拟三方合并分别有 286、192 条冲突路径。VIK 旧 `main` 与默认 `owrt` 均核了所有可达提交的路径账本、历史触及和端点净差，另逐文件枚举 LiBwrt、JiaY、Julius、pbs05、perceival 的固定窗口。路径覆盖不等于所有历史补丁均已进行语义或运行审查。

Terra 的第二次只读核对：VIK main `f9b0ce76`、ImmortalWrt master `2fe3065a`、OpenWrt main `393efd7d`、25.12 `60c494ad`、qosmio main-nss `92a2d104` 未变；VIK owrt 从 `6b5baeb9` 新进 3 个提交至 `6dae72b1`。其中 [3f79bec](https://github.com/VIKINGYFY/immortalwrt/commit/3f79bec2d24ba2863f592bac880eac42e3a14966) 改 Fullcone 本机输入策略，[6dae72b](https://github.com/VIKINGYFY/immortalwrt/commit/6dae72b163fdcc042c959463dab2e0c9bbfa587c) 改防火墙渲染失败时保留旧规则，第三项调整 NSS Wi-Fi 日志。它们和本地传统 ECM/fw4 合同的语义未证实等价，因此不动驱动及防火墙配置。

## 已纳入的代码

源码 `0c7ae6e0c026ad50114e88b7f82b3f7b075c61f3` 是 `828c21b4d753328dce48e8c1a38530668cb246da` 的直接子提交。37 个路径只涉及五个包及测试/说明；保持内核、驱动、FW、feeds/Argon、路由配置和 OpenClash 版本策略。

- **dnsmasq：** [安全补丁组](https://github.com/openwrt/openwrt/commit/6db25ee835eb55af521125c84b12ffd0495f671b)与 [SIGHUP 性能修正](https://github.com/openwrt/openwrt/commit/514fad5218edaa4a36af7c15c0f46cdff0139309)，2.93 原包 SHA256 不变，001–009 与本地 100/200 按序应用。100/200 仅调整 hunk 坐标。保留原 DNS init、LAN-only 选择和用户的订阅/覆盖。
- **odhcpd：** `0320032/26b1220/03dacc2/68f3826/079f447/6828041/998fdad/1e7cc9f`。第一项与 AUTH 偏移修正必须成对；Terra 在合并前发现的[租约主机名转义](https://github.com/openwrt/odhcpd/commit/68f382690bfaec56d5b1f31c3c31c48bcb642e3a) 已纳入。可阻止原样换行造假记录；不据此宣称曾发生实际 XSS。
- **hostapd：** [5b240697](https://github.com/openwrt/openwrt/commit/5b240697987858c59d9798c3d46f2bc3db1de994) 的 C hunk。空、重复及跨接口对象不改变配置，合法重排正常提交。
- **netifd：** `625425e/a8b101f/d1e5a84/68493c7/d25c083/aa4f990`。补充显式空字符串拒绝，防止 parse 空输入为 VLAN 0，未配置的默认 VID 与合法数字 0 保持。这里只验证软件准入/失败路径，不宣称 VLAN/交换机硬件已跑过所有场景。
- **libubox：** [20bea2b](https://github.com/openwrt/libubox/commit/20bea2ba777dec6e62e15415ded5ffd8be1a5f18) 避免越界读。仅叠此项会对恶意对象输出 `{{}}`，随后在逗号输出前跳过无 name header 的对象成员，不改变数组路径和 ABI。

## 门禁与验证

- 宿主：实际包补丁按序以零 fuzz 回放、dnsmasq 本机编译与 `--test`、实际 hostapd/netifd/odhcpd 函数夹具、libubox ASan/UBSan。去掉 hostapd 防护复现 SIGSEGV，退回 netifd 上游单项复现空 VID 断言，libubox 仅上游版本复现非法 JSON。宿主不发送恶意流量，不运行路由服务，不代表 Linux 目标参数。
- 全量源码清单保留从原锁基点的 710 个 present / 21 个 absent（已有变更文件的内容更新不增加条目），不把新批 ID 冒充原 DRV29。DRV29 合同额外锁定本次父提交和完整路径/模式/对象差异；保留旧 DRV27、030–033 与实际 prepare/inventory 的既有门禁。拒绝新驱动文件、意外差异和工作树变化；DNS 测试继续要求精确的包修订。
- 云 Lint 成功后才派发一次 stock。最终 rootfs 除原完整 manifest 门禁之外，还要精确包含[这 7 个运行包](../.github/ax6-upstream-leaves-stock.manifest)。云端成功后须独立下载并验证同 run 的镜像、来源、包集合、FIT/DTB/UBI 和摘要，不能复用旧 run。

## 本批排除及后续

- **先单项继续：** uhttpd 请求/脚本槽需适配旧 recipe 和登录保护；ucode 解析适合独立小批；musl regex 需单独工具链闭包；dnsmasq 的 `b76d1aa/ceb8710/7e4c82b` 与本地 200 结合测试 UBus 生命周期后再纳入。
- **跨组件：** Fullcone/ECM/ctnetlink 目前有单回调所有权问题；必须覆盖加载顺序、netns、规则退役和回收，不能只套内核 chain 或 [VIK 新规则](https://github.com/VIKINGYFY/immortalwrt/commit/3f79bec2d24ba2863f592bac880eac42e3a14966)。rpcd ACL 需匹配 libubus `pre_invoke` 并保留 checked OFF；LuCI/Argon 自有主题与恢复行为也需验。
- **暂缓：** 内核整体升级、ath11k backports 整组、DT/分区迁移、任意 NSS/PPE 或固件替换、VIK split-NAPI/GRO、IRQ/RPS/PBUF/定频；不同驱动生命周期不可互换。054–073、035、独立解绑、LIVE、共享钟、公开表与 FW/DMA 退休均不在本固件。

没有刷写、设备操作或 Release。通过构建与离线验包也不证明启动、吞吐、丢包、时延或设备卸载。
