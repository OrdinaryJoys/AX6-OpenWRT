# P2 Upstream Audit: VIKINGYFY `0bad892`

Date: 2026-07-04

Branch: `codex/ax6-p2-upstream-0bad-audit`

Base: `origin/main@fc7e3b6dfdb1847e108a12003132b34fc4ff35ca`

This branch is intentionally separate from PR #2 (`codex/ax6-remove-unused-proxy-cores`). Do not mix the package cleanup and rootfs guard work with NSS/WiFi/remoteproc upstream integration.

## Compared Upstream State

| Repository | Ref | Result |
|---|---|---|
| `VIKINGYFY/immortalwrt` | `main=0bad892975fe49fd180f99b414a7f168bb694dd7` | New remote state checked on 2026-07-04 |
| Previous recorded VIKINGYFY ref | `1d9b6b4dfa72e863600d50a71699d365065c8bf4` | Compare result is `diverged`, ahead 2 / behind 1 |
| `qosmio/openwrt-ipq` | `main-nss=92a2d104145c8d265851c4b388a41bd8e9c21cd9` | No new main-nss movement in this check |

The VIKINGYFY range contains two commits:

| Commit | Subject | Initial classification |
|---|---|---|
| `3d8336d34fa9` | `refresh patches` | Real patch-stack change; requires P2 static and build validation |
| `0bad892975fe` | `update wifi-scripts` | Listed as modified by GitHub compare, but blob SHA cross-check shows no file-content change |

## Actual Change Groups

| Group | Paths | Risk | Current action |
|---|---|---|---|
| mac80211 / ath11k NSS patch refresh | `package/kernel/mac80211/patches/build/*`, `package/kernel/mac80211/patches/nss/ath11k/*`, `package/kernel/mac80211/patches/nss/subsys/*` | High: touches WiFi NSS, mesh/offload patch context, IOMMU compatibility patches | Do not merge directly; create a source-tree candidate and compile first |
| qualcommax remoteproc / MDT loader | `target/linux/qualcommax/patches-6.18/0805-*`, `0812-*` | High: touches WCSS/MPD firmware load path and driver API compatibility | Must be isolated from WiFi/NSS package refresh and validated by boot logs |
| wifi-scripts | `package/network/config/wifi-scripts/files-ucode/*` | No current content change | Do not treat as a P2e candidate unless a later upstream diff changes blob content |

## wifi-scripts Cross-Check

The following files were listed by GitHub as modified in `0bad892...`, but old and new blob SHA are identical:

| File | Blob result |
|---|---|
| `lib/netifd/wireless/mac80211.sh` | same |
| `usr/share/ucode/wifi/ap.uc` | same |
| `usr/share/ucode/wifi/common.uc` | same |
| `usr/share/ucode/wifi/hostapd.uc` | same |
| `usr/share/ucode/wifi/iface.uc` | same |
| `usr/share/ucode/wifi/netifd.uc` | same |
| `usr/share/ucode/wifi/supplicant.uc` | same |
| `usr/share/ucode/wifi/validate.uc` | same |

Conclusion: there is no actionable wifi-scripts content change in this upstream range.

## Patch-Level Notes

### IOMMU patch changes

VIKINGYFY removes:

- `package/kernel/mac80211/patches/build/150-ath_iommu_paging_domain_revert.patch`
- `package/kernel/mac80211/patches/nss/ath11k/999-921-ath11k-use-iommu_paging_domain_alloc-on-6.18.patch`

These removals are not safe to port blindly. They need comparison against the locked build source `OrdinaryJoys/immortalwrt-nss@8a22411dc1d0e50ba52bc015ba5ef193ee3bd7b4` to confirm whether the current tree already carries equivalent Linux 6.18 IOMMU handling.

### mac80211 NSS refresh

Most `patches/nss/subsys/*` hunks shown by compare are context/line-number refreshes against a moved mac80211 base. They still touch sensitive areas:

- `ieee80211_ops`
- station RX stats and rate reporting
- AP VLAN / dynamic VLAN NSS offload hooks
- mesh NSS offload hooks
- TIM / queue skb offload behavior

Even if many hunks are context-only, they cannot be merged as a documentation-only update because patch application order and mac80211 base drift can change final generated code.

### remoteproc / MDT loader

Two qualcommax patches change:

- `.remove_new` to `.remove` in the q6 WCSS driver patch.
- `qcom_mdt_load*()` internal argument ordering and PD segment loading helper behavior.

These are compile and boot sensitive. Validation must include:

- Kernel build success.
- NSS firmware and WCSS boot log review.
- `dmesg | grep -Ei 'remoteproc|q6|wcss|mdt|nss|ath11k'`.
- `nss-check -v` after boot, if a test image is ever manually installed.

## Required Validation Order

1. Static compare against `OrdinaryJoys/immortalwrt-nss@8a22411dc1d0e50ba52bc015ba5ef193ee3bd7b4`.
2. Build a source candidate for mac80211/ath11k NSS refresh only.
3. Build a separate source candidate for qualcommax remoteproc/MDT loader only.
4. For each candidate, update AX6 build lock only in a matching validation branch.
5. Run lint and stock build first; expand build only after stock rootfs and kernel logs are structurally clean.
6. Do not flash or persistently modify a router without explicit user confirmation.

## Current Decision

Do not merge VIKINGYFY `0bad892...` wholesale.

The only valid next work is isolated candidate construction:

- P2-NSS-WiFi-refresh candidate for mac80211/ath11k NSS patch-stack drift.
- P2-remoteproc-MDT candidate for qualcommax WCSS/MPD loader changes.

Keep PR #2 independent.
