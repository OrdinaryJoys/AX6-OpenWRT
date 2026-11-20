#!/usr/bin/env python3
"""
Validate AX6 firmware image formats.

This verifies standard/complete packaging, not just filenames:
  * sysupgrade.bin: standard sysupgrade tar with CONTROL/kernel/root
  * factory.ubi:   valid UBI image with kernel/rootfs/rootfs_data volumes
  * initramfs ITB: valid FIT with kernel + device tree + configuration
  * kernel/rootfs payload identity between sysupgrade and factory UBI
  * optional DTB identity check

Exit 0 only if all checks pass. Emits a JSON report.
"""
from __future__ import annotations

import argparse
import hashlib
import zlib
import io
import json
import struct
import sys
import tarfile
from pathlib import Path

UBI_EC_MAGIC = 0x55424923  # "UBI#"
UBI_VID_MAGIC = 0x55424921  # "UBI!"
FDT_MAGIC = 0xD00DFEED
SQUASHFS_MAGIC = b"hsqs"

class CheckError(Exception):
    pass

def require(cond: bool, msg: str) -> None:
    if not cond:
        raise CheckError(msg)

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def ubi_crc(data: bytes, init: int = 0xFFFFFFFF) -> int:
    """UBI/Linux CRC32: reflected poly, init 0xFFFFFFFF, no final XOR."""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
    return crc & 0xFFFFFFFF

def parse_fdt(blob: bytes) -> dict:
    """Return {path: {prop: bytes}} for a flattened device tree."""
    need = 40
    require(len(blob) >= need, "FDT too short")
    magic, total, off_struct, off_strings, off_rsv, ver, last, cpuid, size_str, size_struct = struct.unpack(">10I", blob[:40])
    require(magic == FDT_MAGIC, "FDT magic mismatch")
    require(total <= len(blob), "FDT total size exceeds file")
    require(off_struct + size_struct <= len(blob), "FDT structure out of range")

    def string_at(off: int) -> str:
        end = blob.index(b"\0", off_strings + off)
        return blob[off_strings + off:end].decode("utf-8", "replace")

    pos = off_struct
    stack: list[str] = []
    nodes: dict[str, dict[str, bytes]] = {}
    while True:
        tok, = struct.unpack(">I", blob[pos:pos + 4])
        pos += 4
        if tok == 1:
            end = blob.index(b"\0", pos)
            name = blob[pos:end].decode("ascii", "replace")
            pos = (end + 4) & ~3
            stack.append(name)
            nodes["/" + "/".join(x for x in stack if x)] = {}
        elif tok == 2:
            require(stack, "FDT node stack underflow")
            stack.pop()
        elif tok == 3:
            ln, nameoff = struct.unpack(">II", blob[pos:pos + 8])
            pos += 8
            value = blob[pos:pos + ln]
            pos = (pos + ln + 3) & ~3
            if stack:
                nodes["/" + "/".join(x for x in stack if x)][string_at(nameoff)] = value
        elif tok == 4:
            continue
        elif tok == 9:
            break
        else:
            raise CheckError(f"unknown FDT token {tok}")
    return nodes

def fdt_str(nodes: dict, path: str, prop: str) -> str:
    raw = nodes.get(path, {}).get(prop)
    if raw is None:
        return ""
    return raw.rstrip(b"\0").decode("utf-8", "replace")

