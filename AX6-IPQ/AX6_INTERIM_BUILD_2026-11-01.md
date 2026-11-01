# AX6 Interim Cloud Compilation

This is one explicitly authorized intermediate STOCK build, not a release or
device qualification. No flash, reboot, restore, SSH debug or main merge.

Source: OrdinaryJoys/immortalwrt-nss,
codex/ax6-shared-prefix-contract-20261101,
d3fb5b2bbb20423b7ee4d08e09d724d84aa183b4.

Build branch: codex/ax6-interim-cloud-20261101, based on2bcafb435bb316da0f74da1f6ec0817020201ed1.
Manifest:566 present/15 absent; SHA256
19a5a03700c3c66332e378ffe68103cd8296805ef47b11fd836e696b189f63d7.

Actual package releases: mac80211 26, hostapd3, DP9, SSDK21, DRV24, ECM17,
clients27, MCS4, rpcd9. The rpcd checked feature remains OFF.
Other feed/core/component locks and hardware configurations are unchanged;
OpenClash retains its existing tracked master policy and actual provenance gates.

The old run40848841564 used6729b52, not this source/build pair. Its saved failure
log exits after the init host suite and before the owner test without recording
the Linux header candidate count. Do not assert zero, multiple or a proven
underlying kernel defect from that incomplete log.

This candidate explicitly prepares target/linux before observing/selecting
kernel input. The locked source target/linux/Makefile supports prepare. Existing
exact-one/nonempty/header+module-source checks, depth/path and no-fallback rules
remain unchanged. The parent2bc diagnostic is metadata only, not selection PASS.
The workflow binding fixture now requires one top-level target preparation in
the correct order, with missing/echoed/wrong-target/swallowed/duplicate/disabled/
late controls. No kernel command is executed by the local binding tests.

Local preflight: actual nine-package/provenance/default-OFF semantics, full566/15
source-diff coverage,31 semantic-lock controls,12 release tests,353 CI-binding
tests,30 metadata diagnostic tests,5 real-find header selector tests and the
manifest generator fixture pass. YAML plus27 embedded run-block Bash syntax
checks pass. actionlint is not installed locally and was NOT run; these checks
are not a complete Lint workflow or target compilation.

Cloud gates remain: source manifest and release identity, feeds/defconfig,
target toolchain, rpcd ON-clean-OFF components, prepared NSS/Wi-Fi host gates,
full firmware compile, DTB/rootfs/FIT/module/manifest/SHA256 checks and artifacts.
Release/delete-release remain main-only and cannot run on this candidate ref.
New local cohort/API/root host fixtures are not relabeled as cloud-executed;
some intentionally depend on local frozen receipts. Actual target build covers
selected production patches, not every optional profile or all-source semantics.

Keep all outputs NOT-FLASHED. A green build cannot close UK/SD full retirement,
shared PHY ops, root failure rollback, FW/DMA/concurrency or performance gaps.
Do not dispatch a second full build automatically after failure; save exact logs
and analyze the locked source first.
