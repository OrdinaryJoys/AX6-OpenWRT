#!/bin/sh
# AX6 odhcp6c orphan guard fixture test.
# Verifies: anchored matching pattern, multi-instance cleanup keeps the
# newest, stale single-instance cleanup on down+old, and no-op paths.
#
# Time-unit contract (S5-01): /proc/uptime is in seconds, while
# /proc/<pid>/stat field 22 (starttime) is in USER_HZ clock ticks since boot
# (getconf CLK_TCK). Every case therefore uses a physically possible pair
# (uptime_seconds * HZ >= starttime_ticks) and the age is
# uptime_seconds - starttime_ticks / HZ. The boundary cases assert the strict
# "> 120 s" trigger (121 s kills, 120 s does not).
#
# Negative control: point ODHCP6C_GUARD at the pre-patch guard bytes (the
# committed file before the S5-01 fix, e.g. `git show
# HEAD:AX6-IPQ/files/etc/hotplug.d/iface/90-ax6-odhcp6c-guard`); cases 3, 6
# and 7 must then fail because they detect the seconds-vs-ticks unit bug.
#
# shellcheck disable=SC1007 # Keep cd output independent of CDPATH.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
GUARD=${ODHCP6C_GUARD:-$ROOT/AX6-IPQ/files/etc/hotplug.d/iface/90-ax6-odhcp6c-guard}
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
echo "${CLK_TCK:-100}"
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
echo "${UPTIME_NOW:-300}"
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

# Guard exits 0 both when it acts and when it is a no-op; assert effect only.
assert_killed() {
	grep -Fxq "kill 101" "$KILL_LOG" || {
		echo "expected the stale odhcp6c instance to be killed" >&2
		exit 1
	}
}

assert_untouched() {
	if [ -s "$KILL_LOG" ]; then
		echo "expected no kill/logger action for a no-op case:" >&2
		cat "$KILL_LOG" >&2
		exit 1
	fi
	return 0
}

# 1) Normal state: single instance, interface up -> no-op.
: > "$KILL_LOG"
export CLK_TCK=100 PIDOF_OUT=101 PGREP_OUT=101 TS_101=1000 WAN6_UP=true UPTIME_NOW=300
run_guard
assert_untouched
grep -Fxq '^odhcp6c .* wan$' "$PATTERN_LOG"

# 2) Multi-instance: keep newest (102), kill old (101).
#    Ticks 1000/5000 are 10 s / 50 s into a 300 s boot at HZ=100.
: > "$KILL_LOG"
export PIDOF_OUT="101 102" PGREP_OUT="101 102" TS_101=1000 TS_102=5000 \
	WAN6_UP=true UPTIME_NOW=300
run_guard
assert_killed
if grep -Fq "kill 102" "$KILL_LOG"; then
	echo "test-ax6-odhcp6c-guard: newest instance was killed" >&2
	exit 1
fi

# 3) Single instance, interface down, started 10 s into a 300 s boot
#    (age 290 s) -> kill (stale holder). Pre-patch bytes compute a bogus
#    age and must fail this case.
: > "$KILL_LOG"
export PIDOF_OUT=101 PGREP_OUT=101 TS_101=1000 WAN6_UP=false UPTIME_NOW=300
run_guard
assert_killed

# 4) Single instance, interface down, started 299 s into a 300 s boot
#    (age 1 s) -> no-op.
: > "$KILL_LOG"
export PIDOF_OUT=101 PGREP_OUT=101 TS_101=29900 WAN6_UP=false UPTIME_NOW=300
run_guard
assert_untouched

# 5) No odhcp6c at all -> no-op.
: > "$KILL_LOG"
export PIDOF_OUT="" PGREP_OUT="" WAN6_UP=false UPTIME_NOW=300
run_guard
assert_untouched

# 6) Boundary of the strict "> 120 s" trigger at HZ=100, 300 s uptime:
#    started 179 s in -> age 121 -> kill; started 180 s in -> age 120 -> no-op.
: > "$KILL_LOG"
export PIDOF_OUT=101 PGREP_OUT=101 TS_101=17900 WAN6_UP=false UPTIME_NOW=300
run_guard
assert_killed
: > "$KILL_LOG"
export TS_101=18000
run_guard
assert_untouched

# 7) CLK_TCK=250 target: ticks must be divided by the configured HZ.
#    started 179 s in (44,750 ticks) -> age 121 -> kill;
#    started 180 s in (45,000 ticks) -> age 120 -> no-op.
: > "$KILL_LOG"
export CLK_TCK=250 PIDOF_OUT=101 PGREP_OUT=101 TS_101=44750 \
	WAN6_UP=false UPTIME_NOW=300
run_guard
assert_killed
: > "$KILL_LOG"
export TS_101=45000
run_guard
assert_untouched
export CLK_TCK=100

echo "test-ax6-odhcp6c-guard: PASS"
