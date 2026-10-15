# Staged OpenClash restore safety

This is a host-only candidate, not a router package or driver change.
The public `--apply` path is deliberately **unreleased**. Neither a check result,
a successful CI job nor an edited approval JSON authorizes real-device changes.
The old implicit `router backup-directory` invocation is no longer accepted.

## Available Operation

```
./deploy-openclash-runtime.sh --check /absolute/path/to/staged-backup
```

Default/check mode never invokes SSH and never changes the backup. It requires
Python 3.9+ on the host; Python is not installed or invoked on the router.
The complete checksum inventory and four gzip/tar archives are checked as data.
Links, special files, duplicate/ambiguous paths, privileged modes, sparse files,
trailing data and bounded-size violations are refused. Forensic data is never
an input to the transaction payload. The normalized payload contains only the
OpenClash UCI file and config/custom/overwrite roots; it never contains password
hashes, network/system/driver files, cores, Geo caches or package scripts.

An empty ZeroTier public file is surfaced separately, not silently equated with
loss of the secret identity. Structural PASS does not cryptographically validate
an identity. Use the official idtool offline to validate the original secret,
extract its public portion and check the node address; never generate a new node
identity as a repair for an empty public file. Keep the original sealed backup.

## Candidate Protocol

The internal engine exists for isolated tests. It is not a direct-use shell tool.
Before release, a reviewed receipt must bind the complete backup manifest,
archive, every user-hook digest, configuration-schema review, enable state and
the exact init/core of an independently validated target image. The receipt is
an attestation of review, not an automated proof of hook/schema compatibility.
It must not be fabricated from check output to bypass review.

1. A persistent, exclusive transaction directory owns the token and boot ID.
   Existing/abandoned transactions are never stolen or overwritten.
2. Target scripts must be regular reviewed ROM-equivalent files. Uncommitted
   UCI, wrong init/core/keep policy, links/special user data and inadequate staging
   space refuse preparation. No driver or network-topology parameter is changed.
3. Payload is normalized locally, received privately, hash/CRC checked and
   extracted only into the newly created stage. The original target tree and
   cron are captured and independently downloaded/validated before replacement.
4. Current tree/cron/ROM/boot are rechecked. Stop failure or a still-running core
   prevents replacement. A stop hook changing the captured user data also refuses
   replacement; this may require manual intervention, never a false success.
5. Fixed roots are moved, not deleted in advance. Each UCI/start/check failure is
   explicit. Old backup cron is not imported; upstream regenerates its own tagged
   tasks from restored settings, preserving unrelated target cron and Geo intent.
   The restorer never restarts crond or edits subscriptions/overwrite contents.
6. Enabled verification needs a core, bounded DNS probes, the precise fw-health
   probe and configuration audit. Disabled verification additionally requires
   host-parsed nft/rule/route snapshots with no active OpenClash/policy-354 state.
7. Rollback refuses a changed boot/ROM, unrelated cron drift or a foreign data
   replacement. It checks restored files, cron, enabled/disabled state and health;
   any failure says NOT VERIFIED and retains evidence. Lost transport, timeout or
   host interrupt is UNKNOWN, never an assumed rollback success or blind retry.

## Release Gates Still Open

- Native Linux and BusyBox tests of the exact candidate, not a macOS substitute.
- Exact composed OpenClash/procd lifecycle, including its DHCP/DNS/firewall and
  overwrite-metadata side effects. Current fixtures stub those services.
- Actual backup-specific user-hook and old/new UCI-schema review.
- Real disconnect/SIGKILL/power-loss/manual recovery. Phase files are not a
  power-loss durability proof, and the multi-resource operation is not atomic.
- A separately approved router maintenance/restore window and subsequent tests.

The frozen source/build identities and previously accepted NOT-FLASHED firmware
stay unchanged. Host-only tool fixes do not themselves require a firmware rebuild.
