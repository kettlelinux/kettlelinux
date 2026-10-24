"""The Storage tab's moves: games from one storage's Emulation tree to another's (or copied, or
deleted), and the game data (storage.py's data_items(): saves, states, screenshots, the emulator
data folders) from one storage to another.

A game is its file, what its .m3u/.cue/.gdi lists (game_files()) or a whole game folder (PS3), and
keeps its path from the Emulation folder (roms/<system folder>/...), so the plugin finds it again
on the other storage with the same system, path and size: its shortcut, artwork and emulator
choice carry over (roms.carry_moves()). Each file is copied to a .part, synced, checked for its
size and renamed; on a move the source goes only once the whole game is there. A file that's at
the destination already, the same, isn't copied again; a different one there makes the game an
error ("already there, different"), never an overwrite. Free space is checked for the whole run
first, and a FAT32 card refuses a file of 4 GiB or more (that game only).

Moving the game data copies everything first and switches storage.json's "data" only when all of
it is there; then the old copy goes. A file at the destination already that's newer than the one
moved is kept (the old one stays where it was, and the run says so): a move never quietly
overwrites newer data.

Progress goes through `emit(dict)` as the importer's does (start, progress, item, done), so the
plugin shows it the same way.
"""
import os
import shutil
import time

from . import importer, storage, systems

PROGRESS_EVERY = 0.5
SPARE = importer.SPARE
FAT_MAX = (4 << 30) - 1
FAT = ("vfat", "msdos", "fat")


def _real(p):
    return os.path.realpath(p)


def game_files(path):
    """A game's files: a game folder's whole contents, or the file and what its sheet lists
    (that exists in its folder), each once."""
    if os.path.isdir(path):
        return [os.path.join(d, f) for d, _, fs in os.walk(path) for f in sorted(fs)]
    out, seen = [path], {importer._key(path)}
    if systems.ext_of(path) in ("m3u", "cue", "gdi"):
        d = os.path.dirname(path)
        for r in importer.sheet_refs(path):
            p = os.path.join(d, r)
            k = importer._key(p)
            if k not in seen:
                seen.add(k)
                out.append(p)
    return out


def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def game_size(path):
    return sum(_size(f) for f in game_files(path))


def tree_size(path):
    """A folder's (or a file's) size, links not followed."""
    if os.path.isfile(path):
        return _size(path)
    n = 0
    for d, _, fs in os.walk(path):
        for f in fs:
            try:
                n += os.lstat(os.path.join(d, f)).st_size
            except OSError:
                pass
    return n


def data_size(root, db):
    """How much game data a storage holds (data_items() where they'd be on it)."""
    return sum(tree_size(storage.locate(rel, db, root)) for rel, _, _ in storage.data_items(db))


def _emulation_of(path, roots):
    """The Emulation folder (of `roots`) a game is in, or None."""
    real = _real(path)
    for r in roots:
        emu = _real(storage.emulation_dir(r))
        if real.startswith(emu + "/"):
            return storage.emulation_dir(r)
    return None


def _prune(path, stop):
    """Removes the empty folders from `path`'s up to (not) `stop`."""
    d = os.path.dirname(path)
    stop = _real(stop)
    while _real(d).startswith(stop + "/"):
        try:
            os.rmdir(d)
        except OSError:
            return
        d = os.path.dirname(d)


def _fstype(emu, roots):
    for r in roots:
        if _real(storage.emulation_dir(r)) == _real(emu):
            return (r.get("fstype") or "").lower()
    return ""


def free_space(path):
    while path and not os.path.exists(path):
        path = os.path.dirname(path)
    return shutil.disk_usage(path or "/").free


