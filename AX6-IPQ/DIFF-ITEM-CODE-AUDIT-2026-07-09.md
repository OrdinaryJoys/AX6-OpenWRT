# AX6 code-level upstream diff audit

Date: 2026-07-09

Scope:

- Source baseline: `OrdinaryJoys/immortalwrt-nss@56807d9661`
- Build baseline: `OrdinaryJoys/AX6-OpenWRT@099556a`
- Upstreams checked:
  - `VIKINGYFY/immortalwrt@b3a261a4ae`
  - `immortalwrt/immortalwrt master@4cafb73e88`
  - `immortalwrt/immortalwrt openwrt-24.10@253a70f1f8`
  - `qosmio/openwrt-ipq main-nss@92a2d10414`
  - `fightroad/AX6-OpenWRT@4c37d802`

This audit is code-only. No router flash and no persistent router configuration change was performed.

## Summary

| Area | Code result | Conflict or abnormal point | Branch-test decision |
| --- | --- | --- | --- |
| hostapd security advisory 2026-1 | Clean candidate already exists | Only patch offsets and security patches; no AX6/NSS config overlap | Test as low-risk source branch |
| VIKINGYFY wifi-scripts batch 1 | Candidate already exists | One resolved conflict in `mac80211.sh`: keep upstream antenna-change guard plus local silent `iw` calls | Test as medium-risk WiFi branch |
| Official wifi-scripts batch 2 | Dry-run completed on top of batch 1 | Three EAP/alias commits clean; three WPA3/GCMP/SAE commits conflict in `iface.uc` and require official final-state resolution | Create separate `wifi-v2` branch before combining |
| qca-nss scripts and services | High-risk overlap | Rewrites pbuf, ECM, disable_offloads, IRQ, removes UCI config files via cleanup script | Do not mix; needs dedicated NSS runtime branch |
| qca8k/generic patch migration | High-risk topology change | Moves qca8k patches to generic and changes CPU-port/FDB behavior | Do not mix; needs switch-driver branch only |
| AX6 stock DTS/nvmem layout | High-risk board behavior | Replaces alias/delete-nvmem style with fixed ART nvmem layout | Separate board-layout validation only |
| dnsmasq/odhcpd | Not a fix for current DNS issue | DHCP/RA defaults and odhcpd bump; does not address OpenClash runtime `no-resolv -> 127.0.0.1#7874` | Defer; optional DHCP/IPv6 branch |
| kernel 6.18.37/6.18.38 | Broad kernel change | Requires NSS patch-stack refresh and full build/runtime validation | Defer to kernel branch |
| netifd/libubox/ucode | Broad userspace plumbing | May affect ucode WiFi generation and LuCI behavior | Only after WiFi branch passes |
| qosmio main-nss | Reference only | Different long-lived NSS patch stack; 197 files and ~39k lines in key paths | Do not cherry-pick directly |
| fightroad AX6 build repo | Reference only | No merge-base with this build repo; simpler historical workflow | Do not merge directly |

## 1. hostapd security candidate

Candidate branch:

- `OrdinaryJoys/immortalwrt-nss:codex/ax6-b3a261a-hostapd-security-candidate`

Code changes:

- `package/network/services/hostapd/Makefile`
- eight new MLD security patches
- hostapd local patches refreshed for new upstream context offsets:
  - `200-multicall.patch`
  - `600-ubus_support.patch`
  - `601-ucode_support.patch`
  - `720-iface_max_num_sta.patch`
  - `762-AP-don-t-ignore-probe-requests-with-invalid-DSSS-par.patch`

Validation:

- Cherry-pick was clean.
- `git diff --check origin/main...candidate` passed.

Risk:

- Low to medium. This is a security fix with isolated scope. It still needs package/build validation.

Decision:

- Keep as independent first test branch.

## 2. VIKINGYFY wifi-scripts batch 1

Candidate branch:

- `OrdinaryJoys/immortalwrt-nss:codex/ax6-b3a261a-wifi-scripts-candidate`

Included commits:

- HE Operation IE parsing fix
- `connected_time` in iwinfo assoclist
- EAP STA generation fix
- conditional scan output fields
- disabled vif tracking fix
- antenna setting only when config changes
- wpa_supplicant mesh probe guard
- EHT beamforming options

