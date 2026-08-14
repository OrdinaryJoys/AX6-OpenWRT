# AX6 synchronized throughput and kmod repair status (2026-08-14)

## Scope and identity

This record covers read-only runtime testing and repository-side artifact repair.
No router configuration, NSS/PBUF value, IRQ affinity, service state, or firmware
was changed during these tests.

| Item | Value |
| --- | --- |
| Router | Redmi AX6 (stock layout) |
| Running revision | `r0-956cf06` |
| Kernel | `6.18.38` |
| Build commit represented by running image | `7034c37bfdf3fe575a1bf22334b9ac9f89cb093c` |
| Source commit represented by running image | `956cf06b6c86c10de28670157a9c986a74a91454` |
| Mac endpoint | `192.168.5.190`, `en0`, 1000baseT full duplex |
| Windows endpoint | `192.168.5.111`, iperf3 3.21, AX88179 USB3 |

The newer `r0-14f713a` image was not flashed. Therefore these measurements are a
baseline for the currently running image, not runtime validation of the new PBUF
final-readback and first-boot RPS discovery fixes.

## Synchronized sampler

`ax6-router-sync-sampler.sh` is streamed to the router over SSH and writes only
to the local test result directory. During every bidirectional stage it records:

- PBUF/N2H sysctls and selected NSS N2H/driver/PPE/EDMA counters;
- `/proc/net/softnet_stat` per CPU;
- relevant NSS, EDMA, Wi-Fi and CE IRQ counters and affinities;
- RPS/RFS/XPS queue state and LAN/WAN interface counters;
- aggregate CPU jiffies, NSS clock and NSS RPS state.

The analyzer requires contiguous samples, matching boot IDs and complete metric
groups. PBUF drift, softnet drops, NSS/EDMA active error increments, or interface
error/drop increments fail the synchronized stage.

## LAN-LAN pilot: Mac to Windows

| Scenario | Result |
| --- | --- |
| P1 forward | 948.1 Mbit/s, 0 retransmits |
| P1 reverse | 951.3 Mbit/s, 0 retransmits |
| P1 bidirectional | Mac to Windows 497.7; Windows to Mac 949.1 Mbit/s |
| P4 forward | 950.2 Mbit/s, 140 retransmits |
| P4 reverse | 962.3 Mbit/s, 0 retransmits |
| P4 bidirectional with sampler | Mac to Windows 94.3; Windows to Mac 956.9 Mbit/s |
| P4 bidirectional without sampler | Mac to Windows 319.6; Windows to Mac 959.3 Mbit/s |

Both synchronized bidirectional stages had stable `pbuf_high=32768`, zero
softnet drop/time-squeeze delta, zero NSS/EDMA active error delta, and zero LAN
interface error/drop delta. Router aggregate CPU busy time remained about 17%.
The degraded direction follows Windows receive. Sampling can affect the exact
low-side value, but the no-sampler control remains asymmetric, so the sampler is
not the root cause. This is still an endpoint-limited result until repeated with
a second qualified Linux wired endpoint.

## Router-local to Mac isolation

The Mac temporarily ran an iperf3 server on port 15220. The router was the
iperf3 client, so this is host-terminated traffic and must not be used as an
NSS forwarding benchmark.

| Scenario | Result |
| --- | --- |
| P1 router to Mac | 771.1 Mbit/s, 0 retransmits |
| P4 router to Mac | 932.3 Mbit/s, 0 retransmits |
| P1 bidirectional | router to Mac 710.1; Mac to router 823.2 Mbit/s |
| P4 bidirectional | router to Mac 838.8; Mac to router 931.1 Mbit/s |

P4 bidirectional host traffic reached about 65% aggregate router CPU busy time
and increased softnet `time_squeeze` by 422, but softnet drops, NSS/PBUF/EDMA
errors and interface drops remained unchanged. This is evidence of local Linux
protocol-stack pressure, not evidence of NSS forwarding corruption. The Mac
server was stopped after the test.

## Kmod offline feed defect and repair

Run 31770288192 produced 143 staged kmod IPKs but copied a 166-entry target
`Packages` index. Twenty-three indexed files were absent. This did not alter the
firmware rootfs, and all 23 packages were already installed in that image, but
the offline artifact was not self-contained.

The repaired packager now treats `Packages` `Filename` entries as the exact
allowlist, copies every referenced IPK, rejects unsafe paths or missing files,
requires at least one kmod, verifies indexed/staged counts, checks
`Packages.gz`, and regenerates file and archive SHA256 lists. Positive, missing
file and unsafe-path fixtures pass.

## Validation and remaining gates

- Performance hardening fixtures: 32 passed, 0 failed.
- Offline feed packaging fixture: passed.
- All other local lint test commands passed except compiled-DTB fixture, which
  could not run because local `dtc` is not installed.
- The previous cloud stock-DTB gate passed; the next cloud build must rerun it.
- A new build is still required because run 31770288192 predates the offline
  feed fix and synchronized test tooling.
- Runtime validation of `r0-14f713a` still requires explicit flash approval,
  post-boot PBUF `high=65536` readback, RPS device enumeration, and the same
  synchronized throughput matrix.
