#!/bin/sh

STATE_FILE="${STATE_FILE:-/var/run/ax6-openclash-dns-health.state}"
OPENCLASH_INIT="${OPENCLASH_INIT:-/etc/init.d/openclash}"
NSLOOKUP_BIN="${NSLOOKUP_BIN:-/usr/bin/nslookup}"
PROBE_NAME="${PROBE_NAME:-openwrt.org}"
INTERVAL="${INTERVAL:-30}"
QUERY_TIMEOUT="${QUERY_TIMEOUT:-3}"
STARTUP_GRACE="${STARTUP_GRACE:-60}"
FAILURE_THRESHOLD="${FAILURE_THRESHOLD:-3}"
RESTART_COOLDOWN="${RESTART_COOLDOWN:-300}"
DRY_RUN=0

log_notice() {
	logger -t ax6-openclash-dns-health "$1" 2>/dev/null || true
}

log_error() {
	logger -t ax6-openclash-dns-health -p user.error "$1" 2>/dev/null || true
}

valid_uint() {
	case "$1" in
		''|*[!0-9]*) return 1 ;;
	esac
}

valid_port() {
	valid_uint "$1" && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

uptime_seconds() {
	cut -d. -f1 /proc/uptime 2>/dev/null || printf '0\n'
}

read_state() {
	set -- $(cat "$STATE_FILE" 2>/dev/null || true)
	STATE_PID="${1:-0}"
	STATE_FIRST_SEEN="${2:-0}"
	STATE_FAILURES="${3:-0}"
	STATE_LAST_RESTART="${4:-0}"
	valid_uint "$STATE_PID" || STATE_PID=0
	valid_uint "$STATE_FIRST_SEEN" || STATE_FIRST_SEEN=0
	valid_uint "$STATE_FAILURES" || STATE_FAILURES=0
	valid_uint "$STATE_LAST_RESTART" || STATE_LAST_RESTART=0
}

write_state() {
	[ "$DRY_RUN" -eq 0 ] || return 0
	mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || return 1
	tmp="${STATE_FILE}.tmp.$$"
	printf '%s %s %s %s\n' "$1" "$2" "$3" "$4" > "$tmp" &&
		mv "$tmp" "$STATE_FILE"
}

openclash_dns_owner() {
	[ "$(uci -q get openclash.config.enable 2>/dev/null)" = 1 ] || return 1
	redirect="$(uci -q get openclash.config.enable_redirect_dns 2>/dev/null || true)"
	[ -n "$redirect" ] || redirect=1
	[ "$redirect" = 1 ] || return 1
	DNS_PORT="$(uci -q get openclash.config.dns_port 2>/dev/null || true)"
	[ -n "$DNS_PORT" ] || DNS_PORT=7874
	valid_port "$DNS_PORT" || return 1
	dns_servers="$(uci -q get 'dhcp.@dnsmasq[0].server' 2>/dev/null || true)"
	case " $dns_servers " in
		*" 127.0.0.1#${DNS_PORT} "*) return 0 ;;
	esac
	return 1
}

probe_dns() {
	if [ -n "${PROBE_BIN:-}" ]; then
		"$PROBE_BIN" "$DNS_PORT" "$PROBE_NAME"
		return
	fi

	"$NSLOOKUP_BIN" -type=a -port="$DNS_PORT" "$PROBE_NAME" 127.0.0.1 \
		>/dev/null 2>&1 &
	probe_pid=$!
	remaining="$QUERY_TIMEOUT"
	while [ "$remaining" -gt 0 ]; do
		if ! kill -0 "$probe_pid" 2>/dev/null; then
			wait "$probe_pid"
			return
		fi
		sleep 1
		remaining=$((remaining - 1))
	done
	if kill -0 "$probe_pid" 2>/dev/null; then
		kill "$probe_pid" 2>/dev/null || true
		wait "$probe_pid" 2>/dev/null || true
		return 1
	fi
	wait "$probe_pid"
}

health_once() {
	if ! openclash_dns_owner; then
		[ "$DRY_RUN" -eq 1 ] || rm -f "$STATE_FILE"
		return 0
	fi

	core_pid="$(pidof clash 2>/dev/null | awk '{ print $1 }')"
	valid_uint "$core_pid" || {
		# OpenClash's own procd/watchdog lifecycle owns a missing process. This
		# helper handles the distinct case where a live process stops answering.
		return 0
	}

	now="$(uptime_seconds)"
	valid_uint "$now" || now=0
	read_state
	if [ "$core_pid" != "$STATE_PID" ]; then
		write_state "$core_pid" "$now" 0 "$STATE_LAST_RESTART"
		[ "$STARTUP_GRACE" -eq 0 ] || return 0
		STATE_FIRST_SEEN="$now"
		STATE_FAILURES=0
	fi

	elapsed=$((now - STATE_FIRST_SEEN))
	[ "$elapsed" -ge "$STARTUP_GRACE" ] || return 0
	if probe_dns; then
		[ "$STATE_FAILURES" -eq 0 ] ||
			log_notice "OpenClash DNS recovered after ${STATE_FAILURES} failed probe(s)"
		write_state "$core_pid" "$STATE_FIRST_SEEN" 0 "$STATE_LAST_RESTART"
		return 0
	fi

	failures=$((STATE_FAILURES + 1))
	write_state "$core_pid" "$STATE_FIRST_SEEN" "$failures" "$STATE_LAST_RESTART"
	if [ "$failures" -lt "$FAILURE_THRESHOLD" ]; then
		log_error "OpenClash core DNS on 127.0.0.1:${DNS_PORT} failed probe ${failures}/${FAILURE_THRESHOLD}"
		return 1
	fi

	if [ "$STATE_LAST_RESTART" -gt 0 ] &&
	   [ $((now - STATE_LAST_RESTART)) -lt "$RESTART_COOLDOWN" ]; then
		log_error "OpenClash DNS remains unavailable; restart cooldown is active"
		return 1
	fi

	if [ "$DRY_RUN" -eq 1 ]; then
		log_notice "dry-run: would restart OpenClash after ${failures} failed DNS probes"
		return 1
	fi

	log_error "restarting OpenClash after ${failures} consecutive direct DNS probe failures"
	write_state 0 "$now" 0 "$now"
	"$OPENCLASH_INIT" restart >/dev/null 2>&1 || {
		log_error "OpenClash restart command failed"
		return 1
	}
	return 0
}

usage() {
	echo "Usage: $0 [--probe|--once|--daemon|--dry-run]"
}

mode=once
case "${1:-}" in
	''|--once) mode=once ;;
	--probe)
		openclash_dns_owner && probe_dns
		exit $?
		;;
	--daemon) mode=daemon ;;
	--dry-run) DRY_RUN=1; mode=once ;;
	-h|--help) usage; exit 0 ;;
	*) usage >&2; exit 64 ;;
esac

if [ "$mode" = daemon ]; then
	while :; do
		health_once || true
		sleep "$INTERVAL"
	done
fi

health_once
