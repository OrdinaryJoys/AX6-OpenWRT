# AX6 upstream update item audit

Date: 2026-07-09

This document expands the previous upstream audit into a per-item review. It is repository-side only: no router flash and no persistent router configuration change was performed.

## References

| Ref | SHA |
| --- | --- |
| `OrdinaryJoys/immortalwrt-nss origin/main` | `56807d9661db` |
| `VIKINGYFY/immortalwrt viking/main` | `0d3ee80549ea` |
| `immortalwrt/immortalwrt official/master` | `4cafb73e88b6` |
| `immortalwrt/immortalwrt official/openwrt-25.12` | `53566decfc6b` |
| `qosmio/openwrt-ipq qosmio/main-nss` | `92a2d104145c` |
| `qosmio/openwrt-ipq qosmio/25.12-nss` | `d6848fa2ea00` |

Current divergence counts:

| Compare | Local side | Upstream side |
| --- | ---: | ---: |
| `origin/main...viking/main` | 99 | 410 |
| `origin/main...official/master` | 545 | 388 |
| `origin/main...official/openwrt-25.12` | 3297 | 873 |
| `origin/main...qosmio/main-nss` | 5649 | 168 |
| `origin/main...qosmio/25.12-nss` | 8109 | 832 |

The new VIKINGYFY range since the previous reviewed ref `b3a261a4ae` contains 75 commits.

## Decision Legend

| Decision | Meaning |
| --- | --- |
| Included | Already isolated in the current source candidate. |
| Build-test | Needs AX6-NSS firmware build validation before merge. |
| Defer | Not needed for AX6 or too broad for the current repair train. |
| Separate branch | Potentially relevant but must be isolated from WiFi/hostapd. |
| Ignore for AX6 | Different platform or no AX6 runtime path. |

## Per-Commit Evaluation

