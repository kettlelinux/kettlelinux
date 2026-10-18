# Extra cores: the libretro cores Kettle can't ship (systems.json's emulators with "download"),
# fetched on the user's request from libretro's own aarch64 buildbot into
# ~/.config/retroarch/cores, where emu-run finds them. Two reasons keep a core out of the image:
# most (Snes9x, Genesis Plus GX, PicoDrive, FinalBurn Neo, MAME 2003-Plus) are licensed for
# non-commercial use only, and Kettle may be sold; blueMSX is free to use, but its V9938 video
# code's license allows it in MSX emulators only, which is incompatible with the GPL, so it
# can't be distributed with Kettle's GPL software. Each core's license is shown before it's
# downloaded. A download is checked to be an aarch64 ELF library.
#
# A core that needs files of its own in RetroArch's system folder (~/Emulation/bios) gets them
# with it, from libretro's buildbot too (SYSTEM_FILES: blueMSX's Machines and Databases
# folders), checked like the core (each file's CRC, nothing outside those folders, no links)
# and merged into the folders there: only the files we install are replaced, the user's own
# (a real BIOS they put in Machines/Shared Roms) stay. Only the free part of the buildbot's zip
# is installed ("keep"): blueMSX's pack also holds the real MSX, ColecoVision, Spectravideo and
# Sega system ROMs, which Kettle never downloads. What's kept: the Databases, every machine's
# config.ini, and C-BIOS (Machines/MSX*/ - C-BIOS/cbios*: its ROMs and cbios.txt, its BSD
# license, which says its binaries must come with it). C-BIOS is a free MSX BIOS that runs
# cartridges only (no BASIC, disks or tapes).
#
# blueMSX's machine choice (its bluemsx_msxtype option, seeded "Auto" by kettle-emulation's
# seed.py) works with that: on Auto it picks MSX2+ for a cartridge, and when that machine's
# ROMs aren't there it falls back to "MSX2+ - C-BIOS", then MSX2, then MSX C-BIOS (libretro.c,
# blueMSX-libretro e3086eb, 2026-08). A disk (.dsk, .m3u) never falls back: it needs the real
# MSX2+ ROMs (and a disk ROM) in Emulation/bios/Machines/Shared Roms. A machine picked by name
# in the option isn't swapped either; the option's values are machine names only, none of them
# C-BIOS, which is why "Auto" is the setting that reaches C-BIOS. The SG-1000 and SC-3000
# machines need no ROM at all.
import fnmatch
import io
import os
import shutil
import struct
import tempfile
import threading
import urllib.request
import zipfile

BUILDBOT = "https://buildbot.libretro.com/nightly/linux/aarch64/latest"
ASSETS = "https://buildbot.libretro.com/assets/system"
# a core's own files in RetroArch's system folder: the buildbot's zip, the folders it holds and
# the files of those installed (fnmatch patterns on the zip's path; the rest is left out)
SYSTEM_FILES = {
    "bluemsx": {"url": f"{ASSETS}/blueMSX.zip", "dirs": ["Machines", "Databases"],
                "keep": ["Databases/*", "Machines/*/config.ini", "Machines/* - C-BIOS/cbios*"]},
}
STAGE_PREFIX = ".kettle-system-files."
_unpack_lock = threading.Lock()  # one unpack into a system folder at a time
MAX_SYSTEM_BYTES = 256 << 20  # unpacked
MAX_SYSTEM_ENTRIES = 20000
UA = "kettle-emulation/1 (+https://github.com/kettlelinux)"
# what each license allows, as the user reads it
TERMS = {
    "snes9x": "Snes9x's license allows personal use but not selling it or including it in something sold.",
    "genesis_plus_gx": "Genesis Plus GX's license allows non-commercial use only.",
    "picodrive": "PicoDrive's license allows non-commercial use only.",
    "fbneo": "FinalBurn Neo's license allows non-commercial use only.",
    "mame2003_plus": "MAME 2003-Plus is under the old MAME license: non-commercial use only.",
    "bluemsx": "blueMSX's V9938 video code may be used in MSX emulators only, so Kettle can't ship it "
               "with its GPL software; the core itself is free to use. Its Machines and Databases "
               "folders come with it from libretro's buildbot, into Emulation/bios, with only the free "
               "C-BIOS (BSD license) as their system ROMs: it runs MSX cartridges. No real MSX, "
               "ColecoVision or Spectravideo BIOS is downloaded; for disks, tapes and those machines, "
               "put your own in Emulation/bios/Machines.",
}
EM_AARCH64 = 0xB7


