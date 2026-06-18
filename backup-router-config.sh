#!/bin/sh
# AX6 路由器配置备份 — 刷固件前执行
# 用法: sh backup-router-config.sh [router_ip]
set -e

ROUTER="${1:-192.168.5.1}"
BACKUP_DIR="./ax6-backup-$(date +%Y%m%d-%H%M%S)"

echo "=== AX6 Router Config Backup ==="
echo "Router: $ROUTER"
echo "Backup: $BACKUP_DIR"
echo ""

mkdir -p "$BACKUP_DIR"

# 1. OpenClash overwrite scripts
echo "[1/7] OpenClash V25 overwrite..."
ssh root@"$ROUTER" 'cat /etc/openclash/custom/openclash_custom_overwrite.rb' > "$BACKUP_DIR/openclash_custom_overwrite.rb" 2>/dev/null && echo "  ✅ overwrite.rb" || echo "  ⚠️  not found"
ssh root@"$ROUTER" 'cat /etc/openclash/custom/openclash_custom_overwrite.sh' > "$BACKUP_DIR/openclash_custom_overwrite.sh" 2>/dev/null && echo "  ✅ overwrite.sh" || echo "  ⚠️  not found"

# 2. fix_dot.sh (idempotent)
echo "[2/7] fix_dot.sh..."
ssh root@"$ROUTER" 'cat /usr/share/openclash/fix_dot.sh' > "$BACKUP_DIR/fix_dot.sh" 2>/dev/null && echo "  ✅" || echo "  ⚠️  not found"

# 3. nftables bypass rules
echo "[3/7] nftables bypass..."
ssh root@"$ROUTER" 'cat /etc/openclash/custom/openclash_custom_firewall_rules.sh' > "$BACKUP_DIR/openclash_custom_firewall_rules.sh" 2>/dev/null && echo "  ✅" || echo "  ⚠️  not found"

# 4. OpenClash active config (subscription YAML)
echo "[4/7] OpenClash config..."
ssh root@"$ROUTER" 'head -100 /etc/openclash/config/el1si7d_doggygosubs.yaml' > "$BACKUP_DIR/openclash_config_head.yaml" 2>/dev/null && echo "  ✅ (first 100 lines)" || echo "  ⚠️  not found"

# 5. crontab
echo "[5/7] crontab..."
ssh root@"$ROUTER" 'crontab -l' > "$BACKUP_DIR/crontab.txt" 2>/dev/null && echo "  ✅" || echo "  ⚠️  empty"

# 6. UCI openclash dump
echo "[6/7] UCI openclash..."
ssh root@"$ROUTER" 'uci show openclash' > "$BACKUP_DIR/openclash_uci.txt" 2>/dev/null && echo "  ✅" || echo "  ⚠️  not found"

# 7. nss-check output
echo "[7/7] nss-check..."
ssh root@"$ROUTER" 'nss-check -v 2>&1' > "$BACKUP_DIR/nss-check-output.txt" 2>/dev/null && echo "  ✅" || echo "  ⚠️  nss-check not available"

echo ""
echo "=== Backup complete: $BACKUP_DIR ==="
ls -la "$BACKUP_DIR/"
echo ""
echo "Next: after flashing new firmware, run deploy-openclash-runtime.sh"
