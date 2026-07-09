# AX6 upstream audit: VIKINGYFY b3a261a

Date: 2026-07-09

Scope:

- Source repo: `OrdinaryJoys/immortalwrt-nss`
- Build repo: `OrdinaryJoys/AX6-OpenWRT`
- Upstream refs checked:
  - `VIKINGYFY/immortalwrt` at `b3a261a4ae`
  - `qosmio/openwrt-ipq` at `1ff39f9e98`
  - local source baseline at `56807d9661`
  - local build baseline at `099556a`

## Router runtime verification

Real router checks were read-only. No firmware flashing and no persistent OpenClash setting changes were made.

Current router image:

- Model: Redmi AX6 stock layout
- Target: `qualcommax/ipq807x`
- Kernel: `6.18.35`
- Firmware revision: `r0-56807d9`
- Overlay: 41.1 MiB total, 25.8 MiB used, 13.2 MiB free, 66 percent used
- Swap: ZRAM 256 MiB, 0 used

NSS/WiFi/ECM status:

- `nss-check -v`: PASS=40, WARN=4, FAIL=0
- NSS cores booted: 2
- NSS clock auto scaling disabled: locked at max
- ath11k loaded, board file loaded, `fw_mem_mode=1`
- ath11k `frame_mode=2`, `nss_offload=1`, `crypto_mode=0`
- ECM `disable_offloads=1`, `disable_gro_list=1`, `disable_flow_control=0`
- firewall UCI flow offload disabled
- conflicting flow-offload kernel modules not loaded
- br-lan checksum/GRO/GSO/TSO offloads disabled
- physical port offloads still enabled, which matches current `nss-check` policy because only bridge/offload handoff needs guarding
- VLAN path reports `qca_nss_vlan` ready, bridge VLAN filtering is not enabled

Short-window link validation:

- br-lan, wan, lan1, lan2 showed no RX/TX error growth
- 10 second counter window showed no dropped growth on br-lan/wan/lan1/lan2
- router-to-`223.5.5.5` ping: 20 sent, 20 received, 0 percent loss, avg 8.546 ms

## OpenClash DNS single-point validation

Do not disable these OpenClash auto-updates as part of this audit:

- `geoip_auto_update=1`
- `geosite_auto_update=1`
- `geoasn_auto_update=1`
- `chnr_auto_update=1`

Observed runtime DNS path:

- OpenClash is enabled and running in `fake-ip` mode.
- OpenClash custom DNS and redirect DNS are enabled.
- OpenClash DNS port is `7874`.
- Generated dnsmasq runtime config contains:
  - `no-resolv`
  - `server=127.0.0.1#7874`
  - `conf-dir=/tmp/dnsmasq.cfg01411c.d`
- dnsmasq listens on LAN DNS addresses and forwards to local Clash DNS.
- nft DNS redirect rules are active for OpenClash/dnsmasq DNS hijack.

Conclusion:

- The DNS single-point dependency is verified in runtime: LAN DNS depends on local Clash DNS port `7874`.
- Current DNS queries through `127.0.0.1` are fast in the sampled window, so this is a resilience risk rather than a constant failure.
- If Clash DNS stalls during core restart, rule reload, Geo database update, or overlay pressure, dnsmasq has no effective runtime upstream fallback because `no-resolv` is generated.
- Direct upstream DNS reachability is not uniform: `119.29.29.29` and `223.5.5.5` responded, while `8.8.8.8:53` timed out from the router. A fallback design must not assume 8.8.8.8 is usable.

Boundary:

- Do not modify subscription files or OpenClash overwrite files for this issue.
- Do not disable Geo/GeoSite/GeoASN/CHNR auto updates in the repository defaults.
- Candidate fix direction should be a generated-runtime or service-order resilience design, not a subscription-content edit.

## Upstream delta summary

`origin/main...viking/main` from the source repository currently contains 99 local-side commits and 335 VIKINGYFY-side commits.

Relevant VIKINGYFY head:

- `b3a261a4ae qualcommax: ipq807x: add Arista AP-C260/C360 support`
- `9716066e80 kernel: add qualcommax patches to generic`
- `8614a2ba68 hostapd: fix security advisory 2026-1`
- `0bad892975 update wifi-scripts`
- multiple wifi-scripts fixes
- multiple dnsmasq/odhcpd updates
- broad official source, toolchain, kernel, target, and package churn

`qosmio/main` is currently not a direct forward source for this baseline: compared with `origin/main`, it is behind from this local source view.

## Candidate branches created

The following source-repo candidate branches were created and pushed to `OrdinaryJoys/immortalwrt-nss`.

### hostapd security candidate

Branch:

- `codex/ax6-b3a261a-hostapd-security-candidate`

Picked upstream commit:

- `8614a2ba68 hostapd: fix security advisory 2026-1`

Validation:

- Cherry-pick from `origin/main` was clean.
- `git diff --check origin/main...HEAD` passed.
- Scope is limited to `package/network/services/hostapd`.

