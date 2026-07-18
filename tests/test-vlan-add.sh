#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)
SCRIPT="$ROOT/AX6-IPQ/files/sbin/vlan-add"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/vlan-add-test.XXXXXX")
cleanup_test() {
	status=$?
	trap - EXIT HUP INT TERM
	rm -rf "$TMP"
	exit "$status"
}
trap cleanup_test EXIT HUP INT TERM

fail() {
    echo "test-vlan-add: $1" >&2
    exit 1
}

prepare_config() {
    case_dir="$1"
    mkdir -p "$case_dir/config"
    printf 'original-network\n' > "$case_dir/config/network"
    printf 'original-firewall\n' > "$case_dir/config/firewall"
    printf 'original-dhcp\n' > "$case_dir/config/dhcp"
    : > "$case_dir/uci.log"
}

run_case() (
    case_dir="$1"
    fail_firewall="$2"
    scenario="${3:-}"
    export VLAN_ADD_CONFIG_DIR="$case_dir/config"
    export MOCK_UCI_LOG="$case_dir/uci.log"
    export MOCK_FAIL_FIREWALL="$fail_firewall"
    export MOCK_SCENARIO="$scenario"

    uci() {
        [ "${1:-}" = "-q" ] && shift
        command="${1:-}"
        shift || true
        case "$command" in
            show|changes)
                if [ "$command" = "show" ] && [ "${1:-}" = "network" ]; then
                    case "$MOCK_SCENARIO" in
                        overlap)
                            printf '%s\n' \
                                'network.lan=interface'
                            ;;
                        vlan_ref)
                            printf '%s\n' \
                                'network.old=device' \
                                "network.old.ports='lan1.40'"
                            ;;
                    esac
                fi
                return 0
                ;;
            get)
                case "${1:-}" in
                    network.lan.proto)
                        [ "$MOCK_SCENARIO" = "overlap" ] && {
                            printf 'static\n'
                            return 0
                        }
                        ;;
                    network.lan.ipaddr)
                        [ "$MOCK_SCENARIO" = "overlap" ] && {
                            printf '192.168.40.1\n'
                            return 0
                        }
                        ;;
                    network.lan.netmask)
                        [ "$MOCK_SCENARIO" = "overlap" ] && {
                            printf '255.255.255.0\n'
                            return 0
                        }
                        ;;
                esac
                return 1
                ;;
            batch)
                while IFS= read -r line; do
                    printf '%s\n' "$line" >> "$MOCK_UCI_LOG"
                done
                ;;
            add_list|revert)
                printf '%s %s\n' "$command" "$*" >> "$MOCK_UCI_LOG"
                ;;
            commit)
                printf 'commit %s\n' "$1" >> "$MOCK_UCI_LOG"
                if [ "$1" = "network" ]; then
                    printf 'committed-network\n' > "$VLAN_ADD_CONFIG_DIR/network"
                fi
                if [ "$1" = "firewall" ] && [ "$MOCK_FAIL_FIREWALL" = "1" ]; then
                    return 1
                fi
                ;;
            *)
                return 1
                ;;
        esac
    }

    ip() {
        [ "${1:-}" = "link" ] || return 1
        [ "${2:-}" = "show" ] || return 1
        case "${3:-}" in
            lan1|lan2|lan3|lan4) return 0 ;;
            *) return 1 ;;
        esac
    }

    set -- 40 iot 192.168.40.1/24 lan1 lan2
    # shellcheck source=../AX6-IPQ/files/sbin/vlan-add
    . "$SCRIPT"
)

success_dir="$TMP/success"
prepare_config "$success_dir"
run_case "$success_dir" 0 > "$success_dir/output" 2>&1 ||
    fail "successful transaction returned non-zero"
grep -qx 'set firewall.iot.input=REJECT' "$success_dir/uci.log" ||
    fail "secure firewall input policy was not staged"
grep -qx 'set firewall.iot_dns=rule' "$success_dir/uci.log" ||
    fail "DNS allow rule was not staged"
grep -qx 'set firewall.iot_dhcp=rule' "$success_dir/uci.log" ||
    fail "DHCP allow rule was not staged"
grep -qx 'set dhcp.iot.start=100' "$success_dir/uci.log" ||
    fail "DHCP start was not calculated for /24"
grep -qx 'set dhcp.iot.limit=150' "$success_dir/uci.log" ||
    fail "DHCP limit was not calculated for /24"

rollback_dir="$TMP/rollback"
prepare_config "$rollback_dir"
if run_case "$rollback_dir" 1 > "$rollback_dir/output" 2>&1; then
    fail "firewall commit failure unexpectedly succeeded"
fi
grep -qx 'original-network' "$rollback_dir/config/network" ||
    fail "network config was not restored after commit failure"
grep -qx 'original-firewall' "$rollback_dir/config/firewall" ||
    fail "firewall config was not restored after commit failure"
grep -qx 'original-dhcp' "$rollback_dir/config/dhcp" ||
    fail "DHCP config was not restored after commit failure"
grep -q 'configuration failed; network, firewall and DHCP files were restored' "$rollback_dir/output" ||
    fail "rollback was not reported"

overlap_dir="$TMP/overlap"
prepare_config "$overlap_dir"
if run_case "$overlap_dir" 0 overlap > "$overlap_dir/output" 2>&1; then
    fail "overlapping subnet unexpectedly succeeded"
fi
grep -q 'overlaps existing network.lan' "$overlap_dir/output" ||
    fail "overlapping subnet was not reported"

vlan_ref_dir="$TMP/vlan-ref"
prepare_config "$vlan_ref_dir"
if run_case "$vlan_ref_dir" 0 vlan_ref > "$vlan_ref_dir/output" 2>&1; then
    fail "preconfigured VLAN port unexpectedly succeeded"
fi
grep -q "VLAN device 'lan1.40' is already referenced" "$vlan_ref_dir/output" ||
    fail "preconfigured VLAN port reference was not reported"

echo "test-vlan-add: PASS"
