#!/bin/sh
# AX6 R-11 OpenClash reload-fix injector test.
# Verifies the injector transforms the upstream reload_service() anchors into
# the exact self-healing block, is idempotent, and fails hard on structural
# upstream drift.

set -eu

# shellcheck disable=SC1007 # Keep cd output independent of CDPATH.
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
HELPER="$ROOT/.github/scripts/inject-openclash-r11-reload-fix.sh"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/openclash-r11-inject.XXXXXX")
cleanup_test() {
	status=$?
	trap - EXIT HUP INT TERM
	rm -rf "$TMP"
	exit "$status"
}
trap cleanup_test EXIT HUP INT TERM

# Minimal upstream-shaped fixture: reload_service() excerpt with the exact
# anchors the injector matches. Trailing whitespace is significant.
cat > "$TMP/upstream" <<'FIXTURE'
reload_service()
{
   get_config
   MAX_RELOAD=10
   if pidof clash >/dev/null && [ "$enable" == "1" ] && [ "$1" == "firewall" ]; then
      sleep 5
      NOW_TS=$(date +%s)
      RELOAD_COUNT=$(grep "Reload OpenClash Firewall Rules...$" "$LOG_FILE" | wc -l)
      if [ "$RELOAD_COUNT" -ge "$MAX_RELOAD" ]; then
         LOG_OUT "【${CUR_RELOAD_NUM}/$MAX_RELOAD】Skip Reload OpenClash Firewall Rules Until 5 Minutes Later..."
         exit 0
      fi
      LOG_OUT "【${CUR_RELOAD_NUM}/$MAX_RELOAD】Reload OpenClash Firewall Rules..."
      revert_firewall
      do_run_mode
      check_core_status &
   fi
   if pidof clash >/dev/null && [ "$enable" == "1" ] && [ "$1" == "manual" ]; then
      LOG_OUT "Manually Reload Firewall Rules..."
      revert_firewall
      do_run_mode
      check_core_status &
   fi
}
FIXTURE

cp "$TMP/upstream" "$TMP/target"
"$HELPER" "$TMP/target"

# The three fix pieces must all be present.
grep -Fq 'if nft list chain inet fw4 openclash 2>/dev/null | grep -q "counter" ||' "$TMP/target"
grep -Fq 'OpenClash Rules Missing After fw4 Reload, Force Restore...' "$TMP/target"
test "$(grep -Fc '      set_firewall' "$TMP/target")" -eq 2
# The rate-limit skip must be reachable only through the sentinel guard.
test "$(grep -Fxc '            exit 0' "$TMP/target")" -eq 1
# The original block structure must survive (balanced fi pairs).
test "$(grep -Fxc '      fi' "$TMP/target")" -eq 1

# Idempotency: a second run is a no-op.
"$HELPER" "$TMP/target"
"$HELPER" "$TMP/target"

# Structural drift: the swallowed "exit 0" line changed -> fail hard, no
# partial patch (file must stay byte-identical to upstream).
sed 's/^         exit 0$/         exit 1/' "$TMP/upstream" > "$TMP/drift-exit"
cp "$TMP/drift-exit" "$TMP/drift-expected"
if "$HELPER" "$TMP/drift-exit" >/dev/null 2>&1; then
	echo "test-openclash-r11-inject: drifted exit line unexpectedly accepted" >&2
	exit 1
fi
if ! cmp -s "$TMP/drift-exit" "$TMP/drift-expected"; then
	echo "test-openclash-r11-inject: drifted input was modified on failure" >&2
	exit 1
fi

# Structural drift: the background check removed -> fail hard.
sed 's/      check_core_status &/      check_core_status/' "$TMP/upstream" > "$TMP/drift-core"
if "$HELPER" "$TMP/drift-core" >/dev/null 2>&1; then
	echo "test-openclash-r11-inject: drifted core check unexpectedly accepted" >&2
	exit 1
fi

echo "test-openclash-r11-inject: PASS"
