# AX6 full validation without merge

Date: 2026-07-09

User requirement: perform complete validation and do not merge.

No merge into `main` was performed. No router flash and no persistent router configuration change was performed.

## Repositories Checked

| Repository | Branch during validation | Status |
| --- | --- | --- |
| `OrdinaryJoys/immortalwrt-nss` | `codex/ax6-ath12k-mac80211-candidate` | Clean |
| `OrdinaryJoys/AX6-OpenWRT` | `codex/ax6-b3a261a-upstream-audit` | Clean before this report |

## Source Candidate: hostapd + WiFi v2

Ref:

- `OrdinaryJoys/immortalwrt-nss:origin/codex/ax6-b3a261a-hostapd-wifi-v2-candidate`
- Head: `a706a46e462c9f22ce29dc4076d2913c9c1b6452`

Validation performed:

| Check | Result |
| --- | --- |
| `git diff --check origin/main...origin/codex/ax6-b3a261a-hostapd-wifi-v2-candidate` | PASS |
| Changed-file scope | PASS: limited to `wifi-scripts` and `hostapd` |
| Dangerous path scan | PASS: no `package/qca-nss`, `target/linux/qualcommax`, `ecm`, `qca8k`, `qca-ssdk`, OpenClash, ZeroTier, UPnP, firewall, dnsmasq, odhcpd, kernel version files |
| Rejected patch resurrection scan | PASS: no `950-ath11k-add-6ghz-lpi-rule-to-world-regd.patch` or `200-fix-txpwrlist-6ghz-split-wiphy.patch` |
| GCMP-256 logic | PASS: still requires `config.gcmp256 && phy_features?.cipher_gcmp256` |
| Antenna-change merge logic | PASS: keeps upstream `antenna_changed` guard and local silent `iw ... >/dev/null 2>&1` behavior |

Included commit series:

- hostapd security advisory 2026-1
- VIKINGYFY WiFi batch 1
- official WiFi v2 EAP/WPA3/GCMP-256/SAE-EXT-KEY compatibility fixes

Not included:

- `0d3ee80549e refresh patches`
- kernel 6.18.38
- netifd/libubox/ucode updates
- NSS runtime script changes
- qca8k/generic migration
- AX6 stock DTS/nvmem changes

## Source Candidate: ath12k mac80211

Ref:

- `OrdinaryJoys/immortalwrt-nss:origin/codex/ax6-ath12k-mac80211-candidate`
- Head: `c6c608a57a0`

Validation performed:

| Check | Result |
| --- | --- |
| `git diff --check origin/main...origin/codex/ax6-ath12k-mac80211-candidate` | PASS |
| Changed-file scope | PASS: only two ath12k patches and one generic DT binding patch |
| Dangerous path scan | PASS: no NSS/ECM/qualcommax/qca8k/netifd/libubox/ucode/kernel-version/OpenClash/ZeroTier/UPnP/firewall changes |
| Rejected patch resurrection scan | PASS: no deleted ath11k 950 or iwinfo 200 patch restored |
| `ath12k_core_check_dt` occurrence in patch | PASS: one added function body and one call |

Included commits:

- `24ab1e83d05 mac80211: read calibration variant from device tree`
- `273b186ac34 mac80211: ath12k: fix regulatory range for wideband radios`

Risk note:

- AX6 uses ath11k, not ath12k. This candidate is not a direct fix for AX6 runtime WiFi behavior.
- It still touches the shared mac80211 patch stack, so it needs build validation before any later merge decision.

## Rejected Update: `0d3ee80549e refresh patches`

Status: rejected for current candidates.

Reasons:

- It tries to modify `package/kernel/mac80211/patches/ath11k/950-ath11k-add-6ghz-lpi-rule-to-world-regd.patch`, which is deleted in current `origin/main`.
- It tries to modify `package/network/utils/iwinfo/patches/200-fix-txpwrlist-6ghz-split-wiphy.patch`, which is deleted in current `origin/main`.
- Applying it directly would resurrect removed ath11k/iwinfo patches.
- Its refreshed `ath12k/700` context was unsafe during cherry-pick validation and must not be carried blindly.

Decision:

- Do not merge or build-test `0d3ee80549e` in its current form.
- Revisit only through a dedicated patch-stack rebase after proving why the deleted patches should or should not return.

## AX6 Build-Test Branch Validation

Ref:

- `OrdinaryJoys/AX6-OpenWRT:codex/ax6-hostapd-wifi-v2-build-test`

Positive checks:

| Check | Result |
| --- | --- |
| Lock points to source candidate SHA `a706a46e462c9f22ce29dc4076d2913c9c1b6452` | PASS |
| Source candidate SHA matches `immortalwrt-nss` remote candidate HEAD | PASS |
| Lock-file branch boundary simulation for `codex/ax6-*` | PASS |
| `actionlint` on related workflows | PASS |
| `yamllint -d relaxed` on related workflows | PASS |
| `sh tests/test-vlan-add.sh` | PASS |
| `sh tests/test-openclash-archive.sh` | PASS |
| `shellcheck -S error` on AX6-IPQ and workflow scripts | PASS |

Validation issue:

| Issue | Impact | Required action |
| --- | --- | --- |
| `codex/ax6-hostapd-wifi-v2-build-test` is not a pure two-file lock test branch relative to `main`; it also contains documentation files from the audit branch | Does not change firmware content, but makes the build-test branch less clean and caused `git diff --check main...branch` to report an EOF blank-line warning in an audit doc | Recreate or clean a new build-test branch from `main` containing only `.github/ax6-nss-lock.env` and `.github/workflows/lint.yml` before cloud build |

## No-Merge Conclusion

Current safe state:

- Source candidates remain isolated.
- No candidate has been merged into `main`.
- No router-side changes were made.

Before any merge decision:

1. Recreate a pure AX6 build-test branch from `main` for `hostapd + WiFi v2`.
2. Trigger AX6-NSS `stock` workflow on that branch.
3. Inspect firmware contents, rootfs size, kernel modules, OpenClash plugin/core state, NSS blacklist, and BUILD-LOCK.
4. Only then decide whether to promote the source candidate.

