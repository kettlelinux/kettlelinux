# Each game's saves and save states, wherever its emulator keeps them (systems.json: each
# emulator's "saves", [{dir: from the home folder, glob}]), and backing them up.
#
# RetroArch's (its cores' "saves", kettle-emulation's kept config) are sorted by the ROM's folder,
# so they're matched to the ROM: <dir>/<ROM's folder>/<ROM name>.srm, .state[1-9|.auto] (each
# state with a .png). A standalone emulator keeps its own by the game's id or name (PPSSPP's
# SAVEDATA folders, Dolphin's StateSaves, ...): each entry its glob finds under its dir is a game
# of its own, named after the file or folder at the top of it. melonDS keeps <ROM name>.sav and
# .ml1-.ml8 next to the ROM.
#
# A backup is a zip in an Emulation/backups folder: a file under the home folder is stored as
# "home/<path from it>", one on a card as "storage/<filesystem uuid>/<path from its mount>", so a
# restore puts it back where it was (a card's only while it's in), and only into Emulation/ and
# the emulators' save folders. A name that isn't UTF-8 goes in as its bytes, without the zip's
# UTF-8 flag, and comes back as them.
import glob
import os
import re
import shutil
import time
import zipfile

STATE_RE = re.compile(r"\.state(\d*|\.auto)$")
STATE_WORDS = re.compile(r"state", re.I)  # a standalone's dir or file holding save states
# the BIOS folder is the user's own, never a save: not listed, backed up, deleted or restored into
BIOS_DIR = "Emulation/bios"


def _in_bios(rel: str) -> bool:
    rel = rel.strip("/")
    return rel == BIOS_DIR or rel.startswith(BIOS_DIR + "/")


def _rel_dir(d: str) -> str | None:
    """A saves dir from systems.json, as a path under the home folder (None: not one)."""
    d = (d or "").strip("/")
    if not d or d.startswith("~") or any(p in ("", ".", "..") for p in d.split("/")) or _in_bios(d):
        return None
    return d


def save_dirs(db: dict) -> tuple[list[str], list[dict]]:
    """(the RetroArch cores' save dirs, [{emulator, name, dir, glob}] of the standalones)."""
    ra, other, seen = [], [], set()
    for eid, e in db.get("emulators", {}).items():
        for sv in e.get("saves") or ():
            d = _rel_dir(sv.get("dir", ""))
            if not d:
                continue
            if e.get("kind") == "libretro":
                if d not in ra:
                    ra.append(d)
            elif (d, sv.get("glob", "*")) not in seen:
                seen.add((d, sv.get("glob", "*")))
                other.append({"emulator": eid, "name": e.get("name", eid), "dir": d, "glob": sv.get("glob") or "*"})
    return ra, other


def home_save_dirs(db: dict) -> tuple[str, ...]:
    """The folders under the home folder a restore may write to."""
    ra, other = save_dirs(db)
    return ("Emulation/",) + tuple(d + "/" for d in ra) + tuple(o["dir"] + "/" for o in other)


def _file(path: str, kind: str, slot: str = "") -> dict | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    thumb = path + ".png" if kind == "state" and os.path.exists(path + ".png") else ""
    return {"path": path, "kind": kind, "slot": slot, "size": st.st_size, "mtime": int(st.st_mtime), "thumb": thumb}


def _stem(path: str) -> str:
    base = os.path.basename(path)
    return base.rpartition(".")[0] if "." in base.lstrip(".") else base


def rom_files(home: str, rom: dict, ra_dirs: list[str] = ()) -> list[dict]:
    """The saves and states of one ROM ({system, path}): RetroArch's in `ra_dirs`, and melonDS's
    next to the ROM."""
    out = []
    stem = _stem(rom["path"])
    folder = os.path.basename(os.path.dirname(rom["path"]))
    for d in ra_dirs:
        base = os.path.join(home, d, folder, stem)
        for p in sorted(glob.glob(glob.escape(base) + ".*")):
            if p.endswith(".png") or os.path.isdir(p):
                continue
            m = STATE_RE.search(p)
            if m:
                f = _file(p, "state", m.group(1).lstrip(".") or "0")
            elif p.rpartition(".")[0] == base:
                f = _file(p, "save")
            else:
                continue
            if f:
                out.append(f)
    d = os.path.dirname(rom["path"])
    for p in glob.glob(os.path.join(glob.escape(d), glob.escape(stem)) + ".*"):
        ext = p.rpartition(".")[2].lower()
        if ext == "sav":
            f = _file(p, "save")
        elif re.fullmatch(r"ml[1-8]", ext):
            f = _file(p, "state", ext[2:])
        else:
            continue
        if f:
            out.append(f)
    return out


def _walk_files(top: str) -> list[str]:
    if os.path.isfile(top):
        return [top]
    out = []
    for d, dirs, files in os.walk(top):
        dirs.sort()
        out += [os.path.join(d, f) for f in sorted(files)]
    return out


def emulator_files(home: str, entries: list[dict]) -> list[dict]:
    """The standalones' saves, a game per entry their glob finds under their dir: [{id, title,
    system: "", emulator, files}]. A file is a state when its name or its folder's says so."""
    games = {}
    for e in entries:
        root = os.path.join(home, e["dir"])
        for top in sorted(glob.glob(os.path.join(glob.escape(root), e["glob"]))):
            if os.path.islink(top) or not os.path.realpath(top).startswith(os.path.realpath(root) + "/"):
                continue
            name = os.path.relpath(top, root).split("/")[0]
            for p in _walk_files(top):
                if _in_bios(os.path.relpath(os.path.realpath(p), os.path.realpath(home))):
                    continue
                if p.endswith(".png") and os.path.exists(p[:-4]):
                    continue  # a state's picture
                kind = "state" if STATE_WORDS.search(os.path.relpath(p, home)) else "save"
                f = _file(p, kind)
                if f:
                    games.setdefault((e["emulator"], e["name"], e["dir"], name), []).append(f)
    return [{"id": f"{eid}:{d}:{name}", "title": name, "system": "", "emulator": ename, "files": files}
            for (eid, ename, d, name), files in games.items()]


