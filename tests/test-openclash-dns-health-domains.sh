#!/bin/sh
# Domain-sensitive V29 tests. All DNS, UCI, time, logging and restarts are mocks.
set -eu
ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TARGET="${DNS_HEALTH_TEST_TARGET:-$ROOT/AX6-IPQ/files/usr/sbin/ax6-openclash-dns-health}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ax6-v29-domains.XXXXXX")"
REAL_SLEEP="$(command -v sleep)"
cleanup() {
	# Only PIDs emitted by this harness's lookup stub are eligible for cleanup.
	if [ -f "$TMP/query-pids" ]; then
		while IFS= read -r child; do
			case "$child" in ''|*[!0-9]*) continue ;; esac
			kill "$child" 2>/dev/null || true
		done < "$TMP/query-pids"
	fi
	rm -rf "$TMP"
}
trap cleanup EXIT HUP INT TERM
mkdir -p "$TMP/bin"

cat > "$TMP/bin/uci" <<'MOCK'
#!/bin/sh
case "$*" in
	'-q get openclash.config.enable') printf '%s\n' "${OC_ENABLED:-1}" ;;
	'-q get openclash.config.enable_redirect_dns') printf '%s\n' "${REDIRECT_MODE:-1}" ;;
	'-q get openclash.config.dns_port') printf '%s\n' "${OC_PORT:-7874}" ;;
	'-q get dhcp.@dnsmasq[0].server') printf '%s\n' "${DNSMASQ_SERVER:-127.0.0.1#7874}" ;;
	*) exit 91 ;;
esac
MOCK
cat > "$TMP/bin/pidof" <<'MOCK'
#!/bin/sh
[ "$1" = clash ] && [ "${CORE_MISSING:-0}" = 0 ] && printf '%s\n' "${CORE_PID:-1234}"
MOCK
cat > "$TMP/bin/cut" <<'MOCK'
#!/bin/sh
[ "$*" = '-d. -f1 /proc/uptime' ] || exit 92
printf '%s\n' "${TEST_UPTIME:-1000}"
MOCK
cat > "$TMP/bin/logger" <<'MOCK'
#!/bin/sh
printf '%s\n' "$*" >> "$MESSAGE_LOG"
MOCK
cat > "$TMP/probe" <<'MOCK'
#!/bin/sh
printf '%s|%s\n' "$1" "$2" >> "$PROBE_LOG"
case "$2" in
	"${PROBE_NAME:-openwrt.org}") [ "${PRIMARY_OK:-1}" = 1 ] ;;
	"${POLICY_PROBE_NAME:-services.googleapis.cn}") [ "${POLICY_OK:-1}" = 1 ] ;;
	*) exit 93 ;;
esac
MOCK
cat > "$TMP/openclash-init" <<'MOCK'
#!/bin/sh
printf '%s\n' "$*" >> "$RESTART_LOG"
[ "${RESTART_OK:-1}" = 1 ]
MOCK
cat > "$TMP/nslookup" <<'MOCK'
#!/bin/sh
printf '%s|%s|%s|%s\n' "$1" "$2" "$3" "$4" >> "$QUERY_LOG"
printf '%s\n' "$$" >> "$QUERY_PID_FILE"
[ "$#" = 4 ] && [ "$1" = -type=a ] && [ "$2" = -port=7874 ] &&
	[ "$4" = 127.0.0.1 ] || exit 94
case "$3" in
	"${PROBE_NAME:-openwrt.org}")
		[ "${PRIMARY_QUERY_SLEEP:-0}" = 0 ] || exec "$REAL_SLEEP" 30
		[ "${PRIMARY_OK:-1}" = 1 ] ;;
	"${POLICY_PROBE_NAME:-services.googleapis.cn}")
		[ "${POLICY_QUERY_SLEEP:-0}" = 0 ] || exec "$REAL_SLEEP" 30
		[ "${POLICY_OK:-1}" = 1 ] ;;
	*) exit 95 ;;
