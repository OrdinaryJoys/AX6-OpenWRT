#!/usr/bin/env python3
"""Preserve generated config/export evidence; not an ABI acceptance checker."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat


def require(ok, message):
    if not ok:
        raise ValueError(message)


def regular(path, root, allow_empty=False):
    require(path.resolve().is_relative_to(root.resolve()), 'evidence path escapes build directory')
    current = root
    require(current.is_dir() and not current.is_symlink(), 'build directory must be real')
    for part in path.relative_to(root).parts[:-1]:
        current = current / part
        require(current.is_dir() and not current.is_symlink(), 'symlink evidence ancestor')
    require(stat.S_ISREG(path.lstat().st_mode), 'evidence must be regular: ' + str(path))
    data = path.read_bytes()
    require(data or allow_empty, 'empty required kernel evidence: ' + str(path))
    return data


def collect(build, output):
    require(build.is_dir() and not build.is_symlink(), 'build directory missing/linked')
    symvers = sorted(path for path in build.rglob('Module.symvers')
                     if path.relative_to(build).parts[0].startswith('target-'))
    kernels = [path for path in symvers if re.search(
        r'/linux-qualcommax_ipq807x/linux-[^/]+/Module\.symvers$', str(path))]
    require(len(kernels) == 1, 'expected one exact qualcommax kernel export table')
    kernel = kernels[0].parent
    inputs = [('kernel.config', kernel / '.config'), ('kernel.System.map', kernel / 'System.map')]
    inputs.extend((f'module-exports-{index:03}.symvers', path) for index, path in enumerate(symvers))
    # Validate every input before creating output, so missing evidence cannot
    # leave a misleading completed collection.
    payloads = [(name, path, regular(path, build, allow_empty=path in symvers and path != kernels[0]))
                for name, path in inputs]
    require(not output.exists() and not output.is_symlink(), 'output already exists')
    output.mkdir(mode=0o700)
    rows = []
    for name, path, data in payloads:
        with (output / name).open('xb') as stream:
            stream.write(data)
        rows.append({'file': name, 'source': str(path.relative_to(build)),
                     'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                     'kernel_exports': path == kernels[0],
                     'legal_empty_external_export_table': not data and path != kernels[0]})
    report = {'status': 'COLLECTED_GENERATED_EVIDENCE_NOT_ABI_ACCEPTANCE',
              'kernel_directory': str(kernel.relative_to(build)), 'files': rows,
              'limits': ['Export names/config are evidence, not a complete C/symbol/signature ABI proof',
                         'No target code, module loading, router access, boot or performance execution']}
    (output / 'INDEX.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args.build_dir.absolute(), args.output_dir.absolute()), indent=2))
    except (ValueError, OSError) as error:
        print(json.dumps({'status': 'FAIL', 'error': str(error)}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