def listing(home: str, roms: dict, db: dict) -> list[dict]:
    """Every game with saves or states: [{id, title, system, files}], newest first."""
    ra, other = save_dirs(db)
    out = []
    for rid, r in roms.items():
        if r.get("deleted"):
            continue
        files = rom_files(home, r, ra)
        if files:
            out.append({"id": rid, "title": r.get("title") or _stem(r["path"]), "system": r["system"], "files": files})
    out += emulator_files(home, other)
    out.sort(key=lambda g: -max(f["mtime"] for f in g["files"]))
    return out


def all_paths(games: list[dict]) -> set[str]:
    return {f["path"] for g in games for f in g["files"]} | {f["thumb"] for g in games for f in g["files"] if f["thumb"]}


def delete(paths: list[str], allowed: set[str], home: str | None = None) -> int:
    n = 0
    for p in paths:
        if p not in allowed:
            raise ValueError(f"not a save: {p}")
        if home and _in_bios(os.path.relpath(os.path.realpath(p), os.path.realpath(home))):
            raise ValueError(f"a BIOS file isn't a save: {p}")
        for q in (p, p + ".png"):
            try:
                os.remove(q)
                n += 1
            except FileNotFoundError:
                pass
    return n


class _RawName(zipfile.ZipInfo):
    """A zip entry whose name is written as the path's own bytes when they aren't UTF-8 (zipfile
    would refuse it), so restore() gets back the same file."""
    __slots__ = ("raw",)

    def _encodeFilenameFlags(self):
        raw = getattr(self, "raw", None)
        if raw is None:
            return super()._encodeFilenameFlags()
        return raw, self.flag_bits & ~0x800


def _write(z: zipfile.ZipFile, path: str, arc: str):
    info = _RawName.from_file(path, arc)
    info.compress_type = zipfile.ZIP_DEFLATED
    try:
        arc.encode("utf-8")
        info.raw = None
    except UnicodeEncodeError:
        info.raw = os.fsencode(info.filename)
    with open(path, "rb") as src, z.open(info, "w") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)


def _entry_name(info: zipfile.ZipInfo) -> str:
    """An entry's name as a path: one without the UTF-8 flag is its bytes (zipfile reads them as
    cp437), surrogate-escaped where they aren't UTF-8."""
    if info.flag_bits & 0x800:
        return info.filename
    return os.fsdecode(info.filename.encode("cp437"))


def _arcname(path: str, home: str, storages: list[dict]) -> str | None:
    real = os.path.realpath(path)
    for s in storages:
        if s.get("internal"):
            continue
        mp = os.path.realpath(s["path"])
        if real.startswith(mp + "/") and s.get("uuid"):
            return f"storage/{s['uuid']}/{os.path.relpath(real, mp)}"
    home = os.path.realpath(home)
    if real.startswith(home + "/"):
        return "home/" + os.path.relpath(real, home)
    return None


def backup(paths: list[str], dest_dir: str, home: str, storages: list[dict]) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    name = os.path.join(dest_dir, time.strftime("saves-%Y%m%d-%H%M%S.zip"))
    tmp = name + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            if _in_bios(os.path.relpath(os.path.realpath(p), os.path.realpath(home))):
                continue
            for q in (p, p + ".png"):
                arc = _arcname(q, home, storages) if os.path.exists(q) else None
                if arc:
                    _write(z, q, arc)
    os.replace(tmp, name)
    return name


def backups(dirs: list[str]) -> list[dict]:
    out = []
    for d in dirs:
        for p in glob.glob(os.path.join(glob.escape(d), "saves-*.zip")):
            st = os.stat(p)
            out.append({"path": p, "size": st.st_size, "mtime": int(st.st_mtime)})
    out.sort(key=lambda b: -b["mtime"])
    return out


def restore(zip_path: str, home: str, storages: list[dict], allowed: tuple[str, ...] = ("Emulation/",)) -> dict:
    """Puts a backup's files back, under the home folder only into `allowed` (home_save_dirs());
    files of a card that isn't in are skipped."""
    mounts = {s["uuid"]: s["path"] for s in storages if s.get("uuid") and not s.get("internal")}
    done, skipped = 0, 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = _entry_name(info)
            parts = name.split("/")
            if ".." in parts or name.startswith("/") or "\0" in name:
                skipped += 1
                continue
            if parts[0] == "home" and len(parts) > 1:
                base, rel = home, parts[1:]
                # only where saves live: a backup can't write anything else in the home folder
                if _in_bios("/".join(rel)) or not any("/".join(rel).startswith(r) for r in allowed):
                    skipped += 1
                    continue
            elif parts[0] == "storage" and len(parts) > 3 and parts[1] in mounts and parts[2] == "Emulation" \
                    and parts[3] != "bios":
                base, rel = mounts[parts[1]], parts[2:]
            else:
                skipped += 1
                continue
            dest = os.path.join(base, *rel)
            if not os.path.realpath(dest).startswith(os.path.realpath(base) + "/"):
                skipped += 1
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest + ".part", "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            os.replace(dest + ".part", dest)
            done += 1
    return {"restored": done, "skipped": skipped}
