#!/bin/sh
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ax6-audit-zerotier-test.XXXXXX")"
cleanup_test() {
	status=$?
	trap - EXIT HUP INT TERM
	rm -rf "$TMP"
	exit "$status"
}
trap cleanup_test EXIT HUP INT TERM
mkdir -p "$TMP/bin" "$TMP/fw"

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
case "$*" in
    '-q show wireless') printf '%s\n' 'wireless.radio0=wifi-device' ;;
    '-q show network')
        [ "${OPENVPN_NETWORK:-0}" = 1 ] && printf '%s\n' 'network.legacyvpn=interface'
        ;;
    '-q show zerotier')
        if [ "${UCI_SCHEMA:-current}" = legacy ]; then
            printf '%s\n' "zerotier.legacy=zerotier" \
                "zerotier.legacy.join='other123'" "zerotier.legacy.join='abc123'"
        else
            printf '%s\n' "zerotier.global=zerotier" "zerotier.net=network" \
                "zerotier.net.id='abc123'"
        fi
        ;;
    '-q show openvpn')
        [ "${OPENVPN_INSTALLED:-0}" = 1 ] && printf '%s\n' 'openvpn.server=openvpn'
        ;;
    '-q show firewall')
        [ "${OPENVPN_RULE:-0}" = 1 ] && printf '%s\n' 'firewall.ovpn=rule'
        ;;
    '-q get wireless.radio0.band') echo 2g ;;
    '-q get wireless.radio0.htmode') echo HE40 ;;
    '-q get wireless.radio0.ht_coex') echo 1 ;;
    '-q get wireless.radio0.noscan') exit 1 ;;
    '-q get ecm.general.disable_offloads'|'-q get ecm.general.disable_gro_list')
        [ "${ECM_POLICY_MISSING:-0}" = 0 ] && echo 1 || exit 1
        ;;
    '-q get ecm.general.offload_host_ifaces')
        [ "${ECM_POLICY_MISSING:-0}" = 0 ] && echo br-lan || exit 1
        ;;
    '-q get ecm.general.offload_physical_policy')
        [ "${ECM_POLICY_MISSING:-0}" = 0 ] && echo report || exit 1
        ;;
    '-q get zerotier.global') [ "${UCI_SCHEMA:-current}" != legacy ] && echo zerotier ;;
    '-q get zerotier.global.enabled') echo "${ZT_ENABLED:-1}" ;;
    '-q get zerotier.global.fw_allow_input') echo "${FW_ALLOW_INPUT:-1}" ;;
    '-q get zerotier.net.id') echo abc123 ;;
    '-q get zerotier.net.enabled') echo 1 ;;
    '-q get zerotier.net.fw_allow_input') echo "${NETWORK_ALLOW_INPUT:-0}" ;;
    '-q get zerotier.net.fw_allow_forward'|'-q get zerotier.net.fw_allow_masq') echo 0 ;;
    '-q get zerotier.net.allow_default'|'-q get zerotier.net.allow_global'|'-q get zerotier.net.allow_dns') echo 0 ;;
    '-q get zerotier.legacy.id') exit 1 ;;
    '-q get zerotier.legacy.join') echo 'other123 abc123' ;;
    '-q get zerotier.legacy.enabled') echo "${ZT_ENABLED:-1}" ;;
    '-q get zerotier.legacy.fw_allow_input') echo "${FW_ALLOW_INPUT:-1}" ;;
    '-q get zerotier.legacy.fw_allow_forward'|'-q get zerotier.legacy.fw_allow_masq') echo 0 ;;
    '-q get zerotier.legacy.allow_default') echo "${LEGACY_ALLOW_DEFAULT:-0}" ;;
    '-q get zerotier.legacy.allow_global'|'-q get zerotier.legacy.allow_dns') echo 0 ;;
    '-q get firewall.zerotier_input.type') echo nftables ;;
    '-q get firewall.zerotier_input.path') echo "$ZT_FW_PATH/input.nft" ;;
    '-q get firewall.zerotier_input.position') echo chain-pre ;;
    '-q get firewall.zerotier_input.chain') echo input ;;
    '-q get firewall.zerotier_forward.type'|'-q get firewall.zerotier_srcnat.type') echo nftables ;;
    '-q get firewall.zerotier_forward.path') echo "$ZT_FW_PATH/forward.nft" ;;
    '-q get firewall.zerotier_srcnat.path') echo "$ZT_FW_PATH/srcnat.nft" ;;
    '-q get firewall.zerotier_forward.position'|'-q get firewall.zerotier_srcnat.position') echo chain-pre ;;
    '-q get firewall.zerotier_forward.chain') echo forward ;;
    '-q get firewall.zerotier_srcnat.chain') echo srcnat ;;
    '-q get openvpn.server.enabled') echo "${OPENVPN_ENABLED:-0}" ;;
    '-q get network.legacyvpn.proto') echo openvpn ;;
    '-q get network.legacyvpn.device'|'-q get network.legacyvpn.ifname'|'-q get network.legacyvpn.auto') exit 1 ;;
    '-q get firewall.ovpn.src') echo wan ;;
    '-q get firewall.ovpn.dest_port') echo 1194 ;;
    '-q get firewall.ovpn.target') echo ACCEPT ;;
    '-q get firewall.ovpn.enabled') echo "${OPENVPN_RULE_ENABLED:-1}" ;;
    '-q get firewall.vpn') [ "${OPENVPN_LEGACY_FW:-0}" = 1 ] && echo zone || exit 1 ;;
    '-q get firewall.vpn.name') echo vpn ;;
    '-q get firewall.vpn.network') echo vpn0 ;;
    '-q get firewall.vpntowan') [ "${OPENVPN_LEGACY_FW:-0}" = 1 ] && echo forwarding || exit 1 ;;
    '-q get vlmcsd.config') [ "${VLMCS_INSTALLED:-0}" = 1 ] && echo vlmcsd ;;
    '-q get vlmcsd.config.enabled') echo "${VLMCS_ENABLED:-0}" ;;
    '-q get vlmcsd.config.internet_access') echo "${VLMCS_INTERNET:-0}" ;;
    '-q get vlmcsd.config.auto_activate') echo "${VLMCS_AUTO_ACTIVATE:-0}" ;;
    '-q get vlmcsd.config.autoactivate') [ "${VLMCS_LEGACY_OPTION:-0}" = 1 ] && echo 1 ;;
    '-q get upnpd.config') exit 1 ;;
    '-q get openclash.config')
        [ "${OPENCLASH_INSTALLED:-0}" = 1 ] && echo openclash || exit 1
        ;;
    '-q get openclash.config.geo_auto_update') echo "${OPENCLASH_GEO_AUTO:-0}" ;;
    '-q get openclash.config.geoip_auto_update') echo "${OPENCLASH_GEOIP_AUTO:-0}" ;;
    '-q get openclash.config.geosite_auto_update') echo "${OPENCLASH_GEOSITE_AUTO:-0}" ;;
    '-q get openclash.config.geoasn_auto_update') echo "${OPENCLASH_GEOASN_AUTO:-0}" ;;
    '-q get openclash.config.chnr_auto_update') echo "${OPENCLASH_CHNR_AUTO:-0}" ;;
    '-q get openclash.config.enable') echo 0 ;;
    '-q get openclash.config.dns_port'|'-q get openclash.config.enable_redirect_dns'|'-q get openclash.config.operation_mode'|'-q get openclash.config.en_mode'|'-q get dhcp.@dnsmasq[0].server') exit 1 ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/zerotier-cli" <<'EOF'
