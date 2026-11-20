#!/usr/bin/env python3
"""
Build a standard AX6 release bundle containing every firmware format.

This is intentionally a packaging/validation layer, not a flasher:
  * verifies sysupgrade.tar, factory.ubi and initramfs FIT;
  * enforces identity between sysupgrade and factory payloads;
  * classifies the factory UBI against the merged/stock partition and the
    measured U-Boot Web size class (S1-06 / A-05 E1+E2), emitting
    RECOVERY-MATRIX.json plus the same facts in the bundle README;
  * copies all formats and evidence into one directory;
  * emits SHA256SUMS + FORMAT-VERIFICATION.json + README.

`--require-web-proven` is the release-gating mode: it fails the bundle unless
the factory UBI is inside the only measured Web-flash size class
(<= 54,788,096 B, fallback factory 5e44fdad, n=1). A 59 MB self-built factory
is UNPROVEN_OVERSIZE and must not be labelled recovery.

Usage:
  make-ax6-release-bundle.py \
    --sysupgrade <...sysupgrade.bin> \
    --factory-ubi <...factory.ubi> \
    --initramfs-itb <...initramfs-uImage.itb> \
    --manifest <...manifest> \
    [--profiles-json <...profiles.json>] \
    [--compiled-dtb <...dtb>] \
    [--require-web-proven] \
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

def auto_int(text: str) -> int:
    try:
        return int(text, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc

def positive_int(text: str) -> int:
    value = auto_int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be positive: {text!r}")
    return value

def non_negative_int(text: str) -> int:
    value = auto_int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be non-negative: {text!r}")
    return value


def recovery_readme(classification: dict, gate: str) -> str:
    allowed = "YES" if classification["recovery_label_allowed"] else "NO"
    if classification["web_recovery_class"] == "PROVEN_SIZE_CLASS":
        class_note = (
            "This factory is inside the measured Web-flash size class (n=1).\n"
            "That is a risk class, not boot evidence for this build: the RT-4 Web\n"
            "matrix (and RT-7 recovery drill) still decide whether it boots.\n"
        )
    else:
        class_note = (
            "This factory is OUTSIDE the only measured Web-flash size class.\n"
            "Do NOT label it recovery and do NOT flash it before the RT-4 Web\n"
            "matrix records a result. The proven asset remains the 54,788,096 B\n"
            "fallback factory (sha 5e44fdad...).\n"
        )
    return (
        "Recovery classification (S1-06 / A-05)\n"
        "=====================================\n"
        f"factory.ubi           : {classification['factory_ubi']}\n"
        f"factory size          : {classification['factory_bytes']} B\n"
        f"factory sha256        : {classification['factory_sha256']}\n"
        f"PEB size              : {classification['peb_size']} B\n"
        f"merged partition      : {classification['mtd_rootfs_size_bytes']} B "
        f"({classification['mtd_rootfs_pebs']} PEB, usable {classification['merged_usable_pebs']} PEB)\n"
        f"reserved by image     : {classification['reserved_total_pebs']} PEB\n"
        f"stock slot fit        : {classification['fits_stock_slot']}\n"
        f"layout compatibility  : {classification['layout_compat']}\n"
        f"web recovery class    : {classification['web_recovery_class']}\n"
        f"proven size envelope  : <= {classification['web_proven_envelope_bytes']} B\n"
        f"recovery label allowed: {allowed}\n"
        f"release gate          : {gate}\n\n"
        f"{class_note}\n"
        "U-Boot Web path facts (from installed bootloader strings and the\n"
        "2026-11-17 recovery investigation; not re-measured here):\n"
        "  * erases 0x00a00000+0x06640000 and writes the uploaded bytes raw from\n"
        "    0x44000000; it does not decompress and does not read back;\n"
        "  * accepts only a raw UBI# NAND image; there is no size cap and no\n"
        "    readback verification;\n"
        "  * the initramfs ITB is NOT Web-flashable (RAM boot via UART/TFTP only);\n"
        "  * both images are for the merged single-rootfs layout only (no\n"
        "    rootfs_1) and the device has no in-device A/B failover;\n"
        "  * the only Web-proven size class is <= 54,788,096 B (n=1).\n\n"
        "The factory UBI and initramfs ITB are recovery formats, not normal\n"
        "sysupgrade inputs. This bundle does not replace the old-firmware\n"
        "migration helper required by the single-rootfs AX6 layout.\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sysupgrade", required=True)
    ap.add_argument("--factory-ubi", required=True)
    ap.add_argument("--initramfs-itb", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--profiles-json")
    ap.add_argument("--compiled-dtb")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--require-web-proven", action="store_true",
                    help="release gate: fail unless factory.ubi is in the Web-PROVEN size class")
    ap.add_argument("--peb-size", type=positive_int)
    ap.add_argument("--mtd-rootfs-size", type=positive_int)
    ap.add_argument("--mtd-stock-rootfs-size", type=positive_int)
    ap.add_argument("--bad-pebs", type=non_negative_int)
    ap.add_argument("--bad-reserve-pebs", type=non_negative_int)
    ap.add_argument("--recovery-envelope-bytes", type=positive_int)
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
    if args.require_web_proven:
        cmd.append("--require-web-proven")
    for attr, flag in (
        ("peb_size", "--peb-size"),
        ("mtd_rootfs_size", "--mtd-rootfs-size"),
        ("mtd_stock_rootfs_size", "--mtd-stock-rootfs-size"),
        ("bad_pebs", "--bad-pebs"),
        ("bad_reserve_pebs", "--bad-reserve-pebs"),
        ("recovery_envelope_bytes", "--recovery-envelope-bytes"),
    ):
        value = getattr(args, attr)
        if value is not None:
            cmd += [flag, str(value)]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(
            "ERROR: image format/recovery verification FAILED for "
            f"{Path(args.factory_ubi).name} (see FORMAT CHECK message above)")
    verification = json.loads(verify_json.read_text())
    recovery = verification.get("recovery")
    require(isinstance(recovery, dict) and isinstance(recovery.get("classification"), dict),
            "format verification report has no recovery classification")
    classification = recovery["classification"]
    gate = recovery.get("release_gate", "NOT_EVALUATED")

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

    # RECOVERY-MATRIX.json: identity + risk class only. This is L2 artifact
    # admission, never boot/flash/recovery evidence.
    artifacts = {}
    for path in copied:
        artifacts[path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    matrix = {
        "schema": 1,
        "status": "PASS",
        "scope": "L2 artifact identity/format/recovery-class admission only; NOT boot, flash, hardware or recovery evidence",
        "artifacts": artifacts,
        "classification": classification,
        "web_path": recovery.get("web_path"),
        "release_gate": gate,
        "recovery_label_allowed": classification["recovery_label_allowed"],
        "policy": recovery.get("policy"),
        "recovery_facts": [
            "U-Boot Web erases 0x00a00000+0x06640000 and writes uploaded bytes raw from 0x44000000",
            "U-Boot Web accepts only a raw UBI# NAND image; no size cap, no readback verification",
            "initramfs ITB is not Web-flashable (RAM boot via UART/TFTP only)",
            "merged single-rootfs layout only; no rootfs_1 and no in-device failover",
            "only Web-proven size class is <= 54,788,096 B (fallback factory 5e44fdad, n=1)",
        ],
        "quarantine": [
            "A2/B4/B5 are quarantined and must not be cited or flashed",
            "B6 is identity-only, predates the P0/P1 closures and is not a candidate",
        ],
    }
    matrix_path = out / "RECOVERY-MATRIX.json"
    matrix_path.write_text(json.dumps(matrix, indent=2) + "\n")

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
        "                              FIT kernel/fdt/config, payload identity,\n"
        "                              recovery envelope/class\n"
        "  RECOVERY-MATRIX.json      : recovery size class / layout compatibility /\n"
        "                              Web-path facts for the factory UBI\n"
        "  SHA256SUMS                : hashes for every file in this bundle\n\n"
        + recovery_readme(classification, gate)
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
        "recovery_matrix": str(matrix_path),
        "sha256sums": str(out / "SHA256SUMS"),
        "recovery_formats": [
            Path(args.factory_ubi).name,
            Path(args.initramfs_itb).name,
        ],
        "recovery_class": classification["web_recovery_class"],
        "layout_compat": classification["layout_compat"],
        "recovery_label_allowed": classification["recovery_label_allowed"],
        "release_gate": gate,
        "note": "factory.ubi and initramfs ITB are recovery formats; never use them as normal sysupgrade inputs",
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
