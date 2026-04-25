# shellcheck shell=sh
# SSH 登录时显示 NSS / WiFi 简报(只在 SSH session 显示,console 静默)
[ -n "$SSH_CLIENT" ] || [ -n "$SSH_TTY" ] || return 0

_color() { printf '\033[%sm%s\033[0m' "$1" "$2"; }

# NSS 模块数
_nss_count=$(lsmod 2>/dev/null | grep -c '^qca_nss')

# NSS Core 启动状态
if dmesg 2>/dev/null | grep -q 'NSS core .* booted'; then
    _nss_state="$(_color '32' 'OK')"
else
    _nss_state="$(_color '31' 'NOT-BOOTED')"
fi

# ECM 连接数(NSS 卸载工作中)
_ecm_count=0
[ -r /sys/kernel/debug/ecm/ecm_db/connection_count_simple ] && \
    _ecm_count=$(cat /sys/kernel/debug/ecm/ecm_db/connection_count_simple 2>/dev/null)

# WiFi 状态
_wifi_state=""
if iw dev 2>/dev/null | grep -q "channel.*MHz"; then
    _wifi_state="$(_color '32' 'UP')"
else
    _wifi_state="$(_color '33' 'DOWN')"
fi

# RAM
_ram_used_mb=$(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2} END{print int((t-a)/1024)}' /proc/meminfo)
_ram_total_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)

printf ' NSS: modules=%d  core=%b  ecm=%d  WiFi: %b  RAM: %d/%d MB\n' \
    "$_nss_count" "$_nss_state" "$_ecm_count" "$_wifi_state" "$_ram_used_mb" "$_ram_total_mb"
printf ' Run: %s for full health check\n\n' "$(_color '36' 'nss-check -v')"

unset _color _nss_count _nss_state _ecm_count _wifi_state _ram_used_mb _ram_total_mb
