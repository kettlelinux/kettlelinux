# Game Settings: per-game compatibility profiles. A profile is a set of options from the catalog
# (shared/game-options.json, installed next to this file): FEX, DXVK, vkd3d-proton, Turnip and
# Proton settings the frontend writes into the game's launch options, plus custom variables, DLL
# overrides and the Proton version (Steam's compatibility tool). Each game's profile is kept in
# games.json, with which launch option entries the plugin wrote (so it only ever takes out its
# own); profiles the user saves by name to reuse on other games are in profiles.json.
#
# The game database (server/game-db; KETTLE_GAMES_URL in games.conf, set when the image is
# built) holds profiles players shared as known good. A profile can be shared only once the game
# was played for PLAYED_MIN_S with exactly those settings and the user said it works; a player
# who applies one from the database can say whether it worked for them too. Nothing is sent
# unless the user asks.
import asyncio
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

import decky
import steamlib

CATALOG = os.path.join(decky.DECKY_PLUGIN_DIR, "game-options.json")
GAMES = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "games.json")
PROFILES = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "profiles.json")
INSTALL_ID = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "install-id")
SERVER_CONF = "/usr/lib/kettle/games.conf"  # KETTLE_GAMES_URL=https://...; none: no database
PLAYED_MIN_S = 300  # play time with a profile before it can be shared or confirmed
CACHE_S = 600  # the database's answer for a game
RATINGS = ("great", "playable")
MAX_NOTES = 500
MAX_PROFILES = 50

EMPTY = {"settings": {}, "env": [], "dlls": [], "compat_tool": None}
GAME_DEFAULTS = {
    **EMPTY,
    # launch option entries the plugin wrote (option ids, variable names, DLL names), each with
    # what was there before it (None: nothing), which the frontend puts back when it's dropped
    "owned": {"options": {}, "env": {}, "dlls": {}},
    "compat_before": None,  # Steam's tool before the plugin changed it ("" = Steam's default)
    "source": None,         # {id, status, hash}: applied from the game database
    "played": None,         # {hash, seconds, compat_tool}: play time with one profile
    "verdict": None,        # {hash, works}: the user's own verdict on a profile
    "shared": None,         # {id, hash}: shared to the game database
    "voted": [],            # database profiles this device confirmed or reported
}

_cat = None
_cache: dict[int, tuple[float, dict]] = {}


# ---------- catalog and validation ----------

def _catalog() -> dict:
    global _cat
    if _cat is None:
        with open(CATALOG, encoding="utf-8") as f:
            c = json.load(f)
        choices = {o["id"]: {ch["value"] for ch in o["choices"]} for o in c["options"]}
        managed = set(c["custom"]["env_reserved"])
        for o in c["options"]:
            t = o["target"]
            managed.add(t.get("env") or t.get("flags") or "DXVK_CONFIG")
        _cat = {**c, "choices": choices, "managed": managed,
                "dll_modes_set": {m["value"] for m in c["custom"]["dll_modes"]}}
    return _cat


def _valid_env(name, value) -> bool:
    c = _catalog()
    cu = c["custom"]
    return (isinstance(name, str) and isinstance(value, str)
            and re.fullmatch(cu["env_name"], name) is not None
            and any(name.startswith(p) for p in cu["env_prefixes"])
            and name not in c["managed"]
            and re.fullmatch(cu["env_value"], value) is not None)


def _valid_dll(name, mode) -> bool:
    c = _catalog()
    return (isinstance(name, str) and isinstance(mode, str)
            and re.fullmatch(c["custom"]["dll_name"], name) is not None and mode in c["dll_modes_set"])


def _pairs(items, valid, limit: int) -> list[list[str]]:
    out, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if isinstance(item, list) and len(item) == 2 and valid(*item) and item[0] not in seen:
            out.append([item[0], item[1]])
            seen.add(item[0])
    return out[:limit]