esac
MOCK
chmod +x "$TMP/bin/"* "$TMP/probe" "$TMP/openclash-init" "$TMP/nslookup"
export STATE_FILE="$TMP/state" OPENCLASH_INIT="$TMP/openclash-init"
export PROBE_LOG="$TMP/probes" MESSAGE_LOG="$TMP/messages" RESTART_LOG="$TMP/restarts"
export QUERY_LOG="$TMP/queries" QUERY_PID_FILE="$TMP/query-pids" REAL_SLEEP
export NSLOOKUP_BIN="$TMP/nslookup"
EXPECTED_TWO="$(printf '7874|openwrt.org\n7874|services.googleapis.cn')"
EXPECTED_QUERY_TWO="$(printf '%s\n' '-type=a|-port=7874|openwrt.org|127.0.0.1' '-type=a|-port=7874|services.googleapis.cn|127.0.0.1')"

fail() { printf 'V29 assertion failed: %s\n' "$*" >&2; exit 1; }
equal() { [ "$1" = "$2" ] || fail "$3: expected [$2], actual [$1]"; }
no_restart() { [ ! -s "$RESTART_LOG" ] || fail "unexpected mocked restart"; }
state_is() { equal "$(cat "$STATE_FILE")" "$1" state; }
probe_is() { equal "$(cat "$PROBE_LOG")" "$1" 'ordered port/domain probes'; }
logged() { grep -Fq -- "$1" "$MESSAGE_LOG" || fail "missing log: $1"; }
restart_count() { equal "$(wc -l < "$RESTART_LOG" | tr -d ' ')" "$1" 'restart count'; }
reset_case() {
	export OC_ENABLED=1 REDIRECT_MODE=1 OC_PORT=7874 DNSMASQ_SERVER=127.0.0.1#7874
	export CORE_PID=1234 CORE_MISSING=0 TEST_UPTIME=1000 STARTUP_GRACE=0
	export FAILURE_THRESHOLD=3 RESTART_COOLDOWN=300 RESTART_OK=1
	export PRIMARY_OK=1 POLICY_OK=1 PRIMARY_QUERY_SLEEP=0 POLICY_QUERY_SLEEP=0 QUERY_TIMEOUT=1
	export PROBE_NAME=openwrt.org POLICY_PROBE_NAME=services.googleapis.cn PROBE_BIN="$TMP/probe"
	rm -f "$STATE_FILE"
	: > "$PROBE_LOG"; : > "$MESSAGE_LOG"; : > "$RESTART_LOG"; : > "$QUERY_LOG"
	: > "$QUERY_PID_FILE"
}
run_expect() {
	expected_status="$1"; mode_arg="$2"
	: > "$PROBE_LOG"; : > "$QUERY_LOG"
	if PATH="$TMP/bin:$PATH" sh "$TARGET" "$mode_arg" > "$TMP/output" 2>&1; then
		actual_status=0
	else
		actual_status=$?
	fi
	equal "$actual_status" "$expected_status" "exit for $mode_arg"
}
queries_reaped() {
	while IFS= read -r child; do
		kill -0 "$child" 2>/dev/null && fail "lookup PID $child remains alive"
	done < "$QUERY_PID_FILE"
	# The recorded children have exited; do not keep stale PIDs for trap cleanup.
	: > "$QUERY_PID_FILE"
}
policy_discriminator() {
	reset_case
	export POLICY_OK=0
	run_expect 1 --probe
	probe_is "$EXPECTED_TWO"
	[ ! -e "$STATE_FILE" ] || fail '--probe created state'
	no_restart
}
check_preservation() {
	[ -x "$ROOT/AX6-IPQ/files/usr/sbin/ax6-openclash-dns-health" ] || fail 'source script not executable'
	sh -n "$TARGET"
	keep="${DNS_HEALTH_KEEP_TARGET:-$ROOT/AX6-IPQ/files/etc/sysupgrade.conf}"
	init="${DNS_HEALTH_INIT_TARGET:-$ROOT/AX6-IPQ/files/etc/init.d/ax6-openclash-dns-health}"
	equal "$(grep -Fxc /usr/sbin/ax6-openclash-dns-health "$keep")" 1 'keep entry count'
	grep -Fqx 'PROG=/usr/sbin/ax6-openclash-dns-health' "$init" || fail 'init path mismatch'
	# Assert the literal variable in the installed init.
	# shellcheck disable=SC2016
	grep -Fq 'procd_set_param command "$PROG" --daemon' "$init" || fail 'init daemon command mismatch'
	mkdir -p "$TMP/rootfs/usr/sbin"
	cp "$TARGET" "$TMP/rootfs/usr/sbin/ax6-openclash-dns-health"
	# Static preservation-list resolution only; not an executed sysupgrade.
	awk '/^[[:space:]]*#/ || /^[[:space:]]*$/ {next} {print}' "$keep" |
		grep -Fqx /usr/sbin/ax6-openclash-dns-health
	[ -f "$TMP/rootfs/usr/sbin/ax6-openclash-dns-health" ] || fail 'keep entry has no fixture source'
	cmp -s "$TARGET" "$TMP/rootfs/usr/sbin/ax6-openclash-dns-health" || fail 'staged script changed'
}
if [ "${1:-}" = --policy-regression ]; then
	policy_discriminator
	echo 'V29 policy-only discriminator: PASS'
	exit 0
