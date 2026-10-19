"""Sorting ROMs and BIOS files into an Emulation tree: from the inbox, a card or stick, or the
upload page. Each file is identified (identify.py) or recognised as a BIOS by its md5 (bios.py)
and copied or moved to <Emulation>/roms/<system folder> or ~/Emulation/bios. A .cue, .gdi or
.m3u brings the files it lists along; archives are unpacked unless the system plays them zipped
(arcade, DOS). An existing file is never overwritten: an identical one is skipped, a different
one makes the new file "Name (2).ext" (a multi-file set goes into a "Name (2)" folder, since
its .cue names its tracks), unless a "Name (n)" there is identical already. What can't be
identified goes to <Emulation>/inbox/unsorted.

Progress is reported through `emit(dict)`; the command line prints each as a JSON line.
"""
import hashlib
import itertools
import os
import shutil
import struct
import subprocess
import tempfile
import time
import zipfile
import zlib

from . import bios, identify, storage, switch, systems

# folders of an Emulation tree that are never imported from
TREE_DIRS = ("roms", "bios", "saves", "states", "backups", "screenshots")
UNSORTED = "unsorted"
UPLOAD_TMP = ".upload-tmp"
STAGING = ".staging-"
PROGRESS_EVERY = 0.5
# a .part or staging folder untouched this long is a dead run's (killed, or the device went off)
STALE = 3600
# unpacking leaves this much free on the disk
SPARE = 256 << 20
# what an archive that can't be read raises (encrypted: RuntimeError, Deflate64:
# NotImplementedError, truncated: EOFError or zlib.error)
ARCHIVE_ERRORS = (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error)


