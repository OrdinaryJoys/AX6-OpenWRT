#!/usr/bin/env python3
"""Explicit, receipt-bound host controller. Default mode is entirely offline."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shlex
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
from ax6_restore import InvalidBackup, archive, check_backup, digest, normalized_payload, regular, require

# Keep the experimental transaction engine unreachable from the public CLI
# until real Linux/BusyBox and exact OpenClash lifecycle review are complete.
APPLY_RELEASED = False


class RemoteFailure(RuntimeError):
    def __init__(self, action, code):
        self.action, self.code = action, code
        super().__init__("remote " + action + " failed; inspect private receipts")


class RestoreInterrupted(RuntimeError):
    pass


def approved(report, path):
    receipt = json.loads(regular(path, 1024 * 1024))
    require(isinstance(receipt, dict), "invalid approval document")
    require(receipt.get("schema") == 1 and receipt.get("reviewed") is True and receipt.get("schema_reviewed") is True,
            "a reviewed schema/hook/firmware receipt is required; check output is not approval")
    for key in ("manifest_sha256", "archive_sha256", "hook_sha256"):
        require(receipt.get(key) == report[key], "approval does not match the exact backup or hooks")
    for key in ("target_init_sha256", "target_core_sha256"):
        require(isinstance(receipt.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", receipt[key]),
                "approval lacks an exact validated target firmware digest")
    require(type(receipt.get("enabled")) is int and receipt["enabled"] in (0, 1), "invalid approved enable state")
    return receipt


def disabled_clean(snapshots):
    require(isinstance(snapshots["nft"], dict) and isinstance(snapshots["nft"].get("nftables"), list),
            "disabled firewall snapshot is invalid")
    for item in snapshots["nft"]["nftables"]:
        require(isinstance(item, dict), "invalid disabled firewall record")
        rule = item.get("rule")
        if not rule:
            continue
        text = json.dumps(rule).lower()
        require("openclash" not in text, "disabled OpenClash retains firewall rules")
        require('"tproxy"' not in text, "disabled proxy has an unclassified TPROXY producer")
    for name in ("rule4", "rule6", "route4", "route6"):
        require(isinstance(snapshots[name], list), "disabled policy snapshot is invalid")
        for entry in snapshots[name]:
            require(isinstance(entry, dict), "invalid disabled policy record")
            table = entry.get("table")
            value = str(table).lower()
            numeric = int(value, 10) if value.isdecimal() else int(value, 16) if re.fullmatch(r"0x[0-9a-f]+", value) else None
            require(numeric != 354 and "openclash" not in value, "disabled OpenClash retains policy table 354")


class Restore:
    def __init__(self, options, report, payload, receipt):
        ipaddress.ip_address(options.router)
        self.output = options.output
        self.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        key = Path(os.environ.get("SSH_KEY", str(Path.home() / ".ssh/ax6_check")))
        require(key.is_file(), "explicit SSH key unavailable; password/agent fallback is forbidden")
        self.ssh = ["ssh", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
                    "-o", "UserKnownHostsFile=" + os.environ.get("SSH_KNOWN_HOSTS", str(Path.home() / ".ssh/known_hosts")),
                    "root@" + options.router]
        self.script = Path(__file__).with_name("ax6-openclash-restore-remote.sh").read_text()
        self.payload = normalized_payload(payload)
        members = archive(self.payload)
        payload_kb = (sum(len(value) for value in members.values() if value is not None) + len(members) * 1024 + 1023) // 1024
        self.args = [secrets.token_hex(16), digest(self.payload), receipt["target_init_sha256"],
                     receipt["target_core_sha256"], str(receipt["enabled"]), str(payload_kb)]
        self.enabled = receipt["enabled"]
        self.report = report
        self.counter = 0
        (self.output / "approval.json").write_text(json.dumps(receipt, indent=2) + "\n")
        (self.output / "validated-backup.json").write_text(json.dumps(report, indent=2) + "\n")

    def rpc(self, action, data=b""):
        self.counter += 1
        prefix = self.output / (str(self.counter).zfill(2) + "-" + action)
        command = shlex.join(["sh", "-c", self.script, "ax6-restore", action] + self.args)
        try:
            process = subprocess.run(self.ssh + [command], input=data, capture_output=True, timeout=180)
        except subprocess.TimeoutExpired as error:
            prefix.with_suffix(".stderr").write_bytes(error.stderr or b"")
            raise RemoteFailure(action, 255) from error
        prefix.with_suffix(".stdout").write_bytes(process.stdout)
        prefix.with_suffix(".stderr").write_bytes(process.stderr)
        prefix.with_suffix(".json").write_text(json.dumps({"action": action, "exit": process.returncode,
                                                          "stdin_sha256": digest(data)}, indent=2) + "\n")
        if process.returncode:
            raise RemoteFailure(action, process.returncode)
        return process.stdout

    def execute(self):
        result = {"status": "INCOMPLETE", "automatic_flash": False, "automatic_reboot": False}
        try:
            self.rpc("prepare", self.payload)
            rollback = self.rpc("fetch-rollback")
            archive(rollback)
            (self.output / "rollback.tar.gz").write_bytes(rollback)
            cron = self.rpc("fetch-cron")
            (self.output / "crontab.before").write_bytes(cron)
            for name in ("rollback.tar.gz", "crontab.before"):
                with (self.output / name).open("rb") as handle:
                    os.fsync(handle.fileno())
            self.rpc("commit")
            self.rpc("verify")
            if self.enabled == 0:
                snapshots = {name: json.loads(self.rpc("disabled-" + name))
                             for name in ("nft", "rule4", "rule6", "route4", "route6")}
                disabled_clean(snapshots)
            self.rpc("finish")
            result["status"] = "RESTORED_AND_VERIFIED"
        except (RemoteFailure, RestoreInterrupted, InvalidBackup, OSError, ValueError, EOFError, tarfile.TarError) as error:
            result["status"] = "FAILED_RETAIN_EVIDENCE"
            result["error"] = str(error)
            if isinstance(error, RestoreInterrupted) or isinstance(error, RemoteFailure) and error.code == 255:
                result["status"] = "REMOTE_STATE_UNKNOWN_MANUAL_REVIEW_REQUIRED"
            elif not isinstance(error, RemoteFailure) or error.action != "prepare":
                try:
                    state = self.rpc("state").decode().splitlines()
                    phase = state[0]
                    if phase in ("STOPPING", "APPLYING", "APPLIED", "VERIFIED"):
                        self.rpc("rollback")
                        if state[1] == "0":
                            snapshots = {name: json.loads(self.rpc("disabled-" + name))
                                         for name in ("nft", "rule4", "rule6", "route4", "route6")}
                            disabled_clean(snapshots)
                        result["rollback"] = "VERIFIED_CURRENT_CONTRACT"
                    else:
                        result["rollback"] = "NOT_NEEDED_NO_REPLACEMENT_STARTED"
                except (RemoteFailure, OSError, IndexError, UnicodeError, ValueError):
                    result["rollback"] = "NOT_VERIFIED_MANUAL_RECOVERY_REQUIRED"
        (self.output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "RESTORED_AND_VERIFIED" else 2


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="offline only (also the default)")
    mode.add_argument("--apply", action="store_true", help="explicitly perform an approved restoration")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--router", default="192.168.5.1")
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    report, payload = check_backup(options.backup)
    if not options.apply:
        print(json.dumps(report, indent=2))
        return 0
    require(APPLY_RELEASED, "apply is not released: Linux/BusyBox and exact lifecycle approval remain pending")
    require(options.approval is not None and options.output is not None,
            "--apply requires --approval and a new private --output directory")
    require(not options.output.resolve().is_relative_to(options.backup.resolve()),
            "receipts must not alter the original backup directory")
    receipt = approved(report, options.approval)
    def interrupted(signum, _frame):
        raise RestoreInterrupted("interrupted by signal " + str(signum) + "; remote state requires review")
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        return Restore(options, report, payload, receipt).execute()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RestoreInterrupted, InvalidBackup, OSError, ValueError, EOFError, tarfile.TarError) as error:
        print("restore refused: " + str(error), file=sys.stderr)
        sys.exit(2)
