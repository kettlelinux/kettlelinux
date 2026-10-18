# Emulation: games for the consoles of old in Game Mode. ROMs in Emulation/roms/<system> on
# internal storage and on every card become Steam shortcuts (one collection per system, with
# artwork and the standard controls' layout), each running /usr/lib/kettle/emu-run (kettle-
# emulation), which picks the emulator and keeps the controls the same in all of them. The
# frontend does what touches Steam (sync.ts); this side finds the ROMs (roms.py), tells it what
# to change, and keeps what was done in roms.json.
#
# Getting games in, the four ways: the inbox (Emulation/inbox on any storage, sorted on its own,
# kettle-emu-import), a card or stick put in (an offer to import what's on it, or its own
# Emulation tree used in place), the upload page for a phone or PC (kettle-emu-upload, a QR code
# and a PIN) and the "Kettle" network share (kettle-emu-share). BIOS files are recognised by md5,
# whatever they're called; none is shipped or downloaded (blueMSX's Machines and Databases
# folders come with that core, their only system ROMs the free C-BIOS). Also: the emulator per system and per game (choices.json,
# which emu-run reads), saves and states, the extra cores whose licenses keep them out of the
# image, and Quick Access' buttons for the running game (the keys bridge emu-run owns: the same
# keys the Select hotkeys send).
#
# File names that aren't UTF-8 (a card's, an upload's) come from the file system with surrogate
# escapes. They stay so here (roms.json, the paths the plugin works with), but what goes to the
# frontend has to be strict UTF-8 JSON: _shown() gives their bad bytes U+FFFD, and what the
# frontend sends back to mean a file is an id or the path's bytes in hex (_unhex), never the
# name it was shown.
import asyncio
import base64
import json
import os
import select
import sys
import tempfile
import threading
import time

import decky

HOME = decky.DECKY_USER_HOME
EMU = os.path.join(HOME, "Emulation")
os.environ.setdefault("KETTLE_EMU_HOME", EMU)
sys.path.insert(0, "/usr/lib/kettle")
from kettle_emulation import bios, identify, keys, samba, storage, systems  # noqa: E402

import art  # noqa: E402
import cores  # noqa: E402
import roms  # noqa: E402
import saves  # noqa: E402

LIB = "/usr/lib/kettle"
EMU_RUN = f"{LIB}/emu-run"
IMPORT = f"{LIB}/kettle-emu-import"
UPLOAD = f"{LIB}/kettle-emu-upload"
LAYOUT = "local:///usr/share/kettle/emulation/emulation-{}.vdf"
STATE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "roms.json")
SETTINGS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
CHOICES = os.path.join(HOME, ".config", "kettle", "emulation", "choices.json")
CACHE = os.path.join(HOME, ".cache", "kettle", "emulation")
RESCAN_EVERY = 300  # s: and right away when a card comes or goes
INBOX_EVERY = 15  # s
CHECK_AFTER = 120  # s a shortcut is in the library before a missing one counts as deleted in Steam
MISSING_FOR = 600  # s between two syncs that both miss a shortcut before it counts as deleted
INBOX_SETTLE = 30  # s a file in the inbox is left alone before it's sorted (still being copied)
ART_TRIES = 3
DEFAULTS = {"first_run_done": False, "auto_inbox": True, "sgdb_key": ""}

_lock = asyncio.Lock()  # roms.json and settings.json, one writer at a time
_cores_lock = asyncio.Lock()  # one extra core downloaded or removed at a time


def _read_json(path: str, default):
    try:
        with open(path) as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def _state() -> dict:
    s = _read_json(STATE, {})
    # rom id -> {system, path, title, storage, rel, appid, added, art, layout, deleted, seen,
    # missing_since, was_appid}
    s.setdefault("roms", {})
    s.setdefault("collections", {})  # system -> the id of the Steam collection the plugin made
    # "choices": rom id -> the game's own emulator (_game_choices)
    return s


def _game_choices(st: dict) -> dict:
    """Each game's own emulator by rom id, so it stays with the game when its card mounts
    elsewhere; choices.json's "games" (by path, what emu-run reads) is made from it. The first
    time, taken over from choices.json."""
    if not isinstance(st.get("choices"), dict):
        old = _read_json(CHOICES, {}).get("games", {})
        by_path = {r.get("path"): rid for rid, r in st["roms"].items()}
        st["choices"] = {by_path[p]: e for p, e in old.items() if p in by_path}
    return st["choices"]


def _write_choice_paths(st: dict, found: dict):
    """choices.json's "games" with each game's path now (under _lock)."""
    c = _read_json(CHOICES, {})
    games = roms.choice_paths(_game_choices(st), found, st["roms"])
    if c.get("games") != games:
        c["games"] = games
        _write_json(CHOICES, c)


def _settings() -> dict:
    return {**DEFAULTS, **_read_json(SETTINGS, {})}


def _face() -> str:
    try:
        import kettle_device
        return "nintendo" if kettle_device.conf.get("FACE_BUTTONS") == "nintendo" else "xbox"
    except ImportError:
        return "xbox"


def _roots() -> list[dict]:
    return storage.roots()


def _mounted(roots: list[dict]) -> set[str]:
    return {r.get("uuid") or r["path"] for r in roots}


def _shown(s: str) -> str:
    """A name as the frontend gets it: strict UTF-8, a byte that isn't (a surrogate escape) as
    U+FFFD."""
    try:
        return s.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except UnicodeEncodeError:  # a lone surrogate that isn't an escaped byte (a JSON file's)
        return s.encode("utf-8", "surrogatepass").decode("utf-8", "replace")


