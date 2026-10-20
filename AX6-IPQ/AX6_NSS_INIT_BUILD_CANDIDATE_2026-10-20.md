# r19 NSS init ownership build candidate

Local candidate only. NO-FLASH / NO-RELEASE; no cloud build dispatched.

- Source: `codex/ax6-nss-registration-ownership-20261020` at
  `5152be47e9e21d678db6aac4b91856ab24a4ffcc`.
- mac80211 r19 adds 953 on top of r18; NSS/SSDK/ECM/FW/feed pins and stock
  configuration stay unchanged. Not an upstream bulk merge or a performance tune.
- New gate runs after both mac80211 and qca-nss-drv prepare, consuming actual
  prepared functions and driver registry/state APIs. Mutations and sanitizers
  remain enabled. No host fixture is presented as module or runtime acceptance.
- GCC16 and Clang ASan/UBSan: 2689 scenario combinations, 270716 assertions,
  zero candidate failures; real old baseline and five mutations fail as expected.
- Full zero-fuzz replay and 16 existing bounded regression groups pass. Only
  `ath11k/nss.c` changes among 2891 mac80211 prepared files; SSDK/ECM unchanged.
- N02 is repaired only for the existing post-registration state rejection
  unwind; N01 metadata/address-zero ownership is corrected. Startup admission
  stays at its original point: the initial eager precheck was rejected by a
  late-readiness positive control and is not in the final candidate.
- N03/N04 firmware shutdown confirmation, command/generation correlation,
  callback draining and parent cleanup contracts remain open. This candidate
  must not be deployed as a fully repaired or highest-performance system.
- Existing cloud r15 run39237618912 does not contain 949-953. It cannot provide
  target build, package or runtime qualification for this local candidate.

The source manifest and semantic lock must match before any later authorized
push/build. Main integration, Release, hardware access and flashing remain out
of scope for this candidate preparation.
