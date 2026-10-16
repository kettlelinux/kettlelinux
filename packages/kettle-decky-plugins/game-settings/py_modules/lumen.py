# Game Settings' Lumen switch (Performance tab): Lumen, Unreal Engine 5's global illumination and
# reflections, off in UE5 games unless the player turns it back on, for all games or one. It is
# the heaviest part of most UE5 games on these GPUs (Expedition 33 on the Pocket FIT Elite: 24 ->
# 28 fps, no visible change), and many games keep it on even at their Low preset.
#
# It goes through the game's own user config: [SystemSettings] in its user Engine.ini, which UE
# applies over its quality presets: in the Wine prefix (AppData/Local/<project>/Saved/Config/
# Windows, or Documents/My Games/<project>/... as Oblivion Remastered has it) or, for games that
# keep Saved next to the game (Black Myth: Wukong), in the install folder; whichever the game
# made its config in. The file is made read-only, since games rewrite
# it at launch and drop what they don't know (Expedition 33 deletes it). Some games ignore the
# user Engine.ini (Titan Quest II); it changes nothing for them. The config only exists once the
# game has run, so a new game gets it from its second launch on.
#
# lumen.json (the plugin's settings) holds the all-games choice, the games' own, and for each game
# it was written to, the file's text before and after and its mode, so turning Lumen back on
# restores the file exactly (or, when something else changed it since, takes out only our lines).
import json
import os
import struct

import decky
import steamlib

STATE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "lumen.json")
MARK = "; Kettle Linux: Lumen off (Game Settings > Performance)"
CVARS = [("r.DynamicGlobalIlluminationMethod", "0"),  # no Lumen GI (0: none)
         ("r.ReflectionMethod", "2")]                 # screen-space reflections instead of Lumen's
CHOICES = ("default", "off", "on")  # a game's own: follow all games, Lumen off, Lumen on


def _load() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s = s if isinstance(s, dict) else {}
    s["default_off"] = s.get("default_off", True) is not False
    for k in ("games", "applied"):
        s[k] = s[k] if isinstance(s.get(k), dict) else {}
    return s


def _save(s: dict):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATE)


def engine_major(exe: str) -> int | None:
    """The UE major version from the exe's version resource (UE stamps the engine's version
    there: 5.4.4.0 for Expedition 33, 4.27.2.0 for Deep Rock Galactic); only .rsrc is read."""
    try:
        with open(exe, "rb") as f:
            h = f.read(64)
            if h[:2] != b"MZ":
                return None
            f.seek(struct.unpack_from("<I", h, 0x3C)[0])
            pe = f.read(24)
            if pe[:4] != b"PE\0\0":
                return None
            n, opt = struct.unpack_from("<H", pe, 6)[0], struct.unpack_from("<H", pe, 20)[0]
            f.seek(f.tell() + opt)
            secs = f.read(40 * n)
            for i in range(n):
                name, _, _, size, ptr = struct.unpack_from("<8sIIII", secs, 40 * i)
                if name.rstrip(b"\0") == b".rsrc":
                    f.seek(ptr)
                    data = f.read(min(size, 4 << 20))
                    k = data.find(struct.pack("<I", 0xFEEF04BD))  # VS_FIXEDFILEINFO
                    if k >= 0 and len(data) >= k + 12:
                        major = struct.unpack_from("<I", data, k + 8)[0] >> 16
                        return major if 4 <= major <= 9 else None
    except (OSError, struct.error):
        pass
    return None


def _ini_path(appid: int, root: str, exe_rel: str) -> str | None:
    """The game's user Engine.ini: in Saved/Config/Windows under AppData/Local/<project> or
    Documents/My Games/<project> in its prefix (<project>: the folder its Binaries are in, matched
    ignoring case, spaces and punctuation: OblivionRemastered is "Oblivion Remastered"), or under
    <project> in its install folder; the one the game made its config in. None before it has."""
    parts = exe_rel.replace("\\", "/").split("/")
    low = [p.lower() for p in parts]
    if "binaries" not in low or low.index("binaries") == 0:
        return None
    i = low.index("binaries")
    norm = lambda n: "".join(ch for ch in n.lower() if ch.isalnum())
    cands = []
    pfx = steamlib.prefix(appid)
    if pfx:
        user = os.path.join(pfx, "drive_c", "users", "steamuser")
        for base in (os.path.join(user, "AppData", "Local"), os.path.join(user, "Documents", "My Games")):
            try:
                cands += [os.path.join(base, e) for e in os.listdir(base) if norm(e) == norm(parts[i - 1])]
            except OSError:
                pass
    cands.append(os.path.join(root, *parts[:i]))
    for c in cands:
        d = os.path.join(c, "Saved", "Config", "Windows")
        if any(os.path.isfile(os.path.join(d, f)) for f in ("Engine.ini", "GameUserSettings.ini")):
            return os.path.join(d, "Engine.ini")
    return None


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _write(path: str, text: str, mode: int):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.chmod(path, 0o644)  # ours, or the game's: writable to replace it
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _without_ours(text: str) -> str:
    """text with our marker and the lines after it that set our cvars taken out."""
    names = {k.lower() for k, _ in CVARS}
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s == MARK:
            skipping = True
            continue
        if skipping and "=" in s and s.split("=", 1)[0].strip().lower() in names:
            continue
        skipping = False
        out.append(line)
    return "".join(out)