fi
if [ "${1:-}" = --preservation-only ]; then
	check_preservation
	echo 'V29 preservation discriminator: PASS'
	exit 0
fi

reset_case
run_expect 0 --probe
probe_is "$EXPECTED_TWO"; no_restart
[ ! -e "$STATE_FILE" ] || fail '--probe created state'
unset PROBE_NAME POLICY_PROBE_NAME
run_expect 0 --probe; probe_is "$EXPECTED_TWO"
printf '1234 100 2 0\n' > "$STATE_FILE"
run_expect 0 --once
state_is '1234 100 0 0'; probe_is "$EXPECTED_TWO"; no_restart
logged 'recovered after 2 failed probe(s)'
export PROBE_NAME=primary.example POLICY_PROBE_NAME=policy.example
run_expect 0 --probe
probe_is "$(printf '7874|primary.example\n7874|policy.example')"
export POLICY_PROBE_NAME=''
run_expect 0 --probe
probe_is "$(printf '7874|primary.example\n7874|services.googleapis.cn')"
echo 'V29-01 dual success, recovery and explicit/default overrides: PASS'

policy_discriminator
run_expect 1 --once
state_is '1234 1000 1 0'; logged 'failed services.googleapis.cn probe 1/3'; no_restart
run_expect 1 --once
state_is '1234 1000 2 0'; no_restart
run_expect 0 --once
state_is '0 1000 0 1000'; restart_count 1
equal "$(cat "$RESTART_LOG")" restart 'restart argv'
logged '3 consecutive DNS probe failures (services.googleapis.cn)'
echo 'V29-02 policy-only failure and exact threshold: PASS'

reset_case
export PRIMARY_OK=0 POLICY_OK=0
run_expect 1 --probe; probe_is '7874|openwrt.org'; no_restart
run_expect 1 --once; state_is '1234 1000 1 0'; probe_is '7874|openwrt.org'
logged 'failed openwrt.org probe 1/3'
run_expect 1 --once; state_is '1234 1000 2 0'; no_restart
run_expect 0 --once; state_is '0 1000 0 1000'; restart_count 1
echo 'V29-03 primary failure short-circuits, one failure per health cycle: PASS'