def _same_file(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
    except OSError:
        return False
    ha, hb = hashlib.md5(), hashlib.md5()
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(1 << 20), fb.read(1 << 20)
            if x != y:
                return False
            if not x:
                return True
            ha.update(x), hb.update(y)


def numbered(path, ext=True):
    """"Name (2).ext", "Name (3).ext"... for `path`, without end. ext=False: "Name (2)" for a
    folder, whatever dots its name has ("Super Mario Bros. 3 (2)")."""
    d, base = os.path.split(path)
    stem, dot, suffix = base.rpartition(".") if ext and "." in base.lstrip(".") else (base, "", "")
    n = 2
    while True:
        yield os.path.join(d, f"{stem} ({n}){dot}{suffix}")
        n += 1


def free_name(path):
    """`path`, or "Name (2).ext", "Name (3).ext"... the first that doesn't exist."""
    if not os.path.lexists(path):
        return path
    for cand in numbered(path):
        if not os.path.lexists(cand):
            return cand


def _samefile(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _inside(path, folder):
    folder = os.path.realpath(folder)
    return os.path.realpath(path).startswith(folder.rstrip("/") + "/")


def _key(path):
    """The same key for every name of a file: a cue's FILE "GAME.BIN" and the walk's Game.bin on
    a FAT or exFAT card are one file."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def sheet_refs(path):
    """identify.refs_of() for a sheet: the files it lists that exist in its folder (and don't
    lead out of it through a link)."""
    d = os.path.dirname(path)
    return [r for r in identify.refs_of(path)
            if os.path.isfile(os.path.join(d, r)) and _inside(os.path.join(d, r), d)]


def cleanup(emu):
    """Remove what killed runs left in an Emulation tree: .part files and inbox staging folders
    untouched for STALE seconds."""
    now = time.time()
    box = os.path.join(emu, "inbox")
    try:
        names = os.listdir(box)
    except OSError:
        names = []
    for n in names:
        p = os.path.join(box, n)
        if n.startswith(STAGING) and os.path.isdir(p) and not os.path.islink(p):
            newest = os.lstat(p).st_mtime
            for d, _, fs in os.walk(p):
                for f in fs:
                    try:
                        newest = max(newest, os.lstat(os.path.join(d, f)).st_mtime)
                    except OSError:
                        pass
            if now - newest > STALE:
                shutil.rmtree(p, ignore_errors=True)
    for sub in ("roms", "bios", os.path.join("inbox", UNSORTED)):
        for d, _, fs in os.walk(os.path.join(emu, sub)):
            for f in fs:
                p = os.path.join(d, f)
                try:
                    if f.endswith(".part") and now - os.lstat(p).st_mtime > STALE:
                        os.unlink(p)
                except OSError:
                    pass


def _safe_member(name):
    """An archive member's path made relative and free of '..', or None to skip it."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return os.path.join(*parts)


class Item:
    __slots__ = ("kind", "src", "system", "match", "refs", "entry", "size", "hint", "name")

    def __init__(self, kind, src, system=None, match=None, refs=(), entry=None, size=0, hint=None,
                 name=None):
        self.kind, self.src, self.system, self.match = kind, src, system, match
        self.refs, self.entry, self.size, self.hint = list(refs), entry, size, hint
        self.name = name  # a game folder's name when it isn't src's own (one at the walk's root)


# what a PS3 disc game folder holds; one found right in the inbox or a stick's root is these
PS3_MEMBERS = ("PS3_GAME", "PS3_DISC.SFB", "PS3_UPDATE")


def sfo_title(path):
    """The TITLE of a PS3 PARAM.SFO, or None."""
    try:
        with open(path, "rb") as f:
            data = f.read(64 << 10)
        if data[:4] != b"\0PSF":
            return None
        keys, values, count = struct.unpack_from("<III", data, 8)
        for i in range(count):
            koff, _fmt, length, _max, voff = struct.unpack_from("<HHIII", data, 20 + 16 * i)
            key = data[keys + koff:data.index(b"\0", keys + koff)]
            if key == b"TITLE":
                return data[values + voff:values + voff + length].split(b"\0")[0].decode(
                    "utf-8", "replace").strip() or None
    except (OSError, struct.error, ValueError):
        return None
    return None


def _folder_name(title):
    """A folder name from a game's title: no slashes, no leading dots."""
    name = "".join("_" if c in '/\\\0' else c for c in title).strip().lstrip(".")
    return name[:120] or "PS3 game"


class Importer:
    def __init__(self, dest, mode="copy", emit=None, settle=0):
        """dest: the Emulation folder to sort into; mode: "copy" or "move"; settle: skip files
        changed in the last `settle` seconds (still being copied in)."""
        self.dest = dest
        self.mode = mode
        self.emit = emit or (lambda ev: None)
        self.settle = settle
        self.stats = {"games": {}, "bios": [], "unsorted": 0, "identical": 0, "errors": 0}
        self._last = 0
        self._outer = None      # (bytes before, size, total, item number, items) of the archive
        self._offset = (0, 0)   # (items, bytes) of the storages sorted before this one (inbox())
        self._skip = set()
        for r in storage.roots():
            emu = storage.emulation_dir(r)
            self._skip.update(os.path.realpath(os.path.join(emu, d)) for d in TREE_DIRS)
            self._skip.add(os.path.realpath(os.path.join(emu, "inbox", UNSORTED)))
        self._skip.update(os.path.realpath(os.path.join(dest, d)) for d in TREE_DIRS)
        self._skip.add(os.path.realpath(os.path.join(dest, "inbox", UNSORTED)))

    # --- finding and classifying ---------------------------------------------------------

    def _walk(self, path):
        """The files under `path`. With settle, each entry at the top of `path` (a game's folder,
        or a file) is held whole while anything in it, a .part too, changed in the last `settle`
        seconds: a game's Disc1/, Disc2/, tracks and .m3u are copied in one after another and must
        not be sorted apart. `path`'s own times don't count (a file dropped beside the game, a
        run's own staging folder).
        A file's ctime counts as well as its mtime: a copy over SMB (Windows Explorer and many
        file managers) sets a finished file's mtime back to the source's."""
        if os.path.isfile(path):
            yield path
            return
        now = time.time()

        def fresh(p):
            try:
                st = os.stat(p)
            except OSError:
                return True
            return now - max(st.st_mtime, st.st_ctime) < self.settle

        def files_under(top):
            """(files, any fresh) of a top-level entry."""
            found, hot = [], False
            if os.path.isfile(top):
                return ([top] if not os.path.basename(top).startswith(".") else []), \
                    bool(self.settle) and fresh(top)
            for d, dirs, names in os.walk(top):
                dirs[:] = sorted(x for x in dirs if not x.startswith(".")
                                 and x not in storage.JUNK_DIRS
                                 and os.path.realpath(os.path.join(d, x)) not in self._skip)
                if self.settle and fresh(d):
                    hot = True
                for f in sorted(names):
                    p = os.path.join(d, f)
                    if self.settle and fresh(p):
                        hot = True
                    if not (f.startswith(".") or f.endswith(".part")):
                        found.append(p)
                if hot:
                    break
            return found, hot

        try:
            entries = sorted(os.listdir(path))
        except OSError:
            return
        for name in entries:
            top = os.path.join(path, name)
            if os.path.isdir(top) and (name.startswith(".") or name in storage.JUNK_DIRS
                                       or os.path.realpath(top) in self._skip):
                continue
            found, hot = files_under(top)
            if not hot:
                yield from found

    @staticmethod
    def _hint(path, top):
        """The system named by the nearest folder between `top` and the file."""
        d = os.path.dirname(os.path.realpath(path))
        top = os.path.realpath(top) if os.path.isdir(top) else os.path.dirname(os.path.realpath(top))
        while True:
            sid = systems.by_folder(os.path.basename(d))
            if sid:
                return sid
            if d == top or len(d) <= len(top) or d == os.path.dirname(d):
                return None
            d = os.path.dirname(d)

    @staticmethod
    def _game_folders(files):
        """The folders that are one game whole (systems.json "game_folders": a PS3 disc game is
        the folder holding PS3_GAME/PARAM.SFO): {folder: system}."""
        found = {}
        for sid, s in systems.systems().items():
            marker = s.get("game_folders", {}).get("marker")
            if not marker:
                continue
            tail = os.sep + marker.lower().replace("/", os.sep)
            for p in files:
                if p.lower().endswith(tail):
                    found[p[:len(p) - len(tail)]] = sid
        return found

    @staticmethod
    def _firmware_folders(files):
        """The folders holding a Switch firmware (switch.FIRMWARE_MIN .nca files or more, and no
        game): {folder: [its .nca files]}."""
        by_dir = {}
        for p in files:
            if p.lower().endswith(".nca"):
                by_dir.setdefault(os.path.dirname(p), []).append(p)
        games = [p for p in files if p.lower().endswith((".nsp", ".xci"))]
        return {d: sorted(ncas) for d, ncas in by_dir.items()
                if len(ncas) >= switch.FIRMWARE_MIN and not any(_inside(g, d) for g in games)}

    def plan(self, path, hint=None):
        """The Items for everything under `path` (hint: a system for files no folder names)."""
        files = list(self._walk(path))
        items = []
        firmware = self._firmware_folders(files)
        if firmware:
            root = os.path.realpath(path) if os.path.isdir(path) else None
            for d, ncas in sorted(firmware.items()):
                items.append(Item("firmware", d, "switch", identify.Match("switch", 1.0, "Switch firmware"),
                                  [os.path.relpath(p, d) for p in ncas],
                                  size=sum(os.path.getsize(p) for p in ncas),
                                  name="root" if os.path.realpath(d) == root else None))
            taken = {p for ncas in firmware.values() for p in ncas}
            files = [p for p in files if p not in taken]
        folders = self._game_folders(files)
        if folders:
            inside = lambda p, d: p.startswith(d + os.sep)  # noqa: E731
            root = os.path.realpath(path) if os.path.isdir(path) else None
            taken = []
            for d, sid in sorted(folders.items()):
                at_root = os.path.realpath(d) == root
                if at_root:
                    # PS3_GAME/ right in the inbox or a stick's root: never the walk root itself;
                    # its members go into a folder named after the game
                    members = [p for p in files if any(
                        p == os.path.join(d, m) or inside(p, os.path.join(d, m)) for m in PS3_MEMBERS)]
                    name = _folder_name(sfo_title(os.path.join(d, "PS3_GAME", "PARAM.SFO"))
                                        or "PS3 game")
                else:
                    members = [p for p in files if inside(p, d)]
                    name = None
                taken += members
                size = sum(os.path.getsize(p) for p in members if os.path.isfile(p))
                items.append(Item("game", d, sid, identify.Match(sid, 1.0, "game folder"),
                                  [os.path.relpath(p, d) for p in members], size=size, name=name))
            taken = set(taken)
            files = [p for p in files if p not in taken and not any(
                inside(p, d) for d in folders if os.path.realpath(d) != root)]
        settled = {_key(p) for p in files} if self.settle else None
        consumed = set()
        held = set()  # sheets with a file still being copied, and what they list: next round
        refs_of = {}
        for p in files:
            if systems.ext_of(p) in ("cue", "gdi", "m3u"):
                d = os.path.dirname(p)
                refs = sheet_refs(p)
                keys = [_key(os.path.join(d, r)) for r in refs]
                if settled is not None and any(k not in settled for k in keys):
                    # an FF7.m3u whose Disc1/ is still coming: imported alone, its path to the
                    # disc would never resolve
                    held.add(_key(p))
                    held.update(keys)
                    continue
                refs_of[p] = refs
                consumed.update(keys)
        cache = bios._Md5Cache()
        for p in files:
            if _key(p) in consumed or _key(p) in held:
                continue
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            h = self._hint(p, path) or hint
            if systems.ext_of(p) == "zip" and switch.is_firmware(p):
                items.append(Item("firmware", p, "switch", identify.Match("switch", 1.0, "Switch firmware"),
                                  size=size))
                continue
            if p not in refs_of and size <= bios.MAX_SIZE:
                try:
                    rec = bios.recognise(p, cache=cache)
                except OSError:
                    rec = None
                if rec:
                    items.append(Item("bios", p, rec[0], entry=rec[1], size=size))
                    continue
            m = identify.identify(p, h)
            refs = refs_of.get(p, ())
            size += sum(os.path.getsize(os.path.join(os.path.dirname(p), r)) for r in refs)
            if m and m.extract:
                # the inner file's system becomes the hint (0.95 for its extension) only when it
                # would be sorted on its own: a weak guess stays one, and claims no system (scan()
                # lists it as unsorted, the item event names none)
                sure = m.system if m.confidence >= identify.SORT_AT else None
                items.append(Item("extract", p, sure, m, size=size, hint=sure or h))
            elif m and m.system and m.confidence >= identify.SORT_AT:
                items.append(Item("game", p, m.system, m, refs, size=size))
            elif systems.ext_of(p) in identify.JUNK_EXTS:
                continue
            else:
                items.append(Item("unsorted", p, m.system if m else None, m, refs, size=size))
        cache.save()
        return items

    # --- doing ---------------------------------------------------------------------------

    def _progress(self, src, done, total, force=False):
        now = time.monotonic()
        if force or now - self._last >= PROGRESS_EVERY:
            self._last = now
            if self._outer:
                # an archive's contents: within the archive's share of the outer run
                ob, osize, ototal = self._outer[:3]
                done, total = ob + osize * min(done, total) // max(total, 1), ototal
            self.emit({"event": "progress", "file": src, "bytes_done": done + self._offset[1],
                       "bytes": total + self._offset[1]})

    def _transfer(self, src, dst, base=0, total=0):
        """Copy or move one file to `dst` (which must not exist); returns bytes written."""
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if self.mode == "move":
            try:
                os.rename(src, dst)
                return os.path.getsize(dst)
            except OSError:
                pass  # another filesystem: copy, then remove
        tmp = dst + ".part"
        n = 0
        try:
            with open(src, "rb") as fi, open(tmp, "wb") as fo:
                while True:
                    chunk = fi.read(4 << 20)
                    if not chunk:
                        break
                    fo.write(chunk)
                    n += len(chunk)
                    self._progress(src, base + n, total)
            shutil.copystat(src, tmp)
            os.replace(tmp, dst)
        except BaseException:
            # a full disk, a pulled card, a cancel: no half file left behind
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        if self.mode == "move":
            os.unlink(src)
        return n

    def _drop(self, paths):
        if self.mode == "move":
            for p in paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    @staticmethod
    def _clash(item, members, target_dir):
        """Whether a file of the set would land on a different one that's there already."""
        for m, r in zip(members, item.refs):
            mdst = os.path.join(target_dir, r)
            if os.path.lexists(mdst) and not _samefile(m, mdst) and not _same_file(m, mdst):
                return True
        return False

    def _place(self, item, target_dir, base, total):
        """Put a file and the files it lists into target_dir; (action, dest path)."""
        src_dir = os.path.dirname(item.src)
        name = os.path.basename(item.src)
        members = [os.path.join(src_dir, r) for r in item.refs]
        for m, r in zip(members, item.refs):
            if not _inside(m, src_dir) or not _inside(os.path.join(target_dir, r), target_dir):
                raise ValueError(f"{name} lists a file outside its folder: {r}")
        dst = os.path.join(target_dir, name)
        if _samefile(item.src, dst):
            return "identical", dst  # in its place already (a run over a roms folder)
        same = False
        if os.path.lexists(dst) or self._clash(item, members, target_dir):
            if os.path.lexists(dst) and _same_file(item.src, dst) and \
                    not self._clash(item, members, target_dir):
                same = True
            elif item.refs:
                # a different set: into "Name (n)/", the first free one ("Name/" when only its
                # tracks clash: two discs with track01.bin...), unless one holds this set already
                # (a card imported again)
                stem = os.path.join(target_dir, name.rpartition(".")[0] or name)
                first = [] if os.path.lexists(dst) else [stem]
                for cand in itertools.chain(first, numbered(stem, ext=False)):
                    cdst = os.path.join(cand, name)
                    if not os.path.lexists(cand):
                        target_dir, dst = cand, cdst
                        break
                    if os.path.isdir(cand) and os.path.isfile(cdst) and _same_file(item.src, cdst) \
                            and not self._clash(item, members, cand):
                        target_dir, dst, same = cand, cdst, True
                        break
            else:
                for cand in numbered(dst):
                    if not os.path.lexists(cand):
                        dst = cand
                        break
                    if _same_file(item.src, cand):
                        dst, same = cand, True
                        break
        done = base
        for m, r in zip(members, item.refs):
            mdst = os.path.join(target_dir, r)
            if not os.path.lexists(mdst):
                done += self._transfer(m, mdst, done, total)
            elif not _samefile(m, mdst):
                self._drop([m])  # identical: _clash() checked
        if same:
            self._drop([item.src])
            return "identical", dst
        self._transfer(item.src, dst, done, total)
        return ("moved" if self.mode == "move" else "copied"), dst

    def _write_cue(self, bin_path, system):
        with open(bin_path, "rb") as f:
            d = identify.Disc(f)
        mode = "MODE1/2048" if not d.raw else ("MODE2/2352" if d.off == 24 else "MODE1/2352")
        cue = free_name(bin_path.rpartition(".")[0] + ".cue")
        with open(cue, "w") as f:
            f.write(f'FILE "{os.path.basename(bin_path)}" BINARY\n  TRACK 01 {mode}\n    INDEX 01 00:00:00\n')
        return cue

    def _place_folder(self, item, target_dir, base, total):
        """A game that is a folder (a PS3 disc game) into target_dir/<its name>, every file in its
        place; a different game of that name goes to "<name> (n)"."""
        name = item.name or os.path.basename(item.src)
        members = [os.path.join(item.src, r) for r in item.refs]
        dst = os.path.join(target_dir, name)
        if _samefile(item.src, dst):
            return "identical", dst
        for cand in itertools.chain([dst], numbered(dst, ext=False)):
            if not os.path.lexists(cand):
                dst = cand
                break
            if os.path.isdir(cand) and all(
                    os.path.isfile(os.path.join(cand, r)) and _same_file(m, os.path.join(cand, r))
                    for m, r in zip(members, item.refs)):
                self._drop(members)
                return "identical", cand
        done = base
        for m, r in zip(members, item.refs):
            if not _inside(os.path.join(dst, r), dst):
                raise ValueError(f"{name} holds a file outside it: {r}")
            done += self._transfer(m, os.path.join(dst, r), done, total)
        if self.mode == "move":
            self._prune(members, item.src, keep_top=bool(item.name))
        return ("moved" if self.mode == "move" else "copied"), dst

    @staticmethod
    def _prune(members, top, keep_top):
        """After a move: the folders the members left empty, deepest first, up to top (top too,
        unless it's the walk's root: keep_top). Nothing that still holds a file goes."""
        dirs = set()
        for m in members:
            d = os.path.dirname(m)
            while _inside(d, top) and d != top:
                dirs.add(d)
                d = os.path.dirname(d)
        if not keep_top:
            dirs.add(top)
        for d in sorted(dirs, key=len, reverse=True):
            try:
                os.rmdir(d)
            except OSError:
                pass

    def _game(self, item, base, total):
        target = os.path.join(self.dest, "roms", systems.folder(item.system))
        if os.path.isdir(item.src):
            action, dst = self._place_folder(item, target, base, total)
        else:
            action, dst = self._place(item, target, base, total)
        if action != "identical" and item.match and item.match.needs_cue:
            dst = self._write_cue(dst, item.system)
        if action != "identical":
            g = self.stats["games"]
            g[item.system] = g.get(item.system, 0) + 1
        else:
            self.stats["identical"] += 1
        return action, dst

    def _firmware(self, item, base, total):
        """A Switch firmware (a zip, or a folder's .nca files) into internal storage's
        Emulation/bios/switch/firmware, replacing the one there whole (emu-run installs it into
        the emulators: switch.install_firmware). Staged and swapped in, so a failed copy leaves
        the old one; a move removes the source only once the new one is in place."""
        dest = switch.firmware_dir()
        parent = os.path.dirname(dest)
        stage, old = os.path.join(parent, ".firmware-new"), os.path.join(parent, ".firmware-old")
        for d in (stage, old):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(stage)
        members = [os.path.join(item.src, r) for r in item.refs] if os.path.isdir(item.src) else [item.src]
        mode, self.mode = self.mode, "copy"
        try:
            done = base
            for m in members:
                done += self._transfer(m, os.path.join(stage, os.path.basename(m)), done, total)
            if os.path.isdir(dest):
                os.rename(dest, old)
            os.rename(stage, dest)
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            if os.path.isdir(old) and not os.path.exists(dest):
                os.rename(old, dest)
            raise
        finally:
            self.mode = mode
        shutil.rmtree(old, ignore_errors=True)
        if self.mode == "move":
            self._drop(members)
            if os.path.isdir(item.src):
                self._prune(members, item.src, keep_top=item.name == "root")
        return "installed", dest

    def _unsorted(self, item, base, total):
        """Moved to inbox/unsorted for the plugin to ask about. A copy (from a card or stick) leaves
        it where it is: whatever else is on a stick isn't the inbox's business."""
        self.stats["unsorted"] += 1
        if self.mode != "move":
            return "left", None
        target = os.path.join(self.dest, "inbox", UNSORTED)
        action, dst = self._place(item, target, base, total)
        return ("unsorted" if action != "identical" else "identical"), dst

    def _unpacked_size(self, item):
        """What unpacking the archive takes on the disk; OSError when it doesn't fit (a zip bomb,
        or just a full disk)."""
        members = identify.archive_members(item.src)
        if members is None:
            raise OSError(f"can't read {os.path.basename(item.src)}")
        need = sum(s for _, s in members)
        free = shutil.disk_usage(os.path.join(self.dest, "inbox")).free
        if need > free - SPARE:
            raise OSError(f"unpacking {os.path.basename(item.src)} needs {need >> 20} MiB, "
                          f"{max(free - SPARE, 0) >> 20} MiB free")
        return need

    def _extract(self, item, outer):
        """Unpack an archive into a staging folder on the destination's storage and import what's
        in it (moved from there). outer: (bytes before, size, total, item number, items) of the
        archive in this run, for the sub-run's progress."""
        inbox = os.path.join(self.dest, "inbox")
        os.makedirs(inbox, exist_ok=True)
        self._unpacked_size(item)
        staging = tempfile.mkdtemp(prefix=STAGING, dir=inbox)
        try:
            if systems.ext_of(item.src) == "zip":
                with zipfile.ZipFile(item.src) as z:
                    for info in z.infolist():
                        rel = None if info.is_dir() else _safe_member(info.filename)
                        if not rel:
                            continue
                        out = os.path.join(staging, rel)
                        os.makedirs(os.path.dirname(out), exist_ok=True)
                        with z.open(info) as fi, open(out, "wb") as fo:
                            left = info.file_size
                            while True:
                                chunk = fi.read(4 << 20)
                                if not chunk:
                                    break
                                left -= len(chunk)
                                if left < 0:
                                    raise OSError(f"{info.filename}: bigger than the zip says")
                                fo.write(chunk)
            else:
                r = subprocess.run(["7z", "x", "-y", "-bd", "-o" + staging, "--", item.src],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    raise OSError(r.stderr.strip() or "7z failed")
                real = os.path.realpath(staging)
                for d, _, fs in os.walk(staging):
                    for f in fs:
                        if not os.path.realpath(os.path.join(d, f)).startswith(real + os.sep):
                            raise OSError("archive member outside its folder")
            sub = Importer(self.dest, "move", self.emit)
            sub._skip = self._skip
            sub.stats = self.stats
            sub._outer = outer
            sub._offset = self._offset
            errors = self.stats["errors"]
            sub.run_items(sub.plan(staging, item.hint), archive=item.src)
            if self.stats["errors"] == errors:
                self._drop([item.src])
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def run_items(self, items, archive=None):
        total = sum(i.size for i in items)
        if archive is None:
            self.emit({"event": "start", "dest": self.dest, "mode": self.mode,
                       "files": len(items), "bytes": total})
        base = 0
        for n, item in enumerate(items, 1):
            # an archive's contents count as the archive's item; inbox() counts on across storages
            done, count = self._outer[3:5] if self._outer else (n, len(items))
            ev = {"event": "item", "src": item.src, "kind": item.kind, "system": item.system,
                  "done": done + self._offset[0], "files": count + self._offset[0]}
            if archive:
                ev["archive"] = archive
            try:
                if item.kind == "bios":
                    action, dst = bios.install(item.src, item.entry, self.mode == "move")
                    self.stats["bios"].append({"system": item.system, "file": item.entry["file"],
                                               "dest": dst})
                elif item.kind == "firmware":
                    action, dst = self._firmware(item, base, total)
                    self.stats["bios"].append({"system": "switch", "file": "firmware", "dest": dst})
                elif item.kind == "game":
                    action, dst = self._game(item, base, total)
                elif item.kind == "extract":
                    self.emit(dict(ev, action="extracting", dest=None,
                                   reason=item.match.reason if item.match else ""))
                    self._extract(item, self._outer or (base, item.size, total, n, len(items)))
                    base += item.size
                    continue
                else:
                    action, dst = self._unsorted(item, base, total)
                ev.update(action=action, dest=dst,
                          reason=item.match.reason if item.match else ("BIOS" if item.entry else "unknown"))
            except (OSError, ValueError) + ARCHIVE_ERRORS as e:
                self.stats["errors"] += 1
                ev.update(action="error", dest=None, reason=str(e) or type(e).__name__)
                if item.kind == "extract" and self.mode == "move":
                    # out of the inbox, so the next round doesn't try it again
                    try:
                        ev["dest"] = self._unsorted(item, base, total)[1]
                    except (OSError, ValueError):
                        pass
            base += item.size
            self.emit(ev)
        if archive is None:
            self._progress(None, total, total, force=True)
            self.emit(dict(self.stats, event="done"))
        return self.stats

    def run(self, path, hint=None):
        """Import everything under `path`. Refused (ValueError) inside an Emulation tree's own
        folders: moving roms/ onto itself would delete the games."""
        real = os.path.realpath(path)
        for d in self._skip:
            if real == d or real.startswith(d.rstrip("/") + "/"):
                raise ValueError(f"{path} is inside an Emulation folder ({os.path.basename(d)})")
        cleanup(self.dest)
        return self.run_items(self.plan(path, hint))


def scan(path):
    """What importing `path` would do, without doing it."""
    imp = Importer(storage.home(), "copy")
    items = imp.plan(path)
    status = bios.status()
    games, unsorted, found = {}, [], []
    for i in items:
        if i.kind in ("game", "extract") and i.system:
            games[i.system] = games.get(i.system, 0) + 1
        elif i.kind == "firmware":
            found.append({"system": "switch", "file": "firmware", "src": i.src,
                          "installed": switch.find_firmware() is not None})
        elif i.kind == "bios":
            have = any(e["found"] for e in status.get(i.system, {}).get("entries", ())
                       if e["file"] == i.entry["file"])
            found.append({"system": i.system, "file": i.entry["file"], "src": i.src,
                          "installed": have})
        else:
            unsorted.append(i.src)
    return {"path": path, "games": games, "games_total": sum(games.values()), "bios": found,
            "unsorted": unsorted[:50], "unsorted_count": len(unsorted),
            "bytes": sum(i.size for i in items),
            "has_emulation_tree": os.path.isdir(os.path.join(path, "Emulation", "roms"))}


def inbox(emit, settle=30):
    """Sort every storage's inbox into its own Emulation tree (moving). The item and byte counts
    go on from one storage to the next, as one run."""
    stats = []
    offset = (0, 0)
    for r in storage.roots():
        emu = storage.emulation_dir(r)
        box = os.path.join(emu, "inbox")
        if not os.path.isdir(box):
            continue
        emit({"event": "inbox", "root": emu, "internal": r["internal"]})
        imp = Importer(emu, "move", emit, settle)
        imp._offset = offset
        cleanup(emu)
        items = imp.plan(box)
        stats.append(imp.run_items(items))
        offset = (offset[0] + len(items), offset[1] + sum(i.size for i in items))
    return stats


def unsorted():
    """What every storage's inbox/unsorted holds, for the plugin to ask about: [{path, name, size,
    root (its Emulation folder), internal, systems (the likely ones)}]. A .cue, .gdi or .m3u
    stands for its set (size: all of it); the files it lists aren't listed on their own. Sets that
    clashed are in "Name (n)" folders below it."""
    out = []
    for r in storage.roots():
        emu = storage.emulation_dir(r)
        top = os.path.join(emu, "inbox", UNSORTED)
        found = []
        for d, dirs, files in os.walk(top):
            dirs[:] = sorted(x for x in dirs if not x.startswith("."))
            found += [os.path.join(d, f) for f in sorted(files)
                      if not f.startswith(".") and not f.endswith(".part")]
        listed = set()
        sets = {}
        for p in found:
            if systems.ext_of(p) in ("cue", "gdi", "m3u"):
                refs = sheet_refs(p)
                sets[p] = refs
                listed.update(_key(os.path.join(os.path.dirname(p), x)) for x in refs)
        for p in found:
            if _key(p) in listed:
                continue
            try:
                size = os.path.getsize(p) + sum(os.path.getsize(os.path.join(os.path.dirname(p), x))
                                                for x in sets.get(p, ()))
            except OSError:
                continue
            out.append({"path": p, "name": os.path.relpath(p, top), "size": size, "root": emu,
                        "internal": r["internal"], "systems": identify.candidates(p)})
    return out


def _unsorted_root(path):
    """The Emulation folder whose inbox/unsorted holds `path`, or None."""
    for r in storage.roots():
        emu = storage.emulation_dir(r)
        if _inside(path, os.path.join(emu, "inbox", UNSORTED)):
            return emu
    return None


def assign(path, sid, dest=None, emit=None):
    """Sort a file the importer couldn't identify (in inbox/unsorted) as the system the user
    picked, with the files it lists; into the tree of the storage it's on unless `dest` says."""
    if sid not in systems.systems():
        raise ValueError(f"unknown system: {sid}")
    imp = Importer(dest or _unsorted_root(path) or storage.home(), "move", emit)
    refs = sheet_refs(path) if systems.ext_of(path) in ("cue", "gdi", "m3u") else []
    size = os.path.getsize(path) + sum(os.path.getsize(os.path.join(os.path.dirname(path), r)) for r in refs)
    m = identify.Match(sid, 1.0, "picked by the user", refs=tuple(refs))
    kind = "extract" if systems.ext_of(path) in identify.ARCHIVES and not systems.keeps_archives(sid) else "game"
    return imp.run_items([Item(kind, path, sid, m, refs, size=size, hint=sid)])
