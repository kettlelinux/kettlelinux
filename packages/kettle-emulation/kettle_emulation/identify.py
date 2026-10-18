"""Which system a ROM is for. The extension narrows it down; where systems share one (.bin, .iso,
.cue, .chd, .zip...) the file's header decides, and a folder named after a system (psx/, gc/...)
breaks the remaining ties. Only systems in systems.json are ever returned.

identify(path, folder_hint) -> Match or None. Confidence: 1.0 the header proves it, 0.95 the
folder agrees with the extension, 0.9 only one system takes the extension, lower for guesses
(by size, by a CHD's track layout). The importer sorts at 0.6 and above and leaves the rest
in inbox/unsorted for the plugin to ask about.
"""
import os
import re
import struct
import subprocess
import zipfile
import zlib
from collections import namedtuple

from . import systems

SORT_AT = 0.6

# system: the system id; reason: why, for logs and the plugin; extract: an archive whose
# contents are the game (unpack it); refs: the files a .cue/.gdi/.m3u points to (moved with it);
# needs_cue: a bare disc .bin the system only loads through a .cue (the importer writes one)
Match = namedtuple("Match", "system confidence reason extract refs needs_cue",
                   defaults=(False, (), False))

SYNC = b"\x00" + b"\xff" * 10 + b"\x00"
GC_MAGIC = 0xC2339F3D   # big endian at 0x1C of a GameCube disc
WII_MAGIC = 0x5D1C9EA3  # big endian at 0x18 of a Wii disc
A2600_SIZES = {2048, 4096, 6144, 8192, 10240, 12288, 16384, 24576, 28672, 32768, 65536}
ARCHIVES = {"zip", "7z"}
CHIP_MAX = 1 << 20  # a .bin or .rom in an archive smaller than this is a chip, not a disc
DOS_EXES = {"exe", "com", "bat"}
# files in an archive that don't count as its contents
JUNK_EXTS = {"txt", "nfo", "diz", "url", "jpg", "jpeg", "png", "pdf", "htm", "html", "md", "sfv"}


def _known(sid):
    return sid if sid in systems.systems() else None


def _match(sid, conf, reason, **kw):
    sid = _known(sid)
    return Match(sid, conf, reason, **kw) if sid else None


# --- reading disc images ---------------------------------------------------------------------

