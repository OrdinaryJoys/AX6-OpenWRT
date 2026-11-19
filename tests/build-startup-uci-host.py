#!/usr/bin/env python3
"""Build the locked UCI CLI core for private host tests, never target programs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

PIN = '66127cd76c5d0bd46d5a90302cc6110f53a4e2f8'
URL = 'https://github.com/openwrt/uci.git'
C_FILES = ['libuci.c', 'file.c', 'util.c', 'delta.c', 'parse.c', 'cli.c']
INCLUDED_C_FILES = ['list.c']


def run(argv, **kwargs):
    return subprocess.run([str(v) for v in argv], check=True, capture_output=True,
                          timeout=180, **kwargs).stdout


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--uci-git-root', type=Path)
    parser.add_argument('--cc', default=os.environ.get('CC', 'cc'))
    args = parser.parse_args()
    recipe = args.source_root / 'package/system/uci/Makefile'
    pins = re.findall(r'^PKG_SOURCE_VERSION:=(\S+)$', recipe.read_text(), re.M)
    if pins != [PIN]:
        raise ValueError('UCI package pin differs from the reviewed host contract')
    out = args.output.resolve()
    if out.exists():
        raise ValueError('output must be fresh')
    out.mkdir(parents=True)
    repo = args.uci_git_root.resolve() if args.uci_git_root else out / 'upstream-git'
    if not args.uci_git_root:
        run(['git', 'init', '-q', repo])
        run(['git', '-C', repo, 'remote', 'add', 'origin', URL])
        run(['git', '-C', repo, 'fetch', '--no-tags', '--depth=1', 'origin', PIN])
    actual = run(['git', '-C', repo, 'rev-parse', PIN + '^{commit}']).decode().strip()
    if actual != PIN:
        raise ValueError('UCI object mismatch')
    names = run(['git', '-C', repo, 'ls-tree', '--name-only', PIN]).decode().splitlines()
    inputs = out / 'cli-inputs'
    inputs.mkdir()
    hashes = {}
    for name in C_FILES + INCLUDED_C_FILES + [n for n in names if n.endswith('.h') and '/' not in n]:
        data = run(['git', '-C', repo, 'show', f'{PIN}:{name}'])
        (inputs / name).write_bytes(data)
        hashes[name] = sha(data)
    # These are the two OFF defaults of the pinned upstream CMake configuration.
    config = b'/* #undef UCI_DEBUG */\n/* #undef UCI_DEBUG_TYPECAST */\n'
    (inputs / 'uci_config.h').write_bytes(config)
    compiler = shutil.which(args.cc)
    if not compiler:
        raise ValueError('native compiler missing')
    binary = out / 'uci-native'
    command = [compiler, '-Wall', '-Wextra', '-Werror', '-Werror=implicit-function-declaration',
               '-Wformat', '-Werror=format-security', '-Werror=format-nonliteral', '-Os',
               '-std=gnu99', '-g3', '-Wmissing-declarations', '-Wno-unused-parameter',
               '-I', str(inputs), *[str(inputs / n) for n in C_FILES], '-o', str(binary)]
    if sys.platform.startswith('linux'):
        command.append('-ldl')
    completed = subprocess.run(command, capture_output=True, timeout=120)
    (out / 'compile.stdout').write_bytes(completed.stdout)
    (out / 'compile.stderr').write_bytes(completed.stderr)
    if completed.returncode or completed.stdout or completed.stderr:
        raise RuntimeError(f'native UCI compile rejected: exit={completed.returncode}; see {out}')
    report = {'source_url': URL, 'source_commit': PIN, 'source_files_sha256': hashes,
              'generated_config_sha256': sha(config), 'compiler_command': command,
              'compiler_version': run([compiler, '--version']).decode().splitlines()[0],
              'binary_sha256': sha(binary.read_bytes()), 'recipe_sha256': sha(recipe.read_bytes()),
              'scope': 'Real CLI core, no blob/Lua binding; not full target package, kernel or device validation'}
    (out / 'BUILD-REPORT.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
