# Local conditional NSS mesh dump candidate

Source: codex/ax6-mesh-dump-lifecycle-20261020 at
4b6e23461ea7da69b2dae5f51215846624fdb6a0, mac80211 r20.
Parent source5152/r19 and its complete 953 repair remain unchanged.

954 initializes the radio's NSS dump lock at object allocation, not each pdev
setup, and moves stale mpath dump entries with list_splice_tail_init. This is
conditional mesh correctness, not a current stock throughput fix; stock keeps
NSS mesh off. It does not close N03/N04 or firmware/callback lifetime.

Local GCC and Clang ASan/UBSan: 120 combinations / 1716 checks, zero failures.
The old code and six compiled negative controls are rejected. All 17 existing
regression groups, including 953, pass on a complete zero-fuzz prepared tree.
Two compiled source files change; mac.c.orig is a separately verified generated
patch backup, not ignored in the full-tree accounting.

The future workflow extracts one nonempty Linux kernel list.h at the exact
kernel-root depth. It must not count tools/include/linux/list.h. A local
five-case selector test rejects tools-only, ambiguous, empty and symlink input.
That test executes the actual find argv and checks the cardinality contract;
it does not emulate Ubuntu Bash mapfile with macOS's Bash 3.2.

The new host test is wired after mac80211/NSS driver preparation. This is not
evidence that the target or future CI has passed. Other driver/feed/FW pins,
stock image settings and runtime tuning are unchanged.

NO-FLASH / NO-RELEASE: local candidate only. No push, new cloud build, main merge,
hardware access, restart/reload/restore or performance switch changes. Existing
cloud r15 does not contain 949-954. Full runtime and performance remain open.
