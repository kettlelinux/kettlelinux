"""BIOS files: which ones each system wants (systems.json), which are installed in ~/Emulation/bios,
and recognising one anywhere by its md5, whatever its name. Kettle never ships a BIOS; the only
system ROMs it downloads are C-BIOS, which is free (BSD): blueMSX's MSX BIOS, in the Machines
folder that comes with that core from Emulation > Emulators (the plugin's cores.py). The real MSX,
ColecoVision and Spectravideo ROMs in the same buildbot pack are left out; users put their own in
Emulation/bios/Machines.

An entry is found only where the emulators look: install_dir()/<dest or file>, with one of its
md5s (entries without md5s, melonDS's firmware.bin: every console's differs, by size instead).
A file with a right md5 anywhere else in a BIOS folder (another name, a subfolder, a card's
Emulation/bios) is reported as "elsewhere", for install_found() to copy into place. A file with
the entry's name but another md5 is reported as bad.
"""
import hashlib
import json
import os
import shutil

from . import storage, systems

# nothing bigger is a BIOS (the biggest listed, dc_boot.bin, is 2 MiB)
MAX_SIZE = 8 << 20


def cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "kettle", "emulation", "bios-md5.json")


class _Md5Cache:
    """md5s by path, kept while the file's size and mtime stay the same."""

    def __init__(self):
        self.path = cache_path()
        try:
            with open(self.path) as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.dirty = False

    def md5(self, path, st=None):
        st = st or os.stat(path)
        key = f"{st.st_size}:{st.st_mtime_ns}"
        hit = self.data.get(path)
        if hit and hit[0] == key:
            return hit[1]
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        self.data[path] = [key, h.hexdigest()]
        self.dirty = True
        return h.hexdigest()

    def save(self):
        if not self.dirty:
            return
        # only a cache: a full disk costs the next check its speed, never the check
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError:
            pass


def bios_roots():
    """The BIOS folders: internal storage's first, then each card's."""
    return [os.path.join(storage.emulation_dir(r), "bios") for r in storage.roots()]


def install_dir():
    """Where recognised BIOS files are copied: internal storage's, which emu-seed links into the
    emulators' own BIOS paths."""
    return os.path.join(storage.home(), "bios")


def _files(root, depth=3):
    try:
        with os.scandir(root) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                if e.is_dir(follow_symlinks=False) and depth:
                    yield from _files(e.path, depth - 1)
                elif e.is_file():
                    yield e
    except OSError:
        return


def _present(cache):
    """{md5: path} and {lowercased name: [(path, size)]} of the files in the BIOS folders."""
    by_md5, by_name = {}, {}
    for root in bios_roots():
        for e in _files(root):
            st = e.stat()
            by_name.setdefault(e.name.lower(), []).append((e.path, st.st_size))
            if st.st_size <= MAX_SIZE:
                try:
                    by_md5.setdefault(cache.md5(e.path, st), e.path)
                except OSError:
                    pass
    return by_md5, by_name


def dest_of(entry):
    """Where an entry's file has to be: install_dir()/<dest or file>."""
    return os.path.join(install_dir(), entry.get("dest", entry["file"]))


def _has_magic(entry, path):
    """An entry with "magic" (a firmware too big to md5, the PS3's PS3UPDAT.PUP: "SCEUF"):
    whether the file starts with it."""
    magic = entry["magic"].encode()
    try:
        with open(path, "rb") as f:
            return f.read(len(magic)) == magic
    except OSError:
        return False


def _right(entry, path, size, cache):
    if entry.get("magic"):
        return _has_magic(entry, path)
    md5s = [m.lower() for m in entry.get("md5", ())]
    if md5s:
        try:
            return size <= MAX_SIZE and cache.md5(path) in md5s
        except OSError:
            return False
    sizes = entry.get("sizes")
    return not sizes or size in sizes


def _lookup(entry, by_md5, by_name, cache):
    """(found path or None, elsewhere path or None, bad path or None): found is the installed
    file; elsewhere a right one that isn't there."""
    dest = dest_of(entry)
    try:
        st = os.stat(dest)
        here = os.path.isfile(dest)
    except OSError:
        here = False
    if here and _right(entry, dest, st.st_size, cache):
        return dest, None, None
    names = {entry["file"].lower(), os.path.basename(entry.get("dest", entry["file"])).lower()}
    named = [x for n in names for x in by_name.get(n, ())]
    elsewhere = None
    for m in (m.lower() for m in entry.get("md5", ())):
        if m in by_md5 and by_md5[m] != dest:
            elsewhere = by_md5[m]
            break
    if not entry.get("md5"):
        elsewhere = next((p for p, size in named if p != dest and _right(entry, p, size, cache)), None)
    bad = dest if here else next((p for p, _ in named if p != elsewhere), None)
    return None, elsewhere, bad


