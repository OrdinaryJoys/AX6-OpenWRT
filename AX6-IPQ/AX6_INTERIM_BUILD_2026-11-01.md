# AX6 Interim Cloud Compilation

## Current submission: DP containment host retirement dependency repair

Source `codex/ax6-dp-host-retirement-fixture-20261101` at
`bcdaec80470bd7fd58b32aebd07f49f2626b4b66` changes only eight test files.
It binds four actual EDMA retirement functions, their headers and typed ABI,
checks retirement state/order, and requires 21 precise runtime mutation
rejections. No production driver, recipe, release, feed or configuration changed.

The unchanged full workflow runs candidate-only: expect 31 IPQ807X plus five
other-SoC cases (36), not the 41-case local run that also executes five original
baseline controls. The existing extractor entry includes 17 extraction/admission
checks. Compiler failures, timeouts, signals or sanitizer failures cannot count
as successful semantic mutation rejection. Kernel preparation remains first.

The source manifest is regenerated for the new commit: 569 present / 15 absent,
SHA256 `22c9d9ed0ae9d72bd8a4205d5d763dc93e4b0f94a4b2f0ca7d9667548a53f409`.
The prior run 41297957298 failed in the old host fixture; full firmware, final
rootfs, DTB/FIT/UBI, manifest and module gates remain pending for this submission.
Dispatch is stock with SSH debug disabled. No main merge, Release or device
operation is authorized, and a failed dispatch/build must not be blindly retried.

## Prior authorized replacement (history)

Replacement source: codex/ax6-mcs-gate-release-20261101@
0d3f7a7e9df74d08a2cbfedf966d256e9f596d20. Only the shell gate and its new
regression changed relative tod3fb5b2bbb; package/target files and all nine
package releases are byte-identical. No MCS payload or recipe was changed.

The user approved one cancellation/replacement after verification. The original
run41292184950 has already completed with failure, so no cancellation is needed.
Its exact first failing check was test-qca-mcs-log-level.sh requiring release3,
although the source and exact lock both correctly declare release4. The late
target-kernel preparation was never reached and is not that run's failure cause.

The replacement retains the reviewed early kernel preparation. A source-side
test-only change lets the quiet-log gate accept the r3 feature floor and later
releases while enforcing an exact match when the expected build release is set.
Origin, four pr_debug additions/four printk removals and no-new-printk checks
remain. Ten isolated shell regression groups cover compatible versions, bad and
duplicate metadata, exact-lock drift and changed/missing patch inputs. This is
not a qca-mcs driver change or release downgrade. The new regression is also
called by the cloud Fast gate. Source commit/manifest must be rebound before
dispatch; no main/Release/device actions or automatic additional retries.

## Prepare-order correction after independent review

The first dispatch41292184950 remains bound to897b186. Independent source review
found a conditional CI defect in that revision: a cold target kernel preparation
removes the whole KERNEL_BUILD_DIR, including already prepared mac80211/NSS package
trees. The original late position could invalidate later host-gate inputs.
This does not prove the existing run has hit that condition or a device fault.

The follow-up candidate moves the unique target preparation to the start of the
Fast gate, before every kernel-root package preparation. The original selector
remains byte-identical. The binding fixture requires this top-level position,
retains the seven initial negative controls and adds two late-after-package cases.
This includes a negative for the exact faulty897b186 placement before the observer.
The original353 result is historical, not acceptance of the corrected ordering.
The corrected355-case binding suite passes; an explicit read-only check of the
actual897b186 workflow rejects it at the new prepare-before-package gate.
YAML/27 Bash blocks pass again; no local make or target execution was performed.

Any cancellation/replacement of the first run is pending a separate user decision.
Do not automatically dispatch again or silently treat the moving ref as that run.

## Initial dispatch record (historical below)

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
