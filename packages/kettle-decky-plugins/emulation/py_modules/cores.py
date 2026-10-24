# The libretro cores: every core systems.json names (its "libretro" emulators), fetched on the
# user's request from libretro's own aarch64 buildbot into the RetroArch Flatpak's cores folder
# (~/.var/app/org.libretro.RetroArch/config/retroarch/cores), where emu-run's RetroArch finds
# them. Kettle ships none. A free core (systems.json "free") downloads with a tap; one whose
# license isn't free (Snes9x, Genesis Plus GX, PicoDrive, FinalBurn Neo, MAME 2003-Plus:
# non-commercial use only) shows its terms first and needs the user's yes. A download is checked
# to be an aarch64 ELF library.
#
# A core can come from somewhere else than the buildbot (systems.json "source"): ARMSX2, PS2, is
# built by its own project as GitHub nightly prereleases (tags nightly-YYYYMMDD; its stable
# releases are Android-only). Its core is in one .tar.zst, and the resources it needs (fonts,
# shaders, GameIndex.yaml...) in the standalone build's, from which only resources/ is taken,
# into RetroArch's system folder (~/Emulation/bios/pcsx2/resources, where the core reads them).
# The installed nightly's tag is kept next to the core, and a newer nightly shows as an update.
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
import json
import os
import shutil
import struct
import subprocess
import tarfile
import tempfile
import threading
import time
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


RETROARCH = "org.libretro.RetroArch"


def core_dir(home: str) -> str:
    return os.path.join(home, ".var", "app", RETROARCH, "config", "retroarch", "cores")


def path(home: str, core: str) -> str:
    return os.path.join(core_dir(home), f"{core}_libretro.so")


def bios_dir(home: str) -> str:
    return os.path.join(home, "Emulation", "bios")


def _dirs_of(core: str, e: dict | None = None) -> list[str]:
    """The folders a core needs in the system folder: its SYSTEM_FILES', or its source's."""
    src = (e or {}).get("source") or {}
    if src.get("resources_dest"):
        return [src["resources_dest"]]
    return SYSTEM_FILES.get(core, {}).get("dirs", [])


def missing_system_dirs(bios: str, core: str, e: dict | None = None) -> list[str]:
    """The folders of the core's SYSTEM_FILES (or source) not in the system folder."""
    return [d for d in _dirs_of(core, e) if not os.path.isdir(os.path.join(bios, d))]


def _version_file(home: str, core: str) -> str:
    return os.path.join(core_dir(home), f".kettle-{core}.json")


def installed_version(home: str, core: str) -> str:
    """The nightly tag a "source" core was installed from ("" for a buildbot core)."""
    try:
        with open(_version_file(home, core)) as f:
            return json.load(f).get("tag", "")
    except (OSError, ValueError):
        return ""


def known(db: dict) -> dict:
    """core -> its emulator entry (with "id"), for every libretro emulator in systems.json."""
    return {e["core"]: {**e, "id": eid} for eid, e in db["emulators"].items() if e.get("kind") == "libretro"}


def terms(e: dict) -> str:
    """What the core's license allows, as the user reads it ("" for a free core)."""
    if e.get("free", True) and e["core"] not in TERMS:
        return ""
    return TERMS.get(e["core"], "This core's license doesn't allow it to be sold or shipped with Kettle.")


def listing(home: str, db: dict, bios: str | None = None) -> list[dict]:
    """[{core, emulator, name, license, free, terms, installed, size, systems, system_dirs,
    missing}] for every libretro core: installed means the core and its system folders are there
    (missing: the folders that aren't)."""
    out = []
    for core, e in sorted(known(db).items(), key=lambda kv: kv[1]["name"].lower()):
        p = path(home, core)
        systems = [s["name"] for s in db["systems"].values() if e["id"] in s["emulators"]]
        missing = missing_system_dirs(bios or bios_dir(home), core, e) if os.path.exists(p) else []
        row = {"core": core, "emulator": e["id"], "name": e["name"], "license": e.get("license", ""),
               "free": bool(e.get("free", True)), "terms": terms(e),
               "installed": os.path.exists(p) and not missing, "size": os.path.getsize(p) if os.path.exists(p) else 0,
               "systems": systems, "system_dirs": _dirs_of(core, e), "missing": missing}
        if e.get("source", {}).get("kind") == "github-nightly":
            have = installed_version(home, core) if os.path.exists(p) else ""
            latest = latest_nightly_tag(e["source"])
            row.update({"nightly": True, "version": have, "latest": latest or "",
                        "update": bool(have and latest and latest != have)})
        out.append(row)
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