Conflict already resolved:

- File: `package/network/config/wifi-scripts/files-ucode/lib/netifd/wireless/mac80211.sh`
- Upstream wanted to call `iw phy set antenna` only when antenna settings change.
- Local branch already silenced `iw` calls with `>/dev/null 2>&1`.
- Correct merged behavior:
  - keep upstream `antenna_changed` guard
  - keep silent `iw` command execution
  - do not change AX6 country code, channel, HE40/HE80, or `noscan=1` policy

Validation:

- `git diff --check` passed.
- Scope is limited to wifi-scripts.

Risk:

- Medium. It changes WiFi generation/reload behavior and must be tested on 2.4G/5G association and reload.

Decision:

- Keep as independent WiFi test branch.

## 3. Official wifi-scripts batch 2

Dry-run base:

- `/private/tmp/imm-wifi-v2-check`
- base: `origin/codex/ax6-b3a261a-wifi-scripts-candidate`

Tested official master commits:

- `649b42331c wifi-scripts: restore priv_key/priv_key_pwd as config aliases`
- `7be144ad83 wifi-scripts: ucode: fix EAP certificate constraint handling`
- `0cdf956ee1 wifi-scripts: ucode: fix EAP phase2 authentication method`
- `5e067465ff wifi-scripts: ucode: add gcmp256 option, default GCMP-256 per WPA3 mode`
- `fc652db52a wifi-scripts: ucode: default the SAE-EXT-KEY AKM per WPA3 mode`
- `05e87cfcb6 wifi-scripts: ucode: only advertise GCMP-256 when the driver supports it`

Dry-run result:

- First three EAP/alias commits applied cleanly.
- Last three WPA3/GCMP/SAE commits conflicted in:
  - `package/network/config/wifi-scripts/files-ucode/usr/share/ucode/wifi/iface.uc`
- After resolving according to official master final state, all six commits applied and `git diff --check` passed.

Important code behavior:

- Current candidate had broad defaults:
  - HE/EHT could lead to `GCMP-256 CCMP`
  - `sae_ext_key` default behavior was more aggressive
- Official final behavior is more compatible:
  - `gcmp256` and `sae_ext_key` default on only for `sae-compat` with EHT
  - GCMP-256 is advertised only when `phy_features.cipher_gcmp256` is true
  - `parse_encryption()` receives `phy_features`
  - `hostapd.uc` detects `WLAN_CIPHER_SUITE_GCMP_256`
  - EAP phase2 and cert constraint list handling are fixed

AX6 relevance:

- This is likely beneficial for compatibility because it narrows GCMP-256/SAE-EXT-KEY advertising.
- It should reduce risk for older WPA3/transition clients and avoids pushing stronger ciphers where the driver cannot advertise them.
- It does not directly change country code, channel, HE40/HE80, or NSS offload.

Decision:

- Create a separate `wifi-scripts-v2` candidate branch.
- Do not fold this directly into the existing WiFi branch without branch-level build validation.

## 4. qca-nss scripts and services

Relevant VIKINGYFY commits:

- `9e08f0c3cf cleanup qca-nss script`
- `27955135be update qca-nss script`
- `549509ec39 fix qca-nss`
- `bcc56131b8 update qca-nss`
- `2e496928a9 update qca-nss wifi-no`

Key changed files:

- `package/kernel/mac80211/files/qca-nss-pbuf.init`
- `package/qca-nss/qca-nss-ecm/files/disable_offloads.sh`
- `package/qca-nss/qca-nss-ecm/files/qca-nss-ecm.defaults`
- `package/qca-nss/qca-nss-ecm/files/qca-nss-ecm.init`
- `target/linux/qualcommax/base-files/etc/init.d/set-irq-affinity`
- `target/linux/qualcommax/base-files/etc/init.d/smp_affinity`
- `target/linux/qualcommax/base-files/etc/uci-defaults/15_nss_cleanup.sh`

Abnormal or high-risk points:

- `15_nss_cleanup.sh` deletes:
  - `/etc/config/ecm`
  - `/etc/config/nss`
  - `/etc/config/pbuf`
  - `/etc/config/skb_recycler`
  - `/etc/config/smp_affinity`
