#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
DEFAULTS="$ROOT/AX6-IPQ/files/etc/uci-defaults/96-ax6-openclash-geodata-defaults"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/openclash-geodata-test.XXXXXX")
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

mkdir -p "$TMP/bin" "$TMP/state"

cat > "$TMP/bin/uci" <<'EOF'
#!/bin/sh
set -eu

[ "${1:-}" = "-q" ] && shift
command=${1:-}
[ "$#" -eq 0 ] || shift

state_file() {
    key=$(printf '%s' "$1" | tr '.-' '__')
    printf '%s/%s' "$STATE_DIR" "$key"
}

case "$command" in
    get)
        key=${1:-}
        [ "$key" = "openclash.config" ] && {
            printf '%s\n' openclash
            exit 0
        }
        file=$(state_file "$key")
        [ -f "$file" ] || exit 1
        cat "$file"
        ;;
    set)
        assignment=${1:-}
        key=${assignment%%=*}
        value=${assignment#*=}
        printf '%s\n' "$value" > "$(state_file "$key")"
        ;;
    commit)
        count=0
        [ ! -f "$STATE_DIR/commit_count" ] || count=$(cat "$STATE_DIR/commit_count")
        printf '%s\n' "$((count + 1))" > "$STATE_DIR/commit_count"
        ;;
    *)
        exit 2
        ;;
esac
EOF
chmod +x "$TMP/bin/uci"

export STATE_DIR="$TMP/state"
export PATH="$TMP/bin:$PATH"

# Explicit administrator choices must survive; absent options receive defaults.
printf '%s\n' 0 > "$STATE_DIR/openclash_config_geoip_auto_update"
printf '%s\n' 6 > "$STATE_DIR/openclash_config_geosite_update_week_time"

sh "$DEFAULTS"

test "$(uci -q get openclash.config.geo_auto_update)" = 1
test "$(uci -q get openclash.config.geoip_auto_update)" = 0
test "$(uci -q get openclash.config.geosite_auto_update)" = 1
test "$(uci -q get openclash.config.geosite_update_week_time)" = 6
test "$(uci -q get openclash.config.geoasn_auto_update)" = 1
test "$(uci -q get openclash.config.chnr_auto_update)" = 1
test "$(cat "$STATE_DIR/commit_count")" = 1

# A second run must be idempotent and avoid another commit.
sh "$DEFAULTS"
test "$(cat "$STATE_DIR/commit_count")" = 1

echo "test-openclash-geodata-defaults: PASS"