Risk:

- Low to medium. It refreshes hostapd patches and adds upstream security patches. It still needs package build validation before locking into AX6 firmware.

### wifi-scripts candidate

Branch:

- `codex/ax6-b3a261a-wifi-scripts-candidate`

Picked upstream commits:

- `d9c765286d wifi-scripts: fix HE Operation IE parsing in iwinfo scan`
- `7f2effc94d wifi-scripts: expose connected_time in iwinfo assoclist`
- `c92ded2f6e wifi-scripts: fix EAP STA support in supplicant config generation`
- `3b6050fe42 wifi-scripts: make scan output fields conditional`
- `7dd4779183 wifi-scripts: fix disabled vif tracking using wrong dictionary key`
- `0d747a8edb wifi-scripts: ucode: only set antenna when config changes`
- `946b820856 wifi-scripts: ucode: check wpa_supplicant exists before mesh probe`
- `da28c7a67e wifi-scripts: add EHT beamforming options to hostapd config`

Validation:

- First five commits cherry-picked cleanly.
- `0d747a8edb` conflicted in `mac80211.sh`.
- Conflict was resolved by combining both required behaviors:
  - keep upstream's `antenna_changed` conditional execution
  - keep current branch's silent `iw` command behavior with `>/dev/null 2>&1`
- Remaining commits cherry-picked cleanly.
- `git diff --check origin/main...HEAD` passed.
- Scope is limited to wifi-scripts files.

Risk:

- Medium. The candidate changes netifd/wifi setup behavior. It does not directly change AX6 radio defaults, country code, channel, HE40/HE80, NSS, ECM, or DTS, but must be build-tested and then runtime-tested for 2.4G/5G association, reload, and fixed-channel behavior before entering the build lock.

## Items not merged

### Arista AP-C260/C360 support

Upstream commit:

- `b3a261a4ae qualcommax: ipq807x: add Arista AP-C260/C360 support`

Reason not merged:

- It adds new devices, board files, DTS files, radio-mode utilities, upgrade helpers, and image definitions.
- It does not repair a known AX6 failure.
- It increases build scope and firmware asset size.
- It should stay out of AX6 stable repair flow unless a shared driver-side fix is isolated from the new-device payload.

### qca8k/generic kernel patch migration

Upstream commit:

- `9716066e80 kernel: add qualcommax patches to generic`

Reason not merged:

- It moves/reworks qca8k switch patches across generic and qualcommax patch stacks.
- It touches switch topology and CPU-port behavior.
- AX6 currently uses NSS/SSDK/DP path with `nss-check` healthy.
- This needs a dedicated switch-driver candidate with patch-series equivalence review, not a direct cherry-pick.

### qca-nss script updates

Upstream commits include:

- `9e08f0c3cf cleanup qca-nss script`
- `27955135be update qca-nss script`
- `549509ec39 fix qca-nss`
- `bcc56131b8 update qca-nss`

Reason not merged:

- The current source already contains AX6-specific NSS fixes for ECM offloads, pbuf/N2H, remoteproc, stock nvmem, SSDK, ath11k station rate, and monitoring.
- These commits need file-level comparison against current local fixes to avoid replacing or weakening AX6-specific guardrails.

### dnsmasq/odhcpd updates

Relevant upstream commits:

- `85767ac8fe dnsmasq: add some default values of dhcp.conf`
- `6f30f08d0e dnsmasq: add fallback for default dhcpv4/dhcpv6 values`
- `d043c78bb5 dnsmasq: migrate dhcpv4/dhcpv6 default on upgrade`
- `64744ad9a0 Revert "dnsmasq: migrate dhcpv4/dhcpv6 default on upgrade"`
- `313ad4789b odhcpd: update to Git HEAD (2026-06-28)`

Reason not merged:

- These are DHCP/default migration changes, not a direct fix for the verified OpenClash DNS single-point runtime.
- OpenClash currently generates dnsmasq runtime config with `no-resolv` and `server=127.0.0.1#7874`; package defaults alone may not change the effective runtime path.
- Needs separate DNS resilience design.

## Next validation plan

1. Build/package validation for `codex/ax6-b3a261a-hostapd-security-candidate`.
2. Build/package validation for `codex/ax6-b3a261a-wifi-scripts-candidate`.
3. If both pass separately, create a combined candidate branch only after confirming no hostapd/wifi-scripts patch interaction.
4. Update AX6 build lock to the tested combined source commit only after the source candidate passes.
5. Run AX6 firmware build and inspect package list, kernel modules, overlay footprint, and image layout.
6. Real-router testing remains manual-confirmation only:
   - no flashing by automation
   - no persistent router config modification without confirmation
   - runtime tests should focus on OpenClash DNS reload resilience, 2.4G/5G association, fixed 5G channel `noscan=1`, NSS/ECM offload counters, and ZeroTier reachability.

