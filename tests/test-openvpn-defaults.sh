#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/openvpn-defaults-test.XXXXXX")"
cleanup_test() {
	status=$?
	trap - EXIT HUP INT TERM
	rm -rf "$TMP"
	exit "$status"
}
trap cleanup_test EXIT HUP INT TERM
mkdir -p "$TMP/bin"

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
quiet=0
[ "${1:-}" = '-q' ] && { quiet=1; shift; }
cmd="${1:-}"
shift || true

case "$cmd:$*" in
	'get:network.OpenVPN')
		[ "${NETWORK_EXISTS:-0}" = 1 ] && printf '%s\n' interface || exit 1
		;;
	'show:network')
		if [ "${LEGACY_EXACT:-0}" = 1 ]; then
			printf "%s\n" \
				"network.myvpn=interface" \
				"network.myvpn.proto='openvpn'" \
				"network.vpn0=interface" \
				"network.vpn0.ifname='tun0'" \
				"network.vpn0.proto='none'"
		elif [ "${NETWORK_EXISTS:-0}" = 1 ]; then
			printf "%s\n" "network.OpenVPN=interface" "network.OpenVPN.device='tun0'"
		elif [ "${LEGACY_NETWORK:-0}" = 1 ]; then
			printf "%s\n" \
				"network.@interface[0]=interface" \
				"network.@interface[0].name='OpenVPN'" \
				"network.@interface[0].device='tun0'" \
				"network.@interface[0].proto='none'" \
				"network.@interface[0].auto='0'"
		fi
		;;
	'show:network.vpn0')
		[ "${LEGACY_EXACT:-0}" = 1 ] && printf '%s\n' \
			"network.vpn0=interface" "network.vpn0.ifname='tun0'" "network.vpn0.proto='none'"
		;;
	'get:network.myvpn') [ "${LEGACY_EXACT:-0}" = 1 ] && echo interface || exit 1 ;;
	'get:network.myvpn.proto') echo openvpn ;;
	'get:network.myvpn.enabled') echo 0 ;;
	'get:network.myvpn.ovpnproto') echo tcp-server ;;
	'get:network.myvpn.port') echo 1194 ;;
	'get:network.myvpn.ddns') echo example.com ;;
	'get:network.myvpn.server') echo '10.8.0.0 255.255.255.0' ;;
	'get:network.vpn0') [ "${LEGACY_EXACT:-0}" = 1 ] && echo interface || exit 1 ;;
	'get:network.vpn0.ifname') echo tun0 ;;
	'get:network.vpn0.proto') echo none ;;
	'get:network.@interface[0]') printf '%s\n' interface ;;
	'get:network.@interface[0].device') printf '%s\n' tun0 ;;
	'get:network.@interface[0].proto') printf '%s\n' none ;;
	'get:network.@interface[0].auto') printf '%s\n' 0 ;;
	'show:firewall')
		printf "%s\n" \
			"firewall.lan=zone" \
			"firewall.lan.name='lan'" \
			"firewall.openvpn=rule" \
			"firewall.legacy=rule"
		if [ "${LEGACY_EXACT:-0}" = 1 ]; then
			printf '%s\n' 'firewall.vpn=zone' 'firewall.vpntowan=forwarding' \
				'firewall.vpntolan=forwarding' 'firewall.lantovpn=forwarding'
		fi
		;;
	'get:firewall.lan.network') printf '%s\n' lan ;;
	'get:firewall.openvpn') printf '%s\n' rule ;;
	'get:firewall.vpn') [ "${LEGACY_EXACT:-0}" = 1 ] && echo zone || exit 1 ;;
	'get:firewall.vpn.name') echo vpn ;;
	'get:firewall.vpn.input'|'get:firewall.vpn.forward'|'get:firewall.vpn.output') echo ACCEPT ;;
	'get:firewall.vpn.masq') echo 1 ;;
	'get:firewall.vpn.network') echo vpn0 ;;
	'get:firewall.vpntowan'|'get:firewall.vpntolan'|'get:firewall.lantovpn')
		[ "${LEGACY_EXACT:-0}" = 1 ] && echo forwarding || exit 1 ;;
	'get:firewall.vpntowan.src'|'get:firewall.vpntolan.src') echo vpn ;;
	'get:firewall.vpntowan.dest') echo wan ;;
	'get:firewall.vpntolan.dest') echo lan ;;
	'get:firewall.lantovpn.src') echo lan ;;
	'get:firewall.lantovpn.dest') echo vpn ;;
	'get:openvpn.myvpn.enabled') printf '%s\n' "${SERVICE_ENABLED:-0}" ;;
	'get:firewall.legacy.name') printf '%s\n' Allow-OpenVPN ;;
	'get:firewall.legacy.src') printf '%s\n' wan ;;
	'get:firewall.legacy.dest_port') printf '%s\n' 1194 ;;
	'get:firewall.legacy.proto') printf '%s\n' tcp ;;
	'get:firewall.legacy.target') printf '%s\n' ACCEPT ;;
	'get:firewall.legacy.enabled') printf '%s\n' 0 ;;
	set:*|add_list:*|delete:*|commit:*) printf '%s %s\n' "$cmd" "$*" >> "$UCI_LOG" ;;
	*) [ "$quiet" -eq 1 ] && exit 1; exit 1 ;;