def core_dir(home: str) -> str:
    return os.path.join(home, ".config", "retroarch", "cores")


def path(home: str, core: str) -> str:
    return os.path.join(core_dir(home), f"{core}_libretro.so")


def bios_dir(home: str) -> str:
    return os.path.join(home, "Emulation", "bios")


def missing_system_dirs(bios: str, core: str) -> list[str]:
    """The folders of the core's SYSTEM_FILES not in the system folder."""
    return [d for d in SYSTEM_FILES.get(core, {}).get("dirs", []) if not os.path.isdir(os.path.join(bios, d))]


def listing(home: str, db: dict, bios: str | None = None) -> list[dict]:
    """[{core, emulator, name, license, terms, installed, size, systems, system_dirs, missing}]:
    installed means the core and its system folders are there (missing: the folders that aren't)."""
    out = []
    for eid, e in db["emulators"].items():
        if not e.get("download"):
            continue
        p = path(home, e["core"])
        systems = [s["name"] for s in db["systems"].values() if eid in s["emulators"]]
        missing = missing_system_dirs(bios or bios_dir(home), e["core"]) if os.path.exists(p) else []
        out.append({"core": e["core"], "emulator": eid, "name": e["name"], "license": e.get("license", ""),
                    "terms": TERMS.get(e["core"], "This core's license doesn't allow it to be sold or shipped with Kettle."),
                    "installed": os.path.exists(p) and not missing, "size": os.path.getsize(p) if os.path.exists(p) else 0,
                    "systems": systems, "system_dirs": SYSTEM_FILES.get(e["core"], {}).get("dirs", []),
                    "missing": missing})
    return out


def check_elf(data: bytes):
    if data[:4] != b"\x7fELF" or data[4] != 2:
        raise ValueError("the download isn't a 64-bit library")
    if struct.unpack_from("<H", data, 18)[0] != EM_AARCH64:
        raise ValueError("the download isn't built for this device (aarch64)")


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(512 << 20)


def _bad_entry(name: str, parts: list[str], dirs: list[str], is_dir: bool) -> bool:
    return (name.startswith("/") or "\\" in name or "\0" in name or parts[0] not in dirs
            or any(p in ("", ".", "..") for p in parts)
            # a file must be in one of the folders, not be one
            or (len(parts) < 2 and not is_dir))


def _kept(name: str, keep: list[str] | None) -> bool:
    return keep is None or any(fnmatch.fnmatchcase(name, k) for k in keep)


def _clear_stale_stages(bios: str):
    """Staging folders a crashed unpack left (under _unpack_lock: none is in use)."""
    try:
        names = os.listdir(bios)
    except OSError:
        return
    for n in names:
        if n.startswith(STAGE_PREFIX):
            shutil.rmtree(os.path.join(bios, n), ignore_errors=True)


def _merge(stage: str, bios: str, files: list[list[str]]):
    """Moves the staged files into the system folder, each replacing only the file of its name
    there; on an OSError everything done is undone (replaced files back, new files and folders
    gone) and it's a ValueError."""
    old = os.path.join(stage, ".old")
    made, done = [], []  # folders made; (dest, its old copy or None) moved in
    try:
        for parts in files:
            d = bios
            for p in parts[:-1]:
                d = os.path.join(d, p)
                if not os.path.isdir(d):
                    os.mkdir(d)  # a file or a link to nothing there: an OSError
                    made.append(d)
        for n, parts in enumerate(files):
            dest = os.path.join(bios, *parts)
            keep = None
            if os.path.lexists(dest):
                if os.path.isdir(dest) and not os.path.islink(dest):
                    raise IsADirectoryError(f"{dest} is a folder")
                os.makedirs(old, exist_ok=True)
                keep = os.path.join(old, str(n))
                os.rename(dest, keep)
            done.append((dest, keep))
            os.rename(os.path.join(stage, "new", *parts), dest)
    except OSError as e:
        for dest, keep in reversed(done):
            try:
                if keep:
                    os.replace(keep, dest)
                elif os.path.lexists(dest):
                    os.remove(dest)
            except OSError:
                pass
        for d in reversed(made):
            try:
                os.rmdir(d)
            except OSError:
                pass
        raise ValueError(f"putting the system files in place failed: {e}")


