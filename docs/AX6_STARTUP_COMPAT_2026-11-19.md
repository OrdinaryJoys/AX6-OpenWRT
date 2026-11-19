# Startup compatibility candidate, 2026-11-19

This isolated candidate integrates the already reproduced ECM/boot-guard
configuration compatibility corrections. It is not a claim that the reported
828/0c boot failure has been uniquely diagnosed or repaired.

## Production Scope

ECM r18 selects the first typed network globals section, matching locked
netifd's `@globals[0]`. A valid network without that optional section does not
invent it or fail service setup. Existing pending edits and failed queries
prevent persistence, while the existing live queue policy still runs and the
first error remains visible. This is not atomic exclusion against all external
UCI writers after admission.

The boot guard applies the same optional-section contract, retaining required
firewall/ECM sections, stale device-option migration and pending-edit checks.
Process failures during enumeration/key scans and post-delete/commit checks
cannot be reported as successful absence or verification.

The NAND writer's pre-existing local changes are excluded. NSS/SSDK/DP drivers,
FW blobs, clock/reset sequence, data-plane quarantine, DMA lifetime, performance
switches, subscriptions, overrides and Geo policies are unchanged. 035, LIVE
unload, independent unbind and shared-resource retirement remain HOLD.

## Verification

Current-checkout local regression covers the complete ECM service dispatcher,
reload, offload/RPS order, boot-guard fault injection and a freshly compiled real
UCI CLI using private configuration/delta directories. The core CLI uses the
package's exact UCI source commit, original C sources including `list.c`, both
upstream debug defaults OFF, strict compiler diagnostics and no success stubs.
It does not cover target blob/Lua bindings or the complete target UCI package.

Full Lint and stock CI execute the real UCI fixtures with Linux BusyBox ash.
The firmware rootfs gate compares the installed boot guard byte-for-byte and
repeats its real UCI fixture. The extracted ECM init is also tested with the
real CLI, alongside the existing complete callback and RPS tests. Host fixtures
never operate network interfaces, execute target binaries or contact a router.

All prior core/prepare, target toolchain, rpcd ON/clean/OFF, compiled-DTB, ELF,
manifest, FIT/UBI and source-lock gates remain enabled. Record actual workflow
head, source lock and artifact ownership/digest; failures require first-error
analysis, not a blind rerun. Only one stock/ssh=false build follows a successful
full Lint. No main merge or Release.

Build completion and offline artifact checks are not proof of boot, throughput,
latency, loss, memory/CPU behavior or safe recovery. No flash or device-operation
authorization is issued by this document; any produced firmware stays
NOT-FLASHED / DEPLOYMENT HOLD pending separate evidence and user authorization.

## First Lint Result

Lint 44441424619 at build eeef65b failed in step 40: the old Wi-Fi preflight
required the literal named `network.globals` assignment. Its earlier Linux ash
and real UCI fixtures had passed. The obsolete literal check is replaced by the
same packet-steering-zero invariant plus real UCI behavior; an exact SHA-bound
copy of the previous guard must fail on `no-globals`, while the corrected guard
must pass all nine native scenarios. This is a CI contract correction, not an
additional driver repair. The firmware source remains 93ad446e22, and no stock
build was dispatched on the failed Lint commit.