| # | Commit | Update | Scope | AX6/NSS/WiFi impact | Risk | Decision |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `75c21864878` | apm821xx wndr4700 partition merge | `target/linux/apm821xx` | No AX6 target overlap | Low for AX6 | Ignore for AX6 |
| 2 | `a3811bbf4cc` | minimize `kmod-sched-connmark` dependencies | `package/kernel/linux/modules/netsupport.mk` | Could affect package dependency graph if SQM/connmark is selected | Medium | Defer; verify package dependency only if build fails |
| 3 | `f7f75e163b9` | r8152 update to 2.22.1 | USB Ethernet driver | AX6 built-in LAN/WAN path unaffected | Low | Ignore for AX6 |
| 4 | `bf6d2e78ba6` | video module path cleanup | video kmods | No AX6 network/runtime impact | Low | Ignore for AX6 |
| 5 | `2d35c376d8e` | qualcommbe ipq9574 uniphy resets | `target/linux/qualcommbe` | Different target from qualcommax/ipq807x | Low | Ignore for AX6 |
| 6 | `69c55aaaeec` | qualcommbe ipq9574 USXGMII in-band AN | `target/linux/qualcommbe` | Different target; not AX6 SSDK/NSS path | Low | Ignore for AX6 |
| 7 | `da0bafe19a6` | qualcommbe ipq9574 25MHz clock output | `target/linux/qualcommbe` | Different target | Low | Ignore for AX6 |
| 8 | `8a108c529c3` | qualcommbe ipq9574 uniphy reset pulse | `target/linux/qualcommbe` | Different target | Low | Ignore for AX6 |
| 9 | `d9a98ed59de` | qualcommbe ipq9574 MISC2/USXGMII fix | `target/linux/qualcommbe` | Different target | Low | Ignore for AX6 |
| 10 | `c16ef4f318c` | qualcommbe USXGMII bring-up aligned with SSDK | `target/linux/qualcommbe` | SSDK conceptually relevant, but not qualcommax/ipq807x files | Medium if ported blindly | Ignore for AX6; do not cherry-pick |
| 11 | `1d206717c57` | elfutils adds `$(FPIC)` | `package/libs/elfutils` | Host/package build hardening; no runtime driver effect | Low | Defer unless build error references elfutils |
| 12 | `18e11e29a84` | realtek lan_list from DTS | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 13 | `87e02936a4d` | realtek PCS calibration rename | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 14 | `ab49df26438` | realtek PCS debug selection | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 15 | `27d6b62fdaa` | realtek PCS DCVS setter fix | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 16 | `4fc1dea1295` | realtek PCS DCVS cleanup | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 17 | `cfa212ad793` | realtek PCS DCVS helper use | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 18 | `8d6a9e10d28` | realtek PCS LEQ cleanup | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 19 | `75de4464fae` | realtek PCS VTH cleanup | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 20 | `89f145112b3` | realtek PCS TAP cleanup | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 21 | `eb857ca10ef` | realtek PCS VTH/TAP helper use | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 22 | `b1cb70feb0b` | realtek PCS calibration context | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 23 | `c56a15b149d` | realtek PCS delay replacement | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 24 | `ba2467954e9` | realtek PCS calibration cleanup | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 25 | `4d75424ae29` | realtek PCS device loop | `target/linux/realtek` | Different target | Low | Ignore for AX6 |
| 26 | `f03899aef44` | add Ubiquiti USW Pro XG 8 PoE | `target/linux/realtek` | New board support only | Low | Ignore for AX6 |
| 27 | `aba2818b7c3` | add Hasivo S1300WP board | `target/linux/realtek` | New board support only | Low | Ignore for AX6 |
| 28 | `1006c536b50` | ramips GPIO driver moved to files | `target/linux/ramips` | Different target | Low | Ignore for AX6 |
| 29 | `07eec850d8b` | ramips GPIO uses `module_platform_driver` | `target/linux/ramips` | Different target | Low | Ignore for AX6 |
| 30 | `56c5ab49fea` | ramips GPIO uses fwnode | `target/linux/ramips` | Different target | Low | Ignore for AX6 |
| 31 | `ba56736dd11` | apm821xx bootwrapper patch removed | `target/linux/apm821xx` | Different target | Low | Ignore for AX6 |
| 32 | `05e87cfcb6b` | WiFi only advertises GCMP-256 when driver supports it | `wifi-scripts` `ap.uc/hostapd.uc/iface.uc` | Direct WiFi compatibility improvement; avoids advertising unsupported cipher | Medium | Included in `wifi-scripts-v2-candidate` |
| 33 | `fc652db52a2` | default SAE-EXT-KEY per WPA3 mode | `wifi-scripts` schema/iface | Direct WPA3/transition behavior; must avoid old-client breakage | Medium | Included with official final-state conflict resolution |
| 34 | `5e067465ff0` | add `gcmp256` option and default | `wifi-scripts` schema/iface | Direct WPA3 cipher behavior; dangerous if broad default remains | Medium | Included only with later narrowing logic |
| 35 | `0cdf956ee1f` | EAP phase2 authentication method fix | `wifi-scripts` supplicant | EAP client generation fix; low AX6 AP risk | Low | Included |
| 36 | `7be144ad83e` | EAP certificate constraint handling | `wifi-scripts` schema/supplicant | EAP client generation fix; low AX6 AP risk | Low | Included |
| 37 | `649b42331c8` | restore `priv_key` aliases | `wifi-scripts` schema | Compatibility alias; low runtime risk | Low | Included |
| 38 | `5b6bc962bd1` | kernel 6.18.37 to 6.18.38 | generic kernel version and patch refresh | Broad kernel ABI/patch-stack change; NSS/mac80211 patches require full rebuild | High | Separate kernel branch only |
| 39 | `24ab1e83d05` | ath12k calibration variant from DTS | `package/kernel/mac80211/patches/ath12k`, generic binding | AX6 uses ath11k, not ath12k; no direct current device effect | Medium if patch stack changes | Defer; only with mac80211 patch-stack branch |
| 40 | `9055f4ebe80` | apm821xx disables RTC | `target/linux/apm821xx` | Different target | Low | Ignore for AX6 |
| 41 | `6e5b0f352c3` | ramips SPI driver moved to files | `target/linux/ramips` | Different target | Low | Ignore for AX6 |
| 42 | `348fe4f652f` | bcm27xx 6.18 RPi patches | `target/linux/bcm27xx` | Different target; large patch import | Low for AX6 | Ignore for AX6 |
| 43 | `41ab1ae6107` | bcm27xx patch refresh | `target/linux/bcm27xx` | Different target | Low | Ignore for AX6 |
| 44 | `2c03d933d5b` | bcm27xx 6.18 configs | `target/linux/bcm27xx` | Different target | Low | Ignore for AX6 |
| 45 | `fafc2e5925e` | bcm27xx default configs and generic config | bcm27xx plus `target/linux/generic/config-6.18` | Generic config touched; verify kernel config drift before kernel branch | Medium | Defer with kernel branch |
| 46 | `53b070fc8c0` | bcm27xx config update | `target/linux/bcm27xx` | Different target | Low | Ignore for AX6 |
| 47 | `cedb7bbfe3d` | bcm27xx device definitions | `target/linux/bcm27xx` | Different target | Low | Ignore for AX6 |
| 48 | `a085410bc0d` | bcm27xx RP1/media modules | `target/linux/bcm27xx` | Different target | Low | Ignore for AX6 |
| 49 | `11de7145c95` | i2c-designware disable core on 32-bit bcm27xx | `package/kernel/linux/modules/i2c.mk` | Package module dependency touch; no AX6 core network effect | Low | Defer unless build dependency issue |
| 50 | `c73408035d7` | bcm27xx enables 6.18 testing kernel | `target/linux/bcm27xx` | Different target | Low | Ignore for AX6 |
| 51 | `5b01351ad6c` | bcm27xx GPU firmware exclusion | `target/linux/bcm27xx` | Different target | Low | Ignore for AX6 |
| 52 | `2935c748f7e` | bcm27xx GPU firmware dependency | `package/kernel/bcm27xx-gpu-fw` | Different target | Low | Ignore for AX6 |
| 53 | `a296a5adf7a` | bcm27xx-utils update | `package/utils/bcm27xx-utils` | Different target utility | Low | Ignore for AX6 |
| 54 | `fa65dfa9d58` | bcm27xx GPU firmware update | bcm27xx firmware | Different target | Low | Ignore for AX6 |
| 55 | `7c69452c6a9` | ARM64 BRBE and THP Kconfig options | `config/Config-kernel.in` | Generic kernel config menu; could affect defconfig if symbols selected | Medium | Defer with kernel branch |
| 56 | `4b2e7031b22` | feeds update no longer refreshes `.config` | `scripts/feeds` | Build system behavior; could improve reproducibility but changes workflow assumptions | Medium | Separate build-system validation |
| 57 | `37fad8b07e8` | ixp4xx microcode snprintf | firmware source | No AX6 target overlap | Low | Ignore for AX6 |
| 58 | `8bbaad10e0e` | git-src override for host builds | `include/host-build.mk`, `include/package.mk`, `include/unpack.mk` | Build system feature; may affect package source override behavior | Medium | Defer; build-system branch only |
| 59 | `7987b1f799b` | ucode compiler fixes | `package/utils/ucode/patches` | Relevant to wifi-scripts runtime language; can affect LuCI/wifi ucode reliability | Medium | Separate userspace-plumbing branch after WiFi candidate build |
| 60 | `273b186ac34` | ath12k wideband regulatory range fix | `mac80211` ath12k patch | AX6 uses ath11k; no direct current radio path | Medium if patch-stack refresh required | Defer with mac80211 patch-stack branch |
| 61 | `b8a70a15396` | ramips I2C driver moved to files | `target/linux/ramips` | Different target | Low | Ignore for AX6 |
| 62 | `f2851263c7b` | mvebu wt61p803 drivers moved to files | `target/linux/mvebu` | Different target | Low | Ignore for AX6 |
| 63 | `72f6415ef7a` | mvebu LED driver fwnode | `target/linux/mvebu` | Different target | Low | Ignore for AX6 |
| 64 | `c2a758b16a0` | apm821xx enable PM | `target/linux/apm821xx` | Different target | Low | Ignore for AX6 |
| 65 | `2fb1afa7615` | libubox update to 2026-07-08 HEAD | `package/libs/libubox` | Core userspace library; can affect ubus/procd/LuCI indirectly | Medium-high | Separate userspace-plumbing branch |
| 66 | `c5854d65f28` | netifd update to 2026-07-08 HEAD | `package/network/config/netifd` | Direct network manager; can affect DHCP, WiFi reload, VLAN/interface state | High | Separate netifd validation branch |
| 67 | `79d2cf88201` | udebug update | `package/libs/udebug` | Diagnostics library; low direct runtime risk | Low-medium | Defer unless dependency requires it |
| 68 | `bfa2d2f7c6e` | multiplexer menuconfig fix | `package/kernel/linux/modules/multiplexer.mk` | No AX6 core network effect | Low | Ignore for current flow |
| 69 | `b13e9be1a17` | apm821xx PCI quirk config | `target/linux/apm821xx` | Different target | Low | Ignore for AX6 |
| 70 | `bc42f9759ff` | qoriq libdeflate gzip | `target/linux/qoriq` | Different target | Low | Ignore for AX6 |
| 71 | `0cce5275b64` | treewide DTS range syntax conversion | lantiq/mpc85xx/mvebu/ramips/siflower DTS | No qualcommax AX6 DTS touched | Low for AX6 | Ignore for AX6 |
| 72 | `b519bc3b765` | add Ubiquiti USW Pro Max 24 PoE | `target/linux/realtek` | New board support only | Low | Ignore for AX6 |
| 73 | `4cafb73e88b` | Merge Official Source | merge commit | Brings official master batch into VIKINGYFY | Broad | Use constituent commits above, not merge directly |
| 74 | `2994a8cd637` | Merge branch `master` | merge commit | Consolidates official changes into VIKINGYFY | Broad | Do not cherry-pick merge commit |
| 75 | `0d3ee80549e` | refresh patches | ath11k/ath12k/iwinfo patch refresh | Touches WiFi driver and iwinfo patch contexts; ath11k regulatory patch context is directly near AX6 radio stack | Medium-high | Separate mac80211/iwinfo refresh branch only |