def clean_profile(p: dict) -> dict:
    """Only what the catalog allows: for profiles from the frontend, disk and the database."""
    c = _catalog()
    settings = p.get("settings") if isinstance(p.get("settings"), dict) else {}
    tool = p.get("compat_tool")
    return {
        "settings": {k: v for k, v in sorted(settings.items()) if v in c["choices"].get(k, ())},
        "env": _pairs(p.get("env"), _valid_env, c["custom"]["max_env"]),
        "dlls": _pairs(p.get("dlls"), _valid_dll, c["custom"]["max_dlls"]),
        "compat_tool": tool if isinstance(tool, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", tool) else None,
    }


def profile_hash(p: dict) -> str:
    p = clean_profile(p)
    p["env"] = sorted(p["env"])
    p["dlls"] = sorted(p["dlls"])
    return hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]


def _clean_owned(o) -> dict:
    out = {}
    for k in ("options", "env", "dlls"):
        rec = o.get(k) if isinstance(o, dict) else None
        rec = rec if isinstance(rec, dict) else {}
        out[k] = {n: (v if isinstance(v, str) and len(v) <= 512 else None)
                  for n, v in list(rec.items())[:64] if isinstance(n, str)}
    return out


def _is_empty(p: dict) -> bool:
    return clean_profile(p) == EMPTY


# ---------- storage ----------

def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def _load_games() -> dict[int, dict]:
    raw = _read_json(GAMES, {})
    games = {}
    for k, v in raw.items() if isinstance(raw, dict) else []:
        if str(k).isdigit() and isinstance(v, dict):
            games[int(k)] = {**GAME_DEFAULTS, **v, **clean_profile(v), "owned": _clean_owned(v.get("owned"))}
    return games


def _save_games(games: dict[int, dict]):
    _write_json(GAMES, {str(k): v for k, v in sorted(games.items())})


def _view(appid: int, g: dict) -> dict:
    """The stored game plus what the frontend shows: whether it can be shared or confirmed."""
    h = profile_hash(g)
    played = g["played"] if g["played"] and g["played"].get("hash") == h else None
    seconds = played["seconds"] if played else 0
    works = bool(g["verdict"] and g["verdict"].get("hash") == h and g["verdict"].get("works"))
    broken = bool(g["verdict"] and g["verdict"].get("hash") == h and not g["verdict"].get("works"))
    source = g["source"] if g["source"] and g["source"].get("hash") == h else None
    shared = bool(g["shared"] and g["shared"].get("hash") == h)
    return {
        **g,
        "appid": appid,
        "hash": h,
        "played_s": seconds,
        "played_enough": seconds >= PLAYED_MIN_S,
        "played_min_s": PLAYED_MIN_S,
        "works": works,
        "broken": broken,
        "from_database": source,
        "is_shared": shared,
        "can_submit": bool(_server()) and works and seconds >= PLAYED_MIN_S and not shared and not source,
        "can_vote": bool(_server()) and bool(source) and source["id"] not in g["voted"] and seconds > 0,
    }


# ---------- device and server ----------

