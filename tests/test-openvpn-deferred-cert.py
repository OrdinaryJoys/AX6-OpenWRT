#!/usr/bin/env python3
from pathlib import Path
import subprocess, tempfile, sys
root = Path(__file__).resolve().parents[1]
script = root / 'AX6-IPQ/scripts/apply-openvpn-deferred-cert.py'
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / 'openvpn'
    p.write_text('if [ ! -f ca.crt ]; then\n\tsh /etc/openvpn/renewcert.sh 2>&1 >/dev/null\nfi\n')
    subprocess.run([sys.executable, str(script), str(p)], check=True)
    text = p.read_text()
    assert 'openvpn.myvpn.enabled' in text
    assert '( sh /etc/openvpn/renewcert.sh </dev/null >/dev/null 2>&1 & )' in text
    subprocess.run([sys.executable, str(script), str(p)], check=True)
print('PASS openvpn deferred certificate')