def parse_sysupgrade(path: Path) -> dict:
    data = path.read_bytes()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        members = {m.name: m for m in tar.getmembers()}
        root = "sysupgrade-redmi_ax6-stock"
        require(root in members and members[root].isdir(), "sysupgrade top-level dir missing")
        required = [f"{root}/CONTROL", f"{root}/kernel", f"{root}/root"]
        require(all(n in members for n in required), "sysupgrade must contain CONTROL/kernel/root")
        control = tar.extractfile(members[f"{root}/CONTROL"]).read().decode("utf-8", "replace")
        kernel = tar.extractfile(members[f"{root}/kernel"]).read()
        rootfs = tar.extractfile(members[f"{root}/root"]).read()
    board = ""
    for line in control.splitlines():
        if line.startswith("BOARD="):
            board = line.split("=", 1)[1]
    require(board == "redmi_ax6-stock", f"unexpected sysupgrade BOARD {board!r}")
    require(kernel[:4] == b"\xd0\x0d\xfe\xed", "sysupgrade kernel is not FIT/uImage")
    require(rootfs[:4] == SQUASHFS_MAGIC, "sysupgrade root is not squashfs")
    rootfs_used, = struct.unpack_from("<Q", rootfs, 40)
    require(0 < rootfs_used <= len(rootfs), "sysupgrade rootfs bytes_used invalid")
    require(all(b == 0 for b in rootfs[rootfs_used:]), "sysupgrade rootfs has non-zero padding")
    rootfs = rootfs[:rootfs_used]
    meta_marker = b'"metadata_version"'
    meta_pos = data.rfind(meta_marker)
    require(meta_pos >= 0, "sysupgrade appended metadata missing")
    meta_start = data.rfind(b"{", 0, meta_pos)
    require(meta_start >= 0, "sysupgrade metadata opening brace missing")
    meta_pos = meta_start
    meta_text = data[meta_pos:].decode("utf-8", "replace")
    try:
        metadata, _ = json.JSONDecoder().raw_decode(meta_text)
    except json.JSONDecodeError as exc:
        raise CheckError(f"sysupgrade metadata JSON invalid: {exc}")
    require(metadata.get("metadata_version") == "1.1", "sysupgrade metadata_version mismatch")
    supported = metadata.get("supported_devices") or []
    require("redmi,ax6-stock" in supported, "sysupgrade supported_devices missing redmi,ax6-stock")
    return {
        "file": path.name,
        "bytes": len(data),
        "sha256": sha256(data),
        "board": board,
        "kernel_bytes": len(kernel),
        "kernel_sha256": sha256(kernel),
        "rootfs_bytes": len(rootfs),
        "rootfs_sha256": sha256(rootfs),
        "metadata_version": metadata.get("metadata_version"),
        "compat_version": metadata.get("compat_version"),
        "supported_devices": supported,
    }

