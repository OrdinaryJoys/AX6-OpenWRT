# AX6 Core Flow Build Candidate

This branch starts at c8603ccf3ab20cd7fd01684e20179ec5fc1510e8. The source
candidate is `codex/ax6-core-flow-repair-20261017`, pinned exactly in the
build lock. It is not the firmware from run 38875930912 and has not passed
new target compilation or full firmware acceptance.

## Boot Guard

Preserve the existing NSS-owned values only: global packet_steering=0,
firewall flow_offloading/flow_offloading_hw=0, ECM disable_offloads=1,
disable_gro_list=1, offload_host_ifaces=br-lan and physical policy=report.
No Wi-Fi, VLAN, ZeroTier, subscription/overwrite, Geo or performance tuning.

Each start has fresh local status. Read/parse the package and required
section before changes. Resolve anonymous defaults through the actual UCI
section snapshot. Absent optional settings migrate; failed reads do not.
Check write/delete, staged values, commit, cleared delta and committed values.
Continue independent packages but return the first failure. Success logs
require successful commit/readback, and logger failures cannot determine
the configuration result.

Pending UCI edits are refused rather than accidentally committed. A failed
package may retain this invocation's partial staged edits; it is explicitly
reported and not committed as success. Do not perform a whole-package
rollback, reload, restart or recursive retry. Concurrent UCI writers are not
a transaction implemented by this boot service. Returning nonzero also does
not itself prevent every later init service from starting: complete boot
dependency/fail-closed policy is still a separate reviewed contract.

## Late Network Policy

Preserve the first error from IPv4 invariants while still attempting the
independent offload policy. Isolate the sourced policy in a child shell,
so source-time globals, missing functions and fatal syntax/dot failures
cannot overwrite the earlier result or terminate its caller silently.

The sysctl helper now checks read/write/readback for live interfaces;
loopback and disappeared interfaces remain excluded. It neither restarts
networking nor changes the invariant values.

## Validation and Remaining Gates

- Stateful host fault fixtures, including stale reads, ignored writes,
  commit corruption, pending edits, two failures, helper syntax, and repeats.
- Actual firmware BusyBox ash and UCI in an offline, no-network/no-disk/
  no-share Linux guest; private config and delta directories only.
- Native prepared driver statement/function regressions are wired into the
  existing NSS workflow; their evidence is uploaded separately even on failure.
- Kernel/QSDK/source trains and existing DP/DRV containment remain unchanged.

Still required: publish the explicitly reviewed candidate branches only when
authorized; Lint; SSDK/ath11k and ECM IGS ON/OFF target component builds;
complete stock image and independent module/rootfs/DTB/FIT/UBI/manifest/hash
acceptance. Other profiles need separate builds. C03 Wi-Fi remove, generic
NSS lifecycle, XGMAC combined diagnostics, restore apply, W04/coalesce/drop,
Web/DNS/ZT and throughput/performance remain open according to their own
evidence. No claim of zero faults or maximum performance follows from tests.

No router action, main merge, Release or automatic build dispatch was done.
