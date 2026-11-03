#!/usr/bin/env python3
"""Offline recipe guards and actual-function native tests. Never run package scripts."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "AX6-IPQ/scripts/apply-vlmcsd-scope-backport.py"
spec = importlib.util.spec_from_file_location("vlmcsd_scope", HELPER)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
ARCHIVES = {
    "vlmcsd-e599080486478e219cd065e141d6de050a450c27.tar.gz": "752263dbfacc7ec1cd6c7dca8c56367f1693b3c8d8fe2786b756b322a35bb378",
    "debian-971ade7b0e6035e34f46f98bdb95e305ea1abab8.tar.gz": "1d351268c7592b4037b46c183e5997a84e69e4c3205f00275e5f0bcfc5718e0a",
    "docker-4195d04f687973a514e3fb663bd87161afd46697.tar.gz": "b74720ae9fe34f968c8c40f1dcdc9d21630e2199e07e4a0fb71f377b11cbedf9",
    "vlmcsd-2020.03.30~e5990804.tar.zst": "a5b9854a7cb2055fa2c7890ee196a7fbbec1fd6165bf5115504d160e2e3a7a19",
}
PROFILES = {"normal": ([], 17), "no-random": (["-DNO_RANDOM_EPID"], 16),
            "no-log": (["-DNO_LOG"], 17),
            "minimal": (["-DNO_RANDOM_EPID", "-DNO_CL_PIDS", "-DNO_INI_FILE"], 3),
            "minimal-no-log": (["-DNO_RANDOM_EPID", "-DNO_CL_PIDS", "-DNO_INI_FILE", "-DNO_LOG"], 3)}


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def positive_ok(rc, stdout, stderr, cases):
    return rc == 0 and not stderr and stdout == ("VLMCSD_SCOPE cases=%d\n" % cases).encode()


def negative_ok(rc, stdout, stderr, marker):
    return rc == 86 and not stdout and stderr == ("VLMCSD_ASSERT " + marker + "\n").encode()


def snapshot(root):
    result = {}
    for p in root.rglob("*"):
        s = p.lstat()
        value = [stat.S_IFMT(s.st_mode), stat.S_IMODE(s.st_mode)]
        if p.is_symlink():
            value.append(str(p.readlink()))
        elif p.is_file():
            value.append(h.sha(p.read_bytes()))
        result[p.relative_to(root).as_posix()] = value
    return result


def extract_tar(data, target, strip_first=False):
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            require(not name.is_absolute() and ".." not in name.parts and
                    (member.isdir() or member.isfile()), "unsupported archive member")
            parts = name.parts[1:] if strip_first else name.parts
            if not parts:
                continue
            path = target.joinpath(*parts)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile(member).read())
                # Git archives may carry 0664; model checkout executable bits,
                # not the archiver's group-write umask, for helper file modes.
                path.chmod(0o755 if member.mode & 0o111 else 0o644)


def masked(text):
    return re.sub(r'/\*[\s\S]*?\*/|//[^\r\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: "".join(c if c in "\r\n" else " " for c in m[0]), text)


def function(text, name):
    clean = masked(text)
    matches = list(re.finditer(r"(?m)^(?:static\s+)?[\w* ]+\s+" + name +
                              r"\s*\([^;{}]*\)\s*\{", clean))
    require(len(matches) == 1, "actual function cardinality: " + name)
    start = matches[0].start()
    brace = clean.index("{", start)
    depth = 0
    for end in range(brace, len(clean)):
        depth += (clean[end] == "{") - (clean[end] == "}")
        if depth == 0:
            return text[start:end + 1], text.count("\n", 0, start) + 1
    raise RuntimeError("unclosed actual function: " + name)


C_PREFIX = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include "kms.h"
#include "endian.h"
#include "helpers.h"
#include "shared_globals.h"
static unsigned cases, random_calls;
static void check(int ok, const char *marker) {
    if (!ok) { fprintf(stderr, "VLMCSD_ASSERT %s\n", marker); exit(86); }
}
#ifndef NO_RANDOM_EPID
static int fixture_rand(void) { ++random_calls; return 1; }
static time_t fixture_time(time_t *out) { if(out) *out=1700000000; return 1700000000; }
#define rand fixture_rand
#define time fixture_time
#endif
int_fast8_t RandomizationLevel;
uint16_t Lcid=1033, HostBuild=7601;
int_fast8_t UseServerRpcNDR64=0;
KmsResponseParam_t params[1];
KmsResponseParam_t *KmsResponseParameters=params;
static VlmcsdHeader_t data;
PVlmcsdHeader_t KmsData=&data;
'''
C_MAIN = r'''
static void exercise(int level, int configured, int source_hwid, int output_hwid, int unicode, int automatic) {
    RESPONSE r, before;
    BYTE hw[10], source[10];
    const char *label="unchanged";
    const char *expected;
    memset(&r,0xa5,sizeof(r)); before=r;
    memset(hw,0xcc,sizeof(hw));
    for(unsigned i=0;i<sizeof(source);++i) source[i]=(BYTE)(i+10);
    memset(params,0,sizeof(params));
    RandomizationLevel=level; Lcid=automatic?0:1033; HostBuild=automatic?0:7601; random_calls=0;
    params[0].Epid=configured?(unicode?"cfg-\xc3\xa9":"configured-EPID"):NULL;
    params[0].HwId=source_hwid?source+1:NULL;
#ifndef NO_LOG
    params[0].EpidSource="configured source";
#endif
    getEpid(&r,&label,0,output_hwid?hw+1:NULL,"default-EPID");
    ++cases;
#if !defined(NO_RANDOM_EPID) || !defined(NO_CL_PIDS) || !defined(NO_INI_FILE)
    expected=configured?params[0].Epid:"default-EPID";
#ifndef NO_RANDOM_EPID
    if(!configured && level==2)
        expected=automatic?"55041-00206-100-000003-03-1052-7601.0000-1952017":"55041-00206-100-000003-03-1033-7601.0000-1952017";
#endif
#else
    expected="default-EPID";
    configured=0; unicode=0;
#endif
    size_t length=(configured&&unicode)?5:strlen(expected);
    check(LE32(r.PIDSize)==(length+1)*2,"pid-size");
    for(size_t i=0;i<length;i++) {
        uint16_t code=(configured&&unicode&&i==4)?0xe9:(unsigned char)expected[i];
        check(LE16(r.KmsPID[i])==code,"pid-content");
    }
    check(r.KmsPID[length]==0,"pid-terminator");
    before.PIDSize=r.PIDSize;
    memcpy(before.KmsPID,r.KmsPID,(length+1)*sizeof(WCHAR));
    check(!memcmp(&r,&before,sizeof(r)),"response-other-fields");
    check(hw[0]==0xcc&&hw[9]==0xcc,"hwid-canary");
    for(unsigned i=0;i<8;i++)
        check(hw[i+1]==(configured&&source_hwid&&output_hwid?source[i+1]:0xcc),"hwid-content");
#ifndef NO_LOG
    const char *expected_label=configured?"configured source":"vlmcsd default";
#ifndef NO_RANDOM_EPID
    if(!configured&&level==2) expected_label="randomized on every request";
#endif
    check(!strcmp(label,expected_label),"source-label");
#else
    check(!strcmp(label,"unchanged"),"no-log-source");
#endif
    unsigned expected_calls=0;
#ifndef NO_RANDOM_EPID
    if(!configured&&level==2) expected_calls=automatic?6:4;
#endif
    check(random_calls==expected_calls,"random-call-ledger");
}
int main(void) {
    HostBuild_t builds[2]; memset(builds,0,sizeof(builds));
    builds[0].BuildNumber=17763;builds[0].PlatformId=3612;builds[0].ReleaseDate=1530000000;
    builds[1].BuildNumber=7601;builds[1].PlatformId=55041;builds[1].ReleaseDate=1500000000;
    data.HostBuildCount=2;data.HostBuildList=builds;
    data.CsvlkData[0].GroupId=206;data.CsvlkData[0].MinKeyId=100000000;
    data.CsvlkData[0].MaxKeyId=100001000;data.CsvlkData[0].ReleaseDate=1400000000;
    for(int level=0;level<3;level++) exercise(level,0,0,1,0,0);
#if !defined(NO_RANDOM_EPID) || !defined(NO_CL_PIDS) || !defined(NO_INI_FILE)
    for(int level=0;level<3;level++) for(int hw=0;hw<2;hw++) for(int out=0;out<2;out++)
        exercise(level,1,hw,out,0,0);
    exercise(2,1,1,1,1,0);
#ifndef NO_RANDOM_EPID
    exercise(2,0,0,1,0,1);
#endif
#endif
    printf("VLMCSD_SCOPE cases=%u\n",cases);return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages-cache", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True, help="three Git archives plus pinned OpenWrt mirror repack; no network access")
    parser.add_argument('--zstd', default='zstd')
    parser.add_argument("--output", type=Path, required=True, help="fresh directory")
    parser.add_argument("--gcc", default="/opt/homebrew/bin/gcc-16")
    parser.add_argument("--sanitizer-cc", default="/opt/homebrew/bin/gcc-16")
    args = parser.parse_args()
    out = args.output.absolute()
    require(not out.exists(), "fresh test output required")
    bound = [Path(__file__).resolve(), HELPER, *sorted(h.BUNDLE.iterdir())]
    identities = {str(p): h.sha(p.read_bytes()) for p in bound}
    archives = {n: (args.inputs / n).read_bytes() for n in ARCHIVES}
    require({n: h.sha(b) for n, b in archives.items()} == ARCHIVES, "pinned archive bytes mismatch")
    out.mkdir(parents=True)
    results = {"status": "INCOMPLETE", "inputs": identities, "archives": ARCHIVES,
               "source_pin": h.SOURCE_PIN, "feed_pin": h.FEED_PIN, "helper_cases": [], "native": [], "cli": []}
    def checkpoint():
        save(out / "RESULTS.json", results)
    def case(name, fn):
        path = out / "helper-tests" / name
        path.mkdir(parents=True)
        fn(path)
        results["helper_cases"].append(name)
        checkpoint()
    def cli(operation, root, ok=True, reason=None, output=None):
        command = [sys.executable, "-B", str(HELPER), operation, str(root)]
        if output:
            command += ["--output", str(output)]
        run = subprocess.run(command, capture_output=True, timeout=30)
        results["cli"].append({"command": command, "returncode": run.returncode,
                               "stdout": run.stdout.decode(), "stderr": run.stderr.decode()})
        checkpoint()
        require(run.returncode == (0 if ok else 2) and not run.stderr, "helper CLI exit/stderr")
        value = json.loads(run.stdout)
        if not ok:
            require(value["status"] == "FAIL" and (reason is None or reason in value["error"]),
                    "helper exact rejection reason")
        return value
    try:
        upstream = out / 'upstream-source'
        extract_tar(archives[next(iter(ARCHIVES))], upstream, True)
        for name, pin in h.SUBMODULES.items():
            extract_tar(archives[name + "-" + pin + ".tar.gz"], upstream / name, True)
        upstream_files = h.source_inventory(upstream)[0]
        require(len(upstream_files) == 103 and h.tree_sha(upstream_files) ==
                '1306e48387a9a6b048190fc9f0ab2b7564fe745a30f5e2d6175e56b7b0715e5a', 'Git/submodule identity')
        mirror = subprocess.run([args.zstd, '-dc'], input=archives['vlmcsd-2020.03.30~e5990804.tar.zst'],
                                capture_output=True, timeout=30)
        require(mirror.returncode == 0 and not mirror.stderr, 'native zstd mirror decode')
        base = out / 'base-source'
        extract_tar(mirror.stdout, base, True)
        before_files = h.source_inventory(base)[0]
        expected_mirror = dict(upstream_files)
        del expected_mirror['.gitmodules']
        for name in h.SUBMODULES:
            pointer = ('gitdir: ../.git/modules/' + name + '\n').encode()
            expected_mirror[name + '/.git'] = h.sha(pointer)
        require(before_files == expected_mirror and len(before_files) == 104 and
                h.tree_sha(before_files) == h.BASE_TREE_SHA256, 'complete Git-to-mirror packaging identity')
        results['mirror_repack_delta'] = {'removed': ['.gitmodules'],
            'added': ['debian/.git', 'docker/.git'], 'remaining102_files': 'BYTE_IDENTICAL_TO_PINNED_GIT'}
        archive = subprocess.run(["git", "-C", str(args.packages_cache), "archive", "--format=tar",
                                  h.FEED_PIN, "net/vlmcsd"], capture_output=True, timeout=45)
        require(archive.returncode == 0 and not archive.stderr, "exact packages object unavailable")
        (out / "packages-input.tar").write_bytes(archive.stdout)
        def package(parent):
            root = parent / "packages"
            extract_tar(archive.stdout, root)
            (root / "unrelated").mkdir()
            (root / "unrelated/preserve").write_bytes(b"untouched\n")
            require(h.sha((root / "net/vlmcsd/Makefile").read_bytes()) == h.BASE_RECIPE_SHA256,
                    "recipe object does not match helper preimage")
            return root, root / "net/vlmcsd"
        def positive(parent):
            root, pkg = package(parent)
            old_files = snapshot(pkg / "files")
            require(cli("apply", root, output=parent / "apply-evidence")["status"] == "APPLIED_EXACT_BYTES", "apply")
            require(cli("check", root, output=parent / "check-evidence")["status"] == "PASS_DESIRED_PACKAGE_BYTES_ONLY", "check")
            before = snapshot(root)
            require(cli("apply", root)["status"] == "ALREADY_APPLIED_EXACT_BYTES", "idempotence")
            require(snapshot(root) == before and snapshot(pkg / "files") == old_files and
                    (root / "unrelated/preserve").read_bytes() == b"untouched\n", "unrelated preservation")
        case("apply-check-idempotence-and-evidence", positive)
        mutations = {
            "full-recipe-drift": lambda p: (p / "Makefile").write_bytes((p / "Makefile").read_bytes()+b"# drift\n"),
            "wrong-source-pin": lambda p: (p / "Makefile").write_bytes((p / "Makefile").read_bytes().replace(h.SOURCE_PIN.encode(), b"0"*40)),
            "release-only-partial": lambda p: (p / "Makefile").write_bytes((p / "Makefile").read_bytes().replace(b"PKG_RELEASE:=8", b"PKG_RELEASE:=9")),
            "existing-lock": lambda p: (p / ".ax6-vlmcsd-scope.lock").touch(),
            "recipe-mode": lambda p: (p / "Makefile").chmod(0o755),
            "patch-only-partial": lambda p: ((p / "patches").mkdir(), (p / "patches" / h.PATCH_NAME).write_bytes(h.bundle_data())),
            "unknown-patch": lambda p: ((p / "patches").mkdir(), (p / "patches/999.patch").write_bytes(b"bad\n")),
            "recipe-symlink": lambda p: ((p / "Makefile").rename(p / "original"), (p / "Makefile").symlink_to(p / "original")),
            "patch-dir-symlink": lambda p: ((p / "other").mkdir(), (p / "patches").symlink_to(p / "other")),
        }
        for name, change in mutations.items():
            def reject(parent, change=change):
                root, pkg = package(parent); change(pkg); before = snapshot(root)
                cli("apply", root, False)
                require(snapshot(root) == before, "reject mutated package")
            case(name, reject)
        def desired_corrupt(parent):
            root, pkg = package(parent); cli("apply", root)
            (pkg / "patches" / h.PATCH_NAME).write_bytes(b"bad\n")
            before = snapshot(root)
            cli("apply", root, False, "unknown or partially applied")
            cli("check", root, False, "unknown or partially applied")
            require(snapshot(root) == before, "desired drift preservation")
        case("desired-patch-drift", desired_corrupt)
        def bundle_bad(parent):
            root, _ = package(parent); copy = parent / "bundle"; shutil.copytree(h.BUNDLE, copy)
            (copy / h.PATCH_NAME).write_bytes(b"bad\n"); before = snapshot(root)
            try:
                h.apply(root, copy)
            except h.Invalid as e:
                require(str(e) == "vlmcsd source patch hash mismatch", "bundle exact gate")
            else:
                raise RuntimeError("bundle drift accepted")
            require(snapshot(root) == before, "bundle rejection wrote input")
        case("bundle-hash-drift", bundle_bad)
        def interrupted(parent):
            root, pkg = package(parent); original = h.os.replace; count = 0
            def replace(src, dst):
                nonlocal count
                count += 1
                if count == 2:
                    raise OSError("second rename injection")
                return original(src, dst)
            with mock.patch.object(h.os, "replace", side_effect=replace):
                try:
                    h.apply(root)
                except OSError as e:
                    require(str(e) == "second rename injection", "injection exact exception")
                else:
                    raise RuntimeError("publication failure hidden")
            require(count == 2 and not (pkg / ".ax6-vlmcsd-scope.lock").exists(), "lock cleanup")
            before = snapshot(root)
            cli("apply", root, False, "unknown or partially applied")
            cli("check", root, False, "unknown or partially applied")
            require(snapshot(root) == before, "mixed state silently repaired")
        case("interrupted-second-publication-fail-closed", interrupted)
        prepared = out / "prepared-source"; shutil.copytree(base, prepared)
        patch = h.bundle_data()
        operations = []
        for dry in (True, False):
            command = ["patch", "--batch", "--forward", "--fuzz=0", "-p1"] + (["--dry-run"] if dry else [])
            run = subprocess.run(command, cwd=prepared, input=patch, capture_output=True, timeout=30)
            operations.append({"command": command, "returncode": run.returncode,
                               "stdout": run.stdout.decode(), "stderr": run.stderr.decode()})
            require(run.returncode == 0 and not run.stderr and not re.search(
                rb"offset|fuzz|FAILED|reject|malformed", run.stdout, re.I), "real exact-source patch apply")
        results["patch_operations"] = operations
        before_kms = (base / "src/kms.c").read_bytes()
        expected_kms = before_kms.replace(b"\tconst char* pid;\r\n",
            b"#ifndef NO_RANDOM_EPID\r\n\tchar ePid[PID_BUFFER_SIZE];\r\n#endif\r\n\tconst char* pid;\r\n", 1).replace(
            b"\t\t\tchar ePid[PID_BUFFER_SIZE];\r\n", b"", 1)
        require((prepared / "src/kms.c").read_bytes() == expected_kms and
                h.sha(expected_kms) == h.DESIRED_KMS_SHA256, "exact source output bytes")
        final_files = h.source_inventory(prepared)[0]
        require({p for p in before_files if before_files[p] != final_files[p]} == {"src/kms.c"} and
                set(before_files) == set(final_files), "unrelated source changed")
        results["prepared"] = cli("prepared", prepared, output=out / "prepared-evidence")
        require(all(stat.S_IMODE(p.stat().st_mode) == 0o444 for p in
                    (out / "prepared-evidence/source").rglob("*") if p.is_file()), "copied data executable/writable")
        copies = json.loads((out / 'prepared-evidence/SOURCE-COPIES.json').read_text())['files']
        require(len(copies) == h.SOURCE_FILE_COUNT and {r['original']: r['sha256'] for r in copies} == final_files and
                {r['copy'] for r in copies} == {'%04d.dat' % i for i in range(h.SOURCE_FILE_COUNT)}, 'complete non-hidden copy index')
        require(all(not part.startswith('.') for r in copies for part in Path(r['copy']).parts) and
                all(h.sha((out / 'prepared-evidence/source-copies' / r['copy']).read_bytes()) == r['sha256'] and
                    stat.S_IMODE((out / 'prepared-evidence/source-copies' / r['copy']).stat().st_mode) == 0o444
                    for r in copies), 'opaque non-hidden public data bytes/modes')
        for name in ("src/kms.c", "src/helpers.c", "src/kms.h", "debian/control"):
            def source_drift(parent, name=name):
                target = parent / "source"; shutil.copytree(prepared, target)
                p = target / name; require(p.exists(), "real drift input missing")
                p.write_bytes(p.read_bytes() + b"drift\n"); before = snapshot(target)
                cli("prepared", target, False, "mismatch")
                require(snapshot(target) == before, "prepared reject wrote input")
            case("prepared-drift-" + name.replace("/", "-"), source_drift)
        def extra_source(parent):
            target = parent / "source"; shutil.copytree(prepared, target)
            (target / "extra").write_bytes(b"drift"); cli("prepared", target, False, "complete source tree mismatch")
        case("prepared-extra-file", extra_source)
        def generated_metadata(parent):
            target = parent / 'source'; shutil.copytree(prepared, target)
            (target / 'version.date').write_bytes(b'1585545669\n')
            (target / '.prepared_fixture').write_bytes(b'')
            result = cli('prepared', target)
            require(set(result['generated_prepare_metadata']) == {'version.date', '.prepared_fixture'},
                    'generated metadata not explicitly reported')
        case('prepared-generated-metadata', generated_metadata)
        def malformed_metadata(parent):
            target = parent / 'source'; shutil.copytree(prepared, target)
            (target / 'version.date').write_bytes(b'not a timestamp\n')
            cli('prepared', target, False, 'invalid generated version.date')
        case('prepared-malformed-generated-metadata', malformed_metadata)
        def occupied_output(parent):
            root, _ = package(parent); before = snapshot(root)
            cli("apply", root, False, "fresh evidence directory required", output=parent)
            require(snapshot(root) == before, "occupied output modified package")
        case("existing-evidence-refused-before-apply", occupied_output)

        selected = {}
        source_text = (prepared / "src/kms.c").read_bytes().decode()
        helper_text = (prepared / "src/helpers.c").read_bytes().decode()
        random_names = ["getPlatformId", "getReleaseDate", "itoc", "getRandomServerType", "generateRandomPid"]
        other_names = ["getEpidFromString", "getEpid"]
        fragments = out / "extracted"; fragments.mkdir()
        records = []
        for path, text, names in [("src/kms.c", source_text, random_names+other_names),
                                  ("src/helpers.c", helper_text, ["utf8_to_ucs2_char", "utf8_to_ucs2"])]:
            for name in names:
                body, line = function(text, name); selected[name] = body
                (fragments / (name + ".c.txt")).write_bytes(body.encode())
                records.append({"function": name, "path": path, "line": line, "sha256": h.sha(body.encode()),
                                "projection": "none; complete actual definition"})
        lcid = re.findall(r"static const uint16_t LcidList\[\] = \{[\s\S]*?\};", source_text)
        require(len(lcid) == 1, "actual LCID table")
        save(fragments / "MANIFEST.json", records)
        def render(functions):
            return C_PREFIX + "\n" + "\n".join(functions[n] for n in ["utf8_to_ucs2_char", "utf8_to_ucs2"]) + \
                "\n#ifndef NO_RANDOM_EPID\n" + lcid[0] + "\n" + "\n".join(functions[n] for n in random_names) + \
                "\n#endif\n" + "\n".join(functions[n] for n in other_names) + C_MAIN
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:halt_on_error=1:abort_on_error=0:exitcode=97",
                   UBSAN_OPTIONS="halt_on_error=1:abort_on_error=0:print_stacktrace=1:exitcode=98")
        results["sanitizer_environment"] = {k: env[k] for k in ("ASAN_OPTIONS", "UBSAN_OPTIONS")}
        def native(label, code, compiler, flags, expected=None, cases=None, witness=False):
            path = out / (label + ".c"); path.write_bytes(code.encode()); binary = out / label
            command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Werror", "-fno-inline",
                       "-I", str(prepared / "src"), *flags, str(path), "-o", str(binary)]
            compile_result = subprocess.run(command, capture_output=True, timeout=60)
            (out / (label + ".compile.stdout")).write_bytes(compile_result.stdout)
            (out / (label + ".compile.stderr")).write_bytes(compile_result.stderr)
            require(compile_result.returncode == 0 and not compile_result.stdout and not compile_result.stderr,
                    "clean compile: " + label)
            run = subprocess.run([str(binary)], capture_output=True, env=env, timeout=30)
            (out / (label + ".stdout")).write_bytes(run.stdout)
            (out / (label + ".stderr")).write_bytes(run.stderr)
            entry = {"label": label, "compile_command": command, "compile_returncode": compile_result.returncode,
                     "source_sha256": h.sha(path.read_bytes()), "binary_sha256": h.sha(binary.read_bytes()),
                     "returncode": run.returncode, "stdout_sha256": h.sha(run.stdout), "stderr_sha256": h.sha(run.stderr)}
            results["native"].append(entry); checkpoint()
            if witness:
                require(run.returncode == 97 and not run.stdout and b"ERROR: AddressSanitizer: stack-use-after-scope" in run.stderr
                        and b"ePid" in run.stderr, "original source scope witness")
                entry["status"] = "ORIGINAL_BUG_DIAGNOSTIC_WITNESS_NOT_SEMANTIC_MUTANT"
            elif expected:
                require(negative_ok(run.returncode, run.stdout, run.stderr, expected), "exact runtime negative: " + label)
                entry["status"] = "PASS_EXACT_SEMANTIC_NEGATIVE"
            else:
                require(positive_ok(run.returncode, run.stdout, run.stderr, cases), "exact positive: " + label)
                entry["status"] = "PASS_ACTUAL_FUNCTIONS_HOST_ONLY"
            checkpoint()
        mutants = [
            ("random-select", "getEpid", "pid = ePid;", "pid = defaultEPid;", "pid-size"),
            ("random-level", "getEpid", "RandomizationLevel == 2", "RandomizationLevel == 1", "pid-size"),
            ("configured-select", "getEpid", "pid = KmsResponseParameters[index].Epid;", "pid = defaultEPid;", "pid-size"),
            ("conversion-input", "getEpid", "getEpidFromString(baseResponse, pid);", 'getEpidFromString(baseResponse, pid + 1);', "pid-size"),
            ("pid-size", "getEpidFromString", "((unsigned int)length + 1)", "((unsigned int)length + 2)", "pid-size"),
            ("hwid-overcopy", "getEpid", "sizeof(((RESPONSE_V6 *)0)->HwId)", "sizeof(((RESPONSE_V6 *)0)->HwId) + 1", "hwid-canary"),
            ("hwid-skip", "getEpid", "sizeof(((RESPONSE_V6 *)0)->HwId)", "0", "hwid-content"),
            ("source-label", "getEpid", '"randomized on every request"', '"wrong source"', "source-label"),
        ]
        sanitizer = ["-fsanitize=address,undefined", "-fsanitize-address-use-after-scope", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
        results["compilers"] = {}
        for tag, compiler, flags in [("gcc", args.gcc, ["-Wdangling-pointer=2"]), ("sanitizer", args.sanitizer_cc, sanitizer)]:
            identity = subprocess.run([compiler, "--version"], capture_output=True, timeout=15)
            require(identity.returncode == 0 and not identity.stderr, "compiler identity")
            results["compilers"][tag] = identity.stdout.decode()
            for profile, (defines, count) in PROFILES.items():
                native(tag + "-" + profile, render(selected), compiler, flags+defines, cases=count)
            for name, fn, before, after, marker in mutants:
                require(selected[fn].count(before) == 1, "mutant cardinality: " + name)
                mutated = dict(selected); mutated[fn] = mutated[fn].replace(before, after)
                native(tag + "-negative-" + name, render(mutated), compiler, flags, expected=marker)
        old_functions = dict(selected)
        old_functions["getEpid"] = function(before_kms.decode(), "getEpid")[0]
        native("original-scope-witness", render(old_functions), args.sanitizer_cc, sanitizer, witness=True)
        # The actual acceptance predicates, not a different toy predicate.
        require(positive_ok(0,b"VLMCSD_SCOPE cases=17\n",b"",17) and
                negative_ok(86,b"",b"VLMCSD_ASSERT example\n","example"), "oracle valid controls")
        bad = [(0,b"",b"VLMCSD_ASSERT example\n"), (1,b"",b"VLMCSD_ASSERT example\n"),
               (-6,b"",b"VLMCSD_ASSERT example\n"), (97,b"",b"VLMCSD_ASSERT example\n"),
               (86,b"noise",b"VLMCSD_ASSERT example\n"), (86,b"",b"VLMCSD_ASSERT other\n"),
               (86,b"",b"VLMCSD_ASSERT example\nnoise\n"), (86,b"",b"AddressSanitizer: bad\n")]
        require(all(not negative_ok(rc,o,e,"example") for rc,o,e in bad), "negative oracle pollution")
        require(not positive_ok(0,b"VLMCSD_SCOPE cases=16\n",b"",17) and
                not positive_ok(0,b"VLMCSD_SCOPE cases=17\n",b"noise",17), "positive oracle pollution")
        results["oracle_controls"] = {"valid": 2, "negative_rejections": len(bad), "positive_rejections": 2}
        require(h.source_inventory(base)[0] == before_files and h.source_inventory(prepared)[0] == final_files,
                "source stability")
        require({str(p): h.sha(p.read_bytes()) for p in bound} == identities and
                {str(p) for p in h.BUNDLE.iterdir()} == {str(p) for p in bound if p.parent == h.BUNDLE},
                "live test/bundle drift")
        results["artifacts"] = {p.relative_to(out).as_posix(): h.sha(p.read_bytes()) for p in out.iterdir()
                                if p.is_file() and p.name != "RESULTS.json"}
        results["status"] = "PASS_SCOPED_HELPER_AND_NATIVE_FUNCTIONS"
        checkpoint()
        print(json.dumps({"status": results["status"], "helper_cases": len(results["helper_cases"]),
                          "profiles_per_compiler_mode": 5, "positive_calls_per_compiler_mode": 56,
                          "semantic_negatives_per_compiler_mode": len(mutants), "result": str(out / "RESULTS.json")}))
    except Exception as error:
        results["error"] = str(error); checkpoint(); raise


if __name__ == "__main__":
    main()