def unpack_system_files(data: bytes, bios: str, dirs: list[str], keep: list[str] | None = None):
    """Puts a SYSTEM_FILES zip's folders into the system folder, merged into the ones there: the
    files it installs replace those of the same name, everything else in them stays. Only the
    files matching `keep` are installed (all with None). Refused, leaving the folder as it was:
    an entry outside `dirs` (or with "..", an absolute path, a backslash, a file named like one
    of the folders), a link, a bad CRC, a folder with nothing to install, too much, or a file
    that can't be put in place."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("the buildbot's system files aren't a zip")
    with z:
        infos = z.infolist()
        if len(infos) > MAX_SYSTEM_ENTRIES or sum(i.file_size for i in infos) > MAX_SYSTEM_BYTES:
            raise ValueError("the buildbot's system files are too big")
        files = []
        for i in infos:
            name = i.filename
            parts = name.rstrip("/").split("/")
            if _bad_entry(name, parts, dirs, i.is_dir()):
                raise ValueError(f"the buildbot's system files have a bad entry: {name!r}")
            mode = i.external_attr >> 16
            if mode and (mode & 0o170000) not in (0, 0o100000, 0o040000):
                raise ValueError(f"the buildbot's system files have a link or device: {name!r}")
            if not i.is_dir() and _kept(name, keep):
                files.append((i, parts))
        have = {p[0] for _, p in files}
        if set(dirs) - have:
            raise ValueError("the buildbot's system files lack " + ", ".join(sorted(set(dirs) - have)))
        with _unpack_lock:
            os.makedirs(bios, exist_ok=True)
            _clear_stale_stages(bios)
            stage = tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=bios)
            try:
                try:
                    for i, parts in files:
                        dest = os.path.join(stage, "new", *parts)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        # reading checks the CRC (BadZipFile on a mismatch)
                        with z.open(i) as src, open(dest, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                except (zipfile.BadZipFile, OSError, EOFError) as e:
                    raise ValueError(f"unpacking the system files failed: {e}")
                _merge(stage, bios, [p for _, p in files])
            finally:
                shutil.rmtree(stage, ignore_errors=True)


def download(home: str, core: str, known: set[str], bios: str | None = None) -> str:
    """Fetches the core, and its SYSTEM_FILES into the system folder (`bios`, ~/Emulation/bios),
    both checked before either is put in place."""
    if core not in known:
        raise ValueError(f"not an extra core: {core}")
    data = _fetch(f"{BUILDBOT}/{core}_libretro.so.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = f"{core}_libretro.so"
        if name not in z.namelist():
            raise ValueError("the buildbot's zip has no core in it")
        so = z.read(name)
    check_elf(so)
    sysfiles = SYSTEM_FILES.get(core)
    if sysfiles:
        unpack_system_files(_fetch(sysfiles["url"]), bios or bios_dir(home), sysfiles["dirs"], sysfiles.get("keep"))
    dest = path(home, core)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest + ".part", "wb") as f:
        f.write(so)
    os.replace(dest + ".part", dest)
    return dest


def remove(home: str, core: str, known: set[str]):
    """The core goes; its folders in Emulation/bios stay (the user's BIOS folder: they may have
    put their own machines there)."""
    if core not in known:
        raise ValueError(f"not an extra core: {core}")
    try:
        os.remove(path(home, core))
    except FileNotFoundError:
        pass
