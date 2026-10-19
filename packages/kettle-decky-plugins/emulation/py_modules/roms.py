# The ROMs on every storage, and what the Steam library needs doing to match them. Pure: the
# storages, systems and state are passed in (main.py reads them), so the tests run anywhere.
#
# A ROM is a file of one of its system's extensions under <Emulation>/roms/<a system folder>,
# up to DEPTH folders down (a multi-disc game's folder). A .m3u, .cue or .gdi stands for the files
# it lists, which don't show on their own. A system with "game_folders" (PS3: a disc copied as a
# folder holding PS3_GAME/PARAM.SFO) also has folders as games: a folder holding its "marker" is
# one game, the folder itself the ROM's path, with nothing inside it listed; its title is the one
# in PARAM.SFO, or the folder's name. Its id is sha1("<storage uuid>:<path from Emulation>"),
# so it stays the same when a card mounts somewhere else. The same game (system and path in its
# folder, any case) on internal storage and on a card shows once, from internal storage. A game
# that moves to another storage (a card's copied in) keeps its shortcut: carry_moves().
#
# plan() compares a scan with the state (roms.json: each ROM's Steam appid and whether it has its
# artwork and controller layout) and returns what the frontend does to the library:
# - add: a ROM without a shortcut, unless the user deleted its shortcut in Steam (never again);
# - update: a ROM whose shortcut runs another path now (a card in another slot);
# - remove: a ROM whose storage is in but whose file is gone. A pulled card's games keep theirs,
#   and so do those of a storage whose scan hit an I/O error (a flaky card isn't a deletion).
import hashlib
import os
import re
import struct

DEPTH = 3
LIST_EXTS = ("m3u", "cue", "gdi")


def rom_id(uuid: str, rel: str) -> str:
    # os.fsencode: a name that isn't UTF-8 comes from scandir with surrogate escapes
    return hashlib.sha1(os.fsencode(f"{uuid}:{rel}")).hexdigest()


def _ext(name: str) -> str:
    base = os.path.basename(name)
    return base.rpartition(".")[2].lower() if "." in base.lstrip(".") else ""


def listed_files(path: str) -> list[str]:
    """The files a .m3u, .cue or .gdi names, as absolute paths (missing ones too)."""
    ext = _ext(path)
    d = os.path.dirname(path)
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read(1 << 20).splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        name = None
        if ext == "m3u":
            if line and not line.startswith("#"):
                name = line
        elif ext == "cue":
            m = re.match(r'(?i)FILE\s+(?:"([^"]+)"|(\S+))', line)
            if m:
                name = m.group(1) or m.group(2)
        elif ext == "gdi":
            # track lba type sector-size file offset; the file name may be quoted
            m = re.match(r'\d+\s+\d+\s+\d+\s+\d+\s+(?:"([^"]+)"|(\S+))', line)
            if m:
                name = m.group(1) or m.group(2)
        if name:
            out.append(os.path.normpath(os.path.join(d, name.replace("\\", "/"))))
    return out


_TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")


def title(path: str) -> str:
    """The name the library shows: the file name without its extension and No-Intro tags (a game
    folder's name keeps its dots)."""
    stem = os.path.basename(path)
    if _ext(stem) and not os.path.isdir(path):
        stem = stem.rpartition(".")[0]
    clean = _TAGS.sub("", stem).strip(" -_")
    return clean or stem


def sfo_title(path: str) -> str | None:
    """TITLE from a PlayStation PARAM.SFO (header: magic, version, key table, data table, count;
    then 16-byte entries: key offset, format, used length, max length, data offset)."""
    try:
        with open(path, "rb") as f:
            data = f.read(64 << 10)
        magic, _, keys, values, n = struct.unpack_from("<4sIIII", data, 0)
        if magic != b"\0PSF" or n > 256:
            return None
        for i in range(n):
            koff, fmt, used, _, doff = struct.unpack_from("<HHIII", data, 20 + 16 * i)
            end = data.index(b"\0", keys + koff)
            if data[keys + koff:end] == b"TITLE" and fmt in (0x0204, 0x0004):
                t = data[values + doff:values + doff + used].split(b"\0")[0].decode("utf-8", "replace")
                t = " ".join(t.split())  # PS3 titles may hold line breaks
                return t or None
    except (OSError, struct.error, ValueError):
        return None
    return None


class _Failed:
    """Called with each listing error: hit when one wasn't just a folder that isn't there."""
    def __init__(self):
        self.hit = False

    def __call__(self, e: OSError):
        if not isinstance(e, FileNotFoundError):
            self.hit = True


