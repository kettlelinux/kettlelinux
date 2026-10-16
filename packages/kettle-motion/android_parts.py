# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a device's own Android partitions, read-only (kettle-motion-setup, kettle-adsp-firmware)."""
import contextlib
import os
import struct
import subprocess
import tempfile
import time

PARTS = "/dev/disk/by-partlabel"


def super_partitions(path):
    """{name: [(offset, size)]} from an Android super partition's (LP) metadata."""
    with open(path, "rb") as f:
        f.seek(4096)
        if struct.unpack("<I", f.read(4))[0] != 0x616C4467:
            raise ValueError("no LP geometry")
        f.seek(4096 * 3)
        h = f.read(256)
        magic, _, _, hsz = struct.unpack("<IHHI", h[:12])
        if magic != 0x414C5030:
            raise ValueError("no LP metadata")
        tables_size = struct.unpack("<I", h[44:48])[0]
        desc = [struct.unpack("<III", h[80 + i * 12:92 + i * 12]) for i in range(2)]
        f.seek(4096 * 3 + hsz)
        t = f.read(tables_size)
    (po, pn, ps), (eo, en, es) = desc
    extents = [struct.unpack("<QIQI", t[eo + i * es:eo + i * es + 24]) for i in range(en)]
    parts = {}
    for i in range(pn):
        e = t[po + i * ps:po + (i + 1) * ps]
        name = e[:36].rstrip(b"\0").decode()
        first, count = struct.unpack("<II", e[40:48])
        # (num_sectors, target_type, target_data, target_source); type 0 is linear
        parts[name] = [(x[2] * 512, x[0] * 512) for x in extents[first:first + count] if x[1] == 0]
    return parts


@contextlib.contextmanager
def mounted(dev, offset=0, size=0):
    """dev (or a range of it) mounted read-only, without replaying a journal."""
    args = ["losetup", "-r", "-f", "--show"]
    if size:
        args += ["-o", str(offset), "--sizelimit", str(size)]
    loop = subprocess.run(args + [dev], check=True, capture_output=True, text=True).stdout.strip()
    # the calling service's RuntimeDirectory
    mnt = tempfile.mkdtemp(prefix="mnt-", dir=os.environ.get("RUNTIME_DIRECTORY", "/run/kettle-motion"))
    try:
        if subprocess.run(["mount", "-o", "ro,noload", loop, mnt], capture_output=True).returncode:
            subprocess.run(["mount", "-o", "ro", loop, mnt], check=True)
        try:
            yield mnt
        finally:
            for _ in range(10):
                if subprocess.run(["umount", mnt], capture_output=True).returncode == 0:
                    break
                time.sleep(0.5)
    finally:
        subprocess.run(["losetup", "-d", loop], capture_output=True)
        with contextlib.suppress(OSError):
            os.rmdir(mnt)
