#!/bin/sh
set -eu

SCRIPT="${1:-AX6-IPQ/scripts/ax6-nss-frequency-ab.sh}"
[ -f "$SCRIPT" ]
bash -n "$SCRIPT"
grep -Fq -- '--confirm-runtime-write' "$SCRIPT"
grep -Fq '748800000' "$SCRIPT"
grep -Fq '1689600000' "$SCRIPT"
grep -Fq 'auto_scale)" = 0' "$SCRIPT"
grep -Fq 'previous_freq=' "$SCRIPT"
grep -Fq 'router rebooted; do not restore' "$SCRIPT"
grep -Fq 'state source revision does not match' "$SCRIPT"
grep -Fq 'state build commit does not match' "$SCRIPT"
grep -Fq '/proc/sys/dev/nss/clock/current_freq' "$SCRIPT"
grep -Fq 'IdentitiesOnly=yes' "$SCRIPT"
grep -Fq 'StrictHostKeyChecking=yes' "$SCRIPT"
grep -Fq 'UserKnownHostsFile=' "$SCRIPT"
if grep -Fq 'StrictHostKeyChecking=no' "$SCRIPT"; then
    echo "frequency A/B helper must verify the router host key" >&2
    exit 1
fi
if grep -Eq 'uci([[:space:]]+-q)?[[:space:]]+(set|commit)|/etc/config/' "$SCRIPT"; then
    echo "frequency A/B helper must not persist router configuration" >&2
    exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin"
: > "$TMP/key"
: > "$TMP/known_hosts"
echo 748800000 > "$TMP/frequency"

cat > "$TMP/bin/ssh" <<'EOF'
#!/bin/sh
for arg in "$@"; do command=$arg; done
case "$command" in
    *'/etc/openwrt_release'*) echo 'r0-test' ;;
    *'nss-check -q && ax6-config-audit -q'*) exit 0 ;;
    *'compatible='*)
        echo 'compatible=qcom,ipq8074 redmi,ax6'
        echo 'boot_id=fixture-boot-id'
        echo 'auto_scale=0'
        echo "current_freq=$(cat "$AX6_FAKE_FREQ_FILE")"
        ;;
    *'cat /proc/sys/kernel/random/boot_id'*) echo 'fixture-boot-id' ;;
    *"printf '%s"*'/proc/sys/dev/nss/clock/current_freq'*)
        target=$(printf '%s\n' "$command" | grep -oE '748800000|1689600000' | head -n 1)
        [ -n "$target" ] || exit 1
        echo "$target" > "$AX6_FAKE_FREQ_FILE"
        ;;
    *'grep -q "qcom,ipq8074"'*) cat "$AX6_FAKE_FREQ_FILE" ;;
    *) exit 0 ;;
esac
EOF
chmod +x "$TMP/bin/ssh"

PATH="$TMP/bin:$PATH" AX6_FAKE_FREQ_FILE="$TMP/frequency" \
AX6_SSH_KEY="$TMP/key" AX6_KNOWN_HOSTS="$TMP/known_hosts" \
bash "$SCRIPT" status > "$TMP/status"
grep -Fq 'current_freq=748800000' "$TMP/status"

PATH="$TMP/bin:$PATH" AX6_FAKE_FREQ_FILE="$TMP/frequency" \
AX6_SSH_KEY="$TMP/key" AX6_EXPECTED_SOURCE_REVISION=r0-test \
AX6_KNOWN_HOSTS="$TMP/known_hosts" \
AX6_BUILD_COMMIT=193e5fbc276e AX6_FREQ_STATE_FILE="$TMP/state" \
bash "$SCRIPT" set high --confirm-runtime-write > "$TMP/high"
[ "$(cat "$TMP/frequency")" = 1689600000 ]

if PATH="$TMP/bin:$PATH" AX6_FAKE_FREQ_FILE="$TMP/frequency" \
    AX6_SSH_KEY="$TMP/key" AX6_EXPECTED_SOURCE_REVISION=r0-test \
    AX6_KNOWN_HOSTS="$TMP/known_hosts" \
    AX6_BUILD_COMMIT=deadbeef AX6_FREQ_STATE_FILE="$TMP/state" \
    bash "$SCRIPT" restore --confirm-runtime-write > "$TMP/wrong-restore" 2>&1; then
    echo "restore accepted a state file from a different build identity" >&2
    exit 1
fi
grep -Fq 'state build commit does not match' "$TMP/wrong-restore"
[ "$(cat "$TMP/frequency")" = 1689600000 ]

PATH="$TMP/bin:$PATH" AX6_FAKE_FREQ_FILE="$TMP/frequency" \
AX6_SSH_KEY="$TMP/key" AX6_EXPECTED_SOURCE_REVISION=r0-test \
AX6_KNOWN_HOSTS="$TMP/known_hosts" \
AX6_BUILD_COMMIT=193e5fbc276e AX6_FREQ_STATE_FILE="$TMP/state" \
bash "$SCRIPT" restore --confirm-runtime-write > "$TMP/restore"
[ "$(cat "$TMP/frequency")" = 748800000 ]
echo "test-ax6-nss-frequency-ab: PASS"
