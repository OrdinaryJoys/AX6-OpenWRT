#!/usr/bin/env python3
"""
Offline admission of a built AX6 NSS kernel-module artifact (S3-08 / EG-2).

Reads the offline kmod feed produced by AX6-IPQ/scripts/package-ax6-offline-feed.sh
(a Packages index plus the referenced .ipk packages) and verifies the artifact
identity against the locked source tree:

  * index integrity: every record has the mandatory package fields, package
    names and Filenames are unique, the Filename is a safe basename, and the
    referenced IPK exists as a regular file whose Size and SHA256sum match the
    index (Packages.gz, when present, must decompress to Packages byte-exactly);
  * exact NSS package versions derived from the locked source Makefiles
    (kernel release + PKG_VERSION + PKG_RELEASE) instead of hand-typed strings,
    for the five core packages and all 16 enabled qca-nss-clients packages;
  * build-lock SOURCE_*_PKG_RELEASE equality with the same Makefiles;
  * every admitted IPK's control fields equal the index (Package, Version,
    Architecture, Depends) and its SourceName matches the reviewed source
    package -- so a missing, renamed, swapped or repackaged core IPK cannot
    pass on the index version alone;
  * the exact .ko payload inventory from the source Makefile FILES: all
    expected modules present, no renamed/extra/stolen module, all under
    lib/modules/<kernel release>/, and each module basename claimed once;
  * one kernel vermagic across every admitted NSS module;
  * the SSDK withdrawal marker ("no device found") so a withdrawn fail-closed
    layer (A2 r2 / B4 r32) cannot be admitted; when the source carries patch
    054, the retention/degraded banner text added by that patch is required in
    qca-ssdk.ko as well;
  * artifact-level DRV proof for the reviewed command-size layer: the 033
    connection-table containment literal is present in qca-nss-drv.ko and the
    compiled nss_wifili_tx_msg() must compute the message length from the NSS
    common header (+ sizeof(struct nss_cmn_msg)) and reject > NSS_NBUF_PAYLOAD_SIZE
    instead of passing the 2096-byte sizeof(struct nss_wifili_msg) constant.
    This is a byte-level check of the compiled function, not a source-only
    claim; the pre-055 A2-era driver shape fails it;
  * the reviewed 16 enabled qca-nss-clients modules and their expected .ko
    payloads (disabled eogremgr/wifi-meshmgr must be absent from the index and
    from every admitted payload);
  * NSS symbol closure: every undefined `nss_*` symbol of an admitted module is
    exported by another admitted module;
  * optional byte identity of the installed rootfs upgrade scripts against the
    locked source tip; required in release mode.

Release mode (`--expect-withdrawals`, used by the release-gating workflow step)
additionally requires --lock, --config and --rootfs-scripts, so the identity,
client-inventory and installed-script checks can never be silently skipped.

Expected failures are the quarantined artifacts A2 (SSDK r2, pre-055 driver) and
B4 (SSDK r32 with the withdrawn 054, pre-fix nand.sh), plus the negative
controls replayed during the 2026-11-20 CI/admission repair: empty/renamed core
IPK payloads, a core IPK whose control version differs from the index, and a
qca-nss-drv.ko whose nss_wifili_tx_msg() still passes the 2096-byte constant.
This is read-only identity evidence: not boot, flash, hardware or runtime proof.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import struct
import sys
import tarfile
from pathlib import Path

# Index package name -> (source package directory, build-lock release key).
PACKAGE_MAKEFILES = {
    "kmod-qca-ssdk": ("qca-ssdk", "SOURCE_QCA_NSS_SSDK_PKG_RELEASE"),
    "kmod-qca-nss-dp": ("qca-nss-dp", "SOURCE_QCA_NSS_DP_PKG_RELEASE"),
    "kmod-qca-nss-drv": ("qca-nss-drv", "SOURCE_QCA_NSS_DRV_PKG_RELEASE"),
    "kmod-qca-nss-ecm": ("qca-nss-ecm", "SOURCE_QCA_NSS_ECM_PKG_RELEASE"),
    "kmod-qca-mcs": ("qca-mcs", "SOURCE_QCA_MCS_PKG_RELEASE"),
}
CLIENTS_MAKEFILE = "qca-nss-clients"
CLIENTS_LOCK_KEY = "SOURCE_QCA_NSS_CLIENTS_PKG_RELEASE"
CLIENTS_ENABLED = 16
EXPECTED_DISABLED_CLIENTS = (
    "kmod-qca-nss-drv-eogremgr",
    "kmod-qca-nss-drv-wifi-meshmgr",
)
ROOTFS_SCRIPT_SOURCES = {
    "nand.sh": "package/base-files/files/lib/upgrade/nand.sh",
    "platform.sh": "target/linux/qualcommax/ipq807x/base-files/lib/upgrade/platform.sh",
    "bootcount": "target/linux/qualcommax/ipq807x/base-files/etc/init.d/bootcount",
    "30_uboot-envtools": "package/boot/uboot-tools/uboot-envtools/files/qualcommax_ipq807x",
}
INDEX_REQUIRED_FIELDS = ("Package", "Version", "Architecture", "Filename", "Size", "SHA256sum")
SSDK_MARKER = b"no device found"
SSDK_RETENTION_HINT = re.compile(rb"(retain|degraded)", re.IGNORECASE)
DRV_033_MARKER = b"NSS: FW retirement unknown; connection table mappings retained"
DRV_SOURCE_PATCH_REQUIREMENTS = {
    "033": "033-*.patch",
    "055": "055-*.patch",
}
WIFILI_TX_SYMBOL = "nss_wifili_tx_msg"
# Reviewed ABI constants for the compiled nss_wifili_tx_msg() shape.
NSS_NBUF_PAYLOAD_SIZE = 0x7C0       # 1984
NSS_CMN_MSG_BYTES = 0x28            # sizeof(struct nss_cmn_msg), added to ncm->len
WIFILI_MSG_BYTES = 0x830            # 2096 = sizeof(struct nss_wifili_msg), pre-055 constant
MAX_IPK_BYTES = 64 * 1024 * 1024
MAX_KO_BYTES = 64 * 1024 * 1024


class AdmissionError(Exception):
    pass


def require(cond: bool, message: str) -> None:
    if not cond:
        raise AdmissionError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_field(value: str) -> str:
    """Collapse whitespace so IPK/index dependency metadata compares stably."""
    return " ".join(value.split())


def fields(text: str) -> list[dict]:
    """Parse an RFC822-like Packages index into records."""
    records = []
    for block in re.split(r"\n\n+", text.strip("\n")):
        if not block.strip():
            continue
        record = {}
        last = None
        for line in block.splitlines():
            if line[:1].isspace():
                require(last is not None, "orphan package continuation line")
                record[last] += "\n" + line
                continue
            key, separator, value = line.partition(":")
            require(bool(separator and key and key not in record),
                    f"malformed/duplicate package field: {line[:80]}")
            record[key] = value.strip()
            last = key
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Index integrity (no IPK reads)
# ---------------------------------------------------------------------------

def load_index(packages_dir: Path) -> dict[str, dict]:
    """Read, structurally validate and de-duplicate the kmod index."""
    index_path = packages_dir / "Packages"
    require(index_path.is_file() and not index_path.is_symlink(),
            f"regular Packages index missing: {index_path}")
    raw = index_path.read_bytes()
    compressed = packages_dir / "Packages.gz"
    if compressed.exists() or compressed.is_symlink():
        require(compressed.is_file() and not compressed.is_symlink(),
                "Packages.gz must be a regular file")
        require(gzip.decompress(compressed.read_bytes()) == raw,
                "Packages.gz does not match Packages")
    records: dict[str, dict] = {}
    filenames: dict[str, str] = {}
    for record in fields(raw.decode("utf-8")):
        package = record.get("Package")
        require(bool(package), "package record without a Package field")
        require(package not in records, f"duplicate package record in kmod index: {package}")
        for field in INDEX_REQUIRED_FIELDS:
            require(bool(record.get(field)),
                    f"{package}: kmod index record is missing the {field} field")
        filename = record["Filename"]
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.~%-]*\.ipk", filename) is not None,
                f"{package}: unsafe or non-IPK Filename: {filename!r}")
        require(filename not in filenames,
                f"duplicate indexed Filename {filename!r} used by {filenames.get(filename)} and {package}")
        require(re.fullmatch(r"[0-9a-f]{64}", record["SHA256sum"]) is not None,
                f"{package}: invalid indexed SHA256sum")
        require(re.fullmatch(r"[1-9][0-9]*", record["Size"]) is not None,
                f"{package}: invalid indexed Size")
        records[package] = record
        filenames[filename] = package
    require(bool(records), "kmod index is empty")
    return records


# ---------------------------------------------------------------------------
# IPK reading (ar + gzip-tar envelope, no extraction to disk)
# ---------------------------------------------------------------------------

def _ar_members(data: bytes) -> dict[str, bytes]:
    require(data.startswith(b"!<arch>\n"), "IPK envelope is not an ar archive")
    members: dict[str, bytes] = {}
    position = 8
    while position < len(data):
        require(position + 60 <= len(data), "truncated ar header")
        header = data[position:position + 60]
        require(header[58:60] == b"`\n", "invalid ar header magic")
        name = header[:16].decode("ascii").strip().removesuffix("/")
        size_text = header[48:58].decode("ascii").strip()
        require(size_text.isdigit(), "invalid ar member size")
        size = int(size_text)
        position += 60
        require(position + size <= len(data), "truncated ar payload")
        require(name not in members, f"duplicate ar member: {name}")
        members[name] = data[position:position + size]
        position += size + (size % 2)
    return members


def _tar_members(data: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            name = member.name
            while name.startswith("./"):
                name = name[2:]
            require(name and not name.startswith("/") and ".." not in Path(name).parts,
                    f"unsafe tar member: {member.name}")
            if member.isdir() or member.issym() or member.islnk():
                # Kernel IPKs may ship /etc/modules.d symlinks; only regular
                # payload files are read, links are never followed.
                continue
            require(member.isfile(), f"unsupported tar member type: {member.name}")
            require(member.size <= MAX_KO_BYTES, f"tar member too large: {member.name}")
            result[name] = archive.extractfile(member).read()
    return result


def read_ipk(data: bytes) -> tuple[dict, dict[str, bytes]]:
    """Return (control fields, payload files) for a gzip-tar or ar IPK."""
    require(len(data) <= MAX_IPK_BYTES, "IPK too large")
    if data.startswith(b"!<arch>\n"):
        outer = _ar_members(data)
        require("debian-binary" in outer, "IPK missing debian-binary")
        require(("control.tar.gz" in outer) and ("data.tar.gz" in outer),
                "IPK missing control/data members")
        control_files = _tar_members(gzip.decompress(outer["control.tar.gz"]))
        payload = _tar_members(gzip.decompress(outer["data.tar.gz"]))
    elif data.startswith(b"\x1f\x8b"):
        outer = _tar_members(gzip.decompress(data))
        require(("control.tar.gz" in outer) and ("data.tar.gz" in outer),
                "gzip IPK envelope differs")
        control_files = _tar_members(gzip.decompress(outer["control.tar.gz"]))
        payload = _tar_members(gzip.decompress(outer["data.tar.gz"]))
    else:
        raise AdmissionError("unsupported IPK envelope")
    control_name = "control" if "control" in control_files else None
    require(control_name is not None, "IPK control file missing")
    records = fields(control_files[control_name].decode("utf-8"))
    require(len(records) == 1, "IPK must contain exactly one control record")
    return records[0], payload


# ---------------------------------------------------------------------------
# ELF symbol analysis (module exports / undefined NSS symbols)
# ---------------------------------------------------------------------------

def _elf_sections(data: bytes) -> tuple[list[dict], dict[str, dict]]:
    require(len(data) >= 64 and data[:4] == b"\x7fELF", "not an ELF module")
    require(data[4] == 2 and data[5] == 1, "module is not ELF64 little-endian")
    e_shoff, = struct.unpack_from("<Q", data, 0x28)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x3A)
    require(e_shentsize == 64 and 0 < e_shnum < 32768 and e_shstrndx < e_shnum,
            "invalid module section table")
    require(0 < e_shoff and e_shoff + e_shnum * 64 <= len(data),
            "module section table outside file")
    sections = []
    for index in range(e_shnum):
        (name_off, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info,
         sh_align, sh_entsize) = struct.unpack_from("<IIQQQQIIQQ", data, e_shoff + index * 64)
        sections.append({"index": index, "name_off": name_off, "type": sh_type,
                         "flags": sh_flags, "addr": sh_addr, "offset": sh_offset,
                         "size": sh_size, "link": sh_link, "entsize": sh_entsize})
    name_section = sections[e_shstrndx]
    require(name_section["type"] == 3, "section name table is not a string table")
    names = data[name_section["offset"]:name_section["offset"] + name_section["size"]]
    by_name = {}
    for section in sections:
        end = names.find(b"\0", section["name_off"])
        require(end >= 0, "unterminated section name")
        section["name"] = names[section["name_off"]:end].decode("ascii", "replace")
        require(section["name"] not in by_name, f"duplicate module section name: {section['name']}")
        by_name[section["name"]] = section
    return sections, by_name


def elf_symbol_records(data: bytes) -> list[dict]:
    """Return every .symtab entry with its section index, value and size."""
    sections, by_name = _elf_sections(data)
    require(".symtab" in by_name, "module has no .symtab")
    symtab = by_name[".symtab"]
    require(symtab["type"] == 2 and symtab["entsize"] == 24, "invalid .symtab")
    strtab_section = by_name.get(".strtab")
    require(strtab_section is not None, "module has no .strtab")
    require(strtab_section["type"] == 3, ".strtab is not a string table")
    strtab = data[strtab_section["offset"]:strtab_section["offset"] + strtab_section["size"]]
    count = symtab["size"] // 24
    require(0 < count <= 2_000_000, "invalid module symbol count")
    records = []
    for index in range(count):
        offset = symtab["offset"] + index * 24
        require(offset + 24 <= len(data), "module symbol outside file")
        st_name, st_info, st_other, st_shndx, st_value, st_size = \
            struct.unpack_from("<IBBHQQ", data, offset)
        require(st_name < len(strtab), "symbol name outside string table")
        end = strtab.find(b"\0", st_name)
        require(end >= 0, "unterminated symbol name")
        records.append({"name": strtab[st_name:end].decode("ascii", "replace"),
                        "shndx": st_shndx, "value": st_value, "size": st_size})
    return records


def elf_symbol_body(data: bytes, symbol: str) -> bytes:
    """Return the exact compiled function body of a defined text symbol."""
    sections, by_name = _elf_sections(data)
    require(".symtab" in by_name, "module has no .symtab")
    matched = [record for record in elf_symbol_records(data)
               if record["name"] == symbol and record["shndx"] != 0 and record["size"] > 0]
    require(len(matched) == 1,
            f"module has {len(matched)} defined sized {symbol} symbols; expected exactly one")
    record = matched[0]
    require(record["shndx"] < len(sections), f"{symbol} references a nonexistent section")
    section = sections[record["shndx"]]
    require(section["type"] == 1, f"{symbol} is not in a PROGBITS section")
    require(section["addr"] <= record["value"] < section["addr"] + section["size"],
            f"{symbol} value outside its section")
    require(record["size"] <= section["size"], f"{symbol} size exceeds its section")
    offset = section["offset"] + record["value"] - section["addr"]
    require(offset + record["size"] <= len(data), f"{symbol} body outside the module file")
    return data[offset:offset + record["size"]]


def elf_exports(data: bytes) -> set[str]:
    _sections, by_name = _elf_sections(data)
    kss = by_name.get("__ksymtab_strings")
    if kss is None:
        return set()
    strings = data[kss["offset"]:kss["offset"] + kss["size"]]
    exported = set()
    for record in elf_symbol_records(data):
        if record["name"].startswith("__kstrtabns_"):
            continue
        if not record["name"].startswith("__kstrtab_") or record["shndx"] != kss["index"]:
            continue
        if 0 <= record["value"] < len(strings):
            end = strings.find(b"\0", record["value"])
            if end > record["value"]:
                exported.add(strings[record["value"]:end].decode("ascii", "replace"))
    return exported


def elf_undefined(data: bytes) -> set[str]:
    return {record["name"] for record in elf_symbol_records(data)
            if record["shndx"] == 0 and record["name"]}


def module_vermagic(data: bytes) -> str:
    match = re.search(rb"vermagic=([^\x00\n]+)", data)
    if not match:
        raise AdmissionError("module has no .modinfo vermagic string")
    return match.group(1).decode("ascii", "replace")


# ---------------------------------------------------------------------------
# AArch64 instruction decoding for the reviewed nss_wifili_tx_msg() shape.
#
# 055 replaces nss_core_send_cmd(ctx, msg, sizeof(*msg) /* 2096 */, 1984) with
# nss_core_send_cmd(ctx, msg, nss_cmn_get_msg_len(ncm) /* ncm->len + 40 */, 1984)
# plus a >1984 rejection.  The reviewed build compiles that as:
#   ldrh  w?, [x?, #2]      ; ncm->len (uint16)
#   add   w?, w?, #0x28     ; + sizeof(struct nss_cmn_msg)
#   cmp   w?, #0x7c0        ; NSS_NBUF_PAYLOAD_SIZE
#   b.hi  reject
# so the pre-055 constant-size send (mov w?, #0x830) is detectable byte-exactly.
# The same body is produced by the B4 and B6 builds (identical drv.ko sha256),
# and the A2-era driver fails this check.
# ---------------------------------------------------------------------------

def _a64_ldrh_unsigned(word: int):
    if (word >> 22) != 0x1E5:
        return None
    return {"rt": word & 0x1F, "rn": (word >> 5) & 0x1F, "offset": ((word >> 10) & 0xFFF) * 2}


def _a64_add_immediate(word: int):
    if (word >> 22) != 0x44:
        return None
    return {"rn": (word >> 5) & 0x1F, "rd": word & 0x1F, "imm": (word >> 10) & 0xFFF}


def _a64_cmp_immediate(word: int):
    if (word >> 22) != 0x1C4 or (word & 0x1F) != 31:
        return None
    return {"rn": (word >> 5) & 0x1F, "imm": (word >> 10) & 0xFFF}


def _a64_b_cond(word: int):
    if (word >> 24) != 0x54 or (word & 0x10):
        return None
    return {"cond": word & 0xF}


def _a64_movz_32(word: int):
    if (word >> 23) != 0xA5:
        return None
    return {"rd": word & 0x1F, "imm16": (word >> 5) & 0xFFFF}


def wifili_055_fingerprint(body: bytes) -> dict:
    """Byte-level proof that nss_wifili_tx_msg() sends the actual message length."""
    require(len(body) >= 32 and len(body) % 4 == 0, "nss_wifili_tx_msg body is not instruction aligned")
    words = [struct.unpack_from("<I", body, offset)[0] for offset in range(0, len(body), 4)]
    constant_2096 = [index for index, word in enumerate(words)
                     if (_a64_movz_32(word) or {}).get("imm16") == WIFILI_MSG_BYTES]
    match = None
    for index, word in enumerate(words):
        compare = _a64_cmp_immediate(word)
        if not compare or compare["imm"] != NSS_NBUF_PAYLOAD_SIZE:
            continue
        register = compare["rn"]
        add_index = None
        for candidate in range(index - 1, max(-1, index - 9), -1):
            add = _a64_add_immediate(words[candidate])
            if add and add["rn"] == register and add["rd"] == register \
                    and add["imm"] == NSS_CMN_MSG_BYTES:
                add_index = candidate
                break
        if add_index is None:
            continue
        load_index = None
        for candidate in range(add_index - 1, max(-1, add_index - 9), -1):
            load = _a64_ldrh_unsigned(words[candidate])
            if load and load["rt"] == register and load["offset"] == 2:
                load_index = candidate
                break
        if load_index is None:
            continue
        branch_index = None
        for candidate in range(index + 1, min(len(words), index + 5)):
            if _a64_b_cond(words[candidate]) is not None:
                branch_index = candidate
                break
        if branch_index is None:
            continue
        match = {"length_load_word": load_index, "sizeof_add_word": add_index,
                 "payload_size_compare_word": index, "reject_branch_word": branch_index,
                 "instruction_words": len(words)}
        break
    return {"match": match, "constant_2096_movz_words": constant_2096,
            "instruction_words": len(words), "body_bytes": len(body)}


# ---------------------------------------------------------------------------
# Source expectations
# ---------------------------------------------------------------------------

def makefile_fields(path: Path) -> dict:
    require(path.is_file(), f"source Makefile missing: {path}")
    text = path.read_text()
    result = {}
    for line in text.splitlines():
        match = re.match(r"^(PKG_RELEASE|PKG_SOURCE_DATE|PKG_SOURCE_VERSION|QSDK_VERSION|PKG_VERSION)[:?+]?=(.*)$", line)
        if match:
            require(match.group(1) not in result, f"duplicate {match.group(1)} in {path}")
            result[match.group(1)] = match.group(2).strip()
    return result


def expected_version(makefile: dict, kernel_release: str) -> str:
    release = makefile.get("PKG_RELEASE")
    require(release is not None and release.isdigit() and int(release) > 0,
            "source Makefile has no positive PKG_RELEASE")
    explicit = makefile.get("PKG_VERSION")
    if explicit is not None:
        template = explicit.replace("$(QSDK_VERSION)", makefile.get("QSDK_VERSION", ""))
        template = template.replace("$(subst -,.,$(PKG_SOURCE_DATE))",
                                    makefile.get("PKG_SOURCE_DATE", "").replace("-", "."))
        template = template.replace("$(PKG_SOURCE_DATE)", makefile.get("PKG_SOURCE_DATE", ""))
        template = template.replace("$(PKG_SOURCE_VERSION)", makefile.get("PKG_SOURCE_VERSION", ""))
        require("$(" not in template,
                f"unsupported PKG_VERSION expression in source Makefile: {explicit}")
        pkg_version = template
    else:
        date = makefile.get("PKG_SOURCE_DATE")
        commit = makefile.get("PKG_SOURCE_VERSION")
        require(bool(date and commit and re.fullmatch(r"[0-9a-f]{7,40}", commit)),
                "source Makefile has no usable PKG_SOURCE_DATE/PKG_SOURCE_VERSION")
        pkg_version = f"{date.replace('-', '.')}~{commit[:8]}"
    return f"{kernel_release}.{pkg_version}-r{release}"


def source_pkg_dir(source_root: Path, package: str) -> Path:
    return source_root / "package/qca-nss" / package


def package_module_files(makefile_path: Path) -> dict[str, list[str]]:
    """Map `kmod-<KernelPackage>` to the .ko basenames declared in FILES."""
    require(makefile_path.is_file(), f"source Makefile missing: {makefile_path}")
    text = makefile_path.read_text()
    result: dict[str, list[str]] = {}
    for segment in text.split("define KernelPackage/")[1:]:
        suffix, _, rest = segment.partition("\n")
        suffix = suffix.strip()
        if re.fullmatch(r"[a-z0-9-]+", suffix) is None:
            # Sub-blocks such as /description, /config or /install.
            continue
        block = rest.split("\nendef")[0]
        files_match = re.search(r"^\s*FILES:=(.*)$", block, re.M)
        if not files_match:
            continue
        basenames = re.findall(r"/([A-Za-z0-9_.-]+\.ko)\b", files_match.group(1))
        if basenames:
            package = f"kmod-{suffix}"
            require(package not in result, f"duplicate KernelPackage FILES declaration for {package}")
            result[package] = sorted(set(basenames))
    return result


def core_expected_modules(source_root: Path) -> dict[str, list[str]]:
    expected = {}
    for package, (package_dir, _lock_key) in PACKAGE_MAKEFILES.items():
        makefile = source_pkg_dir(source_root, package_dir) / "Makefile"
        try:
            declared = package_module_files(makefile).get(package, [])
        except AdmissionError:
            raise
        require(bool(declared),
                f"{makefile} declares no FILES .ko payload for {package}")
        expected[package] = declared
    return expected


def clients_enabled(config_path: Path) -> list[str]:
    require(config_path.is_file(), f"config file missing: {config_path}")
    enabled = []
    for line in config_path.read_text().splitlines():
        match = re.match(r"^CONFIG_PACKAGE_(kmod-qca-nss-drv-[a-z0-9-]+)=y$", line.strip())
        if match:
            enabled.append(match.group(1))
    return sorted(enabled)


def clients_disabled(config_path: Path) -> list[str]:
    require(config_path.is_file(), f"config file missing: {config_path}")
    disabled = []
    for line in config_path.read_text().splitlines():
        match = re.match(r"^# CONFIG_PACKAGE_(kmod-qca-nss-drv-[a-z0-9-]+) is not set$",
                         line.strip())
        if match:
            disabled.append(match.group(1))
    return sorted(disabled)


def clients_expected_modules(source_root: Path, config_path: Path) -> dict:
    enabled = clients_enabled(config_path)
    disabled = clients_disabled(config_path)
    makefile = source_pkg_dir(source_root, CLIENTS_MAKEFILE) / "Makefile"
    declared = package_module_files(makefile)
    expected = {}
    for package in enabled:
        require(package in declared,
                f"{makefile} declares no FILES .ko payload for enabled client {package}")
        expected[package] = declared[package]
    disabled_modules = {package: declared[package] for package in disabled if package in declared}
    missing_disabled = [package for package in disabled if package not in declared]
    require(not missing_disabled,
            f"source clients Makefile does not declare the disabled client packages: {missing_disabled}")
    return {"enabled": enabled, "disabled": disabled, "expected": expected,
            "disabled_modules": disabled_modules}


def _stable_log_phrase(literal: str) -> str | None:
    """Return a contiguous specifier-free phrase of a log literal.

    The compiled module stores the literal with its %-specifiers intact, so the
    stable substring must be a literal segment between two specifiers.
    """
    text = literal.replace("\\n", " ").replace("\\t", " ").replace('\\"', '"')
    candidates: list[str] = []
    for segment in re.split(r"%[-#0-9.+]*[a-zA-Z]", text):
        for phrase in re.findall(r"[A-Za-z][A-Za-z0-9 _:;=.-]{9,}", segment):
            phrase = " ".join(phrase.split()).strip(" .;:-")
            if len(phrase) >= 10:
                candidates.append(phrase)
    if not candidates:
        return None
    return max(candidates, key=len)


def ssdk_retention_markers(source_root: Path) -> list[bytes]:
    """Extract added retention/degraded log phrases from a 054 source patch."""
    patch_dir = source_root / "package/qca-nss/qca-ssdk/patches"
    markers = []
    for patch in sorted(patch_dir.glob("054-*.patch")) if patch_dir.is_dir() else []:
        for line in patch.read_text(errors="replace").splitlines():
            if not line.startswith("+"):
                continue
            for literal in re.findall(r'"((?:[^"\\]|\\.)*)"', line):
                if not SSDK_RETENTION_HINT.search(literal.encode("utf-8", "replace")):
                    continue
                phrase = _stable_log_phrase(literal)
                if phrase is not None:
                    markers.append(phrase.encode("utf-8", "replace"))
    return sorted(set(markers))


def drv_source_patches(source_root: Path) -> tuple[dict[str, Path], dict[str, str]]:
    """Return ({label: patch path}, {label: failure detail}) for the reviewed patches."""
    patch_dir = source_pkg_dir(source_root, "qca-nss-drv") / "patches"
    found: dict[str, Path] = {}
    errors: dict[str, str] = {}
    for label, pattern in DRV_SOURCE_PATCH_REQUIREMENTS.items():
        matches = sorted(patch_dir.glob(pattern)) if patch_dir.is_dir() else []
        if len(matches) == 1:
            found[label] = matches[0]
        else:
            errors[label] = (f"locked source must carry exactly one {label} patch; "
                             f"found {len(matches)} under {patch_dir}")
    return found, errors


# ---------------------------------------------------------------------------
# Admission checks
# ---------------------------------------------------------------------------

class Admission:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.evidence: dict = {}

    def fail(self, name: str, detail: str) -> None:
        self.checks.append({"name": name, "status": "FAIL", "detail": detail})

    def ok(self, name: str, detail: str = "") -> None:
        self.checks.append({"name": name, "status": "PASS", "detail": detail})

    @property
    def status(self) -> str:
        return "FAIL" if any(c["status"] == "FAIL" for c in self.checks) else "PASS"


def locate_packages_dir(kmod_dir: Path) -> Path:
    if (kmod_dir / "packages").is_dir():
        return kmod_dir / "packages"
    return kmod_dir


def kernel_abi(records: dict) -> tuple[str, str]:
    """Return (kernel ABI version, kernel release) from the kmod index.

    The kernel package itself is published by the target package step, not the
    kmod feed, so the ABI is derived from the exact dependency recorded by every
    NSS kmod (`kernel (=<abi>)`). All records must agree.
    """
    kernel_record = records.get("kernel")
    if kernel_record is not None and kernel_record.get("Version"):
        version = kernel_record["Version"]
    else:
        abis = set()
        for record in records.values():
            for match in re.finditer(r"kernel \(=([^)]+)\)", record.get("Depends", "")):
                abis.add(match.group(1))
        require(len(abis) == 1,
                f"kmod index must pin exactly one kernel ABI; found {sorted(abis)}")
        version = abis.pop()
    release = version.split("~", 1)[0]
    require(re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-rc[0-9]+)?", release) is not None,
            f"unsupported kernel release in index: {version!r}")
    return version, release


def source_expectation(package: str, source_root: Path, lock: dict | None, admission: Admission,
                       kernel_release: str, lock_key: str, package_dir: str) -> str | None:
    """Compare the index version with source Makefile expectations and the lock."""
    makefile = source_pkg_dir(source_root, package_dir) / "Makefile"
    try:
        fields_map = makefile_fields(makefile)
        expected = expected_version(fields_map, kernel_release)
    except AdmissionError as exc:
        admission.fail(f"version:{package}", str(exc))
        return None
    if lock is not None:
        if lock_key not in lock:
            admission.fail(f"lock:{package}",
                           f"build lock is missing the {lock_key} key")
        elif lock[lock_key] != fields_map.get("PKG_RELEASE"):
            admission.fail(f"lock:{package}",
                           f"build lock {lock_key}={lock[lock_key]} but source "
                           f"PKG_RELEASE={fields_map.get('PKG_RELEASE')}")
        else:
            admission.ok(f"lock:{package}", f"{lock_key}={lock[lock_key]}")
    return expected


def admit_ipk(package: str, record: dict, packages_dir: Path, source_root: Path,
              admission: Admission, expected_version_value: str | None,
              expected_modules: list[str], expected_source_name: str,
              kernel_version: str, kernel_release: str,
              module_owners: dict[str, str]) -> dict | None:
    """Read one indexed IPK and prove its control/payload identity."""
    if expected_version_value is not None:
        actual = record.get("Version", "")
        if actual != expected_version_value:
            admission.fail(f"version:{package}",
                           f"artifact version {actual!r} differs from locked source "
                           f"expectation {expected_version_value!r}")
        else:
            admission.ok(f"version:{package}", actual)
    if f"kernel (={kernel_version})" not in record.get("Depends", ""):
        admission.fail(f"kernel-dep:{package}",
                       f"{package} does not depend on the indexed kernel ABI {kernel_version}")
    else:
        admission.ok(f"kernel-dep:{package}", "exact kernel ABI dependency present")

    filename = record["Filename"]
    path = packages_dir / filename
    if not path.is_file() or path.is_symlink():
        admission.fail(f"ipk:{package}",
                       f"indexed IPK is missing or not a regular file: {filename!r}")
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        admission.fail(f"ipk:{package}", f"cannot read indexed IPK {filename!r}: {exc}")
        return None
    if len(data) != int(record["Size"]):
        admission.fail(f"ipk:{package}",
                       f"indexed Size {record['Size']} differs from actual {len(data)} "
                       f"for {filename!r}")
    digest = sha256_bytes(data)
    if digest != record["SHA256sum"]:
        admission.fail(f"ipk:{package}",
                       f"indexed SHA256sum mismatch for {filename!r}: index "
                       f"{record['SHA256sum']} actual {digest}")
    try:
        control, payload = read_ipk(data)
    except (AdmissionError, OSError, ValueError, struct.error, tarfile.TarError,
            EOFError) as exc:
        admission.fail(f"ipk:{package}", f"cannot read IPK {filename!r}: {exc}")
        return None

    identity_errors = []
    for field in ("Package", "Version", "Architecture"):
        if control.get(field) != record.get(field):
            identity_errors.append(f"{field} index={record.get(field)!r} "
                                   f"control={control.get(field)!r}")
    if normalize_field(control.get("Depends", "")) != normalize_field(record.get("Depends", "")):
        identity_errors.append("Depends differs between index and IPK control")
    if control.get("SourceName") != expected_source_name:
        identity_errors.append(f"SourceName control={control.get('SourceName')!r} "
                               f"expected={expected_source_name!r}")
    if identity_errors:
        admission.fail(f"control:{package}",
                       f"{filename}: IPK control is not the indexed/reviewed package: "
                       + "; ".join(identity_errors))
    else:
        admission.ok(f"control:{package}", "index/control identity matches")

    modules: dict[str, bytes] = {}
    for name, module_data in payload.items():
        if not name.endswith(".ko"):
            continue
        basename = Path(name).name
        if basename in modules:
            admission.fail(f"module:{package}", f"duplicate module payload: {name}")
            continue
        modules[basename] = module_data
        module_dir = Path(name).parent
        expected_dir = Path(f"lib/modules/{kernel_release}")
        if module_dir != expected_dir:
            admission.fail(f"module:{package}",
                           f"module payload {name} is not under {expected_dir}")
        owner = module_owners.get(basename)
        if owner is not None:
            admission.fail(f"module:{package}",
                           f"module {basename} already claimed by admitted package {owner}")
        else:
            module_owners[basename] = package
    missing = [name for name in expected_modules if name not in modules]
    unexpected = [name for name in modules if name not in expected_modules]
    if missing:
        admission.fail(f"module:{package}", f"expected module payload missing: {missing}")
    if unexpected:
        admission.fail(f"module:{package}",
                       f"unexpected/renamed module payload for this package: {unexpected}")
    if not missing and not unexpected:
        admission.ok(f"module:{package}", f"exact reviewed payload: {sorted(modules)}")
    return {"version": record.get("Version", ""), "sha256": digest, "bytes": len(data),
            "control": control, "modules": modules}


def check_client_inventory(records: dict, packages_dir: Path, source_root: Path, config_path: Path,
                           lock: dict | None, admission: Admission, kernel_version: str,
                           kernel_release: str, module_owners: dict[str, str]) -> dict:
    clients = clients_expected_modules(source_root, config_path)
    enabled, disabled = clients["enabled"], clients["disabled"]
    evidence = {"enabled": enabled, "disabled": disabled}
    if len(enabled) != CLIENTS_ENABLED:
        admission.fail("clients:count",
                       f"config enables {len(enabled)} qca-nss-clients modules; "
                       f"expected {CLIENTS_ENABLED}")
    else:
        admission.ok("clients:count", f"{CLIENTS_ENABLED} enabled qca-nss-clients modules")
    if set(disabled) != set(EXPECTED_DISABLED_CLIENTS):
        admission.fail("clients:disabled",
                       f"disabled clients set differs: "
                       f"{sorted(set(disabled) ^ set(EXPECTED_DISABLED_CLIENTS))}")
    else:
        admission.ok("clients:disabled", "eogremgr and wifi-meshmgr are disabled")
    clients_makefile = source_pkg_dir(source_root, CLIENTS_MAKEFILE) / "Makefile"
    try:
        clients_fields = makefile_fields(clients_makefile)
        clients_version = expected_version(clients_fields, kernel_release)
    except AdmissionError as exc:
        admission.fail("clients:version", str(exc))
        return evidence
    if lock is not None:
        if CLIENTS_LOCK_KEY not in lock:
            admission.fail("lock:kmod-qca-nss-clients",
                           f"build lock is missing the {CLIENTS_LOCK_KEY} key")
        elif lock[CLIENTS_LOCK_KEY] != clients_fields.get("PKG_RELEASE"):
            admission.fail("lock:kmod-qca-nss-clients",
                           f"build lock {CLIENTS_LOCK_KEY}={lock[CLIENTS_LOCK_KEY]} but source "
                           f"PKG_RELEASE={clients_fields.get('PKG_RELEASE')}")
        else:
            admission.ok("lock:kmod-qca-nss-clients",
                         f"{CLIENTS_LOCK_KEY}={lock[CLIENTS_LOCK_KEY]}")
    evidence["expected_version"] = clients_version
    evidence["expected_modules"] = clients["expected"]
    admitted = {}
    payloads: dict[str, dict[str, bytes]] = {}
    for package in enabled:
        record = records.get(package)
        if record is None:
            admission.fail(f"clients:{package}",
                           "enabled client kmod package missing from the kmod index")
            continue
        result = admit_ipk(package, record, packages_dir, source_root, admission,
                           clients_version, clients["expected"][package], CLIENTS_MAKEFILE,
                           kernel_version, kernel_release, module_owners)
        if result is not None:
            admitted[package] = {"version": result["version"], "sha256": result["sha256"],
                                 "bytes": result["bytes"], "modules": sorted(result["modules"])}
            payloads[package] = result["modules"]
    evidence["admitted"] = admitted
    evidence["payloads"] = payloads
    for package in disabled:
        if package in records:
            admission.fail(f"clients:{package}",
                           "disabled client module is present in the artifact index")
        else:
            admission.ok(f"clients:{package}", "disabled module absent from the artifact index")
    disabled_basenames = {}
    for package, files in clients["disabled_modules"].items():
        for basename in files:
            disabled_basenames[basename] = package
    for basename, owner in sorted(disabled_basenames.items()):
        if basename in module_owners:
            admission.fail(f"clients:disabled-payload:{basename}",
                           f"disabled client module {basename} ({owner}) is claimed by "
                           f"payload of {module_owners[basename]}")
        else:
            admission.ok(f"clients:disabled-payload:{basename}",
                         "disabled module absent from every admitted payload")
    return evidence


def register_modules(package: str, payloads: dict[str, bytes], modules: dict[str, dict],
                     admission: Admission) -> None:
    """Record admitted module bytes with their vermagic/hash evidence."""
    for basename, data in payloads.items():
        try:
            vermagic = module_vermagic(data)
        except AdmissionError as exc:
            admission.fail(f"vermagic:{package}:{basename}", str(exc))
            continue
        modules[basename] = {"package": package, "data": data, "vermagic": vermagic,
                             "sha256": sha256_bytes(data), "bytes": len(data)}


def check_modules(modules: dict[str, dict], source_root: Path, admission: Admission,
                  kernel_release: str) -> dict:
    """Vermagic, withdrawal/containment markers and symbol closure."""
    evidence = {}
    if not modules:
        admission.fail("modules:inventory", "no NSS module payloads found in the admitted packages")
        return evidence
    vermagics = sorted({module["vermagic"] for module in modules.values() if module["vermagic"]})
    evidence["module_count"] = len(modules)
    evidence["vermagic_values"] = vermagics
    if len(vermagics) != 1:
        admission.fail("vermagic:uniform", f"inconsistent module vermagic values: {vermagics}")
    else:
        admission.ok("vermagic:uniform", vermagics[0])
    for name, module in sorted(modules.items()):
        vermagic = module["vermagic"]
        if not vermagic or vermagic.split()[0] != kernel_release:
            admission.fail(f"vermagic:{name}",
                           f"vermagic {vermagic!r} does not start with kernel release "
                           f"{kernel_release}")
    evidence["modules"] = {name: {"package": module["package"], "sha256": module["sha256"],
                                  "bytes": module["bytes"], "vermagic": module["vermagic"]}
                           for name, module in sorted(modules.items())}

    # SSDK withdrawal / retention markers.
    ssdk = modules.get("qca-ssdk.ko")
    if ssdk is None:
        admission.fail("marker:ssdk-withdrawal", "qca-ssdk.ko not found in the admitted artifact")
    else:
        data = ssdk["data"]
        if SSDK_MARKER not in data:
            admission.fail("marker:ssdk-withdrawal",
                           "qca-ssdk.ko lacks the 'no device found' withdrawal marker "
                           "(withdrawn fail-closed SSDK layer, reject)")
        else:
            admission.ok("marker:ssdk-withdrawal", "qca-ssdk.ko contains 'no device found'")
        patch_dir = source_root / "package/qca-nss/qca-ssdk/patches"
        retention_patches = sorted(patch_dir.glob("054-*.patch")) if patch_dir.is_dir() else []
        retention = ssdk_retention_markers(source_root)
        evidence["ssdk_retention_patches"] = [patch.name for patch in retention_patches]
        if not retention_patches:
            admission.ok("marker:ssdk-retention",
                         "no 054 retention layer in the locked source (withdrawal state)")
        elif not retention:
            admission.fail("marker:ssdk-retention",
                           "locked source carries a 054 retention layer but no "
                           "retention/degraded log literal could be derived from it; "
                           "artifact retention cannot be proven")
        else:
            missing = [marker for marker in retention if marker not in data]
            evidence["ssdk_retention_markers"] = [m.decode("utf-8", "replace") for m in retention]
            evidence["ssdk_retention_missing"] = [m.decode("utf-8", "replace") for m in missing]
            if missing:
                admission.fail("marker:ssdk-retention",
                               "source carries a 054 retention layer but qca-ssdk.ko lacks its "
                               "retention/degraded log phrasing: " +
                               "; ".join(m.decode("utf-8", "replace") for m in missing[:4]))
            else:
                admission.ok("marker:ssdk-retention",
                             f"all {len(retention)} retention/degraded phrasings present")

    # DRV command-size layer: 033 containment marker + byte-level 055 proof.
    drv = modules.get("qca-nss-drv.ko")
    drv_patches, drv_patch_errors = drv_source_patches(source_root)
    for label, error in sorted(drv_patch_errors.items()):
        admission.fail(f"marker:drv-{label}", error)
    evidence["drv_source_patches"] = {
        label: {"file": patch.name, "sha256": sha256_bytes(patch.read_bytes())}
        for label, patch in sorted(drv_patches.items())}
    if drv is None:
        admission.fail("marker:drv-033", "qca-nss-drv.ko not found in the admitted artifact")
        admission.fail("marker:drv-055", "qca-nss-drv.ko not found in the admitted artifact")
    else:
        drv_data = drv["data"]
        if DRV_033_MARKER not in drv_data:
            admission.fail("marker:drv-033",
                           "qca-nss-drv.ko lacks the 033 connection-table containment literal")
        else:
            admission.ok("marker:drv-033",
                         "qca-nss-drv.ko contains the 033 containment literal")
        try:
            body = elf_symbol_body(drv_data, WIFILI_TX_SYMBOL)
            fingerprint = wifili_055_fingerprint(body)
        except AdmissionError as exc:
            admission.fail("marker:drv-055",
                           f"cannot prove the 055 actual-length send in the artifact: {exc}")
            fingerprint = None
        if fingerprint is not None:
            evidence["drv_055_fingerprint"] = fingerprint
            if fingerprint["constant_2096_movz_words"]:
                admission.fail("marker:drv-055",
                               "nss_wifili_tx_msg still materializes the pre-055 2096-byte "
                               "constant in words "
                               f"{fingerprint['constant_2096_movz_words']}; the artifact does "
                               "not carry the reviewed actual-length send")
            elif fingerprint["match"] is None:
                admission.fail("marker:drv-055",
                               "nss_wifili_tx_msg does not contain the reviewed "
                               "ncm->len + sizeof(struct nss_cmn_msg) > NSS_NBUF_PAYLOAD_SIZE "
                               "shape; 055 cannot be proven from the artifact bytes")
            else:
                match = fingerprint["match"]
                admission.ok("marker:drv-055",
                             "nss_wifili_tx_msg computes the message length "
                             "(ldrh/add/cmp-branch words "
                             f"{match['length_load_word']}/{match['sizeof_add_word']}/"
                             f"{match['payload_size_compare_word']}) and has no 2096-byte "
                             "constant send")

    # Symbol closure across the admitted module set.
    exports: set[str] = set()
    undefined: dict[str, set[str]] = {}
    for name, module in modules.items():
        try:
            exports |= elf_exports(module["data"])
            undefined[name] = {symbol for symbol in elf_undefined(module["data"])
                               if symbol.startswith("nss_")}
        except AdmissionError as exc:
            admission.fail(f"symbols:{name}", str(exc))
    unresolved = {name: sorted(symbols - exports) for name, symbols in undefined.items()
                  if symbols - exports}
    evidence["exports"] = len(exports)
    evidence["undefined_nss_symbols"] = {name: len(symbols) for name, symbols in undefined.items()}
    if unresolved:
        admission.fail("symbols:closure",
                       "undefined NSS symbols not exported by the admitted module set: " +
                       "; ".join(f"{name}: {symbols[:6]}" for name, symbols in sorted(unresolved.items())))
    else:
        admission.ok("symbols:closure",
                     f"all undefined nss_* symbols resolve inside the admitted module set "
                     f"({len(modules)} modules)")
    evidence["unresolved"] = unresolved
    return evidence


def check_rootfs_scripts(source_root: Path, scripts_dir: Path | None,
                         admission: Admission, required: bool) -> dict:
    if scripts_dir is None:
        if required:
            admission.fail("rootfs-scripts",
                           "release admission requires installed-script identity but no "
                           "directory was supplied")
        else:
            admission.ok("rootfs-scripts",
                         "not supplied; installed-script identity skipped (non-release run)")
        return {}
    evidence = {}
    for name, source_rel in ROOTFS_SCRIPT_SOURCES.items():
        path = scripts_dir / name
        if not path.is_file():
            admission.fail(f"rootfs-script:{name}", f"missing installed script: {path}")
            continue
        source_path = source_root / source_rel
        if not source_path.is_file():
            admission.fail(f"rootfs-script:{name}", f"locked source file missing: {source_path}")
            continue
        digest = sha256_bytes(path.read_bytes())
        source_digest = sha256_bytes(source_path.read_bytes())
        evidence[name] = {"sha256": digest, "source_sha256": source_digest}
        if digest != source_digest:
            admission.fail(f"rootfs-script:{name}",
                           f"installed script sha256 {digest} differs from locked source "
                           f"{source_digest}")
        else:
            admission.ok(f"rootfs-script:{name}", digest)
    return evidence


def load_lock(path: Path) -> dict:
    require(path.is_file(), f"build lock missing: {path}")
    lock = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        require(bool(separator and key), f"malformed build-lock line: {line[:80]}")
        require(key not in lock, f"duplicate build-lock key: {key}")
        lock[key] = value
    return lock


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kmod-dir", required=True,
                    help="offline kmod feed directory (upload/kmod) or a packages directory")
    ap.add_argument("--source-root", required=True,
                    help="locked source tree the artifact must be built from")
    ap.add_argument("--lock", help="build lock env file (enforces SOURCE_*_PKG_RELEASE)")
    ap.add_argument("--config",
                    help="AX6 .config/.config-stock used to derive the enabled clients set")
    ap.add_argument("--rootfs-scripts",
                    help="directory with installed upgrade scripts for byte identity")
    ap.add_argument("--expect-withdrawals", action="store_true",
                    help="release mode: require lock/config/rootfs-scripts and the "
                         "withdrawal-marker assertion")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    admission = Admission()
    report = {
        "schema": 1,
        "gate": "S3-08 NSS artifact admission",
        "scope": "offline kmod identity/version/vermagic/marker/symbol evidence only; "
                 "not boot, flash, hardware or runtime proof",
        "kmod_dir": args.kmod_dir,
        "source_root": args.source_root,
        "status": "PASS",
        "checks": admission.checks,
        "evidence": {},
    }
    try:
        if args.expect_withdrawals:
            require(args.lock is not None,
                    "release admission (--expect-withdrawals) requires --lock")
            require(args.config is not None,
                    "release admission (--expect-withdrawals) requires --config")
            require(args.rootfs_scripts is not None,
                    "release admission (--expect-withdrawals) requires --rootfs-scripts")
        kmod_dir = Path(args.kmod_dir)
        require(kmod_dir.is_dir(), f"kmod feed directory missing: {kmod_dir}")
        packages_dir = locate_packages_dir(kmod_dir)
        records = load_index(packages_dir)
        kernel_version, kernel_release = kernel_abi(records)
        report["evidence"]["index"] = {"records": len(records),
                                       "packages": str(packages_dir / "Packages")}
        report["evidence"]["kernel_version"] = kernel_version
        report["evidence"]["kernel_release"] = kernel_release
        source_root = Path(args.source_root)
        require(source_root.is_dir(), f"locked source tree missing: {source_root}")
        lock = load_lock(Path(args.lock)) if args.lock else None
        if lock is not None:
            report["evidence"]["lock"] = args.lock
            lock_evidence = {"source_commit": lock.get("SOURCE_COMMIT", ""),
                             "patchset_manifest_sha256":
                                 lock.get("SOURCE_PATCHSET_MANIFEST_SHA256", "")}
            report["evidence"]["lock_identity"] = lock_evidence
            if args.expect_withdrawals:
                require(re.fullmatch(r"[0-9a-f]{40}",
                                     lock_evidence["source_commit"]) is not None,
                        "release admission requires a full 40-hex build-lock SOURCE_COMMIT")
                require(re.fullmatch(r"[0-9a-f]{64}",
                                     lock_evidence["patchset_manifest_sha256"]) is not None,
                        "release admission requires a 64-hex build-lock "
                        "SOURCE_PATCHSET_MANIFEST_SHA256")

        module_owners: dict[str, str] = {}
        modules: dict[str, dict] = {}
        packages_evidence = {}
        core_expected = core_expected_modules(source_root)
        for package, (package_dir, lock_key) in PACKAGE_MAKEFILES.items():
            expected = source_expectation(package, source_root, lock, admission,
                                          kernel_release, lock_key, package_dir)
            record = records.get(package)
            if record is None:
                admission.fail(f"package:{package}",
                               f"required core package missing from the kmod index: {package}")
                continue
            result = admit_ipk(package, record, packages_dir, source_root, admission,
                               expected, core_expected[package], package_dir,
                               kernel_version, kernel_release, module_owners)
            if result is not None:
                packages_evidence[package] = {
                    "version": result["version"], "sha256": result["sha256"],
                    "bytes": result["bytes"], "modules": sorted(result["modules"])}
                register_modules(package, result["modules"], modules, admission)
        report["evidence"]["packages"] = packages_evidence
        if args.config:
            clients_evidence = check_client_inventory(
                records, packages_dir, source_root, Path(args.config), lock, admission,
                kernel_version, kernel_release, module_owners)
            client_payloads = clients_evidence.pop("payloads", {})
            report["evidence"]["clients"] = clients_evidence
            for package, payload in sorted(client_payloads.items()):
                register_modules(package, payload, modules, admission)
        report["evidence"]["modules"] = check_modules(modules, source_root, admission,
                                                     kernel_release)
        report["evidence"]["rootfs_scripts"] = check_rootfs_scripts(
            source_root, Path(args.rootfs_scripts) if args.rootfs_scripts else None,
            admission, bool(args.expect_withdrawals))
        report["evidence"]["expect_withdrawals"] = bool(args.expect_withdrawals)
        if args.expect_withdrawals:
            if "qca-ssdk.ko" not in report["evidence"]["modules"].get("modules", {}):
                admission.fail("expect-withdrawals",
                               "SSDK module not admitted; cannot prove withdrawal state")
    except (AdmissionError, OSError, ValueError, KeyError, struct.error, tarfile.TarError,
            gzip.BadGzipFile, EOFError) as exc:
        admission.fail("gate", f"artifact admission failed: {exc}")
    except Exception as exc:  # fail closed on unexpected checker errors
        admission.fail("gate-internal", f"artifact admission checker error: {exc}")
    report["status"] = admission.status
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "output": str(output)}, indent=2))
    if report["status"] != "PASS":
        print("ARTIFACT ADMISSION FAILED:", file=sys.stderr)
        for check in report["checks"]:
            if check["status"] == "FAIL":
                print(f"  - {check['name']}: {check['detail']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