def _system_dirs(roms_dir: str, systems: dict, failed=None) -> list[tuple[str, str]]:
    """(system id, folder path) for each folder in roms_dir that's some system's (any case)."""
    try:
        names = os.listdir(roms_dir)
    except OSError as e:
        if failed:
            failed(e)
        return []
    by_name = {}
    for sid, s in systems.items():
        for f in [sid, *s.get("folders", [])]:
            by_name.setdefault(f.lower(), sid)
    out = []
    for n in sorted(names):
        sid = by_name.get(n.lower())
        p = os.path.join(roms_dir, n)
        if sid and os.path.isdir(p):
            out.append((sid, p))
    return out


def _walk(top: str, failed=None, marker: str | None = None):
    """Files below top, DEPTH folders deep, hidden ones left out; with a game folder's `marker`,
    a folder holding it comes out itself, and nothing in it."""
    stack = [(top, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError as e:
            if failed:
                failed(e)
            continue
        for e in entries:
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir():
                    if marker and os.path.isfile(os.path.join(e.path, marker)):
                        yield e.path
                    elif depth < DEPTH:
                        stack.append((e.path, depth + 1))
                elif e.is_file():
                    yield e.path
            except OSError as err:
                if failed:
                    failed(err)
                continue


def scan_folder(sid: str, folder: str, sysdef: dict, failed=None) -> list[str]:
    """The ROMs in one system folder: files of its extensions, less those a list names."""
    exts = set(sysdef.get("extensions", []))
    marker = (sysdef.get("game_folders") or {}).get("marker")
    files = [p for p in _walk(folder, failed, marker) if _ext(p) in exts or (marker and os.path.isdir(p))]
    hidden = set()
    for p in files:
        if _ext(p) in LIST_EXTS:
            hidden.update(listed_files(p))
    return [p for p in files if os.path.normpath(p) not in hidden]


def signature(roots: list[dict], systems: dict) -> dict:
    """{folder: mtime} of every system folder and its subfolders: a rescan finds nothing new
    while it's the same."""
    sig = {}
    for r in roots:
        for sid, folder in _system_dirs(os.path.join(r["emulation"], "roms"), systems):
            for d in _walk_dirs(folder):
                try:
                    sig[d] = os.stat(d).st_mtime_ns
                except OSError:
                    pass
    return sig


def _walk_dirs(top: str):
    stack = [(top, 0)]
    while stack:
        d, depth = stack.pop()
        yield d
        if depth >= DEPTH:
            continue
        try:
            for e in os.scandir(d):
                if not e.name.startswith(".") and e.is_dir():
                    stack.append((e.path, depth + 1))
        except OSError:
            continue


def scan(roots: list[dict], systems: dict, failed: set | None = None) -> dict:
    """{rom id: {system, path, title, storage, rel}} for every storage, internal first. The
    storages (uuids, or paths) a listing failed on go in `failed`."""
    found = {}
    seen = set()  # (system, path in the system folder, lowercased): the first storage's wins
    for r in roots:
        uuid = r.get("uuid") or r["path"]
        emu = r["emulation"]
        err = _Failed()
        for sid, folder in _system_dirs(os.path.join(emu, "roms"), systems, err):
            for p in scan_folder(sid, folder, systems[sid], err):
                key = (sid, os.path.relpath(p, folder).lower())
                if key in seen:
                    continue
                seen.add(key)
                rel = os.path.relpath(p, emu)
                marker = (systems[sid].get("game_folders") or {}).get("marker")
                is_folder = bool(marker) and os.path.isdir(p)
                try:
                    # a game folder's size: its marker's, the same wherever it's copied
                    size = os.path.getsize(os.path.join(p, marker) if is_folder else p)
                except OSError:
                    size = None
                name = (sfo_title(os.path.join(p, marker)) if is_folder and marker.upper().endswith(".SFO") else None) or title(p)
                found[rom_id(uuid, rel)] = {"system": sid, "path": p, "title": name,
                                            "storage": uuid, "rel": rel, "sub": key[1], "size": size}
        if err.hit and failed is not None:
            failed.add(uuid)
    _disambiguate(found)
    return found


def drop_extras(found: dict, kind_of) -> list[dict]:
    """Takes out of `found` the Switch files that aren't a game: updates and DLC (kind_of(rom)
    says "game", "update", "dlc" or None when it can't be told; those stay). They're installed
    into the emulator, not played, so they never become shortcuts (and a shortcut made before
    goes, as for a file that's gone). Returns what was taken out."""
    out = []
    for rid in [rid for rid, r in found.items() if r["system"] == "switch"]:
        k = kind_of(found[rid])
        if k in ("update", "dlc"):
            out.append({**found.pop(rid), "kind": k})
    return out


def _disambiguate(found: dict):
    """Two ROMs of a system with the same title (two regions): each keeps its tags."""
    by = {}
    for r in found.values():
        by.setdefault((r["system"], r["title"].lower()), []).append(r)
    for group in by.values():
        if len(group) > 1:
            for r in group:
                stem = os.path.basename(r["path"])
                r["title"] = stem.rpartition(".")[0] if _ext(stem) and not os.path.isdir(r["path"]) else stem


def carry_moves(found: dict, state: dict, choices: dict, mounted: set[str]) -> list[tuple[str, str]]:
    """A game gone from one storage (in, scanned without an error) while one with the same
    system, path in its system folder and size turned up on another (copied or moved from a
    card, or the internal copy now winning over the card's): its state (appid, artwork,
    layout, deleted...) and its own emulator choice move to the new id, so plan() updates the
    shortcut instead of removing it and adding another. Fills in "sub" and "size" for the games
    found that lack them. Changes `state` (roms.json's "roms") and `choices` (by rom id); returns
    the (old id, new id) pairs."""
    for rid, r in found.items():
        s = state.get(rid)
        if s is not None:
            for k in ("sub", "size"):
                if s.get(k) != r.get(k):
                    s[k] = r.get(k)
    new = {}
    for rid, r in found.items():
        if rid not in state and r.get("size") is not None:
            new.setdefault((r["system"], r.get("sub"), r["size"]), []).append(rid)
    moves = []
    for rid, s in list(state.items()):
        if rid in found or s.get("storage") not in mounted or s.get("size") is None or not s.get("sub"):
            continue
        cands = new.get((s.get("system"), s["sub"], s["size"]))
        if not cands:
            continue
        nid = cands.pop(0)
        # the new path goes in on the update the shortcut gets
        state[nid] = {**state.pop(rid), **{k: v for k, v in found[nid].items() if k not in ("path", "title")}}
        if rid in choices:
            choices[nid] = choices.pop(rid)
        moves.append((rid, nid))
    return moves


def plan(found: dict, state: dict, mounted: set[str]) -> dict:
    """What to do to the library: {add: [rom], update: [rom], remove: [rom]}, each rom a dict
    with its id (and appid where it has one; an add the appid its shortcut had before the game
    was brought back, as "was"). `state` is roms.json's "roms"; `mounted` the uuids (or paths)
    of the storages that are in and were scanned without an error."""
    add, update, remove = [], [], []
    for rid, r in found.items():
        s = state.get(rid)
        if s is None or (not s.get("appid") and not s.get("deleted")):
            add.append({"id": rid, **r, "was": (s or {}).get("was_appid")})
        elif s.get("deleted"):
            continue
        elif s.get("path") != r["path"] or s.get("title") != r["title"]:
            update.append({"id": rid, "appid": s["appid"], **r})
    for rid, s in state.items():
        if rid in found or not s.get("appid") or s.get("deleted"):
            continue
        if s.get("storage") in mounted:
            remove.append({"id": rid, **s})
    return {"add": add, "update": update, "remove": remove}


def confirm_missing(state: dict, missing: list[str], seen: list[str], now: float, wait: float) -> list[str]:
    """Our shortcuts the library didn't have (missing) or had (seen) in a sync whose library
    was there (others of ours showed). A game counts as deleted in Steam only when it was
    missing in two syncs `wait` s apart, with no sync between that saw it: a library that
    loads late, or a shortcuts.vdf lost to a power cut, isn't a deletion. Returns the ids
    deleted now; `state` (roms.json's "roms") keeps when each was seen or first missed."""
    for rid in seen:
        s = state.get(rid)
        if s:
            s["seen"] = now
            s.pop("missing_since", None)
    out = []
    for rid in missing:
        s = state.get(rid)
        if not s or s.get("deleted") or not s.get("appid"):
            continue
        first = s.get("missing_since")
        if first is None or first > now:
            s["missing_since"] = now
        elif now - first >= wait:
            s["deleted"] = True
            s.pop("missing_since", None)
            out.append(rid)
    return out


def choice_paths(choices: dict, found: dict, state: dict) -> dict:
    """choices.json's "games" ({ROM path: emulator}, what emu-run looks a game up by) from the
    choices kept by ROM id, with each ROM's path now (or its last one, its card being out)."""
    out = {}
    for rid, emu in choices.items():
        r = found.get(rid) or state.get(rid)
        if r and r.get("path") and emu:
            out[r["path"]] = emu
    return out