def status(sid=None):
    """{system: {"state": "ok" | "missing-required" | "missing-optional" | "none",
    "entries": [{file, required, note, found, elsewhere, bad}]}} for every system (or just `sid`);
    found (installed where the emulators look), elsewhere (a right file somewhere else, for
    install_found()) and bad are paths or None."""
    cache = _Md5Cache()
    by_md5, by_name = _present(cache)
    out = {}
    for s, sysdef in systems.systems().items():
        if sid and s != sid:
            continue
        entries = []
        for b in sysdef.get("bios", ()):
            found, elsewhere, bad = _lookup(b, by_md5, by_name, cache)
            entries.append({"file": b["file"], "required": bool(b.get("required")),
                            "one_of": b.get("required") == "one",
                            "note": b.get("note", ""), "found": found, "elsewhere": elsewhere,
                            "bad": bad})
        if not entries:
            state = "none"
        elif unmet(entries):
            state = "missing-required"
        elif all(e["found"] for e in entries):
            state = "ok"
        else:
            state = "missing-optional"
        out[s] = {"state": state, "entries": entries}
    cache.save()
    return out


def unmet(entries):
    """What's missing of status()'s entries: each required file not found, and "a, b or c" for
    entries marked "required": "one" (a region's file each: any one of them is enough)."""
    out = [e["file"] for e in entries if e["required"] and not e["one_of"] and not e["found"]]
    one = [e for e in entries if e["one_of"]]
    if one and not any(e["found"] for e in one):
        names = [e["file"] for e in one]
        out.append(names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1])
    return out


def missing_required(sid):
    """What `sid` still needs of its required BIOS (unmet()); [] if nothing. A file found
    elsewhere counts as missing until install_found() puts it in place."""
    st = status(sid).get(sid)
    return unmet(st["entries"]) if st else []


def install_found(sid=None):
    """Copy every BIOS file status() found elsewhere (another name, a subfolder, a card) to where
    the emulators look, for every system or just `sid`; the names of the files installed. One
    that fails to copy is left out (status() still reports it elsewhere)."""
    done = []
    for s, st in status(sid).items():
        entries = dict((b["file"], b) for b in systems.systems()[s].get("bios", ()))
        for e in st["entries"]:
            if e["found"] or not e["elsewhere"]:
                continue
            try:
                action, _ = install(e["elsewhere"], entries[e["file"]])
            except OSError:
                continue
            if action == "installed" and e["file"] not in done:
                done.append(e["file"])
    return done


def recognise(path, md5=None, cache=None):
    """(system, entry) if the file is a known BIOS: by md5, or for an entry without md5s by its
    name and size. None otherwise."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size == 0:
        return None
    entries = systems.bios_entries()
    for sid, b in entries:  # by their first bytes, whatever their size or name
        if b.get("magic") and _has_magic(b, path):
            return sid, b
    if size > MAX_SIZE:
        return None
    name = os.path.basename(path).lower()
    if md5 is None:
        try:
            md5 = (cache or _Md5Cache()).md5(path)
        except OSError:
            return None
    for sid, b in entries:
        if md5 in [m.lower() for m in b.get("md5", ())]:
            return sid, b
    for sid, b in entries:
        if not b.get("md5") and name == b["file"].lower() and (not b.get("sizes") or size in b["sizes"]):
            return sid, b
    return None


def install(path, entry, move=False):
    """Copy (or move) a recognised BIOS file to install_dir()/<dest or file>. An identical file
    there is left alone; a different one is kept as <name>.old (<name> (2).old... when there is
    one already). Returns (action, dest path): action "installed" or "identical"."""
    from .importer import free_name  # importer imports this module
    dest = dest_of(entry)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.realpath(path) == os.path.realpath(dest):
        return "identical", dest
    if os.path.exists(dest):
        if _same(path, dest):
            if move:
                os.unlink(path)
            return "identical", dest
        os.rename(dest, free_name(dest + ".old"))
    tmp = dest + ".part"
    try:
        shutil.copyfile(path, tmp)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if move:
        os.unlink(path)
    return "installed", dest


def _same(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        c = _Md5Cache()
        return c.md5(a) == c.md5(b)
    except OSError:
        return False