def _read_ubi_headers(data: bytes, peb_size: int) -> dict:
    """Parse UBI headers and volume table. Assumes 4K VID/data offset for AX6."""
    require(data[:4] == UBI_EC_MAGIC.to_bytes(4, "big"), "factory UBI magic missing")
    ec0 = parse_ec(data, 0)
    vid_off, data_off = ec0["vid_hdr_offset"], ec0["data_offset"]
    require(vid_off < peb_size and data_off <= peb_size, "UBI header offsets invalid")

    vols: dict[int, list[dict]] = {}
    image_seq = ec0["image_seq"]
    for pebno in range(len(data) // peb_size):
        ec = parse_ec(data, pebno * peb_size)
        require(ec["magic"] == UBI_EC_MAGIC, f"UBI EC magic missing at PEB {pebno}")
        require(ec["image_seq"] == image_seq, "UBI image sequence mismatch")
        vh = parse_vid(data, pebno * peb_size + vid_off)
        if not vh:
            continue
        vh["peb"] = pebno
        vols.setdefault(vh["vol_id"], []).append(vh)

    layout_id = 0x7FFFEFFF
    require(layout_id in vols and vols[layout_id], "UBI layout volume missing")
    layout = sorted(vols[layout_id], key=lambda v: v["lnum"])[0]
    table_off = layout["peb"] * peb_size + data_off
    table = {}
    for i in range(128):
        base = table_off + i * 172
        if base + 172 > len(data):
            break
        reserved, alignment, data_pad, vol_type, upd_marker, name_len = struct.unpack_from(">IIIBBH", data, base)
        name = data[base + 16:base + 16 + name_len].decode("utf-8", "replace")
        if reserved or name:
            stored_crc, = struct.unpack_from(">I", data, base + 168)
            require(ubi_crc(data[base:base + 168]) == stored_crc,
                    f"UBI volume table record {i} CRC mismatch")
            flags = data[base + 144]
            table[i] = {
                "reserved_pebs": reserved,
                "alignment": alignment,
                "data_pad": data_pad,
                "vol_type": vol_type,
                "upd_marker": upd_marker,
                "name": name,
                "flags": flags,
            }
    return {
        "peb_size": peb_size,
        "vid_hdr_offset": vid_off,
        "data_offset": data_off,
        "image_seq": image_seq,
        "volumes": {k: {"table": table.get(k), "pebs": len(v)} for k, v in vols.items() if k != layout_id},
        "table": table,
        "headers": vols,
        "data": data,
        "data_off": data_off,
    }

def parse_ec(data: bytes, off: int) -> dict:
    require(off + 64 <= len(data), "UBI EC header truncated")
    magic, = struct.unpack_from(">I", data, off)
    version = data[off + 4]
    ec, = struct.unpack_from(">Q", data, off + 8)
    vid, = struct.unpack_from(">I", data, off + 16)
    doff, = struct.unpack_from(">I", data, off + 20)
    seq, = struct.unpack_from(">I", data, off + 24)
    stored, = struct.unpack_from(">I", data, off + 60)
    require(magic == UBI_EC_MAGIC, f"UBI EC magic missing at {off:#x}")
    require(ubi_crc(data[off:off + 60]) == stored,
            f"UBI EC header CRC mismatch at {off:#x}")
    return {"magic": magic, "version": version, "ec": ec, "vid_hdr_offset": vid,
            "data_offset": doff, "image_seq": seq, "hdr_crc": stored}

def parse_vid(data: bytes, off: int) -> dict | None:
    require(off + 64 <= len(data), "UBI VID header truncated")
    magic, = struct.unpack_from(">I", data, off)
    if magic != UBI_VID_MAGIC:
        return None
    version = data[off + 4]
    vol_type = data[off + 5]
    copy_flag = data[off + 6]
    compat = data[off + 7]
    vol_id, = struct.unpack_from(">I", data, off + 8)
    lnum, = struct.unpack_from(">I", data, off + 12)
    # ubi-media.h: padding1[4] at +16, then data_size(+20), used_ebs(+24),
    # data_pad(+28), data_crc(+32), padding2[4] at +36, sqnum(+40), hdr_crc(+60)
    data_size, used_ebs, data_pad, data_crc = struct.unpack_from(">IIII", data, off + 20)
    sqnum, = struct.unpack_from(">Q", data, off + 40)
    stored, = struct.unpack_from(">I", data, off + 60)
    require(ubi_crc(data[off:off + 60]) == stored,
            f"UBI VID header CRC mismatch at {off:#x}")
    return {"magic": magic, "version": version, "vol_type": vol_type,
            "copy_flag": copy_flag, "compat": compat, "vol_id": vol_id,
            "lnum": lnum, "data_size": data_size, "used_ebs": used_ebs,
            "data_pad": data_pad, "data_crc": data_crc, "sqnum": sqnum}

def volume_payload(data: bytes, ubi: dict, vol_id: int) -> bytes:
    """Return the full data capacity of a UBI volume (all data PEBs)."""
    headers = sorted(ubi["headers"].get(vol_id, []), key=lambda v: v["lnum"])
    require(headers, f"UBI volume {vol_id} has no PEBs")
    out = bytearray()
    for v in headers:
        start = v["peb"] * ubi["peb_size"] + ubi["data_off"]
        out += data[start:start + ubi["peb_size"] - ubi["data_off"]]
    return bytes(out)

def trim_ubi_kernel(payload: bytes) -> bytes:
    require(payload[:4] == b"\xd0\x0d\xfe\xed", "UBI kernel is not FIT")
    total, = struct.unpack_from(">I", payload, 4)
    require(total <= len(payload), "UBI kernel FIT total exceeds volume capacity")
    return payload[:total]

def trim_ubi_rootfs(payload: bytes) -> bytes:
    require(payload[:4] == SQUASHFS_MAGIC, "UBI rootfs is not squashfs")
    # SquashFS superblock: bytes_used at offset 40 (little endian).
    bytes_used, = struct.unpack_from("<Q", payload, 40)
    require(0 < bytes_used <= len(payload), "UBI rootfs bytes_used exceeds volume capacity")
    return payload[:bytes_used]

def parse_ubi(path: Path) -> dict:
    data = path.read_bytes()
    # AX6 NAND PEB = 128 KiB; UBI EC header supplies offsets.
    ubi = _read_ubi_headers(data, 128 * 1024)
    table = ubi["table"]
    names = [v["name"] for v in table.values()]
    require("kernel" in names, "factory UBI missing kernel volume")
    require("rootfs" in names, "factory UBI missing rootfs volume")
    require("rootfs_data" in names, "factory UBI missing rootfs_data volume")
    vol_id = {v["name"]: k for k, v in table.items()}
    kernel = trim_ubi_kernel(volume_payload(data, ubi, vol_id["kernel"]))
    rootfs = trim_ubi_rootfs(volume_payload(data, ubi, vol_id["rootfs"]))
    return {
        "file": path.name,
        "bytes": len(data),
        "sha256": sha256(data),
        "peb_size": ubi["peb_size"],
        "image_seq": ubi["image_seq"],
        "volumes": [{"name": v["name"], "reserved_pebs": v["reserved_pebs"]} for v in table.values() if v["name"]],
        "kernel_bytes": len(kernel),
        "kernel_sha256": sha256(kernel),
        "rootfs_bytes": len(rootfs),
        "rootfs_sha256": sha256(rootfs),
    }

def parse_itb(path: Path) -> dict:
    data = path.read_bytes()
    require(data[:4] == b"\xd0\x0d\xfe\xed", "initramfs is not a FIT/DTB")
    nodes = parse_fdt(data)
    kernel = nodes.get("/images/kernel-1", {})
    fdt = nodes.get("/images/fdt-1", {})
    require(kernel.get("type", b"").rstrip(b"\0") == b"kernel", "FIT kernel-1 missing/type mismatch")
    require(fdt.get("type", b"").rstrip(b"\0") == b"flat_dt", "FIT fdt-1 missing/type mismatch")
    require("data" in kernel and "data" in fdt, "FIT image data missing")
    fdt_data = fdt["data"]
    require(fdt_data[:4] == b"\xd0\x0d\xfe\xed", "FIT embedded DTB is invalid")
    default = fdt_str(nodes, "/configurations", "default")
    require(default.startswith("config@"), "FIT default configuration missing")

    def verify_hashes(node_path: str, node: dict, payload: bytes) -> None:
        checked = 0
        for path, child in nodes.items():
            if not path.startswith(node_path + "/hash-"):
                continue
            alg = fdt_str(nodes, path, "algo")
            digest = child.get("value")
            require(digest is not None, f"FIT {path} missing value")
            if alg == "crc32":
                expected = (zlib.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big")
            elif alg == "sha1":
                expected = hashlib.sha1(payload).digest()
            else:
                require(False, f"FIT unsupported hash algorithm {alg!r}")
            require(digest == expected, f"FIT {path} hash mismatch")
            checked += 1
        require(checked > 0, f"FIT {node_path} has no hash node")
        if len(node.get("data", b"")) == 0:
            raise CheckError(f"FIT {node_path} data missing")

    verify_hashes("/images/kernel-1", kernel, kernel["data"])
    verify_hashes("/images/fdt-1", fdt, fdt["data"])
    return {
        "file": path.name,
        "bytes": len(data),
        "sha256": sha256(data),
        "description": fdt_str(nodes, "/", "description"),
        "default_config": default,
        "kernel_bytes": len(kernel["data"]),
        "fdt_bytes": len(fdt_data),
        "fdt_sha256": sha256(fdt_data),
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sysupgrade", required=True)
    ap.add_argument("--factory-ubi", required=True)
    ap.add_argument("--initramfs-itb", required=True)
    ap.add_argument("--compiled-dtb")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    sysu = parse_sysupgrade(Path(args.sysupgrade))
    ubi = parse_ubi(Path(args.factory_ubi))
    itb = parse_itb(Path(args.initramfs_itb))

    require(sysu["kernel_sha256"] == ubi["kernel_sha256"], "sysupgrade vs factory kernel mismatch")
    require(sysu["rootfs_sha256"] == ubi["rootfs_sha256"], "sysupgrade vs factory rootfs mismatch")

    if args.compiled_dtb:
        dtb = Path(args.compiled_dtb).read_bytes()
        require(dtb[:4] == b"\xd0\x0d\xfe\xed", "compiled DTB magic mismatch")
        require(itb["fdt_sha256"] == sha256(dtb), "initramfs FDT differs from compiled DTB")

    report = {
        "status": "PASS",
        "sysupgrade": sysu,
        "factory_ubi": ubi,
        "initramfs_itb": itb,
        "formats": ["sysupgrade.bin", "factory.ubi", "initramfs-uImage.itb"],
        "standard_checks": [
            "sysupgrade tar CONTROL/kernel/root",
            "factory UBI volume table kernel/rootfs/rootfs_data",
            "factory payload magic + identity with sysupgrade",
            "FIT kernel/fdt/default configuration",
        ],
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "output": str(out)}, indent=2))
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except CheckError as exc:
        print(f"FORMAT CHECK FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