#!/bin/sh
printf '%s\n' '{"config":{"settings":{"primaryPort":9993,"secondaryPort":59120,"tertiaryPort":63542,"portMappingEnabled":true}}}'
EOF

cat > "$TMP/bin/jsonfilter" <<'EOF'
#!/bin/sh
input=$(cat)
case "$*" in
    *primaryPort*) echo 9993 ;;
    *secondaryPort*) echo 59120 ;;
    *tertiaryPort*) echo 63542 ;;
    *portMappingEnabled*) echo true ;;
    *) printf '%s\n' "$input" >/dev/null; exit 1 ;;
esac
EOF

cat > "$TMP/bin/nft" <<'EOF'
#!/bin/sh
case "$*" in
    '-a list chain inet fw4 input') cat "$NFT_INPUT" ;;
    '-a list chain inet fw4 forward') cat "$NFT_FORWARD" ;;
    '-a list chain inet fw4 srcnat') cat "$NFT_SRCNAT" ;;
    '-a list chain inet fw4 openclash_'*) exit 1 ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/pidof" <<'EOF'
#!/bin/sh
case "$1" in
    zerotier-one) echo 100 ;;
    openvpn) [ "${OPENVPN_RUNNING:-0}" = 1 ] && echo 102 ;;
    vlmcsd) [ "${VLMCS_RUNNING:-0}" = 1 ] && echo 101 ;;
    *) exit 1 ;;