def _server() -> str:
    try:
        with open(SERVER_CONF, encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == "KETTLE_GAMES_URL" and v:
                    return v.strip().strip('"').rstrip("/")
    except OSError:
        pass
    return ""


def _device() -> dict:
    try:
        with open("/proc/device-tree/model", "rb") as f:
            model = f.read().rstrip(b"\0").decode(errors="replace").strip()
    except OSError:
        model = ""
    osr = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                osr[k] = v.strip('"')
    except OSError:
        pass
    return {"model": model[:64], "variant": osr.get("VARIANT_ID", ""), "build": osr.get("BUILD_ID", "")}


def _install_id() -> str:
    """A random id for this install, so the database counts one vote per device. Nothing else
    about the device or the user is in it."""
    try:
        with open(INSTALL_ID, encoding="utf-8") as f:
            iid = f.read().strip()
        if re.fullmatch(r"[0-9a-f]{32}", iid):
            return iid
    except OSError:
        pass
    iid = secrets.token_hex(16)
    os.makedirs(os.path.dirname(INSTALL_ID), exist_ok=True)
    with open(INSTALL_ID, "w", encoding="utf-8") as f:
        f.write(iid + "\n")
    return iid


def _request(method: str, path: str, body: dict | None = None) -> dict:
    server = _server()
    if not server:
        raise RuntimeError("this image has no game database")
    req = urllib.request.Request(
        server + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "User-Agent": "kettle-game-settings/1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace").strip()[:200]
        raise RuntimeError(msg or f"the game database answered {e.code}") from e


def _fetch(appid: int) -> dict:
    hit = _cache.get(appid)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    out = _request("GET", f"/v1/games/{appid}")
    profiles = []
    for p in out.get("profiles", []) if isinstance(out, dict) else []:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str):
            continue
        profiles.append({
            **clean_profile(p),
            "id": p["id"][:32],
            "status": "approved" if p.get("status") == "approved" else "pending",
            "rating": p.get("rating") if p.get("rating") in RATINGS else "playable",
            "notes": str(p.get("notes") or "")[:MAX_NOTES],
            "device": str(p.get("device") or "")[:64],
            "variant": str(p.get("variant") or "")[:32],
            "build": str(p.get("build") or "")[:20],
            "works": int(p.get("works") or 0),
            "broken": int(p.get("broken") or 0),
        })
    data = {"profiles": profiles, "page": f"{_server()}/g/{appid}"}
    _cache[appid] = (time.monotonic(), data)
    return data


