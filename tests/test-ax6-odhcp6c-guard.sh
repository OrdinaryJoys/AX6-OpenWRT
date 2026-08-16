#!/bin/sh
# AX6 odhcp6c orphan guard fixture test.
# Verifies: anchored matching pattern, multi-instance cleanup keeps the
# newest, stale single-instance cleanup on down+old, and no-op paths.

set -eu

# shellcheck disable=SC1007 # Keep cd output independent of CDPATH.
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
GUARD="$ROOT/AX6-IPQ/files/etc/hotplug.d/iface/90-ax6-odhcp6c-guard"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/odhcp6c-guard-test.XXXXXX")
cleanup_test() {
	status=$?
	trap - EXIT HUP INT TERM
	rm -rf "$TMP"
	exit "$status"
}
trap cleanup_test EXIT HUP INT TERM

mkdir -p "$TMP/bin"

cat > "$TMP/bin/pidof" <<'EOF'
#!/bin/sh
echo "${PIDOF_OUT:-101}"
EOF

cat > "$TMP/bin/pgrep" <<'EOF'
#!/bin/sh
echo "$2" > "${PATTERN_LOG:?}"
echo "${PGREP_OUT:-101}"
EOF

cat > "$TMP/bin/awk" <<'EOF'
#!/bin/sh
# $2 = /proc/<pid>/stat -> starttime from env table
f=$2
d=${f%/stat}
pid=${d##*/}
eval "echo \${TS_$pid:-999999}"
EOF

cat > "$TMP/bin/getconf" <<'EOF'
#!/bin/sh
echo 100
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
echo "${WAN6_UP:-true}"
EOF

cat > "$TMP/bin/ifstatus" <<'EOF'
#!/bin/sh
exit 0
EOF

cat > "$TMP/bin/kill" <<'EOF'
#!/bin/sh
echo "kill $*" >> "${KILL_LOG:?}"
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
echo "logger $*" >> "${KILL_LOG:?}"
EOF

cat > "$TMP/bin/cut" <<'EOF'
#!/bin/sh
echo "${UPTIME_NOW:-100000}"
EOF

cat > "$TMP/bin/sleep" <<'EOF'
#!/bin/sh
exit 0
EOF

chmod +x "$TMP/bin/"*
mkdir -p "$TMP/proc/101" "$TMP/proc/102"
touch "$TMP/proc/101/stat" "$TMP/proc/102/stat" "$TMP/proc/uptime"
export PATH="$TMP/bin:$PATH"
export KILL_LOG="$TMP/kills" PATTERN_LOG="$TMP/pattern" PROC_ROOT="$TMP/proc"

run_guard() {
	ACTION=ifup INTERFACE=wan6 DEVICE=wan "$GUARD"
}

# 1) Normal state: single instance, interface up -> no-op.
: > "$KILL_LOG"
export PIDOF_OUT=101 PGREP_OUT=101 TS_101=5000 WAN6_UP=true UPTIME_NOW=100000
run_guard
test ! -s "$KILL_LOG"
grep -Fxq '^odhcp6c .* wan$' "$PATTERN_LOG"

# 2) Multi-instance: keep newest (102), kill old (101).
: > "$KILL_LOG"
export PIDOF_OUT="101 102" PGREP_OUT="101 102" TS_101=1000 TS_102=5000 \
	WAN6_UP=true UPTIME_NOW=100000
run_guard
grep -Fxq "kill 101" "$KILL_LOG"
if grep -Fq "kill 102" "$KILL_LOG"; then
	echo "test-ax6-odhcp6c-guard: newest instance was killed" >&2
	exit 1
fi

# 3) Single instance, interface down, older than 120s -> kill (stale holder).
: > "$KILL_LOG"
export PIDOF_OUT=101 PGREP_OUT=101 TS_101=1000 WAN6_UP=false UPTIME_NOW=100000
run_guard
grep -Fxq "kill 101" "$KILL_LOG"

# 4) Single instance, interface down, younger than 120s -> no-op.
: > "$KILL_LOG"
export PIDOF_OUT=101 PGREP_OUT=101 TS_101=99000 WAN6_UP=false UPTIME_NOW=100000
run_guard
test ! -s "$KILL_LOG"

# 5) No odhcp6c at all -> no-op.
: > "$KILL_LOG"
export PIDOF_OUT="" PGREP_OUT="" WAN6_UP=false UPTIME_NOW=100000
run_guard
test ! -s "$KILL_LOG"

echo "test-ax6-odhcp6c-guard: PASS"