esac
EOF

cat > "$TMP/bin/ip" <<'EOF'
#!/bin/sh
[ "${OPENVPN_TUN0:-0}" = 1 ] && [ "$*" = 'link show dev tun0' ] && exit 0
exit 1
EOF

cat > "$TMP/bin/ss" <<'EOF'
#!/bin/sh
[ "${OPENVPN_LISTENER:-0}" = 1 ] && echo 'udp UNCONN 0 0 0.0.0.0:1194 0.0.0.0:*'
exit 0
EOF

cat > "$TMP/zt-health" <<'EOF'
#!/bin/sh
exit "${ZT_HEALTH_RC:-0}"
EOF

cat > "$TMP/bin/find" <<'EOF'
#!/bin/sh
printf '%s\n' /sys/class/net/ztmock0
EOF
chmod +x "$TMP/bin/"*
chmod +x "$TMP/zt-health"

export ZT_FW_PATH="$TMP/fw"
export NFT_INPUT="$TMP/nft-input"
export NFT_FORWARD="$TMP/nft-forward"
export NFT_SRCNAT="$TMP/nft-srcnat"
export ZT_HEALTH="$TMP/zt-health"
: > "$NFT_FORWARD"
: > "$NFT_SRCNAT"
: > "$ZT_FW_PATH/forward.nft"
: > "$ZT_FW_PATH/srcnat.nft"

write_exact_rules() {
    cat > "$ZT_FW_PATH/input.nft" <<'EOF'
udp dport 9993 counter accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)"
meta l4proto { udp } th dport 59120 counter accept comment "!fw4: Accept ZeroTier input 59120 (secondaryPort)"
meta l4proto { udp } th dport 63542 counter accept comment "!fw4: Accept ZeroTier input 63542 (tertiaryPort)"
EOF
    cat > "$NFT_INPUT" <<'EOF'
udp dport 9993 counter accept comment "!fw4: Accept ZeroTier input 9993 (primaryPort)" # handle 10
udp dport 59120 counter accept comment "!fw4: Accept ZeroTier input 59120 (secondaryPort)" # handle 11
udp dport 63542 counter accept comment "!fw4: Accept ZeroTier input 63542 (tertiaryPort)" # handle 12
EOF
}

run_audit() {
    PATH="$TMP/bin:$PATH" "$ROOT/AX6-IPQ/files/sbin/ax6-config-audit" -v
}

write_exact_rules
if ! run_audit > "$TMP/pass.log"; then
    cat "$TMP/pass.log" >&2
    exit 1
fi
grep -Fq 'nft input include exactly matches daemon ports and protocols' "$TMP/pass.log"
grep -Fq 'live nft input rules exactly match daemon ports and protocols' "$TMP/pass.log"
grep -Fq 'FAIL=0' "$TMP/pass.log"

OPENCLASH_INSTALLED=1 run_audit > "$TMP/openclash-disabled-geodata.log"
grep -Fq 'all Country/GeoIP/GeoSite/GeoASN/CHNR automatic updates are disabled' \
    "$TMP/openclash-disabled-geodata.log"
grep -Fq 'FAIL=0' "$TMP/openclash-disabled-geodata.log"

OPENCLASH_INSTALLED=1 OPENCLASH_GEO_AUTO=1 run_audit > "$TMP/openclash-country-auto.log"
grep -Fq 'geo_auto_update enabled' "$TMP/openclash-country-auto.log"
if grep -Fq 'all Country/GeoIP/GeoSite/GeoASN/CHNR automatic updates are disabled' \
    "$TMP/openclash-country-auto.log"; then
    echo 'audit ignored an enabled Country.mmdb auto-update policy' >&2
    exit 1
fi
grep -Fq 'FAIL=0' "$TMP/openclash-country-auto.log"

