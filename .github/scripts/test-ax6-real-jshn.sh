#!/usr/bin/env bash
# Host-only composition test. Does not compile firmware or contact the router.
set -euo pipefail

source_root=${1:?usage: test-ax6-real-jshn.sh LOCKED_SOURCE_ROOT}
source_root=$(cd "$source_root" && pwd -P)
libubox_commit=$(awk -F':=' '$1 == "PKG_SOURCE_VERSION" { print $2 }' "$source_root/package/libs/libubox/Makefile")
[[ "$libubox_commit" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid libubox source identity' >&2; exit 1; }
jshn_tmp=$(mktemp -d "${TMPDIR:-/tmp}/ax6-jshn.XXXXXX")
trap 'rm -rf -- "$jshn_tmp"' EXIT
git -C "$jshn_tmp" init -q
git -C "$jshn_tmp" remote add origin https://github.com/openwrt/libubox.git
git -C "$jshn_tmp" fetch --depth=1 origin "$libubox_commit"
git -C "$jshn_tmp" checkout --detach FETCH_HEAD
test "$(git -C "$jshn_tmp" rev-parse HEAD)" = "$libubox_commit"

json_c_version=$(pkg-config --modversion json-c)
# pkg-config returns compiler flag words, not shell code. Never eval them.
read -r -a json_c_cflags <<< "$(pkg-config --cflags json-c)"
read -r -a json_c_libs <<< "$(pkg-config --libs json-c)"
compiler=(cc -std=gnu99 -O1 "${json_c_cflags[@]}"
  jshn.c avl.c avl-cmp.c blob.c blobmsg.c blobmsg_json.c utils.c
  "${json_c_libs[@]}" -o "$jshn_tmp/jshn-host")
(cd "$jshn_tmp" && "${compiler[@]}")

python3 - "$jshn_tmp" "$libubox_commit" "$json_c_version" "${compiler[@]}" > "$jshn_tmp/build-report.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
root, commit, version, *command = sys.argv[1:]
root = Path(root)
print(json.dumps({
    'source_commit': commit,
    'source_url': 'https://github.com/openwrt/libubox.git',
    'binary_sha256': hashlib.sha256((root / 'jshn-host').read_bytes()).hexdigest(),
    'shell_sha256': hashlib.sha256((root / 'sh/jshn.sh').read_bytes()).hexdigest(),
    'json_c_version': version, 'compiler_command': command,
    'boundary': 'Host native binary with host json-c; not AX6 ABI/config or reproducible-build proof',
}, indent=2))
PY
cat "$jshn_tmp/build-report.json"
ECM_TEST_JSHN_SH="$jshn_tmp/sh/jshn.sh" \
ECM_TEST_JSHN_BIN="$jshn_tmp/jshn-host" \
ECM_TEST_JSHN_BUILD_REPORT="$jshn_tmp/build-report.json" \
ECM_TEST_JSON_C_VERSION="$json_c_version" \
  python3 "$source_root/tests/test-ecm-procd-real-jshn.py" "$source_root"
