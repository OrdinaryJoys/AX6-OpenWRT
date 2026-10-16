# rpcd component validation candidate

This branch is test-only, not approved for deployment or merging to main.
The source lock points to f58e128163892af4242c724300a00f3fc69a4a88.
NSS/ECM/EDMA/ath11k, feeds and package selections stay at the prior accepted
85c7a3fc build baseline except for rpcd source backports and release r2.

The source package retains its original archive/hash and adds four official
rpcd commits through d99f703e. The local checked-transaction backend was adapted
to upstream's independent random session dirname, but remains default OFF.
An entropy-read failure allocation cleanup is included. See source package
AX6-VALIDATION.md and provenance.json for exact boundaries and source hashes.

The CI component gate builds checked ON and preserves target core/four-plugin
ELFs, CMake mode, configuration and selected IPKs. It explicitly cleans rpcd,
then repeats with OFF. The firmware build proceeds only with OFF restored.
rpcsys is compile-tested but remains uninstalled in the normal configuration.
Final rootfs core/file/iwinfo/ucode version, architecture, dependency metadata,
regular executable type and bytes must match the retained OFF IPKs.

Local validation includes 22 actual AArch64 daemon transaction cases, seven
default-OFF/file-ACL cases, a baseline entropy failure leak counterexample and
the patched allocation/free control. These use the stock shared libraries in
an isolated VM with no NIC/shares/disks, not the AX6 target kernel or hardware.
Local gate fixtures are not evidence of a successful target compiler or image.

Known open gates: daemon restart durability, LuCI/CGI/Argon frontend integration,
configuration recovery release, existing W04/throughput/real-network symptoms.
No subscription/overwrite edits or geography auto-update changes are included.
No main merge, release, router update, reboot or restore is authorized here.

CI should be dispatched once for Lint on this exact branch/head, then once for
stock (ssh=false) after that Lint passes. Platform dispatch failures do not
constitute a running build; preserve the exact error rather than blindly retry.
