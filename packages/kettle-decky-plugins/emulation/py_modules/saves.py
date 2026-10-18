# Each game's saves and save states, wherever its emulator keeps them, and backing them up.
#
# RetroArch (kettle-emulation's kept config) sorts them by the ROM's folder:
#   ~/Emulation/saves/retroarch/<ROM's folder>/<ROM name>.srm
#   ~/Emulation/states/retroarch/<ROM's folder>/<ROM name>.state[1-9|.auto], each with a .png
# melonDS keeps <ROM name>.sav and .ml1-.ml8 next to the ROM. PPSSPP and Dolphin keep theirs by
# the game's disc id (SAVEDATA folders, StateSaves), shown as games of their own.
#
# A backup is a zip in an Emulation/backups folder: a file under the home folder is stored as
# "home/<path from it>", one on a card as "storage/<filesystem uuid>/<path from its mount>", so a
# restore puts it back where it was (a card's only while it's in). A name that isn't UTF-8 goes
# in as its bytes, without the zip's UTF-8 flag, and comes back as them.
import glob
import os
import re
import shutil
import time
import zipfile

STATE_RE = re.compile(r"\.state(\d*|\.auto)$")
# the folders under the home folder a restore may write to
HOME_SAVE_DIRS = ("Emulation/", ".config/ppsspp/PSP/", ".local/share/dolphin-emu/")


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


def rom_files(home: str, rom: dict) -> list[dict]:
    """The saves and states of one ROM ({system, path}) from RetroArch and melonDS."""
    out = []
    stem = _stem(rom["path"])
    folder = os.path.basename(os.path.dirname(rom["path"]))
    emu = os.path.join(home, "Emulation")
    s = _file(os.path.join(emu, "saves", "retroarch", folder, stem + ".srm"), "save")
    if s:
        out.append(s)
    for p in glob.glob(os.path.join(glob.escape(os.path.join(emu, "states", "retroarch", folder, stem)) + ".state*")):
        m = STATE_RE.search(p)
        if m:
            slot = m.group(1).lstrip(".") or "0"
            f = _file(p, "state", slot)
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


def by_id_files(home: str) -> list[dict]:
    """PPSSPP's and Dolphin's saves, a game per disc id: [{id, title, system, files}]."""
    games = {}
    psp = os.path.join(home, ".config", "ppsspp", "PSP")
    for d in sorted(glob.glob(os.path.join(psp, "SAVEDATA", "*"))):
        gid = os.path.basename(d)[:9]
        for p in glob.glob(os.path.join(glob.escape(d), "*")):
            f = _file(p, "save")
            if f:
                games.setdefault(("psp", gid), []).append(f)
    for p in sorted(glob.glob(os.path.join(psp, "PPSSPP_STATE", "*.ppst"))):
        m = re.match(r"(.{9})_.*_(\d+)\.ppst$", os.path.basename(p))
        if m:
            f = _file(p, "state", m.group(2))
            if f:
                games.setdefault(("psp", m.group(1)), []).append(f)
    dolphin = os.path.join(home, ".local", "share", "dolphin-emu")
    for p in sorted(glob.glob(os.path.join(dolphin, "StateSaves", "*.s[0-9][0-9]"))):
        gid, _, slot = os.path.basename(p).partition(".s")
        f = _file(p, "state", str(int(slot)))
        if f:
            games.setdefault(("gc", gid), []).append(f)
    for p in sorted(glob.glob(os.path.join(dolphin, "GC", "*", "Card ?", "*.gci"))):
        f = _file(p, "save")
        if f:
            games.setdefault(("gc", os.path.basename(p).split("-")[1] if "-" in os.path.basename(p) else "card"), []).append(f)
    return [{"id": f"{sys_}:{gid}", "title": gid, "system": sys_, "files": files}
            for (sys_, gid), files in games.items()]


def listing(home: str, roms: dict) -> list[dict]:
    """Every game with saves or states: [{id, title, system, files}], newest first."""
    out = []
    for rid, r in roms.items():
        if r.get("deleted"):
            continue
        files = rom_files(home, r)
        if files:
            out.append({"id": rid, "title": r.get("title") or _stem(r["path"]), "system": r["system"], "files": files})
    out += by_id_files(home)
    out.sort(key=lambda g: -max(f["mtime"] for f in g["files"]))
    return out


def all_paths(games: list[dict]) -> set[str]:
    return {f["path"] for g in games for f in g["files"]} | {f["thumb"] for g in games for f in g["files"] if f["thumb"]}


def delete(paths: list[str], allowed: set[str]) -> int:
    n = 0
    for p in paths:
        if p not in allowed:
            raise ValueError(f"not a save: {p}")
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


def restore(zip_path: str, home: str, storages: list[dict]) -> dict:
    """Puts a backup's files back; files of a card that isn't in are skipped."""
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
                if not any("/".join(rel).startswith(r) for r in HOME_SAVE_DIRS):
                    skipped += 1
                    continue
            elif parts[0] == "storage" and len(parts) > 3 and parts[1] in mounts and parts[2] == "Emulation":
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
