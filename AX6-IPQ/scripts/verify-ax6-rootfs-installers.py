#!/usr/bin/env python3
"""
Admission gate for the installer scripts embedded in a built AX6 rootfs.

This is the S1-05 / A-00 CI gate: it inspects the rootfs copies of
`lib/upgrade/platform.sh`, `lib/upgrade/nand.sh`, `etc/init.d/bootcount` and
`etc/uci-defaults/30_uboot-envtools` and proves, offline:

  * platform.sh: the merged single-rootfs branch runs exactly one
    `nand_do_upgrade` and performs zero `fw_setenv` calls; the dual-slot
    branch still writes the stock flag batch;
  * bootcount: the merged layout performs zero dead Xiaomi flag writes while
    the dual-slot layout keeps its two writes;
  * 30_uboot-envtools: the merged layout selects the probe-verified
    0x40000/0x20000 env geometry while stock dual-slot keeps 0x10000;
  * nand.sh: the non-atomic writer keeps volume verification (`data_bytes`,
    `upd_marker`), the capacity preflight and checked `ubiupdatevol` calls;
  * when --source-root is supplied, the byte identity of each script against
    the locked source tree tip (artifact must embed the reviewed scripts).

`--mode diagnostic` downgrades behavioural findings to warnings so a
diagnostic control build can still be produced; the release gate mode is the
default and is not swallowable.

This is offline artifact evidence only: it does not boot, flash or exercise
the writer on hardware.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_NAMES = ("platform.sh", "nand.sh", "bootcount", "30_uboot-envtools")
SOURCE_PATHS = {
    "nand.sh": "package/base-files/files/lib/upgrade/nand.sh",
    "platform.sh": "target/linux/qualcommax/ipq807x/base-files/lib/upgrade/platform.sh",
    "bootcount": "target/linux/qualcommax/ipq807x/base-files/etc/init.d/bootcount",
    "30_uboot-envtools": "package/boot/uboot-tools/uboot-envtools/files/qualcommax_ipq807x",
}
PIN_ARG = {
    "nand.sh": "expect_nand_sha256",
    "platform.sh": "expect_platform_sha256",
    "bootcount": "expect_bootcount_sha256",
    "30_uboot-envtools": "expect_ubootenv_sha256",
}
HARNESS_TIMEOUT = 30
MAX_SCRIPT_BYTES = 512 * 1024


class Gate:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.checks: list[dict] = []

    def fail(self, name: str, detail: str) -> None:
        self.checks.append({"name": name, "status": "FAIL", "detail": detail})

    def warn(self, name: str, detail: str) -> None:
        self.checks.append({"name": name, "status": "WARN", "detail": detail})

    def ok(self, name: str, detail: str = "") -> None:
        self.checks.append({"name": name, "status": "PASS", "detail": detail})

    def behaviour_fail(self, name: str, detail: str) -> None:
        if self.mode == "diagnostic":
            self.warn(name, "diagnostic mode: " + detail)
        else:
            self.fail(name, detail)

    @property
    def status(self) -> str:
        return "FAIL" if any(c["status"] == "FAIL" for c in self.checks) else "PASS"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_scripts(scripts_dir: Path, gate: Gate) -> dict:
    scripts = {}
    for name in SCRIPT_NAMES:
        path = scripts_dir / name
        if not path.is_file():
            gate.fail(f"script-present:{name}", f"missing installer script: {path}")
            continue
        data = path.read_bytes()
        if not data:
            gate.fail(f"script-present:{name}", f"empty installer script: {path}")
            continue
        if len(data) > MAX_SCRIPT_BYTES:
            gate.fail(f"script-present:{name}", f"installer script too large: {path} ({len(data)} bytes)")
            continue
        scripts[name] = data
        gate.ok(f"script-present:{name}", f"{len(data)} bytes sha256={sha256_bytes(data)}")
    return scripts


def run_harness(workdir: Path, args: list[str]) -> dict:
    """Run the prepared sh harness with a timeout; returns rc/stdout/stderr."""
    proc = subprocess.run(
        ["sh", "harness.sh", *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=HARNESS_TIMEOUT,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
    )
    return {
        "rc": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


PLATFORM_HARNESS = """\
set -u
calls="$1"
board="$2"
rootfs_mtd="$3"
rootfs1_mtd="$4"
board_name() { printf '%s\\n' "$board"; }
find_mtd_index() {
    case "$1" in
        rootfs) [ -n "$rootfs_mtd" ] && printf '%s\\n' "$rootfs_mtd" ;;
        rootfs_1) [ -n "$rootfs1_mtd" ] && printf '%s\\n' "$rootfs1_mtd" ;;
    esac
    return 0
}
fw_setenv() { printf 'fw_setenv %s\\n' "$*" >> "$calls"; return 0; }
fw_printenv() { printf '0\\n'; return 0; }
nand_do_upgrade() { printf 'nand_do_upgrade %s\\n' "$*" >> "$calls"; return 0; }
nand_do_upgrade_failed() { printf 'nand_do_upgrade_failed\\n' >> "$calls"; return 1; }
nand_do_flash_file() { printf 'nand_do_flash_file\\n' >> "$calls"; return 0; }
nand_do_restore_config() { printf 'nand_do_restore_config\\n' >> "$calls"; return 0; }
. ./platform.sh
platform_do_upgrade /tmp/ax6-admission-sysupgrade.bin
printf 'platform_do_upgrade rc=%s\\n' "$?" >> "$calls"
"""

BOOTCOUNT_HARNESS = """\
set -u
calls="$1"
layout="$2"
board_name() { printf 'redmi,ax6-stock\\n'; }
find_mtd_index() {
    case "$1" in
        rootfs) printf '4\\n' ;;
        rootfs_1) [ "$layout" = dual ] && printf '5\\n' ;;
    esac
    return 0
}
fw_setenv() { printf 'fw_setenv %s\\n' "$*" >> "$calls"; return 0; }
fw_printenv() { printf '0\\n'; return 0; }
. ./bootcount
boot
printf 'boot rc=%s\\n' "$?" >> "$calls"
"""

ENVTOOLS_HARNESS = """\
set -u
calls="$1"
layout="$2"
board="redmi,ax6-stock"
find_mtd_index() {
    case "$1" in
        rootfs) printf '12\\n' ;;
        rootfs_1) [ "$layout" = dual ] && printf '13\\n' ;;
    esac
    return 0
}
ubootenv_add_mtd() { printf 'add_mtd %s\\n' "$*" >> "$calls"; }
ubootenv_add_sys_mtd() { printf 'add_sys_mtd %s\\n' "$*" >> "$calls"; }
ubootenv_add_mmc() { printf 'add_mmc %s\\n' "$*" >> "$calls"; }
ubootenv_add_uci_config() { printf 'add_uci %s\\n' "$*" >> "$calls"; }
ubootenv_mtdinfo() { printf 'mtdinfo\\n'; }
__ENVTOOLS_BODY__
printf 'envtools rc=%s\\n' "$?" >> "$calls"
"""


def read_calls(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text().splitlines() if line]


def check_platform(scripts: dict, gate: Gate) -> dict:
    evidence = {}
    data = scripts.get("platform.sh")
    if data is None:
        gate.behaviour_fail("platform:merged", "platform.sh missing; cannot run merged-layout harness")
        gate.behaviour_fail("platform:dual", "platform.sh missing; cannot run dual-slot harness")
        return evidence
    for layout, rootfs1 in (("merged", ""), ("dual", "5")):
        workdir = Path(tempfile.mkdtemp(prefix=f"ax6-platform-{layout}-"))
        calls = workdir / "calls.txt"
        harness = PLATFORM_HARNESS
        try:
            (workdir / "platform.sh").write_bytes(data)
            (workdir / "harness.sh").write_text(harness)
            result = run_harness(workdir, [str(calls), "redmi,ax6-stock", "4", rootfs1])
            calls_list = read_calls(calls)
            upgrades = [c for c in calls_list if c.startswith("nand_do_upgrade ")]
            setenvs = [c for c in calls_list if c.startswith("fw_setenv ")]
            failures = [c for c in calls_list if c.startswith("nand_do_upgrade_failed")]
            detail = {
                "rc": result["rc"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "nand_do_upgrade_calls": upgrades,
                "fw_setenv_calls": setenvs,
                "upgrade_failed_calls": failures,
            }
            evidence[layout] = detail
            name = f"platform:{layout}"
            if result["rc"] != 0:
                gate.behaviour_fail(name, f"platform harness failed rc={result['rc']}: {result['stderr'][:200]}")
            elif layout == "merged":
                if failures:
                    gate.behaviour_fail(name, "merged layout recorded nand_do_upgrade_failed")
                elif len(upgrades) != 1:
                    gate.behaviour_fail(name, f"merged layout ran {len(upgrades)} nand_do_upgrade calls (expected 1)")
                elif setenvs:
                    gate.behaviour_fail(name, f"merged layout wrote dead Xiaomi flags: {setenvs}")
                elif "AX6-LARGE-PARTITION-BRANCH" not in result["stdout"]:
                    gate.behaviour_fail(name, "merged layout did not announce AX6-LARGE-PARTITION-BRANCH")
                else:
                    gate.ok(name, "exactly 1 nand_do_upgrade, 0 fw_setenv, merged branch announced")
            else:
                if len(upgrades) != 1:
                    gate.behaviour_fail(name, f"dual-slot layout ran {len(upgrades)} nand_do_upgrade calls (expected 1)")
                elif len(setenvs) != 1:
                    gate.behaviour_fail(name, f"dual-slot layout has {len(setenvs)} fw_setenv calls (expected the stock flag batch)")
                else:
                    gate.ok(name, "dual-slot keeps 1 flag batch + 1 nand_do_upgrade")
        except (OSError, subprocess.SubprocessError) as exc:
            gate.behaviour_fail(f"platform:{layout}", f"platform harness error: {exc}")
            evidence[layout] = {"error": str(exc)}
    return evidence


def check_bootcount(scripts: dict, gate: Gate) -> dict:
    evidence = {}
    data = scripts.get("bootcount")
    if data is None:
        gate.behaviour_fail("bootcount:merged", "bootcount missing; cannot prove merged-layout silence")
        gate.behaviour_fail("bootcount:dual", "bootcount missing; cannot prove dual-slot writes remain")
        return evidence
    for layout in ("merged", "dual"):
        workdir = Path(tempfile.mkdtemp(prefix=f"ax6-bootcount-{layout}-"))
        (workdir / "bootcount").write_bytes(data)
        (workdir / "harness.sh").write_text(BOOTCOUNT_HARNESS)
        calls = workdir / "calls.txt"
        try:
            result = run_harness(workdir, [str(calls), layout])
            calls_list = read_calls(calls)
            setenvs = [c for c in calls_list if c.startswith("fw_setenv ")]
            evidence[layout] = {"rc": result["rc"], "stdout": result["stdout"],
                                "stderr": result["stderr"], "fw_setenv_calls": setenvs}
            name = f"bootcount:{layout}"
            if result["rc"] != 0:
                gate.behaviour_fail(name, f"bootcount harness failed rc={result['rc']}: {result['stderr'][:200]}")
            elif layout == "merged":
                if setenvs:
                    gate.behaviour_fail(name, f"merged layout still writes dead Xiaomi flags: {setenvs}")
                else:
                    gate.ok(name, "merged layout writes 0 Xiaomi flags")
            else:
                if len(setenvs) != 2:
                    gate.behaviour_fail(name, f"dual-slot layout writes {len(setenvs)} flags (expected 2: ota_reboot + boot_success)")
                else:
                    gate.ok(name, "dual-slot layout keeps 2 flag writes")
        except (OSError, subprocess.SubprocessError) as exc:
            gate.behaviour_fail(f"bootcount:{layout}", f"bootcount harness error: {exc}")
            evidence[layout] = {"error": str(exc)}
    return evidence


def parse_case_arms(text: str) -> list[dict]:
    """Parse the outer `case "$board" in ... esac` into [{labels, body}] arms."""
    match = re.search(r'(?ms)^case\s+"?\$\{?board\}?"?\s+in\s*$\n(.*?)^esac\s*$', text)
    if not match:
        raise ValueError("no top-level case \"$board\" block found")
    block = match.group(1)
    arms = []
    for chunk in re.split(r'(?m)^[ \t]*;;[ \t]*$', block):
        if not chunk.strip():
            continue
        lines = chunk.splitlines()
        idx = None
        for i, line in enumerate(lines):
            if line.strip().endswith(")"):
                idx = i
                break
        if idx is None:
            continue
        label_text = " ".join(lines[:idx + 1]).replace(")", " ").replace("\\", " ")
        labels = [item.strip() for item in label_text.split("|") if item.strip()]
        arms.append({"labels": labels, "body": "\n".join(lines[idx + 1:])})
    if not arms:
        raise ValueError("case block has no parseable arms")
    return arms


def is_ax6_label(label: str) -> bool:
    return label in ("redmi,ax6", "redmi,ax6-stock")


def check_ubootenv(scripts: dict, gate: Gate) -> dict:
    evidence = {}
    data = scripts.get("30_uboot-envtools")
    if data is None:
        gate.behaviour_fail("ubootenv:merged", "30_uboot-envtools missing; cannot prove merged env geometry")
        gate.behaviour_fail("ubootenv:dual", "30_uboot-envtools missing; cannot prove stock 0x10000 geometry kept")
        return evidence
    text = data.decode("utf-8", "replace")
    try:
        arms = parse_case_arms(text)
    except ValueError as exc:
        gate.behaviour_fail("ubootenv:parse", f"cannot parse uboot-envtools board case: {exc}")
        return evidence
    targets = [arm for arm in arms if any(is_ax6_label(label) for label in arm["labels"])]
    if not targets:
        gate.behaviour_fail("ubootenv:parse", "no redmi,ax6 arm found in uboot-envtools board case")
        return evidence
    for layout in ("merged", "dual"):
        arm_results: list[dict] = []
        for index, arm in enumerate(targets):
            workdir = Path(tempfile.mkdtemp(prefix=f"ax6-envtools-{layout}-{index}-"))
            (workdir / "harness.sh").write_text(
                ENVTOOLS_HARNESS.replace("__ENVTOOLS_BODY__", arm["body"]))
            calls_path = workdir / "calls.txt"
            name = f"ubootenv:{layout}" + (f":arm{index}" if len(targets) > 1 else "")
            try:
                result = run_harness(workdir, [str(calls_path), layout])
            except (OSError, subprocess.SubprocessError) as exc:
                gate.behaviour_fail(name, f"ubootenv harness error: {exc}")
                continue
            arm_calls = read_calls(calls_path)
            add_mtd = [c for c in arm_calls if c.startswith("add_mtd ") and "appsblenv" in c]
            arm_results.append({"arm": index, "add_mtd_calls": add_mtd})
            if result["rc"] != 0:
                gate.behaviour_fail(name, f"harness failed rc={result['rc']}: {result['stderr'][:200]}")
            elif len(add_mtd) != 1:
                gate.behaviour_fail(name, f"{layout} layout has {len(add_mtd)} appsblenv add_mtd calls (expected 1)")
            elif layout == "merged":
                if "0x40000" not in add_mtd[0] or "0x20000" not in add_mtd[0]:
                    gate.behaviour_fail(name, f"merged layout env geometry is not 0x40000/0x20000: {add_mtd[0]}")
                else:
                    gate.ok(name, "merged layout selects probe-verified 0x40000/0x20000 env geometry")
            else:
                if "0x10000" not in add_mtd[0]:
                    gate.behaviour_fail(name, f"dual-slot layout no longer keeps 0x10000 geometry: {add_mtd[0]}")
                else:
                    gate.ok(name, "dual-slot layout keeps stock 0x10000 env geometry")
        evidence[layout] = arm_results
    return evidence


def check_nand(scripts: dict, gate: Gate) -> dict:
    data = scripts.get("nand.sh")
    if data is None:
        gate.behaviour_fail("nand:writer-contract", "nand.sh missing; cannot verify writer transaction")
        return {}
    text = data.decode("utf-8", "replace")
    evidence = {"sha256": sha256_bytes(data), "bytes": len(data)}
    required = {
        "volume-verification function": "nand_verify_ubi_volume",
        "data_bytes readback": "data_bytes",
        "update marker": "upd_marker",
        "capacity preflight (eraseblock_size)": "eraseblock_size",
        "capacity preflight (avail_eraseblocks)": "avail_eraseblocks",
        "guidance marker": "SYSUPGRADE:",
    }
    missing = [label for label, marker in required.items() if marker not in text]
    if missing:
        gate.behaviour_fail("nand:writer-contract",
                            "nand.sh is missing the S1-04 writer contract markers: " + ", ".join(missing))
    else:
        gate.ok("nand:writer-contract",
                "volume verification + capacity preflight + recovery guidance markers present")
    unchecked = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if "ubiupdatevol" not in stripped or stripped.startswith("#"):
            continue
        context = stripped
        if index:
            context = lines[index - 1].strip() + " " + context
        if not re.search(r'\bif\b|\|\||&&', context):
            unchecked.append(f"line {index + 1}: {stripped[:120]}")
    if unchecked:
        gate.behaviour_fail("nand:checked-updatevol",
                            "ubiupdatevol call(s) without an if/||/&& error check: " + "; ".join(unchecked))
    else:
        gate.ok("nand:checked-updatevol", "every ubiupdatevol call is error-checked")
    return evidence


def check_source_identity(scripts: dict, scripts_dir: Path, source_root: Path,
                          gate: Gate, pins: dict) -> dict:
    evidence = {}
    for name, data in scripts.items():
        digest = sha256_bytes(data)
        detail = {"sha256": digest, "bytes": len(data)}
        pin = pins.get(name)
        if pin:
            if digest != pin:
                gate.fail(f"pin:{name}", f"sha256 {digest} does not match expected pin {pin}")
            else:
                gate.ok(f"pin:{name}", "sha256 matches reviewed pin")
        source_path = source_root / SOURCE_PATHS[name]
        if not source_path.is_file():
            gate.fail(f"source:{name}", f"locked source file missing: {source_path}")
            evidence[name] = detail
            continue
        source_data = source_path.read_bytes()
        source_digest = sha256_bytes(source_data)
        detail["source_sha256"] = source_digest
        if data != source_data:
            gate.fail(f"source:{name}",
                      f"rootfs script sha256 {digest} differs from locked source {source_digest}")
        else:
            gate.ok(f"source:{name}", "rootfs script is byte-identical to the locked source tip")
        evidence[name] = detail
    return evidence


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scripts-dir", required=True,
                    help="directory holding platform.sh, nand.sh, bootcount, 30_uboot-envtools")
    ap.add_argument("--source-root",
                    help="locked source tree the artifact must match (openwrt checkout)")
    ap.add_argument("--mode", choices=("release", "diagnostic"), default="release")
    ap.add_argument("--output", required=True)
    ap.add_argument("--expect-nand-sha256")
    ap.add_argument("--expect-platform-sha256")
    ap.add_argument("--expect-bootcount-sha256")
    ap.add_argument("--expect-ubootenv-sha256")
    args = ap.parse_args()

    gate = Gate(args.mode)
    scripts_dir = Path(args.scripts_dir)
    report = {
        "schema": 1,
        "gate": "S1-05 installer admission",
        "mode": args.mode,
        "scope": "offline rootfs artifact evidence only; not boot, flash or hardware evidence",
        "scripts_dir": str(scripts_dir),
        "source_root": args.source_root,
        "status": "PASS",
        "checks": gate.checks,
        "scripts": {},
        "harness": {},
    }
    try:
        scripts = load_scripts(scripts_dir, gate)
        report["harness"]["platform"] = check_platform(scripts, gate)
        report["harness"]["bootcount"] = check_bootcount(scripts, gate)
        report["harness"]["ubootenv"] = check_ubootenv(scripts, gate)
        report["harness"]["nand"] = check_nand(scripts, gate)
        pins = {
            name: getattr(args, PIN_ARG[name])
            for name in SCRIPT_NAMES
            if getattr(args, PIN_ARG[name])
        }
        if args.source_root:
            report["scripts"] = check_source_identity(
                scripts, scripts_dir, Path(args.source_root), gate, pins)
        else:
            report["scripts"] = {name: {"sha256": sha256_bytes(data), "bytes": len(data)}
                                 for name, data in scripts.items()}
            if pins:
                for name, data in scripts.items():
                    if name in pins and sha256_bytes(data) != pins[name]:
                        gate.fail(f"pin:{name}", "sha256 does not match reviewed pin")
    except Exception as exc:  # fail closed on any unexpected checker error
        gate.fail("gate-internal", f"installer admission checker error: {exc}")
    report["status"] = gate.status
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "output": str(output)}, indent=2))
    if report["status"] != "PASS":
        failures = [c for c in report["checks"] if c["status"] == "FAIL"]
        print("INSTALLER ADMISSION FAILED:", file=sys.stderr)
        for check in failures:
            print(f"  - {check['name']}: {check['detail']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
