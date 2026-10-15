#!/usr/bin/env python3
"""Host-only, standard-library validation for staged router backups."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_MEMBERS = 10000
ROOTS = ("etc/config/openclash", "etc/openclash/config", "etc/openclash/custom", "etc/openclash/overwrite")


class InvalidBackup(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidBackup(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path, limit=MAX_ARCHIVE):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), "expected a regular non-symlink file")
        require(0 < info.st_size <= limit, "file is empty or exceeds the size limit")
        data = stream.read(limit + 1)
    require(len(data) <= limit, "file changed beyond the size limit")
    return data


def archive(data, policy="openclash"):
    require(0 < len(data) <= MAX_ARCHIVE, "archive exceeds the compressed size limit")
    # Read through the gzip footer first; tar readers can stop before its CRC.
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
        expanded = compressed.read(MAX_EXPANDED + 1)
    require(len(expanded) <= MAX_EXPANDED, "archive exceeds the expanded size limit")
    members = {}
    total_payload = 0
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as stream:
        for member in stream:
            require(len(members) < MAX_MEMBERS, "too many archive members")
            name = member.name
            if name.startswith("./"):
                name = name[2:]
            name = name.rstrip("/")
            parts = name.split("/")
            require(name and not name.startswith("/") and not any(part in ("", ".", "..") for part in parts),
                    "unsafe archive path")
            require(not any(ord(char) < 32 or ord(char) == 127 for char in name) and "\\" not in name,
                    "non-portable archive path")
            require(name not in members, "duplicate archive member")
            require(member.isfile() or member.isdir(), "links or special archive members are forbidden")
            total_payload += member.size
            require(0 <= member.size <= MAX_EXPANDED and total_payload <= MAX_EXPANDED and not member.sparse,
                    "sparse or oversized archive member")
            require(not member.mode & 0o7000, "privileged archive permissions are forbidden")
            require(PurePosixPath(name).name not in ("shadow", "shadow-"), "login password leaked into archive")
            if policy == "openclash":
                allowed = name == ROOTS[0] and member.isfile() or any(
                    name == root and member.isdir() or name.startswith(root + "/") for root in ROOTS[1:])
            elif policy == "ssh":
                allowed = name == "etc/dropbear/authorized_keys" and member.isfile()
            elif policy == "zerotier":
                allowed = name in ("etc/zerotier/identity.public", "etc/zerotier/identity.secret") and member.isfile()
            elif policy == "forensic":
                allowed = not name.startswith("etc/openclash/") or any(
                    name == root or name.startswith(root + "/") for root in ROOTS[1:])
            else:
                raise InvalidBackup("unknown archive policy")
            label = "OpenClash" if policy == "openclash" else policy
            require(allowed, label + " archive crossed its restore allowlist")
            payload = stream.extractfile(member).read() if member.isfile() else None
            require(payload is None or len(payload) == member.size, "truncated archive member")
            members[name] = payload
        require(not any(expanded[stream.offset:]), "trailing archive data is forbidden")
    require(members, "empty archive")
    for name in members:
        for parent in PurePosixPath(name).parents:
            if str(parent) in members:
                require(members[str(parent)] is None, "regular file used as an archive parent")
    if policy == "openclash":
        require(bool(members.get(ROOTS[0])), "missing OpenClash UCI configuration")
    elif policy == "ssh":
        require(len(members) == 1 and bool(members.get("etc/dropbear/authorized_keys")),
                "SSH archive is not nonempty authorized_keys-only")
    elif policy == "zerotier":
        require(len(members) == 2 and bool(members.get("etc/zerotier/identity.secret")), "ZeroTier secret identity is incomplete")
    return members


def check_backup(directory):
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), "backup directory is unavailable or a symlink")
    entries = {path.name: path for path in directory.iterdir()}
    require(not any(name.startswith("sysupgrade-config") and name.endswith(".tar.gz") for name in entries),
            "legacy whole-restore archive found")
    hashes = regular(directory / "SHA256SUMS.txt", 1024 * 1024).decode("utf-8")
    expected = {}
    for line in hashes.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](?:\./)?([^/\x00\r\n]+)", line)
        require(match is not None, "invalid or non-local checksum record")
        checksum, name = match.groups()
        require(name not in expected and name not in (".", "..", "SHA256SUMS.txt"), "duplicate or recursive checksum record")
        expected[name] = checksum
    require(set(entries) == set(expected) | {"SHA256SUMS.txt"}, "checksum inventory does not cover the complete backup")
    data = {}
    for name, checksum in expected.items():
        data[name] = regular(entries[name])
        require(digest(data[name]) == checksum, "backup checksum verification failed")
    mandatory = {"FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked", "openclash-runtime.tar.gz",
                 "ssh-authorized-keys.tar.gz", "zerotier-identity.tar.gz", "MANIFEST.txt",
                 "DO-NOT-RESTORE-WHOLE-BACKUP.txt", "uci-network.txt", "uci-firewall.txt",
                 "uci-dhcp.txt", "uci-wireless.txt"}
    require(mandatory <= data.keys(), "missing staged backup component")
    require(b"forensic snapshot must never be restored whole" in data["MANIFEST.txt"], "missing forensic restore prohibition")
    require(b"never pass it to sysupgrade -r" in data["DO-NOT-RESTORE-WHOLE-BACKUP.txt"], "missing whole-restore warning")
    checked = {}
    for name, policy in (("FORENSIC-CONFIG-SNAPSHOT.tar.gz.blocked", "forensic"),
                         ("openclash-runtime.tar.gz", "openclash"),
                         ("ssh-authorized-keys.tar.gz", "ssh"), ("zerotier-identity.tar.gz", "zerotier")):
        checked[policy] = archive(data[name], policy)
    hooks = {name: digest(content) for name, content in checked["openclash"].items()
             if content is not None and name.endswith(".sh")}
    report = {"status": "PASS_STRUCTURAL_ONLY", "checksum_files": len(expected),
              "manifest_sha256": digest(hashes.encode()),
              "archive_sha256": digest(data["openclash-runtime.tar.gz"]),
              "archive_members": {name: len(members) for name, members in checked.items()},
              "hook_sha256": hooks, "restoration_authorized": False,
              "zerotier_public_empty": not bool(checked["zerotier"].get("etc/zerotier/identity.public")),
              "zerotier_crypto_validated": False}
    return report, data["openclash-runtime.tar.gz"]


def normalized_payload(data):
    members = archive(data)
    for root in ROOTS[1:]:
        members.setdefault(root, None)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.USTAR_FORMAT) as stream:
        for name in sorted(members):
            content = members[name]
            info = tarfile.TarInfo(name)
            info.uid = info.gid = info.mtime = 0
            info.type = tarfile.DIRTYPE if content is None else tarfile.REGTYPE
            info.mode = 0o700 if content is None or name.endswith(".sh") else 0o600
            info.size = len(content) if content is not None else 0
            stream.addfile(info, io.BytesIO(content) if content is not None else None)
    return output.getvalue()


if __name__ == "__main__":
    import sys
    try:
        require(len(sys.argv) == 3 and sys.argv[1] == "check-backup", "usage: ax6_restore.py check-backup BACKUP")
        report = check_backup(Path(sys.argv[2]))[0]
        if report["zerotier_public_empty"]:
            print("warning: ZeroTier public identity is empty; verify the secret and derive its public portion before identity restoration", file=sys.stderr)
        print(json.dumps(report, indent=2))
    except (InvalidBackup, OSError, EOFError, tarfile.TarError, UnicodeError) as error:
        print("restore validation failed: " + str(error), file=sys.stderr)
        sys.exit(2)