class Copier:
    """Copies files with progress, as one run of `total` bytes."""

    def __init__(self, emit, total):
        self.emit = emit
        self.total = total
        self.done = 0
        self._last = 0

    def progress(self, src, force=False):
        now = time.monotonic()
        if force or now - self._last >= PROGRESS_EVERY:
            self._last = now
            self.emit({"event": "progress", "file": src, "bytes_done": self.done, "bytes": self.total})

    def copy(self, src, dst):
        """src to dst (replaced if it's there) through a .part: no half file is ever left."""
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.islink(src):
            if os.path.lexists(dst):
                os.unlink(dst)
            os.symlink(os.readlink(src), dst)
            return
        tmp = dst + ".part"
        try:
            with open(src, "rb") as fi, open(tmp, "wb") as fo:
                while chunk := fi.read(4 << 20):
                    fo.write(chunk)
                    self.done += len(chunk)
                    self.progress(src)
                fo.flush()
                os.fsync(fo.fileno())
            if os.path.getsize(tmp) != os.path.getsize(src):
                raise OSError(f"{os.path.basename(src)} came out a different size")
            try:
                shutil.copystat(src, tmp)
            except OSError:
                pass  # a FAT card keeps no modes
            os.replace(tmp, dst)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _same_dev(a, b):
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def transfer(paths, dest, mode="move", emit=None, roots=None):
    """Moves (or copies) these games into the Emulation folder `dest`. Raises ValueError, before
    anything is copied, when they don't fit."""
    emit = emit or (lambda ev: None)
    roots = storage.roots() if roots is None else roots
    stats = {"games": {}, "bios": [], "unsorted": 0, "identical": 0, "errors": 0}
    fat = _fstype(dest, roots) in FAT
    plans, need = [], 0
    for p in paths:
        src = _emulation_of(p, roots)
        plan = {"src": p, "emu": src, "files": [], "error": None, "system": None}
        plans.append(plan)
        if src is None:
            plan["error"] = "not on a storage's Emulation folder"
            continue
        rel = os.path.relpath(p, src)
        parts = rel.split("/")
        if parts[0] != "roms" or len(parts) < 3:
            plan["error"] = "not a game in a system's folder"
            continue
        plan["system"] = systems.by_folder(parts[1])
        if _real(src) == _real(dest):
            plan["error"] = "it's on that storage already"
            continue
        if not os.path.exists(p):
            plan["error"] = "it's gone"
            continue
        for f in game_files(p):
            to = os.path.join(dest, os.path.relpath(f, src))
            size = _size(f)
            if fat and size > FAT_MAX:
                plan["error"] = f"{os.path.basename(f)} is 4 GB or more: too big for a FAT32 card"
                break
            if os.path.lexists(to):
                if importer._same_file(f, to):
                    plan["files"].append((f, to, size, True))
                    continue
                plan["error"] = f"{os.path.relpath(to, dest)} is already there, different"
                break
            plan["files"].append((f, to, size, False))
            if not (mode == "move" and _same_dev(f, dest)):
                need += size
    if need and need + SPARE > free_space(dest):
        raise ValueError(f"not enough space: {need >> 20} MB needed, "
                         f"{max(free_space(dest) - SPARE, 0) >> 20} MB free")
    total = sum(sz for pl in plans for _, _, sz, same in pl["files"] if not same)
    emit({"event": "start", "dest": dest, "mode": mode, "files": len(plans), "bytes": total})
    cp = Copier(emit, total)
    for n, pl in enumerate(plans, 1):
        ev = {"event": "item", "src": pl["src"], "kind": "game", "system": pl["system"],
              "done": n, "files": len(plans), "dest": None}
        made = []
        try:
            if pl["error"]:
                raise ValueError(pl["error"])
            for f, to, _, same in pl["files"]:
                if same:
                    continue
                if mode == "move" and _same_dev(f, dest):
                    os.makedirs(os.path.dirname(to), exist_ok=True)
                    os.rename(f, to)
                else:
                    cp.copy(f, to)
                made.append(to)
            if mode == "move":
                for f, _, _, _ in pl["files"]:
                    if os.path.lexists(f):
                        os.unlink(f)
                    _prune(f, os.path.join(pl["emu"], "roms", os.path.relpath(f, pl["emu"]).split("/")[1]))
                if os.path.isdir(pl["src"]):
                    shutil.rmtree(pl["src"], ignore_errors=True)
                    _prune(pl["src"], os.path.join(pl["emu"], "roms"))
            fresh = [t for _, t, _, same in pl["files"] if not same]
            if pl["files"] and not fresh:
                stats["identical"] += 1
            ev.update(action=("moved" if mode == "move" else "copied") if fresh else "identical",
                      dest=os.path.join(dest, os.path.relpath(pl["src"], pl["emu"])))
            if pl["system"]:
                stats["games"][pl["system"]] = stats["games"].get(pl["system"], 0) + 1
        except BaseException as e:
            # a game half there would show as a broken one: what this run put there goes (a
            # cancel too; on a move its source files are all still where they were)
            if mode != "move" or all(os.path.lexists(f) for f, _, _, same in pl["files"] if not same):
                for t in made:
                    try:
                        os.unlink(t)
                    except OSError:
                        pass
            if not isinstance(e, (OSError, ValueError)):
                raise
            stats["errors"] += 1
            ev.update(action="error", reason=str(e) or type(e).__name__)
        emit(ev)
    cp.progress(None, force=True)
    emit(dict(stats, event="done"))
    return stats


