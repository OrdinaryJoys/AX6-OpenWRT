# rpcd021 / r9 local quality-review candidate

Source 05b791d81c3c5e453ee178912a7d70d98801492c repairs a verified r8
temporary-file ownership flaw. Actual old symlink/hardlink tests changed
unrelated host files while returning success. O_CREAT/O_EXCL with NOFOLLOW and
CLOEXEC now rejects any pre-existing temporary without deleting or truncating it.

GCC16 and Clang ASan/UBSan each pass 60 scenarios / 570 assertions; actual r8
fails123 checks, four compiled wrong variants are rejected, and normal behavior
signatures agree. r7 parser and r8 initialization are freshly regression-tested
on final r9 input. Eighteen unchanged driver groups are retained by hashes,
not reported as rerun. Twelve AArch64-musl syntax checks are not an SDK build.

The future ON component gate runs publication tests after prepared-source hash
binding. Original ON-clean-OFF and final OFF artifact checks remain unchanged.
No new cloud run is sent and no r9 firmware or real runtime is qualified.

Crash residue intentionally blocks checked writes pending authorized recovery;
it is not automatically deleted. Path races, directory anchoring/durability,
snapshot persistence, recover authorization, flash/power loss and frontend are
still OPEN. Checked defaults OFF. NSS/Wi-Fi/SSDK/ECM/DP/FW/feed pins and performance
settings do not change. No push, device access, flash, main merge or Release.
