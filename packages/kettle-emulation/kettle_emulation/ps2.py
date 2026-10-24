"""PS2 BIOS dumps, recognised by their contents as PCSX2 (and so ARMSX2's libretro core) does
(pcsx2/ps2/BiosTools.cpp, LoadBiosVersion and the auto-pick): every console's dump differs, so
there are no md5s to list. A dump is 4 to 8 MiB and holds a ROM directory: 16-byte entries
(a 10-byte name, a 2-byte extinfo size, a 4-byte file size) starting at a 16-byte boundary with
one named RESET, and among them ROMVER, whose file says the version and the zone. An arcade
board's BIOS (zone "TZ", COH-H) runs no console game and doesn't count.

ARMSX2's core takes any such file from <RetroArch's system folder>/pcsx2/bios, whatever its name
(Main.cpp); RetroArch's system folder is Emulation/bios.
"""
import os
import struct

MIN_SIZE = 4 << 20
MAX_SIZE = 8 << 20
ENTRY = 16


def _name(entry):
    return entry[:10].split(b"\0", 1)[0]


def bios_info(path):
    """{"version": "2.30", "zone": "A" ...} of a console PS2 BIOS dump, or None."""
    try:
        if not MIN_SIZE <= os.path.getsize(path) <= MAX_SIZE:
            return None
        with open(path, "rb") as f:
            data = f.read(MAX_SIZE + 1)
    except OSError:
        return None
    if not MIN_SIZE <= len(data) <= MAX_SIZE:
        return None
    start = data.find(b"RESET\0\0\0\0\0")
    while start != -1 and start % ENTRY:  # on an entry boundary, as PCSX2 reads them
        start = data.find(b"RESET\0\0\0\0\0", start + 1)
    if start == -1:
        return None
    file_off, romver = 0, None
    for off in range(start, len(data) - ENTRY + 1, ENTRY):
        entry = data[off:off + ENTRY]
        name = _name(entry)
        if not name or len(name) == 10:
            break
        size = struct.unpack_from("<I", entry, 12)[0]
        if name == b"ROMVER":
            romver = data[file_off:file_off + 14]
        file_off += size if size % 0x10 == 0 else (size + 0x10) & 0xfffffff0
    if not romver or len(romver) < 14:
        return None
    if romver[4:6] == b"TZ":  # an arcade board's (COH-H)
        return None
    try:
        text = romver.decode("ascii")
        major = int(text[0:2])
    except (UnicodeDecodeError, ValueError):
        return None
    return {"version": f"{major}.{text[2:4]}", "zone": text[4], "date": text[6:14]}


def is_bios(path):
    return bios_info(path) is not None
