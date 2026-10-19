# r18 core startup ownership build candidate

Local only. Do not push, dispatch, publish, merge or flash as part of this phase.

- Source: 465186423b1930777beeb816ee36ac97538e2c21
- Source branch: codex/ax6-core-start-ownership-20261019
- mac80211 r18; inherits949-951 and adds952 startup failure ownership repair.
- Manifest: 346 present / 15 absent.
- Manifest SHA256: 4898858b53b4e715654e3254bd5609cf03ec388706ef50ee67b7586a1320ab47
- Lock SHA256: 2b80d802cd73bf1fe7491147896b29c343773cfdd26c7670d898e04e19a12564
- All other driver/firmware/feed pins and stock device configs unchanged.
- Future workflow invokes the full prepared core ownership fixture, with
  mutations and ASan/UBSan, after DP/SRNG tests. No gate is removed.

GCC16 and Clang ASan/UBSan each pass 768 scenarios / 6016 assertions; old
startup functions fail224 assertions and five cleanup mutants are rejected.
Complete zero-fuzz replay, 14 existing regression groups, source provenance,
package release semantics, actionlint and validator self-tests pass locally.
Neither target compilation nor hardware execution covers this local r18 yet.

Separate frozen cloud run39237618912 succeeded with buildd605724/source60a65bf159
and mac80211 r15. Its actual sysupgrade/recovery/kernel/rootfs/IPK evidence was
downloaded with digest verification and independently inspected. The final
391-package manifest includes six hold installed entries; 143 installed kmod
packages own193 AArch64 modules, mutually consistent vermagic6.18.38. rpcd r6
is OFF in the final rootfs and binds to the target OFF IPKs. This does not
cover local949-952 and is not runtime or maximum-performance proof.

Next gates remain thermal recovery ownership, NSS/CE partial failure and
QMI_FAIL/remove, coldboot policy, DP reset epoch/IRQ-off, durable rpcd recovery
and LuCI integration. Do not present this as a complete system repair.
