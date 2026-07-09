# AX6 mac80211 / iwinfo candidate audit

Date: 2026-07-09

This audit follows `UPSTREAM-UPDATE-ITEM-AUDIT-2026-07-09.md` and tests the next isolated update group after the hostapd + WiFi v2 candidate.

No router flash and no persistent router configuration change was performed.

## Source Candidate

Created and pushed:

- `OrdinaryJoys/immortalwrt-nss:codex/ax6-ath12k-mac80211-candidate`
- Head: `c6c608a57a0`
- Base: `origin/main@56807d9661d`

Included commits:

| Commit | Title | Result |
| --- | --- | --- |
| `24ab1e83d05` | `mac80211: read calibration variant from device tree` | Clean cherry-pick |
| `273b186ac34` | `mac80211: ath12k: fix regulatory range for wideband radios` | Clean cherry-pick; Git emitted an inexact rename warning due repository size, but no conflict |

Changed files:

- `package/kernel/mac80211/patches/ath12k/104-wifi-ath12k-fix-regulatory-range-for-wideband-radios.patch`
- `package/kernel/mac80211/patches/ath12k/700-ath12k-read-calibration-variant-from-dt.patch`
- `target/linux/generic/pending-6.18/796-dt-bindings-wireless-ath12k-drop-qcom-ath12k-cali.patch`

Static validation:

- `git diff --check origin/main...HEAD` passed.
- No `package/qca-nss`, `target/linux/qualcommax`, AX6 DTS, ECM, OpenClash, ZeroTier, UPnP, firewall, or WiFi AP configuration files were changed.

AX6 impact:

- AX6 uses ath11k, not ath12k, so these commits are not direct fixes for the AX6 WiFi runtime issue set.
- They still touch the shared `mac80211` patch stack and therefore require source build validation before any merge.

## Rejected Item: `0d3ee80549e refresh patches`

Attempted but not included.

Conflict result:

- `package/kernel/mac80211/patches/ath11k/950-ath11k-add-6ghz-lpi-rule-to-world-regd.patch`
  - Deleted in current `origin/main`
  - Modified in VIKINGYFY `0d3ee80549e`
  - Accepting it would resurrect a removed ath11k regulatory patch.
- `package/network/utils/iwinfo/patches/200-fix-txpwrlist-6ghz-split-wiphy.patch`
  - Deleted in current `origin/main`
  - Modified in VIKINGYFY `0d3ee80549e`
  - Accepting it would resurrect a removed iwinfo patch.
- `package/kernel/mac80211/patches/ath12k/700-ath12k-read-calibration-variant-from-dt.patch`
  - The VIKINGYFY refreshed form shows patch context after `ath12k_core_check_dt()` and then adds another `ath12k_core_check_dt()` body.
  - This indicates the refresh is not safe against this repository baseline without deeper patch-stack rebasing.

Decision:

- Do not include `0d3ee80549e` in any build candidate.
- Do not resurrect deleted ath11k/iwinfo patches.
- Revisit only if upstream provides a corrected refresh or if a dedicated branch rebases the complete mac80211/iwinfo stack and proves it with a source build.

## Next Step

This branch is lower priority than the already prepared hostapd + WiFi v2 candidate because it does not directly touch AX6 ath11k runtime behavior. The recommended next validation remains:

1. Build-test `codex/ax6-b3a261a-hostapd-wifi-v2-candidate` through the AX6-NSS workflow.
2. Only after that, optionally create an AX6 build-test branch for `codex/ax6-ath12k-mac80211-candidate`.
3. Keep kernel 6.18.38, netifd/libubox/ucode, and NSS runtime scripts separate.