OPENCLASH_INSTALLED=1 \
OPENCLASH_GEO_AUTO=1 \
OPENCLASH_GEOIP_AUTO=1 \
OPENCLASH_GEOSITE_AUTO=1 \
OPENCLASH_GEOASN_AUTO=1 \
OPENCLASH_CHNR_AUTO=1 \
    run_audit > "$TMP/openclash-geodata-format.log"
grep -Fq 'geo_auto_update, geoip_auto_update, geosite_auto_update, geoasn_auto_update, chnr_auto_update enabled' \
    "$TMP/openclash-geodata-format.log"

export UCI_SCHEMA=legacy LEGACY_ALLOW_DEFAULT=1
run_audit > "$TMP/legacy.log"
grep -Fq 'ZeroTier legacy: remote network may install a default route' "$TMP/legacy.log"
grep -Fq 'FAIL=0' "$TMP/legacy.log"
export UCI_SCHEMA=current LEGACY_ALLOW_DEFAULT=0

sed 's/59120/56064/g' "$ZT_FW_PATH/input.nft" > "$TMP/stale"
mv "$TMP/stale" "$ZT_FW_PATH/input.nft"
if run_audit > "$TMP/stale.log"; then
    echo 'audit unexpectedly accepted a stale include port' >&2
    exit 1
fi
grep -Fq 'input include has missing, stale, or protocol-mismatched service ports' "$TMP/stale.log"

write_exact_rules
printf '%s\n' 'udp dport 56064 counter accept comment "!fw4: Accept ZeroTier input 56064 (secondaryPort)" # handle 13' >> "$NFT_INPUT"
if run_audit > "$TMP/extra.log"; then
    echo 'audit unexpectedly accepted an extra live port' >&2
    exit 1
fi
grep -Fq 'live nft input rules differ from daemon ports or include stale rules' "$TMP/extra.log"

printf '%s\n' 'tcp dport 1234 counter accept comment "user rule"' > "$ZT_FW_PATH/input.nft"
printf '%s\n' 'tcp dport 1234 counter accept comment "user rule" # handle 20' > "$NFT_INPUT"
FW_ALLOW_INPUT=0 run_audit > "$TMP/disabled.log"
grep -Fq 'service-port input permission disabled and no service-port rules remain' "$TMP/disabled.log"
grep -Fq 'FAIL=0' "$TMP/disabled.log"

# Per-network input permission needs the shared include but not daemon service ports.
cat > "$ZT_FW_PATH/input.nft" <<'EOF'
iifname ztmock0 counter accept comment "!fw4: Accept ZeroTier input ztmock0"
EOF
cat > "$NFT_INPUT" <<'EOF'
iifname ztmock0 counter accept comment "!fw4: Accept ZeroTier input ztmock0" # handle 30
EOF
FW_ALLOW_INPUT=0 NETWORK_ALLOW_INPUT=1 run_audit > "$TMP/network-input.log"
grep -Fq 'dynamic nftables input include registered and readable' "$TMP/network-input.log"
grep -Fq 'service-port input permission disabled and no service-port rules remain' "$TMP/network-input.log"
grep -Fq 'FAIL=0' "$TMP/network-input.log"

rm -f "$ZT_FW_PATH/srcnat.nft"
if FW_ALLOW_INPUT=0 NETWORK_ALLOW_INPUT=1 run_audit > "$TMP/missing-include.log"; then
    echo 'audit unexpectedly accepted an unreadable registered include' >&2
    exit 1
fi
grep -Fq 'srcnat include is missing, unreadable, or malformed' "$TMP/missing-include.log"

: > "$ZT_FW_PATH/srcnat.nft"
if FW_ALLOW_INPUT=0 NETWORK_ALLOW_INPUT=1 OPENVPN_INSTALLED=1 OPENVPN_RULE=1 \
    run_audit > "$TMP/openvpn-exposed.log"; then
    echo 'audit unexpectedly accepted WAN OpenVPN exposure with all servers disabled' >&2
    exit 1
fi
grep -Fq 'all servers are disabled but WAN 1194 ACCEPT rule(s) remain active' "$TMP/openvpn-exposed.log"

