#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/zerotier-health-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin"

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
	'-q get zerotier.global') echo zerotier ;;
	'-q get zerotier.global.enabled') echo "${ZT_ENABLED:-1}" ;;
	'-q show zerotier') printf '%s\n' 'zerotier.global=zerotier' 'zerotier.net=network' "zerotier.net.id='abc123'" ;;
	'-q get zerotier.net.id') echo abc123 ;;
	'-q get zerotier.net.join') exit 1 ;;
	'-q get zerotier.net.enabled') echo 1 ;;
	*) exit 1 ;;
esac
EOF

cat > "$TMP/bin/pidof" <<'EOF'
#!/bin/sh
[ "$1" = zerotier-one ] || exit 1
if [ -s "$PID_FILE" ]; then
	cat "$PID_FILE"
else
	echo "${ZT_PID:-2222}"
fi
EOF

cat > "$TMP/bin/cut" <<'EOF'
#!/bin/sh
echo "${TEST_UPTIME:-1000}"
EOF

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
case "$*" in
	'-j info') [ "${CLI_FAIL:-0}" = 0 ] || exit 1; echo info ;;
	'-j listnetworks') [ "${CLI_FAIL:-0}" = 0 ] || exit 1; echo networks ;;
	*) exit 1 ;;
esac
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
cat >/dev/null
case "$*" in
	*'@.online'*) echo "${ZT_ONLINE:-true}" ;;
	*'@[*].portDeviceName'*) echo ztmock0 ;;
	*'.nwid'*) echo abc123 ;;
	*'.status'*) echo "${NETWORK_STATUS:-OK}" ;;
	*'.allowManaged'*) echo "${ALLOW_MANAGED:-true}" ;;
	*'.assignedAddresses'*) echo 172.29.205.171/16 ;;
	*) exit 1 ;;
esac
EOF

cat > "$TMP/bin/ip" <<'EOF'
#!/bin/sh
[ "${KERNEL_ADDR:-1}" = 1 ] && echo '    inet 172.29.205.171/16 scope global ztmock0'
EOF

cat > "$TMP/zerotier-init" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$RESTART_LOG"
[ "${RECOVER_AFTER_NONZERO:-0}" = 1 ] && echo "${RECOVERED_PID:-4444}" > "$PID_FILE"
[ "${RESTART_OK:-1}" = 1 ]
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
exit 0
EOF

chmod +x "$TMP/bin/"* "$TMP/zerotier-init"
export STATE_FILE="$TMP/state" ZEROTIER_INIT="$TMP/zerotier-init"
export ZT_CLI_BIN="$TMP/bin/zerotier-cli" IP_BIN="$TMP/bin/ip"
export RESTART_LOG="$TMP/restarts" STARTUP_GRACE=0 FAILURE_THRESHOLD=3
export RESTART_COOLDOWN=300 RESTART_VERIFY_ATTEMPTS=1 RESTART_VERIFY_DELAY=0
export PID_FILE="$TMP/pid"

run_health() {
	PATH="$TMP/bin:$PATH" "$ROOT/AX6-IPQ/files/usr/sbin/ax6-zerotier-health" --once
}

KERNEL_ADDR=1 run_health
[ "$(cat "$STATE_FILE")" = '2222 1000 0 0' ]

if KERNEL_ADDR=0 run_health; then exit 1; fi
if KERNEL_ADDR=0 run_health; then exit 1; fi
[ ! -e "$RESTART_LOG" ]
KERNEL_ADDR=0 run_health
grep -Fqx restart "$RESTART_LOG" || {
	cat "$RESTART_LOG" >&2
	exit 1
}

# A new daemon PID remains protected by the previous restart cooldown.
: > "$RESTART_LOG"
ZT_PID=3333 TEST_UPTIME=1010 KERNEL_ADDR=0 run_health || true
ZT_PID=3333 TEST_UPTIME=1011 KERNEL_ADDR=0 run_health || true
ZT_PID=3333 TEST_UPTIME=1012 KERNEL_ADDR=0 run_health || true
[ ! -s "$RESTART_LOG" ]

# Control-plane transitions never cause local restart loops.
ZT_PID=3333 TEST_UPTIME=1013 ZT_ONLINE=false KERNEL_ADDR=0 run_health
NETWORK_STATUS=REQUESTING ZT_ONLINE=true KERNEL_ADDR=0 run_health
[ ! -s "$RESTART_LOG" ]

# Healthy state and disabled service clear counters/state.
NETWORK_STATUS=OK KERNEL_ADDR=1 run_health
set -- $(cat "$STATE_FILE")
[ "$3" = 0 ]
ZT_ENABLED=0 run_health
[ ! -e "$STATE_FILE" ]

# Upstream init can return non-zero after procd already replaced the daemon.
# Treat that as success only when the replacement PID is ONLINE.
rm -f "$STATE_FILE" "$PID_FILE"
: > "$RESTART_LOG"
ZT_ENABLED=1 NETWORK_STATUS=OK ZT_ONLINE=true TEST_UPTIME=2000 ZT_PID=5555 KERNEL_ADDR=0 RESTART_OK=0 \
	RECOVER_AFTER_NONZERO=1 run_health || true
ZT_ENABLED=1 NETWORK_STATUS=OK ZT_ONLINE=true TEST_UPTIME=2001 ZT_PID=5555 KERNEL_ADDR=0 RESTART_OK=0 \
	RECOVER_AFTER_NONZERO=1 run_health || true
ZT_ENABLED=1 NETWORK_STATUS=OK ZT_ONLINE=true TEST_UPTIME=2002 ZT_PID=5555 KERNEL_ADDR=0 RESTART_OK=0 \
	RECOVER_AFTER_NONZERO=1 run_health
grep -Fqx restart "$RESTART_LOG" || {
	cat "$RESTART_LOG" >&2
	exit 1
}
[ "$(cat "$PID_FILE")" = 4444 ]

# Probe mode distinguishes healthy, missing L3, and non-converged control plane.
ZT_ENABLED=1 KERNEL_ADDR=1 PATH="$TMP/bin:$PATH" \
	"$ROOT/AX6-IPQ/files/usr/sbin/ax6-zerotier-health" --probe
if ZT_ENABLED=1 KERNEL_ADDR=0 PATH="$TMP/bin:$PATH" \
	"$ROOT/AX6-IPQ/files/usr/sbin/ax6-zerotier-health" --probe; then
	exit 1
fi

echo 'test-zerotier-health: PASS'
