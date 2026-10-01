#!/usr/bin/env python3
"""Canonical identities from an unfiltered `ip -d -j link show` snapshot.

Read stdin only. Empty placeholder objects are invalid, never evidence of an
empty IFB inventory. Ignore volatile counters, but compare every host link.
"""
import json
import sys


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field: ' + key)
        value[key] = item
    return value


def parse(text):
    return canonical(json.loads(text, object_pairs_hook=unique_object))


def canonical(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('host link inventory must be a nonempty JSON array')
    links, indices, names = [], set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('link inventory entry must be an object')
        index, name = row.get('ifindex'), row.get('ifname')
        if type(index) is not int or index <= 0 or not isinstance(name, str) or not name:
            raise ValueError('link inventory entry lacks valid ifindex/ifname')
        info = row.get('linkinfo', {})
        if not isinstance(info, dict) or not isinstance(info.get('info_kind', ''), str):
            raise ValueError('invalid linkinfo/info_kind')
        if 'info_kind' in info and not info['info_kind']:
            raise ValueError('explicit info_kind must not be empty')
        if index in indices or name in names:
            raise ValueError('duplicate link identity in snapshot')
        indices.add(index)
        names.add(name)
        links.append({'ifindex': index, 'ifname': name, 'kind': info.get('info_kind', '')})
    links.sort(key=lambda row: (row['ifindex'], row['ifname']))
    return {'links': links, 'ifb_links': [row for row in links if row['kind'] == 'ifb']}


def main():
    try:
        value = parse(sys.stdin.read())
    except (ValueError, TypeError) as error:
        print('Invalid host link inventory: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(value, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