def _shown_all(v):
    """_shown() on every string in a reply or an event (keys too)."""
    if isinstance(v, str):
        return _shown(v)
    if isinstance(v, dict):
        return {_shown_all(k): _shown_all(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_shown_all(x) for x in v]
    return v


def _hex(path: str) -> str:
    return os.fsencode(path).hex()


def _unhex(h: str) -> str:
    """A path the frontend names by its bytes in hex (what _hex gave it)."""
    try:
        return os.fsdecode(bytes.fromhex(h))
    except (TypeError, ValueError):
        raise ValueError("not a file id")


async def _emit(event: str, *args):
    await decky.emit(event, *_shown_all(list(args)))


def _plain(path: str) -> bool:
    """Steam takes it as a start folder: UTF-8, without a quote or a control character."""
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return not any(c == '"' or ord(c) < 32 or ord(c) == 127 for c in path)


def _start_dir(path: str) -> str:
    """The shortcut's start folder (Steam quotes it; emu-run doesn't use it): the ROM's folder,
    or the nearest one above it whose name Steam can take (a folder that isn't UTF-8)."""
    d = os.path.dirname(path)
    while d and d != "/":
        if _plain(d):
            return d
        d = os.path.dirname(d)
    return HOME if _plain(HOME) else "/"


def _root_by_path(roots: list[dict], path: str) -> dict | None:
    """The storage the frontend names by the path it was shown (exactly, or as _shown() gave it)."""
    r = next((r for r in roots if r["path"] == path), None)
    if r:
        return r
    same = [r for r in roots if _shown(r["path"]) == path]
    return same[0] if len(same) == 1 else None


def _with_system_dirs(bst: dict, db: dict) -> dict:
    """bios.status() with each system's "system_dirs" (the folders its core needs in
    Emulation/bios: blueMSX's Machines and Databases, downloaded with it in Extra cores) as
    needed entries of its own, found when the folder is there."""
    folder = os.path.join(EMU, "bios")
    for sid, s in db["systems"].items():
        dirs = s.get("system_dirs")
        if not dirs:
            continue
        v = bst.setdefault(sid, {"state": "none", "entries": []})
        v["entries"] = list(v.get("entries", [])) + [
            {"file": d + "/", "required": True, "one_of": False, "folder": True,
             "note": "a folder, downloaded with the core in Extra cores",
             "found": os.path.join(folder, d) if os.path.isdir(os.path.join(folder, d)) else None,
             "elsewhere": None, "bad": None} for d in dirs]
        if bios.unmet(v["entries"]):
            v["state"] = "missing-required"
        elif all(e["found"] for e in v["entries"]):
            v["state"] = "ok"
        else:
            v["state"] = "missing-optional"
    return bst


def _needs_only_folders(v: dict) -> bool:
    """A system missing what it needs only for its core's folders (system_dirs): they come with
    the core from Extra cores, not as a BIOS file from the console."""
    entries = v.get("entries", [])
    return (v.get("state") == "missing-required" and any(e.get("folder") for e in entries)
            and not bios.unmet([e for e in entries if not e.get("folder")]))


def _launch(system: str, path: str) -> str:
    """The shortcut's launch options. Steam runs them through a shell, so the ROM's path (any
    name the user, a card or the upload page gave it) never goes in as text: hex, which
    emu-run decodes (os.fsdecode), so a name that isn't UTF-8 goes through as its bytes."""
    return f"{system} x:{os.fsencode(path).hex()}"


def _entry(rid: str, r: dict, db: dict) -> dict:
    sysdef = db["systems"][r["system"]]
    return {"id": rid, "title": _shown(r["title"]), "system": r["system"], "exe": EMU_RUN,
            "dir": _start_dir(r["path"]), "launch": _launch(r["system"], r["path"]),
            "collection": _shown(sysdef.get("collection", sysdef["name"])), "appid": r.get("appid"),
            "was": r.get("was")}


def _emulators(db: dict, sid: str) -> list[dict]:
    from kettle_emulation import run  # installed(): the core or binary is there
    out = []
    for eid in db["systems"][sid]["emulators"]:
        e = db["emulators"][eid]
        try:
            ok = run.installed(e)
        except Exception:
            ok = False
        out.append({"id": eid, "name": e["name"], "installed": ok, "download": bool(e.get("download")),
                    "flatpak": e.get("kind") == "flatpak", "license": e.get("license", "")})
    return out


def _chosen(choices: dict, sid: str, emus: list[dict]) -> str:
    want = choices.get("systems", {}).get(sid)
    for e in emus:
        if e["id"] == want and e["installed"]:
            return e["id"]
    return next((e["id"] for e in emus if e["installed"]), "")


def _mount_watch(loop: asyncio.AbstractEventLoop, changed):
    """/proc/self/mountinfo is pollable: POLLPRI (POLLERR) each time a mount comes or goes."""
    with open("/proc/self/mountinfo") as f:
        p = select.poll()
        p.register(f, select.POLLPRI | select.POLLERR)
        while True:
            p.poll()
            f.seek(0)
            f.read()
            loop.call_soon_threadsafe(changed)


class Plugin:
    def __init__(self):
        self._found: dict = {}
        self._sig: dict = {}
        self._job: dict = {"state": "idle"}  # an import: {state, kind, path, files, done, bytes, bytes_done, current, stats, error}
        self._job_proc: asyncio.subprocess.Process | None = None
        self._upload: dict = {"state": "off"}
        self._upload_proc: asyncio.subprocess.Process | None = None
        self._media: dict = {}  # mount point -> its scan, for the offer to import
        self._seen: set[str] = set()  # the cards in: a new one gets the offer as a toast
        self._error_seen = 0.0
        self._inbox_tried: dict = {}  # the inbox files the running inbox job was started for: {path: mtime}
        self._inbox_left: dict = {}  # those it left there (failed or skipped): not retried until they change
        self._tasks: list[asyncio.Task] = []

    # --- the library ---------------------------------------------------------------------------
    async def overview(self) -> dict:
        """The Library page and Quick Access: each system with its game count, emulators and BIOS
        state; the storages; the settings."""
        db = systems.load()
        st = _state()
        choices = _read_json(CHOICES, {})
        bst = _with_system_dirs(await asyncio.to_thread(bios.status), db)
        counts = {}
        for r in st["roms"].values():
            if not r.get("deleted"):
                counts[r["system"]] = counts.get(r["system"], 0) + 1
        out = []
        for sid, s in db["systems"].items():
            emus = await asyncio.to_thread(_emulators, db, sid)
            out.append({"id": sid, "name": s["name"], "folder": s["folders"][0], "count": counts.get(sid, 0),
                        "emulators": emus, "emulator": _chosen(choices, sid, emus),
                        "bios": bst.get(sid, {}).get("state", "none"), "note": s.get("note", ""),
                        "bios_from_core": _needs_only_folders(bst.get(sid, {})),
                        "extensions": s.get("extensions", [])})
        roots = await asyncio.to_thread(_roots)
        return _shown_all({"systems": out, "total": sum(counts.values()), "face": _face(), "settings": _settings(),
                           "storages": [{"path": r["path"], "emulation": r["emulation"], "label": r["label"],
                                         "internal": r["internal"],
                                         "set_up": os.path.isdir(os.path.join(r["emulation"], "roms"))}
                                        for r in roots]})

    async def sync_plan(self) -> dict:
        """What the frontend does to the library now: add, update and remove shortcuts, and check
        which of ours are still there (one the user deleted in Steam is never added again)."""
        db = systems.load()
        roots = await asyncio.to_thread(_roots)
        failed: set[str] = set()
        self._found = await asyncio.to_thread(roms.scan, roots, db["systems"], failed)
        self._sig = await asyncio.to_thread(roms.signature, roots, db["systems"])
        if failed:
            decky.logger.warning("emulation: scanning %s failed: their games are kept", ", ".join(sorted(failed)))
        mounted = _mounted(roots) - failed
        async with _lock:
            st = _state()
            had = "choices" in st
            before = json.dumps(st["roms"], sort_keys=True)
            moves = roms.carry_moves(self._found, st["roms"], _game_choices(st), mounted)
            for old, new in moves:
                decky.logger.info("emulation: %s moved: %s -> %s", st["roms"][new].get("title", ""), old, new)
            _write_choice_paths(st, self._found)
            if not had or json.dumps(st["roms"], sort_keys=True) != before:
                _write_json(STATE, st)
        p = roms.plan(self._found, st["roms"], mounted)
        now = time.time()
        check = [{"id": rid, "appid": r["appid"], "system": r["system"]} for rid, r in st["roms"].items()
                 if r.get("appid") and not r.get("deleted") and now - r.get("added", 0) > CHECK_AFTER]
        return _shown_all({"add": [_entry(r["id"], r, db) for r in p["add"]],
                           "update": [_entry(r["id"], r, db) for r in p["update"]],
                           "remove": [{"id": r["id"], "appid": r["appid"], "system": r["system"]} for r in p["remove"]],
                           "check": check, "layout": LAYOUT.format(_face())})

    async def synced(self, added: dict, updated: list[str], removed: list[str], missing: list[str],
                     seen: list[str] | None = None) -> list[str]:
        """What the frontend did: added {rom id: appid}, updated and removed rom ids; and of the
        shortcuts it checked, those the library had (seen) and hadn't (missing), both empty when
        the library didn't look loaded. Returns the ids now counted as deleted in Steam (missing
        twice, MISSING_FOR apart)."""
        async with _lock:
            st = _state()
            now = time.time()
            for rid, appid in added.items():
                r = self._found.get(rid)
                if r and appid:
                    st["roms"][rid] = {**r, "appid": int(appid), "added": now, "art": False, "layout": False}
            for rid in updated:
                if rid in self._found and rid in st["roms"]:
                    st["roms"][rid].update(self._found[rid])
            for rid in removed:
                st["roms"].pop(rid, None)
            gone = roms.confirm_missing(st["roms"], missing, seen or [], now, MISSING_FOR)
            _write_json(STATE, st)
        return gone

    async def library_state(self) -> dict:
        """After a sync: each system's collection (name, id, appids), the shortcuts still without
        the controller layout, and those still without artwork."""
        db = systems.load()
        st = _state()
        cols = {}
        for rid, r in st["roms"].items():
            if r.get("appid") and not r.get("deleted"):
                cols.setdefault(r["system"], []).append(r["appid"])
        collections = {}
        for sid in set(cols) | set(st["collections"]):
            s = db["systems"].get(sid)
            if not s:
                continue
            collections[sid] = {"name": s.get("collection", s["name"]), "id": st["collections"].get(sid),
                                "appids": cols.get(sid, [])}
        return {"collections": collections,
                "layout": [r["appid"] for r in st["roms"].values() if r.get("appid") and not r.get("deleted") and not r.get("layout")],
                "art": [{"id": rid, "appid": r["appid"]} for rid, r in st["roms"].items()
                        if r.get("appid") and not r.get("deleted") and r.get("art") is not True and r.get("art_tries", 0) < ART_TRIES]}

    async def set_collection(self, system: str, cid: str | None):
        async with _lock:
            st = _state()
            if cid:
                st["collections"][system] = cid
            else:
                st["collections"].pop(system, None)
            _write_json(STATE, st)

    async def layout_done(self, appids: list[int]):
        async with _lock:
            st = _state()
            done = {int(a) for a in appids}
            for r in st["roms"].values():
                if r.get("appid") in done:
                    r["layout"] = True
            _write_json(STATE, st)

    async def artwork(self, rid: str, chosen: str | None = None) -> dict:
        """The ROM's artwork for Steam: {asset type: {data (base64 PNG), ext}}; {} when there's
        none (it's tried again on a later sync, ART_TRIES times; a try without the network
        doesn't count). The frontend says when Steam has it (art_done)."""
        st = _state()
        r = st["roms"].get(rid)
        if not r:
            return {}
        db = systems.load()
        repo = db["systems"][r["system"]].get("thumbnails")
        # the thumbnail servers' names are UTF-8 (a name that isn't can't be quoted into a URL)
        name = _shown(os.path.basename(r["path"]).rpartition(".")[0] or os.path.basename(r["path"]))
        title = _shown(r["title"])

        def work():
            try:
                pics = art.pictures(repo, name, CACHE, chosen) if repo else {}
            except art.Offline as e:
                decky.logger.info("emulation: artwork for %s: %s", title, e)
                if chosen:
                    raise ValueError("the artwork server can't be reached; try again with the network up")
                return None
            key = _settings()["sgdb_key"]
            if key and "box" not in pics:
                try:
                    pics = {**art.sgdb(key, title, CACHE), **pics}
                except Exception as e:
                    decky.logger.info("emulation: SteamGridDB %s: %s", title, e)
            made = art.compose(pics, os.path.join(CACHE, "art", rid))
            out = {}
            for kind, path in made.items():
                with open(path, "rb") as f:
                    out[str(kind)] = {"data": base64.b64encode(f.read()).decode(), "ext": "png"}
            return out

        out = await asyncio.to_thread(work)
        if out is None:
            return {}
        if not out:
            await self.art_done(rid, False)
        return out

    async def art_done(self, rid: str, ok: bool):
        """Steam took the artwork (ok), or the game had none or Steam refused it: a try used."""
        async with _lock:
            st = _state()
            r = st["roms"].get(rid)
            if r:
                if ok:
                    r["art"] = True
                else:
                    r["art_tries"] = r.get("art_tries", 0) + 1
                _write_json(STATE, st)

    async def art_choices(self, rid: str) -> list[str]:
        """"Fix artwork": the names that could be this game's box art, best first."""
        r = _state()["roms"].get(rid)
        if not r:
            return []
        repo = systems.load()["systems"][r["system"]].get("thumbnails")
        name = _shown(os.path.basename(r["path"]).rpartition(".")[0])
        return _shown_all(await asyncio.to_thread(art.candidates, repo, name, CACHE)) if repo else []

    async def games(self, system: str) -> list[dict]:
        """A system's games: [{id, title, path (both to show), appid, emulator (the game's own
        choice)}]."""
        st = _state()
        choices = _game_choices(st)
        return sorted(({"id": rid, "title": _shown(r["title"]), "path": _shown(r["path"]), "appid": r.get("appid"),
                        "emulator": choices.get(rid, "")}
                       for rid, r in st["roms"].items() if r["system"] == system and not r.get("deleted")),
                      key=lambda g: g["title"].lower())

    async def restore_deleted(self, system: str) -> int:
        """Games whose shortcuts were deleted in Steam come back on the next sync."""
        async with _lock:
            st = _state()
            n = 0
            for r in st["roms"].values():
                if r["system"] == system and r.get("deleted"):
                    r.pop("deleted")
                    r.pop("missing_since", None)
                    # the sync uses the old shortcut if Steam has it after all, instead of a second one
                    r["was_appid"], r["appid"] = r.get("appid"), None
                    n += 1
            _write_json(STATE, st)
        return n

    # --- emulator choices ----------------------------------------------------------------------
    async def set_choice(self, system: str, emulator: str | None):
        db = systems.load()
        if system not in db["systems"] or emulator and emulator not in db["systems"][system]["emulators"]:
            raise ValueError("not an emulator of that system")
        async with _lock:
            c = _read_json(CHOICES, {})
            c.setdefault("systems", {})
            if emulator:
                c["systems"][system] = emulator
            else:
                c["systems"].pop(system, None)
            _write_json(CHOICES, c)

    async def set_game_choice(self, rid: str, emulator: str | None):
        r = _state()["roms"].get(rid)
        if not r:
            raise ValueError("not a game of the library")
        db = systems.load()
        if emulator and emulator not in db["systems"][r["system"]]["emulators"]:
            raise ValueError("not an emulator of that system")
        async with _lock:
            st = _state()
            choices = _game_choices(st)
            if emulator:
                choices[rid] = emulator
            else:
                choices.pop(rid, None)
            _write_json(STATE, st)
            _write_choice_paths(st, self._found)

    # --- the running game ----------------------------------------------------------------------
    async def running(self) -> dict | None:
        """The game emu-run is running: {system, rom, emulator, pid, bridge, appid, title, id,
        emulators, game_choice}; None when there's none."""
        path = os.path.join(keys.runtime_dir(), "running.json")
        r = _read_json(path, {})
        if not r or not r.get("pid"):
            return None
        try:
            os.kill(int(r["pid"]), 0)
        except (OSError, ValueError):
            return None
        db = systems.load()
        st = _state()
        rid = next((k for k, v in st["roms"].items() if v["path"] == r.get("rom")), None)
        sid = r.get("system")
        if sid not in db["systems"]:
            return None
        return _shown_all({**r, "id": rid, "title": roms.title(r.get("rom", "")),
                           "emulator_name": db["emulators"].get(r.get("emulator"), {}).get("name", ""),
                           "emulators": await asyncio.to_thread(_emulators, db, sid),
                           "rewind": bool(db["systems"][sid].get("rewind")),
                           "game_choice": _game_choices(st).get(rid, "") if rid else ""})

    async def hotkey(self, action: str) -> bool:
        if action not in keys.ACTIONS:
            raise ValueError(f"no such action: {action}")
        return await asyncio.to_thread(keys.send, action)

    # --- BIOS ----------------------------------------------------------------------------------
    async def bios(self) -> dict:
        """{systems: [{id, name, state, entries}], folder}: every system that has BIOS files (or
        folders its core needs there: system_dirs)."""
        db = systems.load()
        st = _with_system_dirs(await asyncio.to_thread(bios.status), db)
        out = [{"id": sid, "name": db["systems"][sid]["name"], **v} for sid, v in st.items() if v["state"] != "none"]
        return _shown_all({"systems": out, "folder": os.path.join(EMU, "bios")})

    async def bios_install(self, system: str | None = None) -> list[str]:
        """Copies the BIOS files found elsewhere (another name, a subfolder, a card) to where the
        emulators look, for one system or all; the names of those installed."""
        if system and system not in systems.load()["systems"]:
            raise ValueError("no such system")
        return _shown_all(await asyncio.to_thread(bios.install_found, system or None))

    # --- getting games in ----------------------------------------------------------------------
    async def media(self) -> list[dict]:
        """Cards and sticks that are in, with what importing from them would bring:
        [{path, label, set_up, games_total, games, bios, bytes}]"""
        roots = await asyncio.to_thread(_roots)
        out = []
        for r in roots:
            if r["internal"]:
                continue
            m = self._media.get(r["path"])
            if m is None:
                m = await asyncio.to_thread(self._scan_media, r)
            out.append(m)
        return _shown_all(out)

    def _scan_media(self, r: dict) -> dict:
        from kettle_emulation import importer
        set_up = os.path.isdir(os.path.join(r["emulation"], "roms"))
        m = {"path": r["path"], "label": r["label"], "set_up": set_up, "games_total": 0, "games": {}, "bios": 0, "bytes": 0}
        if not set_up:
            try:
                s = importer.scan(r["path"])
                m.update(games_total=s["games_total"], games=s["games"], bios=len(s["bios"]), bytes=s["bytes"])
            except Exception as e:
                decky.logger.warning("emulation: scanning %s: %s", r["path"], e)
        self._media[r["path"]] = m
        return m

    async def set_up_card(self, path: str):
        """Makes a card's own Emulation tree, so its games are played from it (`path`: its mount
        point as overview or media showed it)."""
        roots = await asyncio.to_thread(_roots)
        r = _root_by_path([r for r in roots if not r["internal"]], path)
        if not r:
            raise ValueError("that card isn't in")
        from kettle_emulation import seed
        await asyncio.to_thread(seed.ensure_dirs, r["emulation"])
        self._media.pop(r["path"], None)

    async def import_start(self, path: str, mode: str = "copy", dest: str = "internal"):
        """Imports a card's, a stick's or any folder's games and BIOS files (kettle-emu-import
        run); progress from import_status and "import" events. A storage's path is the one it
        was shown as (media, overview)."""
        if self._job.get("state") == "running":
            raise ValueError("an import is running already")
        if mode not in ("copy", "move"):
            raise ValueError("copy or move")
        roots = await asyncio.to_thread(_roots)
        r = _root_by_path(roots, path)
        if r:
            path = r["path"]
        if dest != "internal":
            d = _root_by_path(roots, dest)
            if d:
                dest = d["path"]
        await self._run_job("import", [IMPORT, "run", path, f"--{mode}", "--dest", dest], path)

    async def inbox_now(self):
        if self._job.get("state") != "running":
            tried = await asyncio.to_thread(self._inbox_files, 0, False)
            # checked again: an import started meanwhile keeps its own
            if self._job.get("state") != "running":
                self._inbox_tried = tried
                await self._run_job("inbox", [IMPORT, "inbox", "--settle", "0"], "inbox")

    async def _run_job(self, kind: str, cmd: list[str], path: str):
        # no await before the state is set: two jobs never start at once
        if self._job.get("state") == "running":
            raise ValueError("an import is running already")
        job = self._job = {"state": "running", "kind": kind, "path": path, "files": 0, "done": 0, "bytes": 0,
                           "bytes_done": 0, "current": "", "stats": None, "error": "", "unsorted": 0}
        try:
            proc = self._job_proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=1 << 20)
        except Exception as e:
            job.update(state="failed", error=str(e))
            self._job_proc = None
            await _emit("import", dict(job))
            raise ValueError(f"the importer didn't start: {e}")
        self._tasks.append(asyncio.create_task(self._follow_job(proc, job)))

    @staticmethod
    def _add_stats(total: dict | None, ev: dict) -> dict:
        """The done events of every storage (an inbox job sorts each one's inbox) added up."""
        t = total or {"games": {}, "bios": [], "unsorted": 0, "identical": 0, "errors": 0}
        for sid, n in (ev.get("games") or {}).items():
            t["games"][sid] = t["games"].get(sid, 0) + n
        t["bios"] += ev.get("bios") or []
        for k in ("unsorted", "identical", "errors"):
            t[k] += ev.get(k, 0)
        return t

    async def _follow_job(self, proc: asyncio.subprocess.Process, job: dict):
        last = 0.0
        code = None
        err = ""
        # an inbox job's counts go on from one storage to the next already (the importer's)
        handled = set()  # the files it said something about (an item event): sorted, left or failed
        try:
            async for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                e = ev.get("event")
                if e == "start":
                    job["files"] += ev.get("files", 0)
                    job["bytes"] += ev.get("bytes", 0)
                elif e == "progress":
                    job["bytes_done"] = ev.get("bytes_done", 0)
                    job["current"] = os.path.basename(ev.get("file") or "")
                elif e == "item":
                    if not ev.get("archive"):  # an archive's own files aren't in "files"
                        job["done"] = ev.get("done", 0)
                        if ev.get("src"):
                            handled.add(ev["src"])
                    job["current"] = os.path.basename(ev.get("src", ""))
                    if ev.get("action") == "error":
                        job["error"] = f"{os.path.basename(ev.get('src', ''))}: {ev.get('reason', '')}"
                elif e == "done":
                    job["stats"] = self._add_stats(job["stats"], ev)
                    job["unsorted"] = job["stats"]["unsorted"]
                if time.monotonic() - last > 0.5:
                    last = time.monotonic()
                    await _emit("import", dict(job))
            err = (await proc.stderr.read()).decode(errors="replace").strip()
            code = await proc.wait()
        except Exception as e:
            err = str(e)
            if proc.returncode is None:
                proc.kill()
        finally:
            if proc is self._job_proc and job["state"] == "running":
                job["state"] = "done" if code in (0, 1) else "failed"
                if code not in (0, 1) and not job["error"]:
                    job["error"] = err[-300:] or f"exit {code}"
            if job["kind"] == "inbox":
                # what it was started for, tried and left there isn't tried again until it
                # changes (a set: the files its sheet lists too); what it passed over (still
                # being copied in) is
                for p in list(handled):
                    if roms._ext(p) in roms.LIST_EXTS:
                        handled.update(await asyncio.to_thread(roms.listed_files, p))
                left = await asyncio.to_thread(self._inbox_files, 0, False)
                self._inbox_left.update({p: m for p, m in self._inbox_tried.items()
                                         if p in handled and left.get(p) == m})
                self._inbox_tried = {}
        if proc is not self._job_proc:
            return
        self._media.clear()
        await _emit("import", dict(job))
        if job["kind"] != "inbox" or job["files"]:
            await _emit("roms_changed")

    async def import_status(self) -> dict:
        return _shown_all(self._job)

    async def import_cancel(self):
        proc, self._job_proc = self._job_proc, None
        if proc and proc.returncode is None:
            proc.terminate()
        if self._job.get("state") == "running":
            self._job["state"] = "cancelled"

    @staticmethod
    def _unsorted_dir(r: dict) -> str:
        return os.path.join(r["emulation"], "inbox", "unsorted")

    @staticmethod
    def _unsorted() -> list[dict]:
        from kettle_emulation import importer
        labels = {os.path.realpath(r["emulation"]): "" if r["internal"] else r["label"] for r in _roots()}
        return [{"id": _hex(u["path"]), "path": u["path"], "name": u["name"], "size": u["size"], "systems": u["systems"],
                 "storage": labels.get(os.path.realpath(u["root"]), "")} for u in importer.unsorted()]

    async def unsorted(self) -> list[dict]:
        """Files the inbox of any storage couldn't tell the system of: [{id (assign's), path,
        name (in its inbox/unsorted), size, systems (the likely ones), storage (a card's label,
        "" for internal)}]."""
        return _shown_all(await asyncio.to_thread(self._unsorted))

    async def assign(self, fid: str, system: str):
        """Sorts an unsorted file (`fid`: unsorted()'s id; anywhere in some storage's
        inbox/unsorted, a set's "Name (n)" folder too) as the system the user picked, into its
        own storage's tree (the importer picks it)."""
        real = os.path.realpath(_unhex(fid))
        roots = await asyncio.to_thread(_roots)
        r = next((r for r in roots if real.startswith(os.path.realpath(self._unsorted_dir(r)) + os.sep)), None)
        if not r or not os.path.isfile(real):
            raise ValueError("not an unsorted file")
        proc = await asyncio.create_subprocess_exec(IMPORT, "assign", real, system,
                                                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode not in (0,):
            raise ValueError(err.decode(errors="replace").strip() or "sorting it failed")
        # a set's folder ("Game (2)") left empty
        top = os.path.realpath(self._unsorted_dir(r))
        d = os.path.dirname(real)
        while d != top and d.startswith(top + os.sep):
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)
        await _emit("roms_changed")

    async def upload_start(self) -> dict:
        """Starts the upload page: {state, pin, urls, port}. It stops itself after 10 minutes
        without a visit."""
        old = self._upload_proc
        if self._upload.get("state") == "on" and old and old.returncode is None:
            return _shown_all(self._upload)
        if old and old.returncode is None:  # locked: a new one, with a new PIN
            self._upload_proc = None
            old.terminate()
            try:
                await asyncio.wait_for(old.wait(), 10)
            except asyncio.TimeoutError:
                old.kill()
        proc = self._upload_proc = await asyncio.create_subprocess_exec(
            UPLOAD, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=1 << 20)
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), 10)
            ev = json.loads(line)
        except (asyncio.TimeoutError, ValueError):
            proc.kill()
            err = (await proc.stderr.read()).decode(errors="replace").strip()
            raise ValueError(f"the upload page didn't start: {err[-200:]}")
        self._upload = {"state": "on", "pin": ev.get("pin", ""), "urls": ev.get("urls", []), "port": ev.get("port"),
                        "uploaded": 0, "last": ""}
        self._tasks.append(asyncio.create_task(self._follow_upload(proc)))
        return _shown_all(self._upload)

    async def _follow_upload(self, proc: asyncio.subprocess.Process):
        async for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if proc is not self._upload_proc:
                continue
            e = ev.get("event")
            if e == "uploaded":
                self._upload["uploaded"] += 1
                self._upload["last"] = ev.get("name", "")
            elif e == "sorted":
                await _emit("roms_changed")
            elif e == "locked":
                self._upload["state"] = "locked"
            await _emit("upload", dict(self._upload))
        await proc.wait()
        if proc is self._upload_proc:
            self._upload = {"state": "off"}
            await _emit("upload", dict(self._upload))
            await _emit("roms_changed")

    async def upload_status(self) -> dict:
        return _shown_all(self._upload)

    async def upload_stop(self):
        proc = self._upload_proc
        if proc and proc.returncode is None:
            proc.terminate()  # it sorts what came first

    async def share_status(self) -> dict:
        return _shown_all(await asyncio.to_thread(samba.status))

    async def share_enable(self, password: str) -> dict:
        await asyncio.to_thread(samba.enable, password)
        return _shown_all(await asyncio.to_thread(samba.status))

    async def share_disable(self) -> dict:
        await asyncio.to_thread(samba.disable)
        return _shown_all(await asyncio.to_thread(samba.status))

    # --- saves ---------------------------------------------------------------------------------
    @staticmethod
    def _save_ids(games: list[dict]) -> list[dict]:
        """saves.listing() for the frontend: each file with its id (its path in hex), the one
        save_delete, save_thumb (its picture's: "thumb") and backup take."""
        return _shown_all([{**g, "files": [{**f, "id": _hex(f["path"]), "thumb": _hex(f["thumb"]) if f["thumb"] else ""}
                                           for f in g["files"]]} for g in games])

    async def saves(self) -> list[dict]:
        return self._save_ids(await asyncio.to_thread(saves.listing, HOME, _state()["roms"]))

    async def _save_paths(self, ids: list[str]) -> tuple[list[str], list[dict]]:
        games = await asyncio.to_thread(saves.listing, HOME, _state()["roms"])
        paths = [_unhex(i) for i in ids]
        if not set(paths) <= saves.all_paths(games):
            raise ValueError("not a save")
        return paths, games

    async def save_thumb(self, fid: str) -> str:
        (path,), _ = await self._save_paths([fid])
        if not path.endswith(".png"):
            raise ValueError("not a save state's picture")
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()

    async def save_delete(self, ids: list[str]) -> int:
        paths, games = await self._save_paths(ids)
        return await asyncio.to_thread(saves.delete, paths, saves.all_paths(games))

    def _backup_dirs(self, roots: list[dict]) -> list[str]:
        return [os.path.join(r["emulation"], "backups") for r in roots]

    async def backup(self, ids: list[str], dest: str = "internal") -> str:
        """Zips these saves (their ids; all of them when empty) into internal storage's or a
        card's (`dest`: its path as shown) Emulation/backups."""
        games = await asyncio.to_thread(saves.listing, HOME, _state()["roms"])
        allowed = {f["path"] for g in games for f in g["files"]}
        paths = [_unhex(i) for i in ids] or sorted(allowed)
        if not set(paths) <= allowed:
            raise ValueError("not a save")
        roots = await asyncio.to_thread(_roots)
        if dest == "internal":
            r = next((r for r in roots if r["internal"]), None)
        else:
            r = _root_by_path([r for r in roots if not r["internal"]], dest)
        if not r:
            raise ValueError("that card isn't in")
        return _shown(await asyncio.to_thread(saves.backup, paths, os.path.join(r["emulation"], "backups"), HOME, roots))

    async def backups(self) -> list[dict]:
        """[{id (restore's), path, size, mtime}], newest first."""
        roots = await asyncio.to_thread(_roots)
        return _shown_all([{**b, "id": _hex(b["path"])}
                           for b in await asyncio.to_thread(saves.backups, self._backup_dirs(roots))])

    async def restore(self, bid: str) -> dict:
        path = _unhex(bid)
        roots = await asyncio.to_thread(_roots)
        known = {b["path"] for b in await asyncio.to_thread(saves.backups, self._backup_dirs(roots))}
        if path not in known:
            raise ValueError("not a backup")
        return await asyncio.to_thread(saves.restore, path, HOME, roots)

    # --- extra cores ---------------------------------------------------------------------------
    def _extra(self, db: dict) -> set[str]:
        return {e["core"] for e in db["emulators"].values() if e.get("download")}

    async def cores(self) -> list[dict]:
        return _shown_all(await asyncio.to_thread(cores.listing, HOME, systems.load(), os.path.join(EMU, "bios")))

    async def core_download(self, core: str) -> list[dict]:
        """The core, and the folders it needs in Emulation/bios (cores.SYSTEM_FILES)."""
        db = systems.load()
        async with _cores_lock:
            await asyncio.to_thread(cores.download, HOME, core, self._extra(db), os.path.join(EMU, "bios"))
        await _emit("roms_changed")
        return await self.cores()

    async def core_remove(self, core: str) -> list[dict]:
        db = systems.load()
        async with _cores_lock:
            await asyncio.to_thread(cores.remove, HOME, core, self._extra(db))
        return await self.cores()

    # --- settings ------------------------------------------------------------------------------
    async def set_settings(self, changes: dict) -> dict:
        for k, v in changes.items():
            if k not in DEFAULTS or type(v) is not type(DEFAULTS[k]):
                raise ValueError(f"no such setting: {k}")
        async with _lock:
            s = {**_settings(), **changes}
            _write_json(SETTINGS, s)
        return s

    # --- watching ------------------------------------------------------------------------------
    async def _rescan_loop(self):
        while True:
            await asyncio.sleep(RESCAN_EVERY)
            try:
                db = systems.load()
                sig = await asyncio.to_thread(roms.signature, await asyncio.to_thread(_roots), db["systems"])
                if sig != self._sig:
                    await _emit("roms_changed")
            except Exception as e:
                decky.logger.warning("emulation: rescan: %s", e)

    def _inbox_files(self, settle: float, skip_left: bool = True) -> dict:
        """{path: mtime} of the files in every storage's inbox an inbox run would try: settled
        (unchanged for `settle` s), not junk the importer skips, not in inbox/unsorted, and
        (skip_left) not one an earlier run left there unchanged."""
        out = {}
        now = time.time()
        for r in storage.roots():
            box = os.path.join(r["emulation"], "inbox")
            unsorted = os.path.join(box, "unsorted")
            for d, dirs, files in os.walk(box):
                dirs[:] = [x for x in dirs if not x.startswith(".") and x not in storage.JUNK_DIRS
                           and os.path.join(d, x) != unsorted]
                for f in files:
                    if f.startswith(".") or f.endswith(".part") or systems.ext_of(f) in identify.JUNK_EXTS:
                        continue
                    p = os.path.join(d, f)
                    try:
                        m = os.stat(p).st_mtime
                    except OSError:
                        continue
                    if now - m < settle or (skip_left and self._inbox_left.get(p) == m):
                        continue
                    out[p] = m
        if skip_left:  # what's gone is forgotten
            self._inbox_left = {p: m for p, m in self._inbox_left.items() if os.path.exists(p)}
        return out

    async def _inbox_loop(self):
        while True:
            await asyncio.sleep(INBOX_EVERY)
            try:
                if (_settings()["auto_inbox"] and self._job.get("state") != "running"
                        and self._upload.get("state") not in ("on", "locked")):
                    waiting = await asyncio.to_thread(self._inbox_files, INBOX_SETTLE)
                    # checked again: an import the user started meanwhile goes first
                    if waiting and self._job.get("state") != "running":
                        self._inbox_tried = waiting
                        # files still being copied in are left for the next round (--settle)
                        await self._run_job("inbox", [IMPORT, "inbox", "--settle", str(INBOX_SETTLE)], "inbox")
            except Exception as e:
                decky.logger.warning("emulation: inbox: %s", e)

    async def _error_loop(self):
        """emu-run's refusals (a card that isn't in, a missing BIOS or emulator) as toasts."""
        path = os.path.join(keys.runtime_dir(), "last-error.json")
        try:
            self._error_seen = os.path.getmtime(path)
        except OSError:
            pass
        while True:
            await asyncio.sleep(1)
            try:
                m = os.path.getmtime(path)
            except OSError:
                continue
            if m > self._error_seen:
                self._error_seen = m
                e = _read_json(path, {})
                if e:
                    await _emit("launch_error", e)

    async def _on_mounts(self):
        await asyncio.sleep(2)  # the desktop's automounter
        roots = await asyncio.to_thread(_roots)
        now = {r["path"] for r in roots if not r["internal"]}
        known, self._seen = self._seen, now
        for gone in set(self._media) - now:
            self._media.pop(gone, None)
        for r in roots:
            if not r["internal"] and r["path"] not in known:
                m = await asyncio.to_thread(self._scan_media, r)
                if m["set_up"] or m["games_total"] or m["bios"]:
                    await _emit("media", m)
        await _emit("roms_changed")

    async def _main(self):
        loop = asyncio.get_running_loop()
        pending = {"t": None}

        def changed():
            if pending["t"] is None or pending["t"].done():
                pending["t"] = asyncio.ensure_future(self._on_mounts())

        threading.Thread(target=_mount_watch, args=(loop, changed), daemon=True).start()
        # the cards in already: scanned for Quick Access' offer, without a toast
        cards = [r for r in await asyncio.to_thread(_roots) if not r["internal"]]
        self._seen = {r["path"] for r in cards}
        for r in cards:
            self._tasks.append(asyncio.create_task(asyncio.to_thread(self._scan_media, r)))
        try:
            from kettle_emulation import seed
            await asyncio.to_thread(seed.ensure_dirs, EMU)
        except Exception as e:
            decky.logger.warning("emulation: making ~/Emulation: %s", e)
        self._tasks += [asyncio.create_task(self._rescan_loop()), asyncio.create_task(self._inbox_loop()),
                        asyncio.create_task(self._error_loop())]

    async def _unload(self):
        await self.upload_stop()
        for t in self._tasks:
            t.cancel()