def delete(paths, roots=None):
    """Deletes these games (with what their sheets list) from their storages; returns how many."""
    roots = storage.roots() if roots is None else roots
    n = 0
    for p in paths:
        emu = _emulation_of(p, roots)
        if emu is None or os.path.relpath(p, emu).split("/")[0] != "roms" or len(os.path.relpath(p, emu).split("/")) < 3:
            raise ValueError(f"not a game: {p}")
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            for f in game_files(p):
                try:
                    os.unlink(f)
                except FileNotFoundError:
                    pass
        _prune(p, os.path.join(emu, "roms", os.path.relpath(p, emu).split("/")[1]))
        n += 1
    return n


def _data_files(top):
    """(file, path from `top`) under a data folder (or the file itself), links as links."""
    if not os.path.lexists(top):
        return []
    if not os.path.isdir(top) or os.path.islink(top):
        return [(top, "")]
    out = []
    for d, dirs, fs in os.walk(top):
        for x in list(dirs):
            if os.path.islink(os.path.join(d, x)):
                fs.append(x)
                dirs.remove(x)
        for f in sorted(fs):
            p = os.path.join(d, f)
            out.append((p, os.path.relpath(p, top)))
    return out


def move_data(dest_root, db, emit=None, roots=None):
    """Moves the game data from the storage it's on to `dest_root` (a storage.roots() entry) and
    makes that the data storage. Raises ValueError before anything is copied when it doesn't fit,
    or when the data storage isn't in."""
    emit = emit or (lambda ev: None)
    roots = storage.roots() if roots is None else roots
    try:
        src_root = storage.data_root()
    except storage.DataMissing as e:
        raise ValueError(str(e))
    if storage.key(src_root) == storage.key(dest_root):
        raise ValueError("the game data is on that storage already")
    fat = (dest_root.get("fstype") or "").lower() in FAT
    files, need = [], 0
    for rel, _, eid in storage.data_items(db):
        a, b = storage.locate(rel, db, src_root), storage.locate(rel, db, dest_root)
        for f, sub in _data_files(a):
            to = os.path.join(b, sub) if sub else b
            files.append((f, to, eid))
            if not os.path.islink(f):
                need += _size(f)
    big = [f for f, _, _ in files if fat and not os.path.islink(f) and _size(f) > FAT_MAX]
    if big:
        raise ValueError(f"{os.path.basename(big[0])} is 4 GB or more: too big for a FAT32 card")
    dest_emu = storage.emulation_dir(dest_root)
    if need and need + SPARE > free_space(dest_emu):
        raise ValueError(f"not enough space: {need >> 20} MB needed, "
                         f"{max(free_space(dest_emu) - SPARE, 0) >> 20} MB free")
    emit({"event": "start", "dest": dest_emu, "mode": "move", "files": len(files), "bytes": need})
    cp = Copier(emit, need)
    moved, kept, errors = [], 0, 0
    for n, (f, to, eid) in enumerate(files, 1):
        ev = {"event": "item", "src": f, "kind": "data", "system": None, "emulator": eid,
              "done": n, "files": len(files), "dest": to}
        try:
            if os.path.lexists(to) and not os.path.islink(f) and importer._same_file(f, to):
                ev["action"] = "identical"
                moved.append(f)
            elif os.path.lexists(to) and os.lstat(to).st_mtime > os.lstat(f).st_mtime:
                # newer there: kept, and this one stays where it was
                ev.update(action="kept", reason="a newer copy is there already")
                kept += 1
            else:
                cp.copy(f, to)
                ev["action"] = "moved"
                moved.append(f)
        except OSError as e:
            errors += 1
            ev.update(action="error", reason=str(e) or type(e).__name__)
        emit(ev)
    if not errors:
        storage.save_settings(data=storage.key(dest_root),
                              data_label="" if dest_root.get("internal") else dest_root.get("label", ""))
        for f in moved:
            try:
                os.unlink(f)
            except OSError:
                pass
        src_tops = [storage.locate(rel, db, src_root) for rel, _, _ in storage.data_items(db)]
        for top in src_tops:
            if os.path.isdir(top) and not os.path.islink(top):
                for d, _, _ in sorted(os.walk(top), key=lambda w: -len(w[0])):
                    if d != top:
                        try:
                            os.rmdir(d)
                        except OSError:
                            pass
    cp.progress(None, force=True)
    stats = {"games": {}, "bios": [], "unsorted": 0, "identical": 0, "errors": errors,
             "kept": kept, "switched": not errors}
    emit(dict(stats, event="done"))
    return stats
