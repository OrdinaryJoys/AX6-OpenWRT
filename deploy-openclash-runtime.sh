#!/bin/sh
# AX6 OpenClash 运行时配置部署 — 刷固件后执行
# 用法: sh deploy-openclash-runtime.sh [router_ip]
# ⚠️ 仅部署配置，不修改固件文件
set -e

ROUTER="${1:-192.168.5.1}"
BACKUP_DIR="${2:-./ax6-backup-*}"

echo "=== AX6 OpenClash Runtime Deploy ==="
echo "Router: $ROUTER"
echo ""

# ---- V25 Overwrite Script (Ruby) ----
echo "[1/6] Deploy V25 overwrite (Ruby)..."
cat > /tmp/oc_overwrite.rb << 'RUBY'
# OpenClash V25 Overwrite — DNS + CDN 修复
# 由 deploy-openclash-runtime.sh 部署

require 'yaml'
require 'fileutils'

config_file = ARGV[0]
exit 0 unless config_file && File.exist?(config_file)

cfg = YAML.safe_load(File.read(config_file), permitted_classes: [Symbol])
exit 0 unless cfg.is_a?(Hash)

changed = false

# DNS: DoT → DoH (CN servers)
if cfg['dns'] && cfg['dns']['nameserver-policy']
  cfg['dns']['nameserver-policy'].each do |domain, servers|
    if servers.is_a?(Array)
      servers.map! do |s|
        s = s.to_s
        %w[223.5.5.5 dot.pub dns.alidns.com].each do |cn_dns|
          if s.include?(cn_dns)
            s = s.gsub('tls://', 'https://')
            s = s.gsub(/:853/, '')
            s = s.gsub(/^https:\/\/#{Regexp.escape(cn_dns)}$/, "https://#{cn_dns}/dns-query")
            s = s.gsub(/#skip-cert-verify=true$/, '#skip-cert-verify=true')
            s = "#{s}#skip-cert-verify=true" unless s.include?('#skip-cert-verify=true')
            changed = true
          end
        end
        s
      end
    end
  end
end

# fallback → select
if cfg.dig('proxy-groups')
  cfg['proxy-groups'].each do |pg|
    if pg['type'] == 'fallback'
      pg['type'] = 'select'
      changed = true
    end
  end
end

if changed
  File.write(config_file, cfg.to_yaml)
  puts "[V25] Overwrite applied: DoT→DoH + fallback→select"
end
RUBY

cat > /tmp/oc_overwrite.sh << 'SHELL'
#!/bin/sh
. /usr/share/openclash/ruby.sh
. /usr/share/openclash/log.sh
. /lib/functions.sh
LOG_TIP "Start Running Custom Overwrite Scripts..."
CONFIG_FILE="$1"
if [ -f /etc/openclash/custom/openclash_custom_overwrite.rb ]; then
  ruby -ryaml -rYAML -I /usr/share/openclash -E UTF-8 /etc/openclash/custom/openclash_custom_overwrite.rb "$CONFIG_FILE" 2>>/tmp/openclash.log
  LOG_TIP "V25 overwrite applied"
fi
exit 0
SHELL

scp /tmp/oc_overwrite.rb root@"$ROUTER":/etc/openclash/custom/openclash_custom_overwrite.rb 2>/dev/null && echo "  ✅ overwrite.rb" || echo "  ❌ scp failed"
scp /tmp/oc_overwrite.sh root@"$ROUTER":/etc/openclash/custom/openclash_custom_overwrite.sh 2>/dev/null && echo "  ✅ overwrite.sh" || echo "  ❌ scp failed"
ssh root@"$ROUTER" 'chmod +x /etc/openclash/custom/openclash_custom_overwrite.sh' 2>/dev/null

# ---- fix_dot.sh (Idempotent) ----
echo "[2/6] Deploy fix_dot.sh..."
cat > /tmp/fix_dot.sh << 'FIX'
#!/bin/sh
for f in /etc/openclash/config/*.yaml; do
  [ -f "$f" ] || continue
  if grep -q "tls://" "$f" 2>/dev/null; then
    sed -i "s|tls://223.5.5.5#skip-cert-verify=true|https://223.5.5.5/dns-query#skip-cert-verify=true|g" "$f"
    sed -i "s|tls://dot.pub#skip-cert-verify=true|https://doh.pub/dns-query#skip-cert-verify=true|g" "$f"
    sed -i "s|tls://dns.alidns.com#skip-cert-verify=true|https://dns.alidns.com/dns-query#skip-cert-verify=true|g" "$f"
  fi
  if grep -q "type: fallback" "$f" 2>/dev/null; then
    sed -i "s|type: fallback|type: select|g" "$f"
  fi
done
FIX
scp /tmp/fix_dot.sh root@"$ROUTER":/usr/share/openclash/fix_dot.sh 2>/dev/null && echo "  ✅" || echo "  ❌"
ssh root@"$ROUTER" 'chmod +x /usr/share/openclash/fix_dot.sh' 2>/dev/null

# ---- UCI Settings ----
echo "[3/6] Configure UCI..."
ssh root@"$ROUTER" '
uci set openclash.config.enable_custom_dns=0
uci set openclash.config.auto_update=0
uci set openclash.config.config_auto_update_mode=0
uci set openclash.config.stream_auto_select=0
uci set openclash.config.auto_restart=0
uci set openclash.config.config_update_interval=360
uci commit openclash
' 2>/dev/null && echo "  ✅" || echo "  ❌"

# ---- Cron ----
echo "[4/6] Configure cron..."
ssh root@"$ROUTER" '
(crontab -l 2>/dev/null | grep -v "fix_dot\|openclash-weekly"; echo "10 * * * * /usr/share/openclash/fix_dot.sh"; echo "0 4 * * 0 /usr/share/openclash/openclash.sh #openclash-weekly") | crontab -
' 2>/dev/null && echo "  ✅" || echo "  ❌"

# ---- Restart OpenClash ----
echo "[5/6] Restart OpenClash..."
ssh root@"$ROUTER" '/etc/init.d/openclash restart 2>&1' 2>/dev/null && echo "  ✅" || echo "  ⚠️  may need manual restart"

# ---- Verify ----
echo "[6/6] Verify..."
sleep 5
ssh root@"$ROUTER" '
echo "  fb=$(grep -c "type: fallback" /etc/openclash/config/el1si7d_doggygosubs.yaml 2>/dev/null || echo 0)"
echo "  DoT=$(grep -c "tls://" /etc/openclash/config/el1si7d_doggygosubs.yaml 2>/dev/null || echo 0)"
echo "  auto_update=$(uci get openclash.config.auto_update 2>/dev/null)"
echo "  stream_auto_select=$(uci get openclash.config.stream_auto_select 2>/dev/null)"
' 2>/dev/null

echo ""
echo "=== Deploy complete ==="
echo "Verify: fb=0 DoT=0 auto_update=0 stream_auto_select=0"
echo "Full check: ssh root@$ROUTER 'nss-check -v && ax6-config-audit -v'"