# --- GitHub nightlies (systems.json "source": {"kind": "github-nightly", ...}) ----------------
GITHUB_API = "https://api.github.com"
NIGHTLY_TTL = 3600  # seconds the newest nightly's tag is remembered, for the Update button
_nightly_cache: dict = {}
MAX_RESOURCES_BYTES = 1 << 30  # unpacked
MAX_RESOURCES_ENTRIES = 50000


def _api(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read(8 << 20))


def newest_nightly(src: dict) -> dict:
    """{tag, core_url, resources_url} of the newest release of the source's repo that has both
    assets (GitHub lists releases newest first)."""
    releases = _api(f"{GITHUB_API}/repos/{src['repo']}/releases?per_page=30")
    for r in releases if isinstance(releases, list) else ():
        if not str(r.get("tag_name", "")).startswith(src.get("tag_prefix", "")):
            continue
        urls = {k: next((a.get("browser_download_url") for a in r.get("assets", ())
                         if str(a.get("name", "")).endswith(src[k])), None)
                for k in ("core_asset", "resources_asset") if src.get(k)}
        if urls and all(urls.values()):
            return {"tag": r["tag_name"], "core_url": urls.get("core_asset"),
                    "resources_url": urls.get("resources_asset")}
    raise ValueError(f"no {src['repo']} nightly has a Linux arm64 libretro build")


def latest_nightly_tag(src: dict) -> str | None:
    """The newest nightly's tag, remembered NIGHTLY_TTL; None when GitHub can't be reached."""
    hit = _nightly_cache.get(src["repo"])
    if hit and time.monotonic() - hit[0] < NIGHTLY_TTL:
        return hit[1]
    try:
        tag = newest_nightly(src)["tag"]
    except (OSError, ValueError):
        tag = None
    _nightly_cache[src["repo"]] = (time.monotonic(), tag)
    return tag