reset_case
export POLICY_OK=0
run_expect 1 --once; run_expect 1 --once
export POLICY_OK=1
run_expect 0 --once; state_is '1234 1000 0 0'; no_restart
export POLICY_OK=0
run_expect 1 --once; state_is '1234 1000 1 0'; no_restart
run_expect 1 --once; no_restart
run_expect 0 --once; restart_count 1
echo 'V29-04 transient recovery resets consecutive failure threshold: PASS'

reset_case
export STARTUP_GRACE=60 POLICY_OK=0
run_expect 0 --once; probe_is ''; state_is '1234 1000 0 0'
export TEST_UPTIME=1059
run_expect 0 --once; probe_is ''; no_restart
export TEST_UPTIME=1060
run_expect 1 --once; state_is '1234 1000 1 0'; probe_is "$EXPECTED_TWO"
export TEST_UPTIME=1061
run_expect 1 --once
export TEST_UPTIME=1062
run_expect 0 --once; state_is '0 1062 0 1062'; restart_count 1
export CORE_PID=4321 TEST_UPTIME=1070
run_expect 0 --once; state_is '4321 1070 0 1062'; probe_is ''
export TEST_UPTIME=1130
run_expect 1 --once
export TEST_UPTIME=1131
run_expect 1 --once
export TEST_UPTIME=1132
run_expect 1 --once; state_is '4321 1070 3 1062'; restart_count 1
logged 'services.googleapis.cn remains unavailable; restart cooldown is active'
export TEST_UPTIME=1361
run_expect 1 --once; restart_count 1
export TEST_UPTIME=1362
run_expect 0 --once; state_is '0 1362 0 1362'; restart_count 2
reset_case
export FAILURE_THRESHOLD=1 POLICY_OK=0 RESTART_OK=0
run_expect 1 --once; state_is '0 1000 0 1000'; restart_count 1
logged 'OpenClash restart command failed'
export TEST_UPTIME=1001
run_expect 1 --once; restart_count 1
echo 'V29-05 startup grace, PID change, exact cooldown boundary and failed restart: PASS'

reset_case
unset PROBE_BIN
run_expect 0 --probe
equal "$(cat "$QUERY_LOG")" "$EXPECTED_QUERY_TWO" 'nslookup exact argv/order'; queries_reaped; no_restart
export POLICY_OK=0
run_expect 1 --once
equal "$(cat "$QUERY_LOG")" "$EXPECTED_QUERY_TWO" 'query policy failure'
state_is '1234 1000 1 0'; logged 'services.googleapis.cn'; queries_reaped; no_restart
export PRIMARY_OK=0 POLICY_OK=1
run_expect 1 --probe
equal "$(cat "$QUERY_LOG")" '-type=a|-port=7874|openwrt.org|127.0.0.1' 'query primary short-circuit'; queries_reaped
export PRIMARY_OK=1 POLICY_QUERY_SLEEP=1
started="$(date +%s)"
run_expect 1 --once
elapsed=$(( $(date +%s) - started ))
[ "$elapsed" -ge 1 ] && [ "$elapsed" -le 5 ] || fail "second-query timeout took ${elapsed}s"
equal "$(cat "$QUERY_LOG")" "$EXPECTED_QUERY_TWO" 'policy timeout invocation'
state_is '1234 1000 2 0'; logged 'services.googleapis.cn'; queries_reaped; no_restart
echo "V29-06 mocked real-query argv, failure and second-query timeout (${elapsed}s), children reaped: PASS"

