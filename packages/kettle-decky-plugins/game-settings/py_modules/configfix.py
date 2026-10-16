# Game config fixes: a value set in a game's own config file in its Wine prefix, for games that
# need one to run here and have no launch option for it (those are shared/gameFixes.ts). Shown with
# the game fixes in the Compatibility tab, on unless the player turns one off for the game.
#
# A fix only adds its key when the file doesn't have it: a value the game or the player set (in
# the game's own options) is never changed, so the file stays writable and the game keeps it up
# (unlike Lumen's Engine.ini, which games rewrite). The prefix only exists once the game has run
# through Proton, so a new game gets its fix after its first launch (synced at plugin start and
# after every game exits).
#
# configfix.json (the plugin's settings) holds the fixes the player turned off, and for each fix
# written, the file's text before and after; turning a fix off restores the file exactly, or, when
# the game rewrote it since, takes out only our key while it still holds our value.
import json
import os

import decky
import steamlib

STATE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "configfix.json")

FIXES = [
    {
        # Path of Exile 2 picks its native Vulkan renderer with a fresh config and crashes about 2 s
        # after its window opens (vkCreatePipelineLayout: access violation in the Unix call), with
        # any Proton and FEX settings, on the Pocket FIT Elite's Adreno 830. In DirectX 12 (through
        # vkd3d-proton) it runs. The exe has no command-line switch for the renderer; its first
        # (crashing) launch leaves the config holding only a UTF-8 BOM.
        "id": "poe2-directx12",
        "appid": 2694490,
        "path": "drive_c/users/steamuser/Documents/My Games/Path of Exile 2/poe2_production_Config.ini",
        "section": "DISPLAY",
        "key": "renderer_type",
        "value": "DirectX12",
        "new_file": "﻿",  # what a new file starts with: the game writes it with a BOM...
        "newline": "\r\n",     # ...and CRLF line endings
        "title": "Start in DirectX 12",
        "description": "Its Vulkan renderer crashes on these GPUs at load. A renderer picked in "
                       "the game's own options is kept.",
    },
]


def _load() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s = s if isinstance(s, dict) else {}
    s["off"] = [i for i in s.get("off", []) if isinstance(i, str)] if isinstance(s.get("off"), list) else []
    s["applied"] = s["applied"] if isinstance(s.get("applied"), dict) else {}
    return s


def _save(s: dict):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATE)


