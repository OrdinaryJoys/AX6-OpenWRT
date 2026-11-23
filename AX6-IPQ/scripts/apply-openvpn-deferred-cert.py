#!/usr/bin/env python3
"""Defer OpenVPN certificate generation out of the blocking S10boot path.

luci-app-openvpn-server's uci-defaults synchronously runs renewcert.sh
(easy-rsa gen-dh) on first boot.  That blocks every later rc script,
including network/hostapd/dnsmasq.  Keep the generation but background it.
"""
from pathlib import Path
import sys

path = Path(sys.argv[1])
old = "\tsh /etc/openvpn/renewcert.sh 2>&1 >/dev/null\n"
new = (
    "\t# AX6: a disabled OpenVPN server must not burn first-boot CPU generating DH.\n"
    "\tif [ \"$(uci -q get openvpn.myvpn.enabled 2>/dev/null || echo 0)\" = \"1\" ]; then\n"
    "\t\t( sh /etc/openvpn/renewcert.sh </dev/null >/dev/null 2>&1 & )\n"
    "\tfi\n"
)
text = path.read_text()
if new in text:
    print("already deferred")
    sys.exit(0)
if old not in text:
    print(f"refusing: expected synchronous renewcert invocation not found in {path}", file=sys.stderr)
    sys.exit(2)
path.write_text(text.replace(old, new, 1))
print("deferred OpenVPN renewcert")
