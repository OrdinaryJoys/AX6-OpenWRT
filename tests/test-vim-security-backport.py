#!/usr/bin/env python3
"""Offline locked-byte helper tests; no downloads/builds or production commands.

Optional --prepared-source-root adds an actual exact-source positive control.
Without it, prepared-source identity success is NOT claimed by synthetic mocks.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "AX6-IPQ/scripts/apply-vim-security-backport.py"
FIXTURES = ROOT / "tests/fixtures/vim-security"
spec = importlib.util.spec_from_file_location("vim_backport", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
META, _, PATCH = helper.bundle_data()
results = []
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--prepared-source-root", type=Path)
args = parser.parse_args()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(parent):
    packages = parent / "packages"
    target = packages / "utils/vim"
    (target / "patches").mkdir(parents=True)
    shutil.copyfile(FIXTURES / "base.Makefile", target / "Makefile")
    for name in META["base_patchset"]:
        shutil.copyfile(FIXTURES / name, target / "patches" / name)
    # Unrelated package content must survive application unchanged.
    (target / "files").mkdir()
    (target / "files/preserve-me").write_bytes(b"unrelated pinned package content\n")
    return packages, target


def snapshot(root):
    data = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        value = [stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode)]
        if path.is_symlink():
            value.append(str(path.readlink()))
        elif path.is_file():
            value.append(digest(path))
        data[str(path.relative_to(root))] = value
    return data


def cli(operation, root, expected):
    cp = subprocess.run([sys.executable, str(HELPER), operation, str(root)],
                        capture_output=True, text=True, timeout=40)
    assert cp.returncode == expected, (operation, cp.returncode, cp.stdout, cp.stderr)
    value = json.loads(cp.stdout)
    assert not cp.stderr, cp.stderr
    if expected:
        assert value["status"] == "FAIL"
    return value


def positive(parent):
    packages, target = package(parent)
    old_patches = {name: digest(target / "patches" / name) for name in META["base_patchset"]}
    assert cli("apply", packages, 0)["status"] == "APPLIED_EXACT_BYTES"
    assert digest(target / "Makefile") == META["desired_recipe_sha256"]
    assert cli("check", packages, 0)["status"] == "PASS_DESIRED_PACKAGE_BYTES_ONLY"
    before = snapshot(packages)
    assert cli("apply", packages, 0)["status"] == "ALREADY_APPLIED_EXACT_BYTES"
    assert snapshot(packages) == before
    assert old_patches == {name: digest(target / "patches" / name) for name in old_patches}
    assert (target / "files/preserve-me").read_bytes() == b"unrelated pinned package content\n"
    return packages, target


def run(name, callback):
    with tempfile.TemporaryDirectory(prefix="ax6-vim-unit-") as directory:
        callback(Path(directory))
    results.append({"name": name, "status": "PASS"})


run("full-apply-check-idempotence-preserves-unrelated-and-old-patches", positive)


def reject_mutation(parent, change, desired=False, operation="apply"):
    packages, target = positive(parent) if desired else package(parent)
    change(packages, target)
    before = snapshot(packages)
    cli(operation, packages, 2)
    assert snapshot(packages) == before, "rejected input was modified"


mutations = {
    "changed-base-full-recipe": lambda p, t: (t / "Makefile").write_bytes((t / "Makefile").read_bytes() + b"# drift\n"),
    "unknown-extra-patch": lambda p, t: (t / "patches/999-unknown.patch").write_bytes(b"unknown\n"),
    "extra-patch-backup-file": lambda p, t: (t / "patches/010-no-msgfmt.patch.orig").write_bytes(b"unknown\n"),
    "missing-packaging-patch": lambda p, t: (t / "patches/010-no-msgfmt.patch").unlink(),
    "changed-packaging-patch": lambda p, t: (t / "patches/020-remove-helptags-generation.patch").write_bytes(b"drift\n"),
    "partial-source-patch-only": lambda p, t: (t / "patches" / META["source_patch_name"]).write_bytes(PATCH),
    "makefile-wrong-mode": lambda p, t: (t / "Makefile").chmod(0o755),
    "cooperative-lock-exists": lambda p, t: (t / ".ax6-vim-security.lock").write_bytes(b"busy\n"),
    "patch-name-is-directory": lambda p, t: ((t / "patches/010-no-msgfmt.patch").unlink(), (t / "patches/010-no-msgfmt.patch").mkdir()),
    "makefile-symlink": lambda p, t: ((t / "Makefile").unlink(), (t / "Makefile").symlink_to(FIXTURES / "base.Makefile")),
    "patch-symlink": lambda p, t: ((t / "patches/010-no-msgfmt.patch").unlink(), (t / "patches/010-no-msgfmt.patch").symlink_to(FIXTURES / "010-no-msgfmt.patch")),
}
for name, mutation in mutations.items():
    run(name, lambda parent, mutation=mutation: reject_mutation(parent, mutation))


for name, mutation in {
    "partial-recipe-only": lambda p, t: (t / "patches" / META["source_patch_name"]).unlink(),
    "changed-desired-recipe": lambda p, t: (t / "Makefile").write_bytes((t / "Makefile").read_bytes() + b"# drift\n"),
    "changed-desired-source-patch": lambda p, t: (t / "patches" / META["source_patch_name"]).write_bytes(b"drift\n"),
    "desired-extra-patch": mutations["unknown-extra-patch"],
    "desired-missing-original-patch": mutations["missing-packaging-patch"],
}.items():
    for operation in ("apply", "check"):
        run(name + "-" + operation, lambda parent, mutation=mutation, operation=operation:
            reject_mutation(parent, mutation, desired=True, operation=operation))


run("check-refuses-unmodified-base", lambda parent: reject_mutation(parent, lambda p, t: None, operation="check"))


def bundle_negative(parent, name, data):
    packages, _ = package(parent)
    bundle = parent / "bundle"
    shutil.copytree(helper.BUNDLE, bundle)
    if data is None:
        (bundle / name).unlink()
    else:
        (bundle / name).write_bytes(data)
    before = snapshot(packages)
    try:
        helper.apply(packages, bundle)
    except (helper.Invalid, OSError, ValueError):
        pass
    else:
        raise AssertionError("unlocked bundle was accepted")
    assert snapshot(packages) == before


for name, entry, data in (
    ("bundle-changed-recipe-patch", "recipe.delta.patch", b"bad patch\n"),
    ("bundle-changed-source-patch", META["source_patch_name"], b"bad patch\n"),
    ("bundle-missing-source-patch", META["source_patch_name"], None),
    ("bundle-extra-entry", "extra.json", b"{}\n"),
    ("bundle-source-provenance-drift", "provenance.json",
     (helper.BUNDLE / "provenance.json").read_bytes().replace(META["source_commit"].encode(), b"0" * 40)),
    ("bundle-archive-provenance-drift", "provenance.json",
     (helper.BUNDLE / "provenance.json").read_bytes().replace(META["source_mirror_sha256"].encode(), b"0" * 64)),
):
    run(name, lambda parent, entry=entry, data=data: bundle_negative(parent, entry, data))


def patch_result_negative(parent, stdout, rc):
    # Pure guard injection, explicitly not a GNU/BSD patch behavior claim.
    packages, _ = package(parent)
    before = snapshot(packages)
    fake = subprocess.CompletedProcess(["patch"], rc, stdout, b"")
    with mock.patch.object(helper.subprocess, "run", return_value=fake):
        try:
            helper.apply(packages)
        except helper.Invalid:
            pass
        else:
            raise AssertionError("invalid patch result accepted")
    assert snapshot(packages) == before


for name, stdout, rc in (
    ("patch-offset-refused-before-publication", b"Hunk #1 succeeded (offset 1 line).\n", 0),
    ("patch-fuzz-refused-before-publication", b"Hunk #1 succeeded with fuzz 1.\n", 0),
    ("patch-error-refused-before-publication", b"Hunk FAILED\n", 1),
    ("patch-noop-success-refused-by-exact-output-hash", b"patching file Makefile\n", 0),
):
    run(name, lambda parent, stdout=stdout, rc=rc: patch_result_negative(parent, stdout, rc))


def interrupted_publication(parent):
    packages, target = package(parent)
    real_replace = helper.os.replace
    calls = []

    def replace(src, dst):
        calls.append((str(src), str(dst)))
        if len(calls) == 2:
            raise OSError("injected second-publication failure")
        return real_replace(src, dst)

    with mock.patch.object(helper.os, "replace", side_effect=replace):
        try:
            helper.apply(packages)
        except OSError as exc:
            assert str(exc) == "injected second-publication failure"
        else:
            raise AssertionError("injected failure was hidden")
    assert len(calls) == 2
    assert digest(target / "Makefile") == META["desired_recipe_sha256"]
    assert not (target / "patches" / META["source_patch_name"]).exists()
    assert not (target / ".ax6-vim-security.lock").exists()
    partial = snapshot(packages)
    cli("apply", packages, 2)
    cli("check", packages, 2)
    assert snapshot(packages) == partial


run("second-publication-error-propagates-and-partial-rerun-refuses", interrupted_publication)


def source_negative(parent, missing=False, symlink=False):
    source = parent / "source"
    for name in META["prepared_files"]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unverified source\n")
    if missing:
        (source / "src/version.c").unlink()
    if symlink:
        (source / "src/sign.c").unlink()
        (source / "src/sign.c").symlink_to(FIXTURES / "base.Makefile")
    before = snapshot(source)
    cli("prepared", source, 2)
    assert snapshot(source) == before


run("prepared-unknown-source-bytes-refused", source_negative)
run("prepared-missing-version-refused", lambda parent: source_negative(parent, missing=True))
run("prepared-symlink-refused", lambda parent: source_negative(parent, symlink=True))

if args.prepared_source_root:
    actual = cli("prepared", args.prepared_source_root, 0)
    assert actual["files"] == META["prepared_files"]
    results.append({"name": "actual-prepared-source-complete-hash-positive", "status": "PASS"})

    def actual_source_mutation(parent, changed):
        for name in META["prepared_files"]:
            target = parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.prepared_source_root / name, target)
        target = parent / changed
        target.write_bytes(target.read_bytes() + b"\n/* deliberate test drift */\n")
        before = snapshot(parent)
        cli("prepared", parent, 2)
        assert snapshot(parent) == before

    for changed in META["prepared_files"]:
        run("actual-source-one-file-drift-refused-" + changed,
            lambda parent, changed=changed: actual_source_mutation(parent, changed))

print(json.dumps({"status": "PASS", "cases": len(results), "results": results,
                  "actual_prepared_source_positive": bool(args.prepared_source_root),
                  "boundary": "Offline byte/dispatcher/patch guards. No package cross-build or AX6 runtime proof; four patch-result guards and one publication-failure guard use explicit mocks, not real process/power loss."}, indent=2))
