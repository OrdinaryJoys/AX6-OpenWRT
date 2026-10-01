#!/usr/bin/env python3
"""Apply one locked Vim recipe/backport, or inspect prepared source bytes.

No network, source execution, package install or whole-feed update. Publication
of Makefile + patch is not an atomic multi-file transaction: an interruption
can leave a partial state, which every subsequent invocation refuses. The
exclusive lock coordinates this helper only, not unrelated writers or attackers.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

BUNDLE = Path(__file__).resolve().parents[1] / "package-patches/vim"
PROVENANCE_SHA256 = "9d6d6dc4719652c3f11aa17ec5e8d490a976265b356da07591ac83cb26aebec1"


class Invalid(ValueError):
    """The locked input contract was not met; no implicit repair is allowed."""


def require(ok, reason):
    if not ok:
        raise Invalid(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def directory(path):
    require(stat.S_ISDIR(path.lstat().st_mode), "not a real directory: " + str(path))


def regular(path, root):
    """No symlink inside the caller-selected root, including file ancestors."""
    directory(root)
    relative = path.relative_to(root)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        directory(current)
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode), "not a regular file: " + str(path))
    require(stat.S_IMODE(st.st_mode) == 0o644, "expected mode 0644: " + str(path))
    return path.read_bytes()


def bundle_data(bundle=BUNDLE):
    directory(bundle)
    require({p.name for p in bundle.iterdir()} == {
        "provenance.json", "recipe.delta.patch", "030-sign-jump-ex-command-injection.patch"},
        "unknown/missing Vim bundle entry")
    raw = regular(bundle / "provenance.json", bundle)
    require(sha(raw) == PROVENANCE_SHA256, "Vim provenance hash mismatch")
    meta = json.loads(raw)
    recipe = regular(bundle / "recipe.delta.patch", bundle)
    patch = regular(bundle / meta["source_patch_name"], bundle)
    require(sha(recipe) == meta["recipe_delta_sha256"], "recipe delta hash mismatch")
    require(sha(patch) == meta["source_patch_sha256"], "source patch hash mismatch")
    return meta, recipe, patch


def package_state(packages, meta):
    directory(packages)
    package = packages / "utils/vim"
    recipe = regular(package / "Makefile", packages)
    patch_dir = package / "patches"
    directory(patch_dir)
    names = {p.name for p in patch_dir.iterdir()}
    original = meta["base_patchset"]
    desired = dict(original, **{meta["source_patch_name"]: meta["source_patch_sha256"]})
    require(names in (set(original), set(desired)), "unknown/missing Vim patchset entry")
    hashes = {name: sha(regular(patch_dir / name, packages)) for name in sorted(names)}
    require(all(hashes[name] == value for name, value in original.items()),
            "original Vim packaging patch hash mismatch")
    recipe_hash = sha(recipe)
    if recipe_hash == meta["base_recipe_sha256"] and hashes == original:
        return "base", recipe
    if recipe_hash == meta["desired_recipe_sha256"] and hashes == desired:
        return "desired", recipe
    raise Invalid("unknown or partially applied Vim recipe/patchset")


def strict_recipe_stage(stage, recipe_delta):
    patch_tool = shutil.which("patch")
    require(patch_tool is not None, "patch tool is missing")
    operations = []
    for dry_run in (True, False):
        argv = [patch_tool, "--batch", "--forward", "--fuzz=0", "-p1"]
        if dry_run:
            argv.append("--dry-run")
        result = subprocess.run(argv, input=recipe_delta, cwd=stage, capture_output=True,
                                timeout=30, env=dict(os.environ, LC_ALL="C"))
        stdout, stderr = result.stdout.decode(errors="replace"), result.stderr.decode(errors="replace")
        operations.append({"argv": argv, "returncode": result.returncode,
                           "stdout": stdout, "stderr": stderr})
        require(result.returncode == 0, "recipe patch failed: " + stdout + stderr)
        require(not re.search(r"\b(?:offset|fuzz)\b", stdout + stderr, re.I),
                "recipe patch used fuzz/offset")
    return operations


def write_new(path, data):
    with path.open("xb") as stream:
        stream.write(data)
    path.chmod(0o644)


def apply(packages, bundle=BUNDLE):
    meta, recipe_delta, patch = bundle_data(bundle)
    # Inspect before any write, then lock and inspect again before staging.
    package_state(packages, meta)
    package = packages / "utils/vim"
    lock = package / ".ax6-vim-security.lock"
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    identity = os.fstat(fd)
    try:
        state, before = package_state(packages, meta)
        if state == "desired":
            return {"status": "ALREADY_APPLIED_EXACT_BYTES", "version": meta["version"],
                    "release": meta["release"], "provenance_sha256": PROVENANCE_SHA256}
        with tempfile.TemporaryDirectory(prefix=".ax6-vim-stage-", dir=package.parent) as name:
            stage = Path(name)
            write_new(stage / "Makefile", before)
            operations = strict_recipe_stage(stage, recipe_delta)
            require(sha(regular(stage / "Makefile", stage)) == meta["desired_recipe_sha256"],
                    "recipe patch produced unexpected bytes")
            write_new(stage / meta["source_patch_name"], patch)
            require(package_state(packages, meta) == ("base", before), "Vim package changed during staging")
            # No recursive package replacement. Original patches and other package
            # files remain untouched. A crash between renames is fail-closed later.
            os.replace(stage / "Makefile", package / "Makefile")
            os.replace(stage / meta["source_patch_name"], package / "patches" / meta["source_patch_name"])
        require(package_state(packages, meta)[0] == "desired", "post-apply byte verification failed")
        return {"status": "APPLIED_EXACT_BYTES", "version": meta["version"], "release": meta["release"],
                "provenance_sha256": PROVENANCE_SHA256, "patch_commands": operations}
    finally:
        os.close(fd)
        current = lock.lstat()
        require((current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino),
                "Vim helper lock identity changed; refusing to remove replacement")
        lock.unlink()


def check(packages, bundle=BUNDLE):
    meta, _, _ = bundle_data(bundle)
    require(package_state(packages, meta)[0] == "desired", "Vim security candidate not applied")
    return {"status": "PASS_DESIRED_PACKAGE_BYTES_ONLY", "provenance_sha256": PROVENANCE_SHA256,
            "version": meta["version"], "release": meta["release"],
            "source_tag": meta["source_tag"], "source_commit": meta["source_commit"],
            "source_mirror_sha256": meta["source_mirror_sha256"],
            "recipe_sha256": meta["desired_recipe_sha256"], "source_patch_sha256": meta["source_patch_sha256"]}


def prepared(source, bundle=BUNDLE):
    meta, _, _ = bundle_data(bundle)
    actual = {name: sha(regular(source / name, source)) for name in meta["prepared_files"]}
    require(actual == meta["prepared_files"], "prepared Vim source bytes differ from selective pinned backport")
    return {"status": "PASS_PREPARED_SOURCE_BYTES_ONLY", "provenance_sha256": PROVENANCE_SHA256,
            "source_commit": meta["source_commit"], "files": actual,
            "boundary": "No source command executed. Not compiled-binary, package, full source tree or runtime proof."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("apply", "check", "prepared"))
    parser.add_argument("root", type=Path, help="feeds/packages for apply/check; prepared Vim source for prepared")
    args = parser.parse_args()
    try:
        result = {"apply": apply, "check": check, "prepared": prepared}[args.operation](args.root.absolute())
    except (Invalid, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAIL", "operation": args.operation, "error": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
