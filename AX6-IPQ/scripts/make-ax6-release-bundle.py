#!/usr/bin/env python3
"""
Build a standard AX6 release bundle containing every firmware format.

This is intentionally a packaging/validation layer, not a flasher:
  * verifies sysupgrade.tar, factory.ubi and initramfs FIT;
  * enforces identity between sysupgrade and factory payloads;
  * copies all formats and evidence into one directory;
  * emits SHA256SUMS + FORMAT-VERIFICATION.json + README.

Usage:
  make-ax6-release-bundle.py \
    --sysupgrade <...sysupgrade.bin> \
    --factory-ubi <...factory.ubi> \
    --initramfs-itb <...initramfs-uImage.itb> \
    --manifest <...manifest> \
    [--profiles-json <...profiles.json>] \
    [--compiled-dtb <...dtb>] \
    --outdir <bundle-dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERIFY = ROOT / "verify-ax6-image-formats.py"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def require(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"ERROR: {msg}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sysupgrade", required=True)
    ap.add_argument("--factory-ubi", required=True)
    ap.add_argument("--initramfs-itb", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--profiles-json")
    ap.add_argument("--compiled-dtb")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    verify_json = out / "FORMAT-VERIFICATION.json"
    cmd = [
        sys.executable, str(VERIFY),
        "--sysupgrade", args.sysupgrade,
        "--factory-ubi", args.factory_ubi,
        "--initramfs-itb", args.initramfs_itb,
        "--output", str(verify_json),
    ]
    if args.compiled_dtb:
        cmd += ["--compiled-dtb", args.compiled_dtb]
    subprocess.run(cmd, check=True)

    files = [
        Path(args.sysupgrade),
        Path(args.factory_ubi),
        Path(args.initramfs_itb),
        Path(args.manifest),
    ]
    if args.profiles_json:
        files.append(Path(args.profiles_json))
    if args.compiled_dtb:
        files.append(Path(args.compiled_dtb))

    copied = []
    for src in files:
        if not src.is_file():
            raise SystemExit(f"ERROR: missing release input: {src}")
        dst = out / src.name
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        copied.append(dst)

    if args.profiles_json:
        profile_path = Path(args.profiles_json)
        try:
            profiles = json.loads(profile_path.read_text())
        except Exception as exc:
            raise SystemExit(f"ERROR: invalid profiles.json: {exc}")
        require_map = {"sysupgrade": Path(args.sysupgrade).name,
                       "factory": Path(args.factory_ubi).name,
                       "kernel": Path(args.initramfs_itb).name}
        require(profiles.get("metadata_version") is not None, "profiles.json metadata_version missing")
        profile = (profiles.get("profiles") or {}).get("redmi_ax6-stock")
        require(profile is not None, "profiles.json redmi_ax6-stock profile missing")
        images = profile.get("images") or []
        found = {}
        for image in images:
            found[image.get("type")] = image
        for image_type, expected_name in require_map.items():
            image = found.get(image_type)
            require(image is not None, f"profiles.json missing {image_type} image")
            require(image.get("name") == expected_name,
                    f"profiles.json {image_type} name mismatch: {image.get('name')!r} != {expected_name!r}")
            actual = sha256(Path(args.sysupgrade if image_type == "sysupgrade" else
                                 args.factory_ubi if image_type == "factory" else args.initramfs_itb))
            require(image.get("sha256") == actual,
                    f"profiles.json {image_type} sha256 mismatch")
            require("sha256_unsigned" in image, f"profiles.json {image_type} sha256_unsigned missing")

    readme = out / "FORMAT-README.txt"
    readme.write_text(
        "AX6 standard firmware bundle\n"
        "============================\n\n"
        "Formats in this bundle:\n"
        "  *-squashfs-sysupgrade.bin : normal LuCI / sysupgrade image\n"
        "  *-squashfs-factory.ubi    : full UBI factory/recovery image (do NOT use as sysupgrade)\n"
        "  *-initramfs-uImage.itb    : RAM boot / recovery image (do NOT write raw to NAND)\n\n"
        "Verification:\n"
        "  FORMAT-VERIFICATION.json  : sysupgrade CONTROL/kernel/root,\n"
        "                              UBI volume table kernel/rootfs/rootfs_data,\n"
        "                              FIT kernel/fdt/config, payload identity\n"
        "  SHA256SUMS                : hashes for every file in this bundle\n\n"
        "The factory UBI and initramfs ITB are recovery formats, not normal\n"
        "sysupgrade inputs. This bundle does not replace the old-firmware\n"
        "migration helper required by the single-rootfs AX6 layout.\n"
    )

    # SHA256SUMS covers all files except itself.
    hash_targets = sorted(p for p in out.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    hash_lines = [f"{sha256(p)}  {p.name}" for p in hash_targets]
    (out / "SHA256SUMS").write_text("\n".join(hash_lines) + "\n")

    report = {
        "status": "PASS",
        "outdir": str(out),
        "formats": [p.name for p in copied],
        "format_verification": str(verify_json),
        "sha256sums": str(out / "SHA256SUMS"),
        "recovery_formats": [
            Path(args.factory_ubi).name,
            Path(args.initramfs_itb).name,
        ],
        "note": "factory.ubi and initramfs ITB are recovery formats; never use them as normal sysupgrade inputs",
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
