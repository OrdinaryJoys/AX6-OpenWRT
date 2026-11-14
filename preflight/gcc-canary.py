"""Compile actual prepared NSS branches under all three logging modes."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys

driver, gcc, evidence = map(Path, sys.argv[1:])
core = (driver / "nss_core.c").read_bytes()
assert hashlib.sha256(core).hexdigest() == "2ffd9f7c12cf21a77b5413b85ffccb0669dab35bd9122c07c5580b0c011f2680"
header = (driver / "nss_core.h").read_bytes()
start = header.index(b"#if defined(CONFIG_DYNAMIC_DEBUG)")
end = header.index(b"#endif", header.index(b"#define nss_trace(s, ...) pr_info", start))
end = header.index(b"#endif", end + len(b"#endif")) + len(b"#endif")
macros = header[start:end]
assert b"#define nss_warning(s, ...)\n" in macros
makefile = (driver / "Makefile").read_bytes()
assert b"-DNSS_DEBUG_LEVEL=0" in makefile and b"-Wall -Werror" in makefile
pattern = rb"(?m)^\t\tret = nss_ipv[46]_update_conn_count[^\n]+\n\t\tif \(ret\) \{\n\t\t\tnss_warning[^\n]+;\n\t\t\}"
blocks = re.findall(pattern, core)
assert len(blocks) == 2 and b"ipv4" in blocks[0] and b"ipv6" in blocks[1]
stale = [block.replace(b"if (ret) {\n", b"if (ret)\n").removesuffix(b"\n\t\t}") for block in blocks]
normalized = core
for good, bad in zip(blocks, stale):
    assert core.count(good) == 1
    normalized = normalized.replace(good, bad)
assert hashlib.sha256(normalized).hexdigest() == "6bebd12a1dcc9a15c1dc0dacb9d275b860740f319dd29e9f5e514a1dd0262d1a"
before = b"""extern void logger(const char *, ...);
#define pr_warn(...) logger(__VA_ARGS__)
#define pr_debug(...) logger(__VA_ARGS__)
extern int nss_ipv4_update_conn_count(int);
extern int nss_ipv6_update_conn_count(int);
"""
for mode, flags in {
    "stock": ["-DNSS_DEBUG_LEVEL=0"],
    "static": ["-DNSS_DEBUG_LEVEL=2"],
    "dynamic": ["-DNSS_DEBUG_LEVEL=0", "-DCONFIG_DYNAMIC_DEBUG=1"],
}.items():
    for label, source in (("candidate", blocks), ("old", stale)):
        name = mode + "-" + label
        code = before + macros + b"\nvoid canary(int max_ipv4_conn, int max_ipv6_conn, void *nss_ctx)\n{\n"
        code += b"int ret; (void)nss_ctx;\n" + b"\n".join(source) + b"\n}\n"
        (evidence / (name + ".c")).write_bytes(code)
        run = subprocess.run([str(gcc), "-std=gnu11", "-Wall", "-Werror", "-Wempty-body",
                              *flags, "-x", "c", "-fsyntax-only", "-"],
                             input=code, capture_output=True)
        diagnostics = run.stderr.decode("ascii", errors="replace")
        (evidence / (name + ".stderr")).write_text(diagnostics)
        if name == "stock-old":
            assert run.returncode == 1 and diagnostics.count("[-Werror=empty-body]") == 2, diagnostics
            assert diagnostics.count("error:") == 2, diagnostics
        else:
            assert run.returncode == 0 and not run.stderr, diagnostics
        print(name, run.returncode)
print("PASS_STOCK_GCC_14_3_NEGATIVE_AND_POSITIVE")