def _fetch_to(url: str, dest: str, limit: int = 1 << 30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        got = 0
        while chunk := r.read(1 << 20):
            got += len(chunk)
            if got > limit:
                raise ValueError("the download is too big")
            f.write(chunk)


def unzstd(src: str, dest: str):
    """A .zst file decompressed: with the zstd tool (pacman's, on every Kettle image), else
    Python's zstandard module (on the image too) or 3.14's compression.zstd."""
    if shutil.which("zstd"):
        r = subprocess.run(["zstd", "-q", "-d", "-f", "-o", dest, src], capture_output=True, text=True)
        if r.returncode:
            raise ValueError(f"the download isn't zstd data: {r.stderr.strip()[:200]}")
        return
    try:
        import zstandard
        opener = lambda f: zstandard.ZstdDecompressor().stream_reader(f)  # noqa: E731
    except ImportError:
        try:
            from compression import zstd
            opener = lambda f: zstd.ZstdFile(f)  # noqa: E731
        except ImportError:
            raise ValueError("no zstd decompressor on this system")
    try:
        with open(src, "rb") as f, opener(f) as z, open(dest, "wb") as out:
            shutil.copyfileobj(z, out, 1 << 20)
    except Exception as e:  # each library has its own error type
        raise ValueError(f"the download isn't zstd data: {e}")


def _tar_member_ok(m: tarfile.TarInfo) -> bool:
    parts = m.name.split("/")
    return (not m.name.startswith("/") and "\\" not in m.name and "\0" not in m.name
            and not any(p in ("", ".", "..") for p in parts) and (m.isfile() or m.isdir()))


def _core_from_tar(tar_path: str, core_file: str) -> bytes:
    with tarfile.open(tar_path) as t:
        for m in t:
            if m.isfile() and os.path.basename(m.name) == core_file and _tar_member_ok(m):
                return t.extractfile(m).read(512 << 20)
    raise ValueError(f"the nightly's archive has no {core_file}")


def _resources_from_tar(tar_path: str, want: str, dest: str):
    """The archive's <top>/<want>/ folder put at `dest`, whole: staged next to it, then swapped in
    (the old one gone only once the new one is there). Refused, leaving dest as it was: a link,
    an absolute path or "..", nothing under <want>/, too much."""
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    stage = tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=parent)
    try:
        n = size = 0
        with tarfile.open(tar_path) as t:
            for m in t:
                parts = m.name.split("/")
                if len(parts) < 2 or parts[1] != want:
                    continue
                if not _tar_member_ok(m):
                    raise ValueError(f"the nightly's resources have a bad entry: {m.name!r}")
                n += 1
                size += m.size
                if n > MAX_RESOURCES_ENTRIES or size > MAX_RESOURCES_BYTES:
                    raise ValueError("the nightly's resources are too big")
                out = os.path.join(stage, *parts[2:]) if len(parts) > 2 else stage
                if m.isdir():
                    os.makedirs(out, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with t.extractfile(m) as src, open(out, "wb") as f:
                    shutil.copyfileobj(src, f, 1 << 20)
        if not n:
            raise ValueError(f"the nightly's archive has no {want} folder")
        old = None
        if os.path.lexists(dest):
            old = dest + ".kettle-old"
            shutil.rmtree(old, ignore_errors=True)
            os.rename(dest, old)
        try:
            os.rename(stage, dest)
        except OSError:
            if old:
                os.rename(old, dest)
            raise
        stage = None
        if old:
            shutil.rmtree(old, ignore_errors=True)
    except (OSError, tarfile.TarError, EOFError) as e:
        raise ValueError(f"unpacking the nightly failed: {e}")
    finally:
        if stage:
            shutil.rmtree(stage, ignore_errors=True)


def download_nightly(home: str, core: str, src: dict, bios: str) -> str:
    """A "github-nightly" core: the newest nightly's core into RetroArch's cores folder and its
    resources into the system folder, both checked before either is put in place."""
    rel = newest_nightly(src)
    # the work files (hundreds of MB unpacked) go on disk next to the cores, never in /tmp's RAM
    os.makedirs(core_dir(home), exist_ok=True)
    work = tempfile.mkdtemp(prefix=".kettle-nightly.", dir=core_dir(home))
    try:
        _fetch_to(rel["core_url"], os.path.join(work, "core.tar.zst"))
        unzstd(os.path.join(work, "core.tar.zst"), os.path.join(work, "core.tar"))
        so = _core_from_tar(os.path.join(work, "core.tar"), src["core_file"])
        check_elf(so)
        if src.get("resources_asset"):
            _fetch_to(rel["resources_url"], os.path.join(work, "res.tar.zst"))
            unzstd(os.path.join(work, "res.tar.zst"), os.path.join(work, "res.tar"))
            with _unpack_lock:
                _resources_from_tar(os.path.join(work, "res.tar"), src["resources_dir"],
                                    os.path.join(bios, src["resources_dest"]))
        dest = path(home, core)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".part", "wb") as f:
            f.write(so)
        os.replace(dest + ".part", dest)
        with open(_version_file(home, core) + ".part", "w") as f:
            json.dump({"tag": rel["tag"]}, f)
        os.replace(_version_file(home, core) + ".part", _version_file(home, core))
        _nightly_cache[src["repo"]] = (time.monotonic(), rel["tag"])
        return dest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def download(home: str, core: str, cores: dict, bios: str | None = None, accepted: bool = False) -> str:
    """Fetches the core (one of known()'s), and its SYSTEM_FILES into the system folder (`bios`,
    ~/Emulation/bios), both checked before either is put in place. A core whose license isn't
    free needs `accepted` (the user said yes to its terms)."""
    if core not in cores:
        raise ValueError(f"not a core Kettle knows: {core}")
    if not cores[core].get("free", True) and not accepted:
        raise ValueError(f"{cores[core]['name']}'s license has to be accepted first")
    src = cores[core].get("source") or {}
    if src.get("kind") == "github-nightly":
        return download_nightly(home, core, src, bios or bios_dir(home))
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


def remove(home: str, core: str, cores: dict):
    """The core goes; its folders in Emulation/bios stay (the user's BIOS folder: they may have
    put their own machines there)."""
    if core not in cores:
        raise ValueError(f"not a core Kettle knows: {core}")
    for p in (path(home, core), _version_file(home, core)):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
