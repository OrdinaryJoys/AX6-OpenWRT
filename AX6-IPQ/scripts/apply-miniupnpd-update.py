#!/usr/bin/env python3
"""Apply only the reviewed miniupnpd package; preserve the locked feed and UCI."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import re

ASSETS = Path(__file__).resolve().parents[1] / 'package-updates/miniupnpd'


def need(ok, why):
    if not ok:
        raise ValueError(why)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def inventory(root):
    need(root.is_dir() and not root.is_symlink(), 'regular package root')
    rows = {}
    for path in sorted(root.rglob('*')):
        need(not path.is_symlink() and (path.is_file() or path.is_dir()), 'nonregular package member')
        if path.is_file():
            rows[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return rows


def load():
    data = json.loads((ASSETS / 'profile.json').read_bytes())
    need(data['schema'] == 1 and data['version'] == '2.3.11' and data['release'] == 1,
         'reviewed package policy')
    for name in set(data['baseline']) | set(data['candidate']):
        rel = PurePosixPath(name)
        need(str(rel) == name and not rel.is_absolute() and '..' not in rel.parts and
             '.git' not in rel.parts, 'package member name')
    changed = {name for name in data['candidate'] if data['baseline'].get(name) != data['candidate'][name]}
    need(set(data['payload']) == changed, 'exact changed payload')
    need(set(data['payload_modes']) == changed and
         all(mode in ('100644', '100755') for mode in data['payload_modes'].values()),
         'fixed upstream payload modes')
    need(len(set(data['payload'].values())) == len(changed), 'unique payload identities')
    for name, filename in data['payload'].items():
        need(re.fullmatch(r'[0-9]{4}\.data', filename) is not None, 'fixed payload filename')
        need(not (ASSETS / filename).is_symlink(), 'payload symlink')
        raw = (ASSETS / filename).read_bytes()
        need(digest(raw) == data['candidate'][name], 'payload integrity')
    need(set(p.name for p in ASSETS.iterdir()) == {'profile.json', *data['payload'].values()}, 'asset inventory')
    return data


def apply(feed):
    data = load()
    need(feed.is_dir() and not (feed / 'net').is_symlink(), 'regular feed parent')
    root = feed / 'net/miniupnpd'
    before = inventory(root)
    def modes_match():
        return all(stat.S_IMODE((root / name).stat().st_mode) == int(mode, 8) & 0o777
                   for name, mode in data['payload_modes'].items())
    if before == data['candidate']:
        need(modes_match(), 'locally modified candidate payload mode')
        return {'status': 'ALREADY_REVIEWED', 'version': data['version']}
    need(before == data['baseline'], 'unknown or locally modified miniupnpd; refusing overwrite')
    originals = {name: ((root / name).read_bytes(), stat.S_IMODE((root / name).stat().st_mode)) for name in before}
    try:
        for name, filename in data['payload'].items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ASSETS / filename).read_bytes())
            target.chmod(int(data['payload_modes'][name], 8) & 0o777)
        for name in set(before) - set(data['candidate']):
            (root / name).unlink()
        need(inventory(root) == data['candidate'], 'exact updated package')
        need(modes_match(), 'exact upstream payload modes')
    except Exception:
        for name in set(data['candidate']) - set(before):
            target = root / name
            if target.is_file() and not target.is_symlink():
                target.unlink()
        for name, (raw, mode) in originals.items():
            target = root / name; target.write_bytes(raw); target.chmod(mode)
        need(inventory(root) == before, 'rollback failed; do not build')
        raise
    return {'status': 'APPLIED_SELECTED_PACKAGE_ONLY', 'version': data['version'],
            'feed_commit': data['candidate_commit'], 'source_sha256': data['source_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('feed', type=Path)
    args = parser.parse_args()
    print(json.dumps(apply(args.feed.resolve()), sort_keys=True))


if __name__ == '__main__':
    main()
