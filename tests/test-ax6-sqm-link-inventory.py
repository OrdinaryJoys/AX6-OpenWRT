#!/usr/bin/env python3
"""No kernel actions: validate full host inventory parsing and change detection."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

path = Path(__file__).resolve().parents[1] / '.github/scripts/ax6-sqm-link-inventory.py'
spec = importlib.util.spec_from_file_location('ax6_inventory', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def rejects(name, value):
    try:
        module.canonical(value)
    except ValueError:
        checks.append(name)
        return
    raise AssertionError(name)


base = [{'ifindex': 1, 'ifname': 'lo'},
        {'ifindex': 2, 'ifname': 'eth0'},
        {'ifindex': 3, 'ifname': 'ifb-looking-name', 'linkinfo': {'info_kind': 'veth'}}]
value = module.canonical(base)
rejects('empty full host inventory rejected', [])
check('ordering is not a resource change', module.canonical(list(reversed(base))) == value)
check('name alone never implies IFB kind', value['ifb_links'] == [])
with_ifb = base + [{'ifindex': 4, 'ifname': 'testifb', 'linkinfo': {'info_kind': 'ifb'}}]
check('actual IFB kind is recorded', module.canonical(with_ifb)['ifb_links'] ==
      [{'ifindex': 4, 'ifname': 'testifb', 'kind': 'ifb'}])
check('added host link fails equality guard', module.canonical(with_ifb) != value)
check('removed host link fails equality guard', module.canonical(base[:-1]) != value)
renamed = [dict(row) for row in base]
renamed[1]['ifname'] = 'changed'
check('renamed host link fails equality guard', module.canonical(renamed) != value)
changed_index = [dict(row) for row in base]
changed_index[1]['ifindex'] = 99
check('recreated identity fails equality guard', module.canonical(changed_index) != value)
changed_kind = [dict(row) for row in base]
changed_kind[1]['linkinfo'] = {'info_kind': 'ifb'}
check('changed kind fails equality guard', module.canonical(changed_kind) != value)
noisy = [dict(row, stats64={'rx': {'packets': 1}}, flags=['UP']) for row in base]
check('volatile statistics excluded, identities retained', module.canonical(noisy) == value)
rejects('old filtered empty objects are not empty inventory', [{}, {}, {}, {}])
rejects('non-array rejected', {})
rejects('non-object row rejected', [1])
rejects('missing name rejected', [{'ifindex': 1}])
rejects('missing index rejected', [{'ifname': 'lo'}])
rejects('boolean index rejected', [{'ifindex': True, 'ifname': 'lo'}])
rejects('duplicate index rejected', base + [{'ifindex': 2, 'ifname': 'other'}])
rejects('duplicate name rejected', base + [{'ifindex': 4, 'ifname': 'eth0'}])
rejects('malformed linkinfo rejected', [{'ifindex': 1, 'ifname': 'lo', 'linkinfo': None}])
rejects('malformed kind rejected', [{'ifindex': 1, 'ifname': 'lo', 'linkinfo': {'info_kind': 1}}])
rejects('explicit empty kind rejected', [{'ifindex': 1, 'ifname': 'lo', 'linkinfo': {'info_kind': ''}}])
for name, text in [('duplicate JSON keys rejected', '[{"ifindex":1,"ifindex":2,"ifname":"lo"}]'),
                   ('damaged JSON rejected', '[{"ifindex":1'),
                   ('null kind rejected', '[{"ifindex":1,"ifname":"lo","linkinfo":{"info_kind":null}}]')]:
    try:
        module.parse(text)
    except ValueError:
        checks.append(name)
    else:
        raise AssertionError(name)
prep_path = path.with_name('prepare-ax6-sqm-kernel-ci.sh')
source = prep_path.read_text()
function = re.search(r'^host_inventory\(\) \{\n.*?^\}\n', source, re.M | re.S)
assert function, 'actual preparation function must be found'
wiring_checks = []
# Exercise the actual function inside command substitution: Bash may disable
# errexit there. Tools are replaced before the function is invoked, and no
# preparation top-level or real ip/modprobe command is executed.
script = ('set -euo pipefail\nscript_dir=' + shlex.quote(str(path.parent)) + '\n'
          'ip() { printf "%s\\n" "$MOCK_IP_JSON"; return "$MOCK_IP_RC"; }\n'
          'modprobe() { printf "MOCK_MODULE_BOUNDARY_REACHED\\n"; }\n'
          + function[0] + '\nbefore_links=$(host_inventory before)\n'
          'modprobe ifb numifbs=0\n')
for name, payload, rc, expected in [
    ('valid zero-return inventory permits next mocked step', json.dumps(base), 0, 0),
    ('nonzero ip with valid JSON blocks module boundary', json.dumps(base), 7, 7),
    ('nonzero ip with empty output blocks module boundary', '', 7, 7),
    ('empty full JSON blocks module boundary', '[]', 0, 1),
    ('placeholder JSON blocks module boundary', '[{},{}]', 0, 1),
    ('damaged JSON blocks module boundary', '[', 0, 1),
]:
    result = subprocess.run(['bash', '-c', script], env=dict(os.environ,
                            MOCK_IP_JSON=payload, MOCK_IP_RC=str(rc)),
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == expected, (name, result)
    assert ('MOCK_MODULE_BOUNDARY_REACHED' in result.stdout) == (expected == 0), name
    wiring_checks.append(name)
print(json.dumps({'status': 'PASS_INVENTORY_UNIT_ONLY', 'checks': checks,
                  'shell_wiring_checks': wiring_checks,
                  'real_kernel_executed': False}, indent=2))