## High-Signal Findings

### Already Safe-Isolated

The WiFi v2 items `05e87cfcb6b`, `fc652db52a2`, `5e067465ff0`, `0cdf956ee1f`, `7be144ad83e`, and `649b42331c8` were isolated into:

- `OrdinaryJoys/immortalwrt-nss:codex/ax6-b3a261a-wifi-scripts-v2-candidate`
- `OrdinaryJoys/immortalwrt-nss:codex/ax6-b3a261a-hostapd-wifi-v2-candidate`

Conflict resolution preserved the official final behavior:

- `parse_encryption(config, dev_config, phy_features)` receives driver capabilities.
- `GCMP-256` is advertised only when `config.gcmp256` is true and `phy_features.cipher_gcmp256` is present.
- Default `gcmp256` and `sae_ext_key` stay limited to `sae-compat` BSSes using EHT htmode.

### Must Not Mix With Current WiFi Candidate

The following require separate branches:

| Group | Items | Reason |
| --- | --- | --- |
| Kernel branch | `5b6bc962bd1`, `7c69452c6a9`, `fafc2e5925e` | Kernel version/config drift requires NSS/mac80211 patch-stack rebuild. |
| mac80211/iwinfo refresh | `24ab1e83d05`, `273b186ac34`, `0d3ee80549e` | Patch context is near WiFi driver/regulatory behavior; even ath12k-only commits can shift shared patch-stack order. |
| userspace network plumbing | `2fb1afa7615`, `c5854d65f28`, `7987b1f799b`, `79d2cf88201` | libubox/netifd/ucode can affect ubus, netifd reload, WiFi generation, VLAN/DHCP and LuCI behavior. |
| build-system behavior | `4b2e7031b22`, `8bbaad10e0e` | Changes source/feed/package build assumptions; should be tested without driver changes. |

### Not Current AX6 Fixes

No new item in `b3a261a4ae..viking/main` changes:

- `package/qca-nss`
- `target/linux/qualcommax`
- AX6 DTS files
- AX6 stock layout files
- OpenClash DNS behavior
- ZeroTier or UPnP configuration
- ECM `disable_offloads` runtime guard

Therefore, the current update range does not directly fix the previously tracked OpenClash DNS single-point issue, ZeroTier behavior, or NSS/ECM runtime guardrails.

## Recommended Next Order

1. Finish AX6-NSS stock build validation for `codex/ax6-b3a261a-hostapd-wifi-v2-candidate`.
2. If that build passes, inspect firmware contents and rootfs size before any router-side action.
3. Create a separate `mac80211-iwinfo-refresh-candidate` from `origin/main` for `24ab1e83d05`, `273b186ac34`, and `0d3ee80549e`.
4. Create a separate `userspace-plumbing-candidate` for `ucode/libubox/netifd/udebug`, but only after WiFi candidate build is clean.
5. Defer kernel 6.18.38 until the NSS/mac80211 patch-stack can be rebuilt and validated as one isolated kernel candidate.