- `disable_offloads.sh` is reduced to forcing `rx-gro-list` off only.
- Older UCI-driven choices around `disable_offloads`, `disable_gro`, `disable_flow_control`, and `disable_interrupt_moderation` are removed.
- `qca-nss-ecm.init` is simplified and forces front-end mode to auto.
- IRQ/SMP affinity is moved from configurable UCI behavior to fixed startup behavior.
- pbuf service behavior is rewritten and includes WiFi restart behavior.

AX6 relevance:

- Current router health depends on:
  - `ecm.general.disable_offloads=1`
  - `ecm.general.disable_gro_list=1`
  - br-lan offload guard
  - pbuf/N2H profile being applied early
  - upstream IRQ/RPS scripts being left in control
- This upstream script set touches all of those assumptions.

Decision:

- Do not merge into WiFi/hostapd candidates.
- Needs a dedicated NSS runtime branch with router-side staged validation.
- The cleanup script must be reviewed before any candidate because deleting config files can hide or reset required guardrails.

## 5. qca8k/generic migration and switch path

Relevant upstream:

- `9716066e80 kernel: add qualcommax patches to generic`

Key behavior:

- qca8k patches move from `target/linux/qualcommax/patches-6.18` into `target/linux/generic/pending-6.18` and `backport-6.18`.
- Multi-CPU/FDB behavior changes:
  - old host FDB merge patch removed
  - new "do not program unicast host FDB entries on CPU ports" patch added
- CPU-port, preferred default local CPU port, PHY-to-PHY CPU link and force-mode patches are reshuffled.

AX6 relevance:

- AX6 current runtime uses NSS/SSDK/DP path and does not show active switch-driver failure.
- qca8k is still a critical switch-family patch area; accidental merge could alter port forwarding/FDB learning behavior.

Decision:

- Do not merge into current repair flow.
- If needed, create a dedicated switch-driver branch and validate only after NSS/WiFi candidates pass.

## 6. AX6 stock DTS/nvmem layout

Relevant upstream:

- `a949f0445e qualcommax: add nvmem support for xiaomi ax6/ax3600/ax9000 stock layout`

Key code difference in `ipq8071-ax6-stock.dts`:

- Current baseline removes dp2/dp3/dp4/dp5 nvmem cells and keeps ethernet aliases.
- Upstream adds fixed ART nvmem layout:
  - `macaddr@6`
  - `macaddr@c`
  - `macaddr@12`
  - `macaddr@18`
- Upstream removes the local ethernet aliases block.

Risk:

- May affect LAN/WAN MAC derivation and interface naming expectations.
- Needs actual boot log and `ip link` MAC validation.

Decision:

- Separate board-layout branch only.
- Do not combine with WiFi/hostapd.

## 7. dnsmasq and odhcpd

Relevant upstream:

- `85767ac8fe dnsmasq: add some default values of dhcp.conf`
- `6f30f08d0e dnsmasq: add fallback for default dhcpv4/dhcpv6 values`
- `313ad4789b odhcpd: update to Git HEAD (2026-06-28)`

Code behavior:

- Adds LAN defaults:
  - `ra=server`
  - `dhcpv4=server`
  - `dhcpv6=disabled`
- Makes dnsmasq init default `dhcpv4/dhcpv6` to disabled when absent.
- Bumps odhcpd source date/version.

AX6 relevance:

- This is not a direct fix for current OpenClash DNS single-point runtime.
- The verified DNS single point is generated runtime config:
  - `no-resolv`
  - `server=127.0.0.1#7874`
- Package defaults will not solve that runtime ownership path.

Decision:

- Defer.
- Consider only in a DHCP/IPv6 defaults branch if IPv6/RA issues appear.

## 8. kernel, netifd, libubox, ucode

Official master newer than VIKINGYFY includes:

- `5b6bc962bd kernel: bump 6.18 to 6.18.38`
- `c5854d65f2 netifd: update to Git HEAD (2026-07-08)`
- `2fb1afa761 libubox: update to Git HEAD (2026-07-08)`
- `7987b1f799 ucode: fix two compiler issues`

