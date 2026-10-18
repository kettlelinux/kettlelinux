"""Shared test setup: a temporary home, media dir and cache, a systems.json based on the real one
with BIOS md5s the tests can produce, and builders for synthetic ROM and disc images."""
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

FAKE_BIOS = b"KETTLE-TEST-PSX-BIOS" * 1000
FAKE_SEGACD = b"KETTLE-TEST-SEGACD" * 500


def md5(b):
    return hashlib.md5(b).hexdigest()


class Env(unittest.TestCase):
    """Each test gets its own home (~/Emulation), media dir (cards) and cache."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kettle-emu-test-")
        self.home = os.path.join(self.tmp, "home", "Emulation")
        self.media = os.path.join(self.tmp, "media")
        os.makedirs(self.home)
        os.makedirs(self.media)
        with open(os.path.join(PKG, "systems.json")) as f:
            data = json.load(f)
        for b in data["systems"]["psx"]["bios"]:
            if b["file"] == "scph5501.bin":
                b["md5"] = [md5(FAKE_BIOS)]
        for b in data["systems"]["segacd"]["bios"]:
            if b["file"] == "bios_CD_U.bin":
                b["md5"] = [md5(FAKE_SEGACD)]
        self.systems = os.path.join(self.tmp, "systems.json")
        with open(self.systems, "w") as f:
            json.dump(data, f)
        self._env = {k: os.environ.get(k) for k in
                     ("KETTLE_EMU_SYSTEMS", "KETTLE_EMU_HOME", "KETTLE_EMU_MEDIA", "XDG_CACHE_HOME")}
        os.environ.update(KETTLE_EMU_SYSTEMS=self.systems, KETTLE_EMU_HOME=self.home,
                          KETTLE_EMU_MEDIA=self.media, XDG_CACHE_HOME=os.path.join(self.tmp, "cache"))

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, data, root=None):
        p = os.path.join(root or self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb" if isinstance(data, bytes) else "w") as f:
            f.write(data)
        return p


# --- image builders ---------------------------------------------------------------------------

SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


def raw_disc(sectors, count=24, mode=2):
    """A raw (2352-byte sector) image; sectors: {lba: user data}."""
    out = bytearray()
    for lba in range(count):
        data = sectors.get(lba, b"").ljust(2048, b"\0")[:2048]
        head = SYNC + b"\0\0\0" + bytes([mode])
        if mode == 2:
            sec = head + b"\0" * 8 + data + b"\0" * (2352 - 24 - 2048)
        else:
            sec = head + data + b"\0" * (2352 - 16 - 2048)
        out += sec
    return bytes(out)


def cooked_disc(sectors, count=24):
    return b"".join(sectors.get(i, b"").ljust(2048, b"\0")[:2048] for i in range(count))


def pvd(sysid, root_extent=18, files=None):
    """Sectors for an ISO 9660 volume: PVD at 16, a root directory at 18 listing `files`
    ({name: content}), file contents from 19."""
    p = bytearray(2048)
    p[0] = 1
    p[1:6] = b"CD001"
    p[8:40] = sysid.encode().ljust(32)
    files = files or {}
    rec = bytearray(34)
    rec[0] = 34
    struct.pack_into("<I", rec, 2, root_extent)
    struct.pack_into("<I", rec, 10, 2048)
    p[156:190] = rec
    sectors = {16: bytes(p)}
    d = bytearray()
    lba = root_extent + 1
    for name, content in files.items():
        n = (name + ";1").encode()
        r = bytearray(33 + len(n) + (1 - len(n) % 2))
        r[0] = len(r)
        struct.pack_into("<I", r, 2, lba)
        struct.pack_into("<I", r, 10, len(content))
        r[32] = len(n)
        r[33:33 + len(n)] = n
        d += r
        sectors[lba] = content
        lba += 1
    sectors[root_extent] = bytes(d)
    return sectors


def chd(meta):
    """A CHD v5 header with metadata entries [(tag, text)]."""
    head = bytearray(124)
    head[:8] = b"MComprHD"
    struct.pack_into(">I", head, 8, 124)
    struct.pack_into(">I", head, 12, 5)
    out = bytearray(head)
    off = 124
    struct.pack_into(">Q", out, 48, off)
    for i, (tag, text) in enumerate(meta):
        data = text.encode() + b"\0"
        nxt = off + 16 + len(data) if i + 1 < len(meta) else 0
        out += tag + struct.pack(">I", len(data)) + struct.pack(">Q", nxt) + data
        off = nxt
    return bytes(out)