class Plugin:
    async def status(self) -> dict:
        games = _load_games()
        return {
            "can_share": bool(_server()),
            "device": _device(),
            "configured": sorted(a for a, g in games.items() if not _is_empty(g)),
        }

    async def installed_games(self) -> list[dict]:
        return steamlib.installed_games()

    async def get_game(self, appid: int) -> dict:
        return _view(appid, _load_games().get(appid) or dict(GAME_DEFAULTS))

    async def set_game(self, appid: int, patch: dict) -> dict:
        """Store a game's profile (settings, env, dlls, compat_tool) and bookkeeping (owned,
        compat_before, source, verdict) from the frontend; anything else in patch is ignored."""
        games = _load_games()
        g = {**(games.get(appid) or GAME_DEFAULTS)}
        g.update(clean_profile({**g, **{k: patch[k] for k in EMPTY if k in patch}}))
        if isinstance(patch.get("owned"), dict):
            g["owned"] = _clean_owned(patch["owned"])
        if "compat_before" in patch:
            g["compat_before"] = patch["compat_before"] if isinstance(patch["compat_before"], str) else None
        if "source" in patch:
            s = patch["source"]
            g["source"] = ({"id": str(s["id"])[:32], "status": str(s.get("status", "pending"))[:16],
                            "hash": profile_hash(g)} if isinstance(s, dict) and s.get("id") else None)
        if "verdict" in patch:
            g["verdict"] = {"hash": profile_hash(g), "works": bool(patch["verdict"])} \
                if patch["verdict"] is not None else None
        games[appid] = g
        _save_games(games)
        return _view(appid, g)

    async def reset_game(self, appid: int) -> dict:
        """Forget a game's profile; what it has learnt about sharing and votes stays."""
        games = _load_games()
        old = games.get(appid) or GAME_DEFAULTS
        games[appid] = {**GAME_DEFAULTS, "voted": old["voted"], "shared": old["shared"]}
        _save_games(games)
        return _view(appid, games[appid])

    async def record_play(self, appid: int, seconds: float, compat_tool: str):
        """A session of a game ended: count its time towards the profile it ran with."""
        if seconds <= 0:
            return
        games = _load_games()
        g = games.get(appid) or dict(GAME_DEFAULTS)
        h = profile_hash(g)
        played = g["played"] if g["played"] and g["played"].get("hash") == h else {"hash": h, "seconds": 0}
        played["seconds"] = int(played["seconds"] + seconds)
        if isinstance(compat_tool, str) and re.fullmatch(r"[A-Za-z0-9_.-]{0,64}", compat_tool):
            played["compat_tool"] = compat_tool
        g["played"] = played
        games[appid] = g
        _save_games(games)

    # ----- saved profiles -----

    async def list_profiles(self) -> list[dict]:
        raw = _read_json(PROFILES, [])
        return [{"name": str(p.get("name"))[:40], **clean_profile(p)}
                for p in raw if isinstance(p, dict) and p.get("name")] if isinstance(raw, list) else []

    async def save_profile(self, name: str, profile: dict) -> list[dict]:
        name = " ".join(str(name).split())[:40]
        if not name:
            raise ValueError("a profile needs a name")
        profiles = [p for p in await self.list_profiles() if p["name"] != name]
        p = clean_profile(profile)
        p["compat_tool"] = None  # a tool belongs to a game; saved profiles are for any game
        _write_json(PROFILES, ([{"name": name, **p}] + profiles)[:MAX_PROFILES])
        return await self.list_profiles()

    async def delete_profile(self, name: str) -> list[dict]:
        _write_json(PROFILES, [p for p in await self.list_profiles() if p["name"] != name])
        return await self.list_profiles()

    # ----- game database -----

    async def community(self, appid: int) -> dict:
        if not _server():
            return {"profiles": [], "page": None, "error": None, "enabled": False}
        try:
            data = await asyncio.to_thread(_fetch, appid)
            return {**data, "error": None, "enabled": True}
        except Exception as e:
            decky.logger.warning("game database: %s: %r", appid, e)
            return {"profiles": [], "page": None, "error": str(e), "enabled": True}

    async def submit(self, appid: int, game: str, rating: str, notes: str) -> dict:
        """Share the game's profile as known good. Only what's listed here is sent."""
        games = _load_games()
        g = games.get(appid)
        if not g or not _view(appid, g)["can_submit"]:
            raise RuntimeError(f"play the game for {PLAYED_MIN_S // 60} minutes with these settings "
                               "and mark them as working first")
        d = _device()
        body = {
            "install_id": _install_id(),
            "app_id": appid,
            "game": str(game)[:128],
            "device": d["model"],
            "variant": d["variant"],
            "build": d["build"],
            **clean_profile({**g, "compat_tool": g["played"].get("compat_tool") or None}),
            "rating": rating if rating in RATINGS else "playable",
            "notes": " ".join(str(notes).split())[:MAX_NOTES],
        }
        try:
            out = await asyncio.to_thread(_request, "POST", "/v1/profiles", body)
        except Exception as e:
            decky.logger.error("game database: sharing %s failed: %r", appid, e)
            raise RuntimeError(f"Couldn't share the settings: {e}") from e
        g["shared"] = {"id": str(out.get("id", ""))[:32], "hash": profile_hash(g)}
        games[appid] = g
        _save_games(games)
        _cache.pop(appid, None)
        decky.logger.info("game database: shared %s as %s", appid, g["shared"]["id"])
        return {"id": g["shared"]["id"], "url": out.get("url") or f"{_server()}/g/{appid}"}

    async def vote(self, appid: int, works: bool) -> dict:
        """Say whether the database profile applied to this game worked here."""
        games = _load_games()
        g = games.get(appid)
        v = _view(appid, g) if g else None
        if not v or not v["can_vote"]:
            raise RuntimeError("play the game with the database settings first")
        if works and not v["played_enough"]:
            raise RuntimeError(f"play for {PLAYED_MIN_S // 60} minutes before confirming these settings")
        pid = v["from_database"]["id"]
        d = _device()
        try:
            await asyncio.to_thread(_request, "POST", f"/v1/profiles/{urllib.parse.quote(pid)}/votes", {
                "install_id": _install_id(), "works": bool(works),
                "device": d["model"], "variant": d["variant"], "build": d["build"]})
        except Exception as e:
            raise RuntimeError(f"Couldn't send it: {e}") from e
        g["voted"] = (g["voted"] + [pid])[-200:]
        g["verdict"] = {"hash": profile_hash(g), "works": bool(works)}
        games[appid] = g
        _save_games(games)
        _cache.pop(appid, None)
        return _view(appid, g)

    async def _main(self):
        n = sum(not _is_empty(g) for g in _load_games().values())
        decky.logger.info("game settings: %d games with a profile, database %s", n, _server() or "off")

    async def _unload(self):
        pass