def _with_ours(text: str) -> str:
    """text with our block at the top of [SystemSettings] (a new section when there's none), and
    any other values for our cvars taken out, so ours are the ones UE reads."""
    names = {k.lower() for k, _ in CVARS}
    lines = _without_ours(text).splitlines(keepends=True)
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    if lines and not lines[-1].endswith(("\r", "\n")):
        lines[-1] += nl
    block = [MARK + nl] + [f"{k}={v}{nl}" for k, v in CVARS]
    out, cur, placed = [], None, False
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
            out.append(line)
            if cur.lower() == "systemsettings" and not placed:
                out += block
                placed = True
            continue
        if cur and cur.lower() == "systemsettings" and "=" in s and not s.startswith(";") \
                and s.split("=", 1)[0].strip().lower() in names:
            continue
        out.append(line)
    if not placed:
        out += ([nl] if out else []) + [f"[SystemSettings]{nl}"] + block
    return "".join(out)


def _empty(text: str) -> bool:
    """Nothing but an empty [SystemSettings] (what's left of a file we made)."""
    return all(not l.strip() or l.strip().lower() == "[systemsettings]" for l in text.splitlines())


def _apply(s: dict, appid: int, path: str) -> bool:
    """Our block in the game's Engine.ini, the file read-only; False when it already was."""
    a = s["applied"].get(str(appid))
    cur = _read(path)
    if a and a.get("path") == path and cur is not None and cur == a.get("written"):
        if os.stat(path).st_mode & 0o222:
            os.chmod(path, 0o444)
        return False
    if a and a.get("path") == path:
        # the file changed since we wrote it (a game update, Steam's verify): what's there now,
        # less our lines, is the game's
        orig = _without_ours(cur) if cur is not None else a.get("orig")
        mode = a.get("mode")
    else:
        orig = cur
        mode = os.stat(path).st_mode & 0o777 if cur is not None else None
    written = _with_ours(cur or "")
    _write(path, written, 0o444)
    s["applied"][str(appid)] = {"path": path, "orig": orig, "written": written, "mode": mode}
    return True


def _undo(s: dict, appid: int) -> bool:
    """The game's Engine.ini as it was before; False when there was nothing of ours."""
    a = s["applied"].pop(str(appid), None)
    if not a:
        return False
    path = a["path"]
    cur = _read(path)
    if cur is None:
        return True
    rest = a.get("orig") if cur == a.get("written") else _without_ours(cur)
    if rest is None or (a.get("orig") is None and _empty(rest)):
        os.chmod(path, 0o644)
        os.remove(path)
    else:
        _write(path, rest, a.get("mode") or 0o644)
    return True


def wanted_off(s: dict, appid: int) -> bool:
    c = s["games"].get(str(appid), "default")
    return s["default_off"] if c == "default" else c == "off"


def sync_game(s: dict, appid: int, engine: dict | None) -> dict:
    """Bring one game's Engine.ini in line with its choice. engine: what gameengine found (with
    the main exe relative to install), None when not installed. Returns the game's state."""
    root = steamlib.install_dir(appid)
    exe = engine.get("exe") if engine and engine.get("engine") == "unreal" else None
    major = None
    if root and exe and exe.lower().endswith(".exe"):
        # some exes are packed, without a version resource; the engine's crash reporter has it too
        major = engine_major(os.path.join(root, exe)) or \
            engine_major(os.path.join(root, "Engine", "Binaries", "Win64", "CrashReportClient.exe"))
    off = wanted_off(s, appid)
    path = _ini_path(appid, root, exe) if major == 5 else None
    a = s["applied"].get(str(appid))
    if major == 5 and not path and a and os.path.isdir(os.path.dirname(a["path"])):
        path = a["path"]  # the game deleted its Engine.ini (Expedition 33): where it was
    changed = False
    try:
        if major == 5 and off and path:
            changed = _apply(s, appid, path)
        elif str(appid) in s["applied"] and not (major == 5 and off):
            changed = _undo(s, appid)
    except OSError as e:
        decky.logger.warning("lumen: %s: %s", appid, e)
    if changed:
        decky.logger.info("lumen: %s: Lumen %s (%s)", appid, "off" if str(appid) in s["applied"] else "back on", path)
    return {"ue5": major == 5, "choice": s["games"].get(str(appid), "default"), "off": off,
            "applied": str(appid) in s["applied"], "pending": major == 5 and off and not path}


def get(appid: int | None, engine_of) -> dict:
    """appid None: the all-games choice. engine_of(appid) -> what gameengine found, or None."""
    s = _load()
    if appid is None:
        return {"default_off": s["default_off"]}
    g = sync_game(s, appid, engine_of(appid))
    _save(s)
    return {"default_off": s["default_off"], **g}


def set_choice(appid: int | None, value, engine_of) -> dict:
    """appid None: value is whether Lumen is off in UE5 games by default (every game following
    it is synced); else value is the game's own choice (CHOICES)."""
    s = _load()
    if appid is None:
        s["default_off"] = bool(value)
        _save(s)
        sync_all(engine_of)
        return get(None, engine_of)
    if value not in CHOICES:
        raise ValueError(f"invalid Lumen choice {value!r}")
    if value == "default":
        s["games"].pop(str(appid), None)
    else:
        s["games"][str(appid)] = value
    _save(s)
    return get(appid, engine_of)


def sync_all(engine_of):
    """Every installed game, plus the ones we wrote to that are gone (uninstalled: nothing to do
    but forget them)."""
    s = _load()
    games = {g["appid"] for g in steamlib.installed_games()}
    for appid in sorted(games | {int(a) for a in s["applied"]}):
        try:
            engine = engine_of(appid) if appid in games else None
        except Exception as e:  # one game's scan mustn't stop the others
            decky.logger.warning("lumen: %s: %r", appid, e)
            continue
        if engine is None and appid not in games:
            s["applied"].pop(str(appid), None)
            continue
        sync_game(s, appid, engine)
    _save(s)
