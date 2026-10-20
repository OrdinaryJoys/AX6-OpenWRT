# rpcd019 / r7 candidate (local only)

Source 604a90934b636a33e587270c974f6144ff542a53 adds strict checked-journal
input validation without changing its writer, storage policy, upstream pin or
checked=OFF default. mac80211 r20 and all NSS/SSDK/ECM/DP pins remain unchanged.
No hardware operations, push, cloud build, merge or Release are authorized here.

The complete parser is exercised against host files: GCC16 and Clang ASan/UBSan
each pass 354 scenarios / 1830 assertions. The actual r6 loader fails 224
assertions, and six compilable wrong implementations are rejected. Twelve
AArch64-musl ON/OFF translation-unit syntax checks are not an SDK build/link or
runtime qualification. Eighteen prior driver regression groups pass again on
fresh prepared sources; mac80211/SSDK/ECM prepared trees remain byte-identical.

Build gates now check SSDK and rpcd releases against their recipes and require
rpcd provenance to match the release and checked=OFF. Duplicate release lock
keys and duplicate provenance JSON keys are rejected rather than last-wins.
The workflow previously omitted these two releases from environment export and
BUILD-LOCK output; both are added. The older semantic fixture is updated with
valid SSDK/rpcd inputs so unrelated failures cannot make its negative tests pass.

The future ON component phase runs the parser host suite only after the prepared
source hash check. ON-clean-OFF target compilation and final OFF artifact checks
remain intact. These changes have local tests only; no new r7 firmware exists.

NSS stop/ACK/instance correlation, callback draining and real DMA quiescence are
still one joint OPEN contract, not solved by returning errors or freeing early.
Persistent recovery, directory durability, authorized recovery, reboot/power
loss, flash wear, LuCI, DP stats/IRQ-off and real performance remain unverified.
