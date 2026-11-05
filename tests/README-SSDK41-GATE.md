# Independent SSDK41 Quality35 Gate

This unwired source and host evidence gate freezes reviewed quality commit
`4245760179a1fbf2a0ce35cc4e6f21fc49b642cc`. It is not firmware, shared root
lifecycle, target ABI, real clock/reader, router or performance qualification.
The build remains
`f8d092d9ba159b3e8fc96e4189663e3f2c1fa440`, locked to
`fce57df4d7828fa9e9c7a45975f37f09a77fa101` / SSDK40 / release30.
No workflow, source lock, source manifest, or older gate is changed here.

The new contract inherits the byte-frozen 40 contract (SHA256
`a4c6901e6175a56d7c8930838a0b75ee90e05cdf5eecccae91750d7585772872`).
Its six source overrides come from that reviewed quality35 Git commit, never
from prepared inputs. The four test assets have explicit Git blob identities
and SHA256 values in the contract.
The complete 692-file inventory changes only `src/init/ssdk_plat.c` to
`aff83ac50ba65685ab44d1c6ad8c96d8c6f040045a532e52b6cc7af2f1d0474f`.
The exact41 patch set, 053 and release31 recipe are unchanged from historical
`f41e5fd9aa974fb679268ba1517e769e2a3e4fa2`.

## Quality History

Historical f41 tests had mapping address, read callback, foreign clock-rights
and same-source getter/expected oracle blind spots. The reviewed quality35
commit changes only README, fixture, runner and oracles. Historical f41 source
identity and all four old test assets are rejected, not accepted through a
compatibility fallback.

Current tests check exact mapping address/length, both callback directions,
immediate foreign-exit rights and side-effect snapshots, profile/modes/device
role sequences independent of the getter selected by tested code, and exact
live successful-slot identity. The frozen list contains35 exact runtime
negatives: historical20, eight red-team cases, three wrong getters, one wrong
device, and three wrong slots. Names, mutation bytes, cases and markers are
explicitly bound in the gate, not inferred from runner status or counts.
These are stronger host test oracles, not new production or router defects.

Shared root/module UK/SD/PHY provider and reader retirement, nested void GCC
clock/reset success, clock error propagation, Linux GCC11/target/hardware/
firmware/performance qualification, and workflow/lock/manifest integration
remain OPEN. Source host campaigns reported by the parent are separate from
this gate's pure-control verification and future full parent campaign.

## Execution

The parent campaign must supply separate real checkouts for 40, 39, 38 and
legacy; an archive without Git HEAD is not a frozen40 checkout. The 40 checkout
must actually be at `fce57df4d7828fa9e9c7a45975f37f09a77fa101`.

```sh
python3 -B .github/scripts/verify-ssdk-platform-resource.py \
  --source-root /absolute/quality35-source \
  --accepted40-source-root /absolute/frozen40-source \
  --accepted39-source-root /absolute/frozen39-source \
  --baseline-source-root /absolute/frozen38-source \
  --legacy-source-root /absolute/legacy-source \
  --ssdk /absolute/prepared41 --dp /absolute/prepared-dp \
  --cc /absolute/host-compiler --output /absolute/new-campaign-directory
```

The entry point admits fixed Git inputs and the complete prepared tree, retains
input evidence, copies code to independent trees, and reverses 053 with exact
diagnostics and full40 equality. Only that reversed tree and the real frozen40
source checkout are passed to the unchanged 40/39/38 parent gate. The actual41
tree runs the fixed `test-ssdk-platform-resources.py --sanitize` campaign.

The independent reader does not import the runner or accept status/counts as
proof. It reconstructs all46 complete C inputs, including every exact mutant,
old40 witness, and the SDK-only four-callback view; verifies compiler bytes,
instrumentation flags, each argv/environment and all1792 raw command records;
requires clean compilations and precise exit86/empty stdout/single-marker
negatives; and reads isolated sanitizer activation/disabled/crossed controls
using the frozen parent reader. It checks exact simple-case resource counts,
source/replay stability, host binary presence, and evidence contamination.
Host evidence is not a target ABI or real clock/reader proof.

The dSYM reader admits only the current thin arm64 companion layout belonging
to an exact expected host program: `Contents/Info.plist`,
`Contents/Resources/DWARF/<basename>.host`, and
`Contents/Resources/Relocations/aarch64/<basename>.host.yml`. It does not grant
a wildcard exception for `.dSYM` directories or extra `.host` files. Program
MH_EXECUTE=2 and debug MH_DSYM=10 must have matching CPU/subtype and one matching
nonzero LC_UUID. Standard `plistlib` verifies the bundle identity and type.
The YAML file is only opaque, non-executed UTF-8 metadata of1..16MiB; its YAML
semantics are not parsed or used as identity evidence. No x86, legacy or other
bundle layout is added, and the Linux path without dSYM is not relaxed.

The r1 results were pure synthetic controls, not actual Clang-v2 acceptance.
The first real readback rejected DWARF `.host` files as extra programs; its
failure record and all actual campaign files remain intact. Corrected debug
companion controls do not themselves qualify the real campaign.

For read-only inspection of an existing sanitized campaign, the parent can
import this gate and call `platform_receipts(directory, cc, source, current,
prefix, configuration())` with absolute paths. This only reads and verifies
data; it does not execute retained programs or scripts. It expects the original
source/current/prefix paths recorded in the receipts and the same Python
executable identity. Receipt readback alone does not grant the full immutable
40/39/38 campaign's status.

`--admission-only` accepts source, ssdk and output arguments only as a narrow
source/reverse053 check. Its separate status explicitly grants neither native
nor parent qualification. Output directories must be fresh and outside inputs.
Any execution-stage failure leaves `RESULTS.json` with `status=FAIL`.

## Reader Controls

Run normal and optimized Python in different fresh output directories:

```sh
python3 -B tests/test-ssdk41-gate.py \
  --source-git /absolute/repository-containing-reviewed-quality35 \
  --prepared41 /absolute/read-only-reviewed41-tree \
  --output /absolute/new-reader-control-directory
```

Repeat with `python3 -B -O`. These tests read exact Git blobs and prepared data,
never archived scripts or host programs. Fabricated receipt fixtures are
explicitly named synthetic; only the detector subtree reader is mocked for
negative controls, and the same synthetic bundle is rejected without that mock.
No compiler or native campaign is run by these unit tests. All generated data,
raw unittest logs, and the scoped result are kept below `--output`.

For the targeted r2 dSYM controls only, without rerunning the original synthetic
receipt suite or source tests, run `python3 -B tests/test-ssdk41-gate.py
--debug-controls-only --output /absolute/quality35-controls-normal-r2`, then
repeat with `-O` and a fresh `quality35-controls-optimized-r2` directory. These
controls construct synthetic thin Mach-O headers/UUID commands and plist data;
no compiler or retained program is invoked. They reject foreign/fake bundles,
wrong type/UUID/architecture/plist, missing/extra files, malformed load commands,
ELF-owned dSYM and invalid/unbounded relocation metadata.

Task D quality35 output is confined to fresh `quality35-*` directories under
`/Volumes/FX-MD87/Review-AX6/audits/20261105/multi-quality/gate41-worker`.
The full campaign and actual Clang-v2 receipt readback are reserved for the
parent in separate fresh directories; no workflow integration is claimed.