reset_case
printf '1234 100 2 0\n' > "$STATE_FILE"
cp "$STATE_FILE" "$TMP/expected-state"
run_expect 0 --probe; cmp -s "$STATE_FILE" "$TMP/expected-state" || fail 'probe success changed state'
export POLICY_OK=0
run_expect 1 --probe; cmp -s "$STATE_FILE" "$TMP/expected-state" || fail 'probe failure changed state'; no_restart
run_expect 1 --dry-run
cmp -s "$STATE_FILE" "$TMP/expected-state" || fail 'dry-run threshold changed state'
logged 'dry-run: would restart OpenClash after 3 failed DNS probes (services.googleapis.cn)'; no_restart
export POLICY_OK=1
run_expect 0 --dry-run
cmp -s "$STATE_FILE" "$TMP/expected-state" || fail 'dry-run recovery changed state'; no_restart
export POLICY_OK=0 CORE_PID=4321
run_expect 1 --dry-run
cmp -s "$STATE_FILE" "$TMP/expected-state" || fail 'dry-run PID change changed state'; no_restart
export OC_ENABLED=0
run_expect 0 --dry-run
cmp -s "$STATE_FILE" "$TMP/expected-state" || fail 'dry-run non-owner deleted state'; no_restart
reset_case
export POLICY_OK=0 FAILURE_THRESHOLD=1
run_expect 1 --dry-run
[ ! -e "$STATE_FILE" ] || fail 'dry-run created previously absent state'
logged '(services.googleapis.cn)'; no_restart
for owner_case in disabled redirect external_dns invalid_port missing_core; do
	reset_case
	printf '1234 100 2 0\n' > "$STATE_FILE"
	export POLICY_OK=0
	case "$owner_case" in
		disabled) export OC_ENABLED=0 ;;
		redirect) export REDIRECT_MODE=0 ;;
		external_dns) export DNSMASQ_SERVER=1.1.1.1 ;;
		invalid_port) export OC_PORT=invalid ;;
		missing_core) export CORE_MISSING=1 ;;
	esac
	run_expect 0 --once; probe_is ''; no_restart
	if [ "$owner_case" = missing_core ]; then
		state_is '1234 100 2 0'
	else
		[ ! -e "$STATE_FILE" ] || fail "non-owner $owner_case retained stale state"
	fi
done
echo 'V29-07 probe/dry-run state immutability and owner/PID boundaries: PASS'

check_preservation
sed '\|^/usr/sbin/ax6-openclash-dns-health$|d' "$keep" > "$TMP/missing-keep"
cp "$keep" "$TMP/duplicate-keep"
printf '/usr/sbin/ax6-openclash-dns-health\n' >> "$TMP/duplicate-keep"
for broken_keep in missing duplicate; do
	if DNS_HEALTH_KEEP_TARGET="$TMP/$broken_keep-keep" sh "$0" --preservation-only > "$TMP/keep-negative" 2>&1; then
		fail "$broken_keep keep entry passed preservation gate"
	fi
	grep -Fq 'keep entry count: expected [1]' "$TMP/keep-negative" || fail 'keep negative control failed for unrelated reason'
done
echo 'V29-08 source/install path and unique keep entry, static staging fixture: PASS (no upgrade executed)'

old="$ROOT/tests/fixtures/openclash-dns-health-5ceaf77.sh"
old_expected=31b2257f04322cab0264b173235c198ac21dc6b33692b7455da4f1e0e2ef2417
if command -v sha256sum >/dev/null 2>&1; then old_hash="$(sha256sum "$old" | awk '{print $1}')"
else old_hash="$(shasum -a 256 "$old" | awk '{print $1}')"; fi
equal "$old_hash" "$old_expected" 'exact old 5ceaf77 helper fixture SHA256'
if DNS_HEALTH_TEST_TARGET="$old" sh "$0" --policy-regression > "$TMP/negative-control" 2>&1; then
	fail 'old single-probe helper unexpectedly passed policy-failure discriminator'
fi
grep -Fq 'exit for --probe: expected [1], actual [0]' "$TMP/negative-control" ||
	fail 'old helper negative control failed for an unrelated reason'
echo 'V29 negative control: exact 5ceaf77 helper rejected (policy failure incorrectly returned healthy)'
echo 'test-openclash-dns-health-domains: PASS (all restart, DNS and UCI operations mocked)'
