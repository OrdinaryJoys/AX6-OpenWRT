#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ax6-boot-guard-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin"

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
[ "${1:-}" = -q ] && shift
case "${1:-}" in
	get)
		case "${2:-}" in
			network.globals.packet_steering|firewall.@defaults\[0\].flow_offloading|firewall.@defaults\[0\].flow_offloading_hw)
				printf '%s\n' 0
				;;
			ecm.general.disable_offloads|ecm.general.disable_gro_list)
				printf '%s\n' 1
				;;
			ecm.general.offload_host_ifaces)
				[ "${ECM_LAYERED:-0}" = 1 ] && printf '%s\n' br-lan || exit 1
				;;
			ecm.general.offload_physical_policy)
				[ "${ECM_LAYERED:-0}" = 1 ] && printf '%s\n' report || exit 1
				;;
			*) exit 1 ;;
		esac
		;;
	set|commit)
		printf '%s' "$1" >> "$UCI_LOG"
		shift
		printf ' %s' "$@" >> "$UCI_LOG"
		printf '\n' >> "$UCI_LOG"
		;;
	show)
		exit 0
		;;
	*) exit 1 ;;
esac
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$TMP/bin/uci" "$TMP/bin/logger"

run_guard() {
	: > "$TMP/uci.log"
	PATH="$TMP/bin:$PATH" UCI_LOG="$TMP/uci.log" ECM_LAYERED="$1" \
		sh -c '. "$1"; start' sh "$ROOT/AX6-IPQ/files/etc/init.d/ax6-boot-guard"
}

# A retained pre-layered config must acquire both AX6 policy keys without
# rewriting already-correct packet steering, flow offload, or GRO settings.
run_guard 0
grep -Fqx 'set ecm.general.offload_host_ifaces=br-lan' "$TMP/uci.log"
grep -Fqx 'set ecm.general.offload_physical_policy=report' "$TMP/uci.log"
grep -Fqx 'commit ecm' "$TMP/uci.log"
if grep -Fq 'set ecm.general.disable_' "$TMP/uci.log"; then
	echo 'boot guard rewrote an already-correct ECM boolean' >&2
	exit 1
fi

# Once migrated, the guard is idempotent.
run_guard 1
[ ! -s "$TMP/uci.log" ]

echo 'test-ax6-boot-guard: PASS'
