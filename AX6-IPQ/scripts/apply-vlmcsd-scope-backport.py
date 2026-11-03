#!/usr/bin/env python3
"""Install one pinned vlmcsd scope backport; no fetch, make or source execution.

Like the Vim helper, publication is per-file, not an atomic multi-file update.
Interrupted mixed states are refused. The exclusive lock is cooperative only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

BUNDLE = Path(__file__).resolve().parents[1] / "patches/vlmcsd"
FEED_PIN = "03d8b9d71b5e27972e4111ebe39898d093544c92"
SOURCE_PIN = "e599080486478e219cd065e141d6de050a450c27"
PATCH_NAME = "001-keep-generated-epid-live-through-conversion.patch"
PATCH_SHA256 = "e31cfe688a3a253b5005c8ea68109bfd831b20c4c0b40a1610dacbbb52c7ab2e"
BASE_RECIPE_SHA256 = "445faf46fe37f35c3826fdd350f33ace58bdc55531e23b847f9dd4a25849f1a8"
DESIRED_RECIPE_SHA256 = "6aa012397cd9a397a45f822ca2c5f2130177b33e48797dca9867d826e6ca21e2"
BASE_KMS_SHA256 = "df88f6e13b584f9652bc0bba3ef3e2702170e492b9983d686abdd431477fd598"
DESIRED_KMS_SHA256 = "68f244ce0906a620376cbe6a4b025ad1a0163125e084816691885d614148e026"
SOURCE_FILE_COUNT = 104
BASE_TREE_SHA256 = "4117022f7d35544d9bf6acb12eb373e536a80a8676ea4a0f44f4286a2ed36526"
DESIRED_TREE_SHA256 = "cf3e073e011191c57ed72c3334dde4d2221ae05242c12804d75ddd2da56699bc"
SUBMODULES = {"debian": "971ade7b0e6035e34f46f98bdb95e305ea1abab8",
              "docker": "4195d04f687973a514e3fb663bd87161afd46697"}


class Invalid(ValueError):
    """Unknown inputs are rejected without implicit migration or repair."""


def require(ok, why):
    if not ok:
        raise Invalid(why)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def directory(path):
    require(stat.S_ISDIR(path.lstat().st_mode), "not a real directory: " + str(path))


def regular(path, root):
    directory(root)
    current = root
    for part in path.relative_to(root).parts[:-1]:
        current /= part
        directory(current)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode), "not a regular file: " + str(path))
    require(stat.S_IMODE(info.st_mode) == 0o644, "expected mode 0644: " + str(path))
    return path.read_bytes()


def bundle_data(bundle=BUNDLE):
    directory(bundle)
    require({p.name for p in bundle.iterdir()} == {PATCH_NAME, "README.md"},
            "unknown/missing vlmcsd bundle entry")
    regular(bundle / "README.md", bundle)
    data = regular(bundle / PATCH_NAME, bundle)
    require(sha(data) == PATCH_SHA256, "vlmcsd source patch hash mismatch")
    return data


def package_state(packages):
    directory(packages)
    package = packages / "net/vlmcsd"
    recipe = regular(package / "Makefile", packages)
    require(recipe.splitlines().count(b"PKG_SOURCE_VERSION:=" + SOURCE_PIN.encode()) == 1,
            "vlmcsd source pin mismatch")
    patch_dir = package / "patches"
    hashes = {}
    if os.path.lexists(patch_dir):
        directory(patch_dir)
        require({p.name for p in patch_dir.iterdir()} in (set(), {PATCH_NAME}),
                "unknown vlmcsd patchset entry")
        hashes = {p.name: sha(regular(p, packages)) for p in patch_dir.iterdir()}
    if sha(recipe) == BASE_RECIPE_SHA256 and not hashes:
        return "base", recipe
    if sha(recipe) == DESIRED_RECIPE_SHA256 and hashes == {PATCH_NAME: PATCH_SHA256}:
        return "desired", recipe
    raise Invalid("unknown or partially applied vlmcsd recipe/patchset")


def write_new(path, data):
    with path.open("xb") as stream:
        stream.write(data)
    path.chmod(0o644)


def apply(packages, bundle=BUNDLE):
    patch = bundle_data(bundle)
    package_state(packages)
    package = packages / "net/vlmcsd"
    lock = package / ".ax6-vlmcsd-scope.lock"
    require(not os.path.lexists(lock), "vlmcsd helper lock already exists")
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    identity = os.fstat(fd)
    try:
        state, before = package_state(packages)
        if state == "desired":
            return receipt("ALREADY_APPLIED_EXACT_BYTES")
        old = b"\nPKG_RELEASE:=8\n"
        require(before.count(old) == 1, "vlmcsd base release mismatch")
        after = before.replace(old, b"\nPKG_RELEASE:=9\n", 1)
        require(sha(after) == DESIRED_RECIPE_SHA256, "unexpected desired vlmcsd recipe bytes")
        with tempfile.TemporaryDirectory(prefix=".ax6-vlmcsd-stage-", dir=package.parent) as name:
            stage = Path(name)
            write_new(stage / "Makefile", after)
            write_new(stage / PATCH_NAME, patch)
            require(regular(stage / "Makefile", stage) == after and
                    regular(stage / PATCH_NAME, stage) == patch, "vlmcsd staging drift")
            require(bundle_data(bundle) == patch, "vlmcsd bundle changed during staging")
            require(package_state(packages) == ("base", before), "vlmcsd package changed during staging")
            patch_dir = package / "patches"
            if not os.path.lexists(patch_dir):
                patch_dir.mkdir(mode=0o755)
            directory(patch_dir)
            # Leave all files/, other packages, source pins and mirror hashes intact.
            os.replace(stage / "Makefile", package / "Makefile")
            os.replace(stage / PATCH_NAME, patch_dir / PATCH_NAME)
        require(package_state(packages)[0] == "desired", "vlmcsd post-apply bytes differ")
        return receipt("APPLIED_EXACT_BYTES")
    finally:
        os.close(fd)
        current = lock.lstat()
        require((current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino),
                "vlmcsd helper lock identity changed; refusing replacement removal")
        lock.unlink()


def receipt(status):
    return {"status": status, "base_feed_commit": FEED_PIN, "source_commit": SOURCE_PIN,
            "release": 9, "recipe_sha256": DESIRED_RECIPE_SHA256,
            "source_patch_sha256": PATCH_SHA256}


def check(packages, bundle=BUNDLE):
    bundle_data(bundle)
    require(package_state(packages)[0] == "desired", "vlmcsd scope backport not applied")
    return receipt("PASS_DESIRED_PACKAGE_BYTES_ONLY")


def prepared(source, bundle=BUNDLE):
    bundle_data(bundle)
    require(sha(regular(source / "src/kms.c", source)) == DESIRED_KMS_SHA256,
            "prepared vlmcsd kms.c bytes mismatch")
    files, markers = source_inventory(source)
    require(len(files) == SOURCE_FILE_COUNT and tree_sha(files) == DESIRED_TREE_SHA256,
            "prepared vlmcsd complete source tree mismatch")
    result = receipt("PASS_PREPARED_COMPLETE_SOURCE_BYTES_ONLY")
    result.update({"kms_sha256": DESIRED_KMS_SHA256, "source_files": files,
                   "source_tree_sha256": DESIRED_TREE_SHA256, "submodules": SUBMODULES,
                   "generated_prepare_metadata": markers,
                   "boundary": "All104 files from the pinned OpenWrt mirror repack; no target binary, ABI, build or runtime proof."})
    return result


def tree_sha(files):
    return sha("".join(name + "\0" + digest + "\n" for name, digest in sorted(files.items())).encode())


def source_inventory(source):
    directory(source)
    files, markers = {}, {}
    for path in sorted(source.rglob("*")):
        info = path.lstat()
        require(not path.is_symlink(), "source symlink refused: " + str(path))
        if stat.S_ISDIR(info.st_mode):
            continue
        require(stat.S_ISREG(info.st_mode), "source special file refused: " + str(path))
        name = path.relative_to(source).as_posix()
        data = path.read_bytes()
        if path.parent == source and name.startswith(".prepared_") and not data:
            markers[name] = sha(data)
        elif path.parent == source and name == 'version.date':
            # Build/Prepare/Default generates this timestamp before patching.
            # It is metadata, not upstream source or an acceptance expectation.
            require(re.fullmatch(rb'[0-9]{1,12}\n', data), 'invalid generated version.date')
            markers[name] = sha(data)
        else:
            files[name] = sha(data)
    return files, markers


def output_evidence(output, operation, root, result):
    output.mkdir(parents=True)
    files = result.get("source_files", {})
    if operation == "prepared":
        copies, index = output / 'source-copies', []
        copies.mkdir()
        for number, (name, digest) in enumerate(sorted(files.items())):
            data = (root / name).read_bytes()
            require(sha(data) == digest, "source changed during evidence copy: " + name)
            target = output / "source" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            write_new(target, data)
            target.chmod(0o444)
            # upload-artifact excludes hidden paths. Retain an explicit public
            # source allowlist as non-hidden opaque data, never enable a broad
            # include-hidden-files option or copy credentials from a workspace.
            opaque = '%04d.dat' % number
            write_new(copies / opaque, data)
            (copies / opaque).chmod(0o444)
            index.append({'original': name, 'copy': opaque, 'sha256': digest, 'bytes': len(data)})
        require(source_inventory(root)[0] == files, "source inventory changed during copy")
        require(source_inventory(output / "source")[0] == files, "copied source bytes differ")
        require({p.name for p in copies.iterdir()} == {r['copy'] for r in index} and
                all(sha((copies / r['copy']).read_bytes()) == r['sha256'] for r in index),
                'non-hidden complete source copies differ')
        write_new(output / 'SOURCE-COPIES.json',
                  (json.dumps({'status': 'PUBLIC_SOURCE_DATA_ONLY_NO_EXECUTION', 'files': index},
                              indent=2) + '\n').encode())
    else:
        require(package_state(root)[0] == "desired", "package changed before evidence copy")
        write_new(output / "Makefile", regular(root / "net/vlmcsd/Makefile", root))
        (output / "Makefile").chmod(0o444)
    write_new(output / PATCH_NAME, bundle_data())
    (output / PATCH_NAME).chmod(0o444)
    write_new(output / "RESULTS.json", (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("apply", "check", "prepared"))
    parser.add_argument("root", type=Path, help="feeds/packages, or prepared source for prepared")
    parser.add_argument("--output", type=Path, help="optional fresh evidence directory; never executes copied source")
    args = parser.parse_args()
    try:
        root = args.root.absolute()
        if args.output:
            output = args.output.absolute()
            require(not os.path.lexists(output), "fresh evidence directory required")
            require(not output.resolve().is_relative_to(root.resolve()), "evidence must be outside input root")
        result = {"apply": apply, "check": check, "prepared": prepared}[args.operation](root)
        if args.output:
            output_evidence(output, args.operation, root, result)
    except (Invalid, OSError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "operation": args.operation, "error": str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