class Disc:
    """The 2048-byte user data of a disc image's sectors: a cooked ISO (2048 bytes a sector) or a
    raw one (2352: mode 1 data at 16, mode 2 form 1 at 24), from `base` in the file."""

    def __init__(self, f, base=0):
        self.f, self.base = f, base
        self.size, self.off = 2048, 0
        head = self._read(base, 16)
        if head[:12] == SYNC:
            self.size = 2352
            # the mode byte of the PVD sector; sector 0 of some discs is an odd one out
            mode = self._read(base + 16 * 2352 + 15, 1) or head[15:16]
            self.off = 24 if mode == b"\x02" else 16
        self.raw = self.size == 2352

    def _read(self, pos, n):
        try:
            self.f.seek(pos)
            return self.f.read(n)
        except (OSError, ValueError):
            return b""

    def sector(self, lba):
        return self._read(self.base + lba * self.size + self.off, 2048)

    def iso_file(self, name):
        """The first sector of a file in the ISO 9660 root directory, or None."""
        pvd = self.sector(16)
        if pvd[1:6] != b"CD001":
            return None
        rec = pvd[156:190]
        extent, length = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
        want = name.upper().encode()
        for i in range(min((length + 2047) // 2048, 16)):
            data, pos = self.sector(extent + i), 0
            while pos < len(data):
                n = data[pos]
                if n == 0:
                    break
                fname = data[pos + 33:pos + 33 + data[pos + 32]].upper()
                if fname.split(b";")[0] == want:
                    return self.sector(struct.unpack_from("<I", data, pos + 2)[0])
                pos += n
        return None


def disc_system(f, base=0):
    """The system of a CD/DVD image's data track, or None."""
    d = Disc(f, base)
    s0 = d.sector(0)
    if s0.startswith(b"SEGADISCSYSTEM"):
        return _match("segacd", 1.0, "Sega CD disc header")
    if s0.startswith(b"SEGA SEGAKATANA"):
        return _match("dreamcast", 1.0, "Dreamcast disc header")
    if s0.startswith(b"SEGA SEGASATURN"):
        return _match("saturn", 1.0, "Saturn disc header")
    for lba in (0, 1, 2):
        if b"PC Engine CD-ROM SYSTEM" in d.sector(lba):
            return _match("pcenginecd", 1.0, "PC Engine CD boot sector")
    pvd = d.sector(16)
    if pvd[1:6] == b"CD001":
        sysid = pvd[8:40].strip()
        if sysid.startswith(b"PSP GAME"):
            return _match("psp", 1.0, "PSP UMD image")
        if sysid.startswith(b"PLAYSTATION"):
            cnf = d.iso_file("SYSTEM.CNF") or b""
            if b"BOOT2" in cnf:
                return None  # PlayStation 2: no emulator for it
            return _match("psx", 1.0, "PlayStation disc")
    if b"Sony Computer Entertainment" in d.sector(4):
        return _match("psx", 1.0, "PlayStation licence sector")
    return None


def _u32be(b, off):
    return struct.unpack_from(">I", b, off)[0] if len(b) >= off + 4 else None


def _u32le(b, off):
    return struct.unpack_from("<I", b, off)[0] if len(b) >= off + 4 else None


def nintendo_disc(head):
    """GameCube or Wii from a plain disc header."""
    if _u32be(head, 0x1C) == GC_MAGIC:
        return _match("gc", 1.0, "GameCube disc header")
    if _u32be(head, 0x18) == WII_MAGIC:
        return _match("wii", 1.0, "Wii disc header")
    return None


def _image(f, ext):
    """An optical image (.iso and the compressed GameCube/Wii/PSP formats)."""
    f.seek(0)
    head = f.read(0x100)
    m = nintendo_disc(head)
    if m:
        return m
    if head[:4] == b"WBFS":
        return _match("wii", 1.0, "WBFS image")
    if head[:4] in (b"RVZ\x01", b"WIA\x01"):
        kind = _u32be(head, 0x48)
        return {1: _match("gc", 1.0, "GameCube RVZ/WIA"), 2: _match("wii", 1.0, "Wii RVZ/WIA")}.get(kind)
    if _u32le(head, 0) == 0xB10BC001:
        kind = _u32le(head, 4)
        return {0: _match("gc", 1.0, "GameCube GCZ"), 1: _match("wii", 1.0, "Wii GCZ")}.get(kind)
    if head[:4] in (b"CISO", b"ZISO"):
        # PSP CSO: header size 0x18 (or 0) at 4; Dolphin's CISO: a block size there and the disc
        # from 0x8000
        if head[:4] == b"ZISO" or _u32le(head, 4) in (0, 0x18):
            return _match("psp", 1.0, "PSP CSO image")
        f.seek(0x8000)
        return nintendo_disc(f.read(0x100))
    return disc_system(f)


# --- cue, gdi, m3u, chd ----------------------------------------------------------------------

def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return s[1:-1]
    return s


def parse_cue(text):
    """[(file name, [(track number, type, index 01 frames or None)])]"""
    files = []
    for line in text.splitlines():
        words = line.strip()
        up = words.upper()
        if up.startswith("FILE "):
            rest = words[5:].strip()
            if rest.startswith('"'):
                name = rest[1:rest.index('"', 1)] if '"' in rest[1:] else rest[1:]
            else:
                name = rest.rsplit(None, 1)[0] if len(rest.split()) > 1 else rest
            files.append((name, []))
        elif up.startswith("TRACK ") and files:
            parts = words.split()
            if len(parts) >= 3:
                files[-1][1].append([int(parts[1]) if parts[1].isdigit() else 0, parts[2].upper(), None])
        elif up.startswith("INDEX 01") and files and files[-1][1]:
            mm, ss, ff = (int(x) for x in re.findall(r"\d+", words[8:])[:3])
            files[-1][1][-1][2] = (mm * 60 + ss) * 75 + ff
    return [(n, [tuple(t) for t in tr]) for n, tr in files]


def _sheet(path):
    """A .cue, .gdi or .m3u's text (a Windows editor's UTF-8 BOM dropped)."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def safe_ref(ref):
    """Whether a sheet's file name stays in the sheet's folder: no absolute path, no '..'."""
    parts = ref.replace("\\", "/").split("/")
    return bool(ref) and not os.path.isabs(ref) and ".." not in parts


def cue_refs(path):
    try:
        return [n for n, _ in parse_cue(_sheet(path)) if safe_ref(n)]
    except OSError:
        return []


def gdi_refs(path):
    refs = []
    try:
        lines = _sheet(path).splitlines()
    except OSError:
        return refs
    for line in lines[1:]:
        m = re.match(r'\s*\d+\s+\d+\s+\d+\s+\d+\s+("[^"]+"|\S+)', line)
        if m and safe_ref(_unquote(m.group(1))):
            refs.append(_unquote(m.group(1)))
    return refs


def m3u_refs(path):
    try:
        lines = [l.strip() for l in _sheet(path).splitlines()]
    except OSError:
        return []
    return [l for l in lines if l and not l.startswith("#") and safe_ref(l)]


def refs_of(path):
    """The files a .cue, .gdi or .m3u points to, relative to its folder (a .m3u's discs bring their
    own: a .cue listed in one brings its .bins). Names that would leave the folder (absolute, or
    with '..') are left out."""
    ext = systems.ext_of(path)
    if ext == "cue":
        return cue_refs(path)
    if ext == "gdi":
        return gdi_refs(path)
    if ext == "m3u":
        out, d = [], os.path.dirname(path)
        for r in m3u_refs(path):
            out.append(r)
            sub = os.path.join(d, r)
            if systems.ext_of(r) in ("cue", "gdi") and os.path.isfile(sub):
                rd = os.path.dirname(r)
                out += [os.path.join(rd, x) if rd else x for x in refs_of(sub)]
        return out
    return []


def _cue(path):
    try:
        files = parse_cue(_sheet(path))
    except OSError:
        return None
    d = os.path.dirname(path)
    for name, tracks in files:
        data = [t for t in tracks if t[1].startswith("MODE")]
        if not data or not safe_ref(name):
            continue
        sector = 2048 if data[0][1].endswith("/2048") else 2352
        base = (data[0][2] or 0) * sector if data[0] is not tracks[0] else 0
        try:
            with open(os.path.join(d, name), "rb") as f:
                m = disc_system(f, base)
        except OSError:
            continue
        if m:
            return m._replace(refs=tuple(cue_refs(path)))
    return None


def _chd_tracks(f):
    """(tags, tracks) from a CHD's metadata: tags like b'CHGD', tracks as {number: type}."""
    f.seek(0)
    head = f.read(124)
    if head[:8] != b"MComprHD":
        return None
    ver = _u32be(head, 12)
    meta = struct.unpack_from(">Q", head, 48 if ver >= 5 else 36)[0]
    tags, tracks = set(), {}
    for _ in range(256):
        if not meta:
            break
        f.seek(meta)
        e = f.read(16)
        if len(e) < 16:
            break
        tag, fl, nxt = e[:4], _u32be(e, 4), struct.unpack_from(">Q", e, 8)[0]
        tags.add(tag)
        if tag in (b"CHT2", b"CHTR", b"CHGT"):
            text = f.read(min(fl & 0xFFFFFF, 512)).decode("ascii", "replace")
            t, ty = re.search(r"TRACK:(\d+)", text), re.search(r"TYPE:(\S+)", text)
            if t and ty:
                tracks[int(t.group(1))] = ty.group(1).rstrip("\0")
        meta = nxt
    return tags, tracks


def _chd(f):
    """A CHD's system from its metadata alone: its hunks are Huffman-mapped and codec-compressed,
    more than the importer should decode. GD-ROM metadata proves Dreamcast; otherwise the track
    layout guesses (PlayStation: one mode 2 data track first; Sega CD: mode 1 first; PC Engine CD:
    audio first, then mode 1), all below SORT_AT: Saturn, 3DO and Neo Geo CD discs start with mode
    1 too, and PS2 CDs with mode 2, so without a folder naming the system the user picks."""
    info = _chd_tracks(f)
    if not info:
        return None
    tags, tracks = info
    if b"CHGD" in tags:
        return _match("dreamcast", 1.0, "GD-ROM CHD")
    first, second = tracks.get(1, ""), tracks.get(2, "")
    if first.startswith("MODE2"):
        return _match("psx", 0.55, "CHD: mode 2 data track first")
    if first.startswith("MODE1"):
        return _match("segacd", 0.4, "CHD: mode 1 data track first")
    if first == "AUDIO" and second.startswith("MODE1"):
        return _match("pcenginecd", 0.5, "CHD: audio, then mode 1")
    return None


# --- cartridges ------------------------------------------------------------------------------

def _bin(f, size):
    f.seek(0)
    head = f.read(0x200)
    if head[:12] == SYNC:
        m = disc_system(f)
        return m._replace(needs_cue=m.system in ("psx", "segacd", "pcenginecd")) if m else None
    if head[:14] == b"SEGADISCSYSTEM":
        return _match("segacd", 1.0, "Sega CD disc header", needs_cue=True)
    if head[0x100:0x108] == b"SEGA 32X":
        return _match("sega32x", 1.0, "32X cartridge header")
    if b"SEGA" in head[0x100:0x106]:
        return _match("megadrive", 1.0, "Mega Drive cartridge header")
    if size in A2600_SIZES:
        return _match("atari2600", 0.7, "Atari 2600 cartridge size")
    if size > 0x20000:
        return _match("megadrive", 0.5, "a large .bin without a header")
    return None


def _gb(f):
    f.seek(0x143)
    if f.read(1) == b"\xc0":
        return _match("gbc", 1.0, "Game Boy Color-only cartridge")
    return None


# --- archives --------------------------------------------------------------------------------

def archive_members(path):
    """[(name, size)] of a .zip or .7z's files, or None if it can't be read."""
    ext = systems.ext_of(path)
    try:
        if ext == "zip":
            with zipfile.ZipFile(path) as z:
                return [(i.filename, i.file_size) for i in z.infolist() if not i.is_dir()]
        if ext == "7z":
            out = subprocess.run(["7z", "l", "-slt", "-ba", path], capture_output=True, text=True,
                                 timeout=60).stdout
            res, name, size, isdir = [], None, 0, False
            for line in out.splitlines() + [""]:
                if line.startswith("Path = "):
                    name = line[7:]
                elif line.startswith("Size = "):
                    size = int(line[7:] or 0)
                elif line.startswith("Attributes = ") and line[13:14] == "D":
                    isdir = True
                elif line.startswith("Folder = +"):
                    isdir = True
                elif not line.strip() and name is not None:
                    if not isdir:
                        res.append((name, size))
                    name, size, isdir = None, 0, False
            return res
    except (OSError, zipfile.BadZipFile, subprocess.SubprocessError, ValueError):
        return None
    return None


def _archive(path, folder_hint):
    members = archive_members(path)
    if members is None:
        return None
    if folder_hint and systems.keeps_archives(folder_hint):
        return _match(folder_hint, 0.95, "archive in its system's folder")
    files = [(n, s) for n, s in members if systems.ext_of(n) not in JUNK_EXTS]
    exts = {systems.ext_of(n) for n, _ in files}
    if exts & DOS_EXES:
        return _match("dos", 0.8, "archive with a DOS program")
    roms = systems.rom_extensions() - ARCHIVES
    inner = [(n, s) for n, s in files if systems.ext_of(n) in roms]
    sheets = [x for x in inner if systems.ext_of(x[0]) in ("m3u", "cue", "gdi")]
    chips = [(n, s) for n, s in inner if systems.ext_of(n) in ("bin", "rom")]
    small = any(s < CHIP_MAX for _, s in chips)
    stem = lambda n: os.path.splitext(os.path.basename(n))[0].lower()  # noqa: E731
    # one chip and files of its own name beside it (Pitfall.bin + Pitfall.cfg, Game.rom +
    # Game.ips): a game with its extras. 51xx.bin among gg1_1b.3p, prom-1.1d...: a set
    lone = (len(chips) == 1 and len(inner) == 1
            and all(stem(n) == stem(chips[0][0]) for n, _ in files))
    if len(files) > 1 and not sheets and chips and (len(inner) > 1 or small) and (
            len(inner) < len(files) or small) and not lone:
        # several files, no .cue/.gdi/.m3u tying them together, .bin/.rom chips among them and
        # either chip names no system takes or small .bin/.rom files: an arcade set (dkong.zip:
        # c_5et_g.bin..., neogeo.zip: uni-bios_4_0.rom, sm1.sm1...), not games to unpack (a 4 KiB
        # chip would pass for an Atari 2600 game, a .rom for an MSX one). Sorted as arcade when it
        # holds chip names no system takes; otherwise left for the user to say. Big .bins alone
        # (a game's discs) are unpacked, and so is one chip with its own extras (lone)
        if len(inner) < len(files):
            return _match("arcade", 0.6, "archive of ROM chips (arcade set)")
        return _match("arcade", 0.5, "archive of several .bin/.rom files (an arcade set?)")
    if inner:
        # the game is what's inside: identify the main file (a .cue/.gdi/.m3u over its tracks)
        main = sheets or inner
        name, size = main[0]
        sid = None
        if systems.ext_of(path) == "zip" and len(inner) == 1:
            try:
                with zipfile.ZipFile(path) as z, z.open(name) as f:
                    m = identify_stream(name, f, size, folder_hint)
                    sid = m and m.system
            except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError,
                    zlib.error):
                sid = None
        if not sid:
            m = by_extension(name, folder_hint)
            sid = m and m.system
        # the inner file's own confidence: a weak guess (a CHD's 0.4, a .bin's size) stays one
        conf = m.confidence if m and sid else 0
        if sid:
            return Match(sid, conf, "archive holding " + os.path.basename(name), extract=True)
        return Match(None, 0, "archive holding " + os.path.basename(name), extract=True)
    if files:
        return _match("arcade", 0.6, "archive of unnamed ROM chips (arcade set)")
    return None


# --- the entry points ------------------------------------------------------------------------

def by_extension(name, folder_hint=None):
    """The answer from the extension and folder alone."""
    cands = systems.by_extension(systems.ext_of(name))
    if folder_hint in cands:
        return _match(folder_hint, 0.95, "extension, in its system's folder")
    if len(cands) == 1:
        return _match(cands[0], 0.9, "extension")
    return None


def candidates(name):
    return systems.by_extension(systems.ext_of(name))


def identify_stream(name, f, size, folder_hint=None):
    """identify() for an open, seekable binary file."""
    ext = systems.ext_of(name)
    m = None
    if ext == "bin":
        m = _bin(f, size)
    elif ext in ("iso", "gcm", "rvz", "gcz", "wia", "ciso", "cso", "wbfs", "img"):
        m = _image(f, ext)
    elif ext == "chd":
        m = _chd(f)
    elif ext == "gb":
        m = _gb(f)
    if m and m.confidence >= 1.0:
        return m
    hinted = by_extension(name, folder_hint)
    if hinted and (not m or hinted.confidence > m.confidence):
        if ext == "iso" and folder_hint == "dos":
            return hinted
        return hinted if not m or hinted.confidence >= 0.95 else m
    return m or hinted


def identify(path, folder_hint=None):
    """The system of the file at `path` (folder_hint: the system its folder is named after)."""
    ext = systems.ext_of(path)
    if ext in ARCHIVES:
        return _archive(path, folder_hint)
    if ext == "cue":
        return _cue(path) or (by_extension(path, folder_hint) or Match(None, 0, "cue"))._replace(
            refs=tuple(cue_refs(path)))
    if ext == "gdi":
        m = by_extension(path, folder_hint)
        return m._replace(refs=tuple(gdi_refs(path))) if m else None
    if ext == "m3u":
        refs = refs_of(path)
        first = os.path.join(os.path.dirname(path), m3u_refs(path)[0]) if m3u_refs(path) else None
        m = identify(first, folder_hint) if first and os.path.isfile(first) else None
        if m and m.system and "m3u" in systems.systems()[m.system].get("extensions", ()):
            return m._replace(refs=tuple(refs), reason="playlist of " + m.reason)
        m = by_extension(path, folder_hint)
        return m._replace(refs=tuple(refs)) if m else None
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            return identify_stream(path, f, size, folder_hint)
    except OSError:
        return None
