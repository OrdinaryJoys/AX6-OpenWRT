# rpcd020 / r8 local candidate

Source ba0869f944dd8d29c07da563515a114cc51bf4b3 validates the root and two
private checked snapshot directories and skips journal loading if validation
fails. It does not chmod/chown/remove incorrect objects. Existing root 0755
is compatible; snapshot directories must remain private. Checked defaults OFF.

The complete API/storage initializers and helper pass 57 scenarios / 399 checks
under GCC16 and Clang ASan/UBSan; actual r7 fails 49, six compiled wrong variants
are rejected. UCI/ubus boundaries and Linux trailing-slash behavior are models;
host files are real. ON/OFF and allocation failure behavior are included.
Prior 019 tests and 18 driver regression groups are rechecked on fresh inputs.

Future ON component validation runs this host test after prepared-source hash
binding. ON-clean-OFF target flow and final OFF artifact checks are unchanged.
No new target build or runtime evidence is claimed, and no cloud run is sent.

NSS/SSDK/ECM/DP/Wi-Fi pins, source trees and performance settings are unchanged.
NSS callback lifetime/request generation/DMA quiescence/parent release remain
OPEN; this is not an NSS teardown repair or a throughput/performance fix.
Directory TOCTOU, durable snapshot/recovery, power loss, flash wear, frontend
and actual runtime still require independent qualification. NO-FLASH/Release.
