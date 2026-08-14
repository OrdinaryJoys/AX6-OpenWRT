# AX6 clean-flash backup and restore safety

Date: 2026-08-14

## Conclusion

The legacy file named `sysupgrade-config-restore-safe.tar.gz` is not safe to
restore after a clean flash. It is a filtered forensic copy of `sysupgrade -l`,
not a portable configuration bundle. It must not be uploaded through LuCI,
renamed, or passed to `sysupgrade -r`.

The confirmed failure mechanism is:

1. The archive contains `/etc/config/network` and `/etc/config/system`.
2. OpenWrt `config_generate` exits immediately when both files are non-empty.
3. The new firmware therefore cannot generate the `redmi,ax6-stock` board
   topology (`lan1 lan2 lan3` for LAN and `wan` for WAN), or an already
   generated topology is overwritten after boot.
4. Reloading network/firewall or rebooting can then remove the reachable LAN
   address, bridge membership, DHCP path, WAN path, or SSH path at the same
   time. Remote rollback is no longer possible, which explains why factory
   reset has repeatedly been required.

The same archive also contains old NSS, ECM, PBUF, IRQ, firewall, DHCP, WiFi,
Dropbear host-key, ZeroTier generated-state and boot configuration. Even when
the old and new firmware use the same IP address, those files are not a safe
cross-build restore contract.

## Implemented repository controls

- The complete capture is now named
  `FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked` and is capture-only.
- Every backup includes `DO-NOT-RESTORE-WHOLE-BACKUP.txt`.
- `preflight-router-restore.sh` rejects every legacy
  `sysupgrade-config*.tar.gz` file before flashing.
- SSH recovery data contains only `/etc/dropbear/authorized_keys`; it excludes
  password hashes and Dropbear host keys.
- ZeroTier recovery data contains only `identity.public` and `identity.secret`;
  generated network state is excluded.
- OpenClash recovery remains limited to its UCI file plus `config`, `custom`
  and `overwrite`; core, Geo databases, caches and providers are excluded.
- UCI exports for network, firewall, DHCP and WiFi are reference material only.
  They must not be imported as complete packages.
- Backup and deployment require a previously confirmed SSH host key.

## Required clean-flash sequence

1. Run `backup-router-config.sh` and require its final offline preflight to pass.
2. Keep the router recovery image, current firmware, checksums and serial/TFTP
   recovery instructions available.
3. Flash without retaining configuration. Do not upload any backup archive in
   LuCI and do not use `sysupgrade -r`.
4. On the first boot, verify the model, partition layout, kernel, rootfs, LAN
   bridge ports, WAN device, management address and DHCP before restoring data.
5. Confirm the new SSH host key out of band, update the dedicated known_hosts
   entry, and restore only `authorized_keys` if needed. Do not restore host keys
   or the root password; set the login password manually.
6. Restore ZeroTier identity only. Then configure the network ID using the new
   package defaults and verify the interface, firewall zone, route table,
   secondary port and OpenClash bypass before proceeding.
7. Restore OpenClash only through `deploy-openclash-runtime.sh`. Require its
   DNS health and `ax6-config-audit` checks to pass.
8. Recreate DHCP reservations, WiFi credentials, VLANs, UPnP and optional
   services one package at a time against the new defaults. Validate LAN and
   WAN after each stage. Do not copy old `network`, `firewall`, `dhcp`,
   `wireless`, `system`, `ecm`, `nss`, `pbuf`, `smp_affinity` or `sqm` files.
9. Run core-driver, packet-loss, latency and bidirectional throughput tests only
   after the staged configuration is stable.

## Audited backup inventory

The following historical archives contain the same unsafe network/core and
boot/system scope. They are forensic records only and have been quarantined by
renaming them with a `.blocked` suffix:

- `/Volumes/FX-MD87/Review/AX6-BACKUP-20260718-233137-PRE-FLASH/`
- `/Volumes/FX-MD87/Review/AX6-BACKUPS/ax6-backup-20260719-114550/`
- `/Volumes/FX-MD87/Review/backups/backup-20260731.tar.gz.blocked`
- `/Volumes/FX-MD87/Review/backups/preflash-20260813-p1/`
- `router-backups/Redmi-AX6-20260814-full-audit/ax6-pre-audit-20260814-120831/`

The current staged backup is:

`router-backups/Redmi-AX6-20260814-clean-flash-safe/ax6-preflash-staged-20260814-124519/`

It passed archive integrity, member type, path allowlist and checksum checks on
2026-08-14. Its UCI reference exports match the earlier same-day capture, so no
configuration drift occurred between the two captures.

## Stop conditions

Do not proceed to flashing when any of the following is true:

- restore preflight fails or a legacy whole-restore archive is present;
- the firmware checksum, model/layout compatibility or `sysupgrade -T` fails;
- the backup lacks SSH authorized keys, ZeroTier identity or OpenClash staged
  data expected for this router;
- recovery access and the new host-key confirmation method are unavailable;
- the current router has an unresolved link, filesystem or core-driver fault.

Passing the backup preflight proves archive integrity and restore scope only.
It does not authorize flashing and does not prove that a later real-device
restore will succeed. Each real-device stage still requires explicit approval.

## Current flash gate status

- Real-device staged backup: PASS at
  `router-backups/Redmi-AX6-20260814-clean-flash-safe/ax6-preflash-staged-20260814-124519/`.
- Historical directly-restorable archive names under `/Volumes/FX-MD87/Review`:
  none remaining; four archives were preserved with `.blocked` names and
  independent SHA256 sidecars.
- Repository restore-safety commit: `3b27db65fc682a38c1c9625fb2f30d8729ea768d`.
- CI annotation follow-up: `9b211af9317167def024fd9d5841038f57c120f4`.
- Cloud Lint run `31771229090`: PASS, including ShellCheck, Actionlint,
  Yamllint, DTB, NSS/ECM/ath11k, PBUF, IRQ, ZRAM and restore policy gates.
- Post-backup router reachability: 20/20 LAN pings, 0% loss,
  0.672 ms average; LAN `br-lan` and WAN both remained up.
- Stock build run `31770288192` at firmware commit `0d9224a` was still compiling
  when this document was updated. The later commits change only host-side
  maintenance scripts, tests and documentation; no firmware input differs.

Flashing remains blocked until the stock run succeeds, artifacts are downloaded
and independently checked, the exact sysupgrade image passes `sysupgrade -T` on
this router, and the user explicitly authorizes the write and reboot.
