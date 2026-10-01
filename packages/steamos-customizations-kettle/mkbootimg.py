#!/usr/bin/env python3
"""Minimal Android boot image v0 writer (the format ROCKNIX's ABL loads as \\KERNEL).

Layout matches AOSP mkbootimg --header_version 0 with base 0x10000000 and all
offsets 0, as used by ROCKNIX/pocknix for SM8550: header page, then kernel
(gzip(Image) + appended DTBs) and ramdisk, each padded to page_size.
"""
import argparse
import hashlib
import struct
import sys

BOOT_MAGIC = b"ANDROID!"
BASE = 0x10000000


def pad(data: bytes, page: int) -> bytes:
    return data + b"\0" * ((page - len(data) % page) % page)


def os_version(ver: str, patch: str) -> int:
    a, b, c = (int(x) for x in ver.split("."))
    y, m = (int(x) for x in patch.split("-"))
    return ((a << 14 | b << 7 | c) << 11) | ((y - 2000) << 4 | m)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--ramdisk", help="omitted: none (a bootloader, e.g. U-Boot)")
    ap.add_argument("--cmdline", default="")
    ap.add_argument("--pagesize", type=int, default=2048)
    ap.add_argument("--kernel_offset", type=lambda v: int(v, 0), default=0)
    ap.add_argument("--os_version", default="12.0.0")
    ap.add_argument("--os_patch_level", default="2026-01")
    ap.add_argument("-o", "--output", required=True)
    a = ap.parse_args()

    kernel = open(a.kernel, "rb").read()
    ramdisk = open(a.ramdisk, "rb").read() if a.ramdisk else b""
    cmdline = a.cmdline.encode()
    if len(cmdline) > 512 + 1024 - 1:
        sys.exit("cmdline too long")
    main_cmd, extra_cmd = cmdline[:511], cmdline[511:]

    sha = hashlib.sha1()
    for blob in (kernel, ramdisk, b""):  # kernel, ramdisk, second
        sha.update(blob)
        sha.update(struct.pack("<I", len(blob)))

    hdr = struct.pack(
        "<8s10I16s512s32s1024s",
        BOOT_MAGIC,
        len(kernel), BASE + a.kernel_offset,  # kernel size / addr
        len(ramdisk), BASE,         # ramdisk size / addr
        0, 0,                       # second size / addr (unused, AOSP writes 0)
        BASE,                       # tags addr
        a.pagesize,
        0,                          # header_version 0
        os_version(a.os_version, a.os_patch_level),
        b"",                        # board name
        main_cmd,
        sha.digest(),
        extra_cmd,
    )
    with open(a.output, "wb") as f:
        f.write(pad(hdr, a.pagesize))
        f.write(pad(kernel, a.pagesize))
        f.write(pad(ramdisk, a.pagesize))
    return 0


if __name__ == "__main__":
    sys.exit(main())