Risk:

- Kernel bump requires NSS patch-stack refresh.
- netifd/libubox/ucode can affect wireless ucode generation and service behavior.

Decision:

- Do not include in current candidate.
- Revisit after WiFi/hostapd combined branch passes.

## 9. qosmio main-nss

`qosmio/main-nss` includes many relevant NSS/ath11k ideas, including:

- ath11k NSS AP_VLAN/dynamic VLAN/mesh fixes
- NSS pbuf examples
- NSS README/support matrix
- skb recycler and NSS DTS work

But the diff is broad:

- key-path stat showed about 197 files and ~39k added lines
- it targets a different long-lived patch stack and kernel baseline

Decision:

- Use as reference for concepts only.
- Never cherry-pick directly into the stable AX6 repair flow without isolating a single patch and proving patch-stack compatibility.

## 10. fightroad AX6 build repo

Finding:

- No merge-base with this build repository.
- `fightroad/main` is a historical/simple build workflow.
- This repo now includes:
  - source lock file
  - feed locks
  - lint workflow
  - sync-check workflow
  - OpenClash latest tracking
  - NSS/ECM boot guards
  - ZeroTier firewall helpers
  - `nss-check`
  - `ax6-config-audit`

Decision:

- Do not merge directly.
- Only use for historical configuration reference.

## Branch-test recommendations

Proceed in this order:

1. Test `hostapd-security-candidate`.
2. Create and test `wifi-scripts-v2-candidate` from the existing WiFi branch.
3. If 1 and 2 pass, create combined `hostapd + wifi-v2` candidate.
4. Lock AX6 build repo to combined source commit and build firmware.
5. Only after that, consider separate branches:
   - `nss-runtime-script-candidate`
   - `qca8k-generic-switch-candidate`
   - `ax6-stock-nvmem-layout-candidate`
   - `dnsmasq-odhcpd-defaults-candidate`
   - `kernel-6.18.38-candidate`

Do not combine NSS runtime scripts, qca8k/generic, DTS/nvmem, and kernel bump with WiFi/hostapd. Their risk surfaces are different and would make failures hard to isolate.

## Follow-up branch validation

Completed on 2026-07-09:

| Branch | Source base | Included scope | Validation result | Status |
| --- | --- | --- | --- | --- |
| `codex/ax6-b3a261a-wifi-scripts-v2-candidate` | `origin/codex/ax6-b3a261a-wifi-scripts-candidate` | Official wifi-scripts EAP alias/certificate/phase2 fixes plus WPA3 GCMP-256/SAE-EXT-KEY compatibility fixes | `git diff --check` passed; JSON schema parsed with `jq`; no conflict markers; changed files limited to five `wifi-scripts` files | Pushed |
| `codex/ax6-b3a261a-hostapd-wifi-v2-candidate` | `origin/main` | Hostapd security advisory 2026-1 plus WiFi batch 1 and WiFi v2 | `git diff --check origin/main...HEAD` passed; changed files limited to `package/network/services/hostapd` and `package/network/config/wifi-scripts`; no NSS/ECM/SSDK/qca8k/DTS/kernel/DNS/firewall files included | Pushed |

Conflict-resolution notes:

- `wifi/iface.uc` keeps the official final behavior: `parse_encryption(config, dev_config, phy_features)` receives driver capabilities.
- `GCMP-256` is only advertised when both `config.gcmp256` is true and `phy_features.cipher_gcmp256` is reported by the driver.
- The default `gcmp256` and `sae_ext_key` behavior remains limited to `sae-compat` BSSes using EHT htmode.
- This keeps the compatibility-oriented behavior and avoids forcing stronger WPA3 ciphers onto clients or drivers that did not advertise support.

Next build-side step:

1. Create an AX6 build test branch that locks the source repository to `codex/ax6-b3a261a-hostapd-wifi-v2-candidate`.
2. Run lint/static checks and GitHub Actions build against that source branch.
3. Inspect the generated firmware contents before any real-router action.
4. Keep NSS runtime scripts, qca8k/generic migration, DTS/nvmem layout, kernel bump, and dnsmasq/odhcpd changes out of this build test branch.