FW_ALLOW_INPUT=0 NETWORK_ALLOW_INPUT=1 OPENVPN_INSTALLED=1 OPENVPN_RULE=1 \
    OPENVPN_RULE_ENABLED=0 run_audit > "$TMP/openvpn-disabled.log"
grep -Fq 'disabled state has no active interface, process, listener, WAN rule, or legacy forwarding' \
    "$TMP/openvpn-disabled.log"
grep -Fq 'FAIL=0' "$TMP/openvpn-disabled.log"

if FW_ALLOW_INPUT=0 NETWORK_ALLOW_INPUT=1 OPENVPN_INSTALLED=1 \
    OPENVPN_NETWORK=1 run_audit > "$TMP/openvpn-network.log"; then
    echo 'audit unexpectedly accepted a disabled OpenVPN netifd interface' >&2
    exit 1
fi
grep -Fq 'active netifd interface declaration(s) remain: legacyvpn' "$TMP/openvpn-network.log"

if FW_ALLOW_INPUT=0 NETWORK_ALLOW_INPUT=1 OPENVPN_INSTALLED=1 \
    OPENVPN_RUNNING=1 run_audit > "$TMP/openvpn-runtime.log"; then
    echo 'audit unexpectedly accepted a running disabled OpenVPN process' >&2
    exit 1
fi
grep -Fq 'process, tun0, or port 1194 listener is active' "$TMP/openvpn-runtime.log"

if FW_ALLOW_INPUT=0 NETWORK_ALLOW_INPUT=1 ZT_HEALTH_RC=1 \
    run_audit > "$TMP/zerotier-l3.log"; then
    echo 'audit unexpectedly accepted a missing ZeroTier managed address' >&2
    exit 1
fi
grep -Fq 'controller owns a managed address that is missing' "$TMP/zerotier-l3.log"

# Shells differ on whether assignments prefixed to a function call remain
# visible after the function returns. Clear earlier fault injections so the
# VLMCS scenario verifies only its own policy.
export OPENVPN_NETWORK=0 OPENVPN_RUNNING=0 ZT_HEALTH_RC=0
FW_ALLOW_INPUT=0 NETWORK_ALLOW_INPUT=1 VLMCS_INSTALLED=1 VLMCS_ENABLED=1 \
    VLMCS_RUNNING=1 VLMCS_INTERNET=1 VLMCS_AUTO_ACTIVATE=1 \
    run_audit > "$TMP/vlmcs.log"
grep -Fq 'internet_access=1 exposes TCP/1688' "$TMP/vlmcs.log"
grep -Fq 'upstream auto_activate option is enabled' "$TMP/vlmcs.log"
grep -Fq 'FAIL=0' "$TMP/vlmcs.log"

# Disabled ZeroTier must not leave per-network forward/NAT rules behind.
: > "$ZT_FW_PATH/input.nft"
: > "$ZT_FW_PATH/forward.nft"
: > "$ZT_FW_PATH/srcnat.nft"
: > "$NFT_INPUT"
printf '%s\n' \
    'iifname "ztold0" counter accept comment "!fw4: Accept ZeroTier input forward ztold0" # handle 40' \
    > "$NFT_FORWARD"
if ZT_ENABLED=0 run_audit > "$TMP/disabled-stale-forward.log"; then
    echo 'audit unexpectedly accepted a stale disabled ZeroTier forward rule' >&2
    exit 1
fi
grep -Fq 'disabled but owned firewall or OpenClash bypass rules remain' \
    "$TMP/disabled-stale-forward.log"

: > "$NFT_FORWARD"
ZT_ENABLED=0 run_audit > "$TMP/disabled-clean.log"
grep -Fq 'installed, disabled, and owned firewall rules are absent' "$TMP/disabled-clean.log"
grep -Fq 'FAIL=0' "$TMP/disabled-clean.log"

if ZT_ENABLED=0 ECM_POLICY_MISSING=1 run_audit > "$TMP/ecm-missing.log"; then
    echo 'audit unexpectedly accepted a missing AX6 ECM layered policy' >&2
    exit 1
fi
grep -Fq 'offload_physical_policy=unset; expected report' "$TMP/ecm-missing.log"
grep -Fq 'offload_host_ifaces=unset; expected br-lan' "$TMP/ecm-missing.log"

echo 'test-ax6-config-audit-zerotier: PASS'