# The files are read and written as UTF-8 with undecodable bytes kept as they are
# (surrogateescape), so nothing of the game's changes but our line.
def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _write(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        mode = 0o644
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _header(line: str) -> str | None:
    """The section a line opens (lowercase), None for any other line."""
    s = line.strip().lstrip("﻿")
    return s[1:-1].strip().lower() if s.startswith("[") and s.endswith("]") else None


def _key_line(line: str, key: str) -> str | None:
    """The value a line sets for key, None when it sets something else (or is a comment)."""
    s = line.strip().lstrip("﻿")
    if s.startswith((";", "#")) or "=" not in s:
        return None
    k, v = s.split("=", 1)
    return v.strip() if k.strip().lower() == key.lower() else None


def _find(text: str, fix: dict) -> tuple[int, str] | None:
    """The line (index in splitlines) setting the fix's key in its section, and its value."""
    cur = None
    for i, line in enumerate(text.splitlines(keepends=True)):
        h = _header(line)
        if h is not None:
            cur = h
        elif cur == fix["section"].lower():
            v = _key_line(line, fix["key"])
            if v is not None:
                return i, v
    return None


def _with_key(text: str, fix: dict) -> str:
    """text with the fix's key set, after the last line of its section (the section added at the
    end when there's none). The caller knows the key isn't there."""
    bom = "﻿" if text.startswith("﻿") else ""
    lines = text[len(bom):].splitlines(keepends=True)
    nl = next((l[len(l.rstrip("\r\n")):] for l in lines if l.endswith(("\r", "\n"))), fix["newline"])
    if lines and not lines[-1].endswith(("\r", "\n")):
        lines[-1] += nl
    entry = f"{fix['key']}={fix['value']}{nl}"
    start = next((i for i, l in enumerate(lines) if _header(l) == fix["section"].lower()), None)
    if start is None:
        # a blank line before the new section, unless the file is empty
        pad = [nl] if lines and lines[-1].strip() else []
        return bom + "".join(lines + pad + [f"[{fix['section']}]{nl}", entry])
    end = next((i for i in range(start + 1, len(lines)) if _header(lines[i]) is not None), len(lines))
    last = max((i for i in range(start, end) if lines[i].strip()), default=start)  # blank lines stay after
    return bom + "".join(lines[:last + 1] + [entry] + lines[last + 1:])


def _without_key(text: str, fix: dict) -> str:
    """text with the line setting the fix's key to its value taken out (nothing else)."""
    f = _find(text, fix)
    if not f or f[1] != fix["value"]:
        return text
    lines = text.splitlines(keepends=True)
    del lines[f[0]]
    return "".join(lines)


def _path(fix: dict) -> str | None:
    pfx = steamlib.prefix(fix["appid"])
    return os.path.join(pfx, *fix["path"].split("/")) if pfx else None


def _apply(s: dict, fix: dict, path: str) -> bool:
    """The fix's key in the file when the file doesn't set it; False when nothing changed."""
    cur = _read(path)
    a = s["applied"].get(fix["id"])
    found = _find(cur, fix) if cur is not None else None
    if found:
        if a and found[1] != fix["value"]:
            # the game or the player chose something else (the renderer, in the game's options):
            # theirs from now on, and nothing of ours left to take out
            s["applied"].pop(fix["id"])
        # (the game rewrote the file keeping our value: turning off takes out only our line)
        return False
    written = _with_key(cur if cur is not None else fix["new_file"], fix)
    _write(path, written)
    s["applied"][fix["id"]] = {"path": path, "orig": cur, "written": written}
    return True


def _undo(s: dict, fix_id: str) -> bool:
    """The file as it was before our key; False when there was nothing of ours."""
    a = s["applied"].pop(fix_id, None)
    fix = next((f for f in FIXES if f["id"] == fix_id), None)
    if not a or not fix:
        return False
    path = a["path"]
    cur = _read(path)
    if cur is None:
        return True
    if cur == a.get("written"):
        if a.get("orig") is None:
            os.remove(path)  # we made it
        else:
            _write(path, a["orig"])
    else:
        rest = _without_key(cur, fix)
        if rest != cur:
            _write(path, rest)
    return True


def sync_fix(s: dict, fix: dict, installed: bool) -> dict:
    """Bring one fix's file in line with whether it's on. Returns its state for the panel."""
    on = fix["id"] not in s["off"]
    path = _path(fix) if installed else None
    changed = False
    try:
        if on and path:
            changed = _apply(s, fix, path)
        elif fix["id"] in s["applied"] and not on:
            changed = _undo(s, fix["id"])
        elif fix["id"] in s["applied"] and not installed:
            s["applied"].pop(fix["id"])  # uninstalled: nothing to do but forget it
    except OSError as e:
        decky.logger.warning("config fix: %s: %s", fix["id"], e)
    if changed:
        decky.logger.info("config fix: %s %s (%s)", fix["id"],
                          "applied" if fix["id"] in s["applied"] else "taken out", path)
    cur = _read(path) if path else None
    found = _find(cur, fix) if cur is not None else None
    return {"id": fix["id"], "title": fix["title"], "description": fix["description"], "on": on,
            "applied": fix["id"] in s["applied"],
            # the game's own value for the key, when it isn't ours
            "game_value": found[1] if found and fix["id"] not in s["applied"] else None,
            "pending": on and installed and not path}


def _installed() -> set[int]:
    return {g["appid"] for g in steamlib.installed_games()}


def get(appid: int) -> list[dict]:
    """The game's fixes and their state (synced first: the game may have rewritten its file)."""
    s = _load()
    inst = _installed()
    out = [sync_fix(s, f, f["appid"] in inst) for f in FIXES if f["appid"] == appid]
    _save(s)
    return out


def set_on(appid: int, fix_id: str, on: bool) -> list[dict]:
    fix = next((f for f in FIXES if f["id"] == fix_id and f["appid"] == appid), None)
    if not fix:
        raise ValueError(f"no config fix {fix_id!r} for {appid}")
    s = _load()
    s["off"] = [i for i in s["off"] if i != fix_id] + ([] if on else [fix_id])
    _save(s)
    return get(appid)


def sync_all():
    """Every fix whose game is installed (and forgetting the ones whose game is gone)."""
    s = _load()
    inst = _installed()
    for f in FIXES:
        sync_fix(s, f, f["appid"] in inst)
    _save(s)
