#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/openclash-dns-health-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin"

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
	'-q get openclash.config.enable') echo "${OC_ENABLED:-1}" ;;
	'-q get openclash.config.enable_redirect_dns') echo "${REDIRECT_MODE:-1}" ;;
	'-q get openclash.config.dns_port') echo 7874 ;;
	'-q get dhcp.@dnsmasq[0].server') echo "${DNSMASQ_SERVER:-127.0.0.1#7874}" ;;
	*) exit 1 ;;
esac
EOF

cat > "$TMP/bin/pidof" <<'EOF'
#!/bin/sh
[ "$1" = clash ] && echo "${CORE_PID:-1234}"
EOF

cat > "$TMP/bin/cut" <<'EOF'
#!/bin/sh
echo "${TEST_UPTIME:-1000}"
EOF

cat > "$TMP/probe" <<'EOF'
#!/bin/sh
[ "${PROBE_OK:-1}" = 1 ]
EOF

cat > "$TMP/openclash-init" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$RESTART_LOG"
[ "${RESTART_OK:-1}" = 1 ]
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
exit 0
EOF

chmod +x "$TMP/bin/"* "$TMP/probe" "$TMP/openclash-init"
export STATE_FILE="$TMP/state" PROBE_BIN="$TMP/probe"
export OPENCLASH_INIT="$TMP/openclash-init" RESTART_LOG="$TMP/restarts"
export STARTUP_GRACE=0 FAILURE_THRESHOLD=3 RESTART_COOLDOWN=300

run_health() {
	PATH="$TMP/bin:$PATH" "$ROOT/AX6-IPQ/files/usr/sbin/ax6-openclash-dns-health" --once
}

PROBE_OK=1 run_health
[ "$(cat "$STATE_FILE")" = '1234 1000 0 0' ]

if PROBE_OK=0 run_health; then exit 1; fi
if PROBE_OK=0 run_health; then exit 1; fi
[ ! -e "$RESTART_LOG" ]
PROBE_OK=0 run_health
grep -Fqx restart "$RESTART_LOG"
[ "$(cat "$STATE_FILE")" = '0 1000 0 1000' ]

# A new core PID preserves the cooldown and cannot trigger a restart storm.
: > "$RESTART_LOG"
CORE_PID=4321 TEST_UPTIME=1010 PROBE_OK=0 run_health || true
CORE_PID=4321 TEST_UPTIME=1011 PROBE_OK=0 run_health || true
CORE_PID=4321 TEST_UPTIME=1012 PROBE_OK=0 run_health || true
[ ! -s "$RESTART_LOG" ]

# A successful direct DNS query clears the failure counter.
CORE_PID=4321 TEST_UPTIME=1013 PROBE_OK=1 run_health
set -- $(cat "$STATE_FILE")
[ "$3" = 0 ]

# Disabled or non-owned DNS is never restarted.
: > "$RESTART_LOG"
OC_ENABLED=0 PROBE_OK=0 run_health
[ ! -e "$STATE_FILE" ]
[ ! -s "$RESTART_LOG" ]
OC_ENABLED=1 DNSMASQ_SERVER=1.1.1.1 PROBE_OK=0 run_health
[ ! -s "$RESTART_LOG" ]

# Probe mode exposes the real health result without changing state.
DNSMASQ_SERVER=127.0.0.1#7874 PROBE_OK=1 \
	PATH="$TMP/bin:$PATH" "$ROOT/AX6-IPQ/files/usr/sbin/ax6-openclash-dns-health" --probe
if DNSMASQ_SERVER=127.0.0.1#7874 PROBE_OK=0 \
	PATH="$TMP/bin:$PATH" "$ROOT/AX6-IPQ/files/usr/sbin/ax6-openclash-dns-health" --probe; then
	exit 1
fi

echo 'test-openclash-dns-health: PASS'