esac
EOF

cat > "$TMP/bin/logger" <<'EOF'
#!/bin/sh
exit 0
EOF

chmod +x "$TMP/bin/uci" "$TMP/bin/logger"
touch "$TMP/openvpn"
chmod +x "$TMP/openvpn"
export UCI_LOG="$TMP/uci.log"

PATH="$TMP/bin:$PATH" OPENVPN_BIN="$TMP/openvpn" SERVICE_ENABLED=0 NETWORK_EXISTS=0 \
	LEGACY_NETWORK=1 \
	sh "$ROOT/AX6-IPQ/files/etc/uci-defaults/zz-ax6-openvpn-defaults"

grep -Fqx 'delete network.@interface[0]' "$UCI_LOG"
grep -Fqx 'set network.OpenVPN=interface' "$UCI_LOG"
grep -Fqx 'set network.OpenVPN.device=tun0' "$UCI_LOG"
grep -Fqx 'add_list firewall.lan.network=OpenVPN' "$UCI_LOG"
grep -Fqx 'set firewall.openvpn.enabled=0' "$UCI_LOG"
grep -Fqx 'delete firewall.legacy' "$UCI_LOG"

: > "$UCI_LOG"
PATH="$TMP/bin:$PATH" OPENVPN_BIN="$TMP/openvpn" SERVICE_ENABLED=0 NETWORK_EXISTS=0 \
	LEGACY_NETWORK=0 LEGACY_EXACT=1 \
	sh "$ROOT/AX6-IPQ/files/etc/uci-defaults/zz-ax6-openvpn-defaults"

for deleted in network.myvpn network.vpn0 firewall.vpn firewall.vpntowan \
	firewall.vpntolan firewall.lantovpn; do
	grep -Fqx "delete $deleted" "$UCI_LOG"
done

: > "$UCI_LOG"
PATH="$TMP/bin:$PATH" OPENVPN_BIN="$TMP/openvpn" SERVICE_ENABLED=1 NETWORK_EXISTS=1 \
	sh "$ROOT/AX6-IPQ/files/etc/uci-defaults/zz-ax6-openvpn-defaults"

if grep -Fq 'network.OpenVPN=' "$UCI_LOG"; then
	echo 'existing OpenVPN network must not be recreated' >&2
	exit 1
fi
if grep -Fq 'firewall.openvpn.enabled=0' "$UCI_LOG"; then
	echo 'enabled OpenVPN server must not have its canonical rule disabled' >&2
	exit 1
fi
grep -Fqx 'delete firewall.legacy' "$UCI_LOG"

echo 'test-openvpn-defaults: PASS'
