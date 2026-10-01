#!/usr/bin/env python3
"""Local synthetic kernel evidence collection controls; no compiler/kernel."""
import importlib.util
import json
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location('collector', Path(__file__).resolve().parents[1] /
    '.github/scripts/collect-ax6-kernel-evidence.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
results = []


def probe(name, change=None, expected_pass=False):
    with tempfile.TemporaryDirectory(prefix='ax6-kernel-evidence-') as temporary:
        root = Path(temporary)
        build = root / 'build'
        kernel = build / 'target-aarch64/linux-qualcommax_ipq807x/linux-6.18.38'
        kernel.mkdir(parents=True)
        for filename, data in {'.config': b'# CONFIG_MODVERSIONS is not set\n',
                               'System.map': b'ffff T symbol\n',
                               'Module.symvers': b'0 symbol vmlinux EXPORT_SYMBOL\n'}.items():
            (kernel / filename).write_bytes(data)
        module = build / 'target-aarch64/external-module'
        module.mkdir()
        (module / 'Module.symvers').write_bytes(b'0 external driver EXPORT_SYMBOL\n')
        output = root / 'new-evidence'
        if change:
            change(root, build, kernel, module, output)
        try:
            report = collector.collect(build, output)
            passed = True
            assert len(report['files']) == 4 and sum(row['kernel_exports'] for row in report['files']) == 1
        except (ValueError, OSError) as error:
            passed = False
            assert not (output / 'INDEX.json').exists()
        assert passed == expected_pass, name
        results.append({'name': name, 'matched': True})


probe('complete generated evidence', expected_pass=True)
probe('legal empty external export table retained',
      lambda r,b,k,m,o: (m / 'Module.symvers').write_bytes(b''), expected_pass=True)
probe('empty main kernel exports refused', lambda r,b,k,m,o: (k / 'Module.symvers').write_bytes(b''))
probe('missing kernel config', lambda r,b,k,m,o: (k / '.config').unlink())
probe('empty System.map', lambda r,b,k,m,o: (k / 'System.map').write_bytes(b''))
probe('missing kernel exports', lambda r,b,k,m,o: (k / 'Module.symvers').unlink())
probe('existing output refused', lambda r,b,k,m,o: o.mkdir())


def linked_file(root, build, kernel, module, output):
    (module / 'Module.symvers').unlink()
    (root / 'foreign').write_bytes(b'foreign')
    (module / 'Module.symvers').symlink_to(root / 'foreign')


def duplicate_kernel(root, build, kernel, module, output):
    other = build / 'target-other/linux-qualcommax_ipq807x/linux-6.18.39'
    other.mkdir(parents=True)
    (other / 'Module.symvers').write_bytes(b'other')


probe('symlink export refused', linked_file)
probe('multiple kernel export tables refused', duplicate_kernel)
print(json.dumps({'scope': 'Synthetic collection, not actual build/ABI proof', 'tests': results}, indent=2))
