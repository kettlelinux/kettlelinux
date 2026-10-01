# Crash Reports: the reports kettle-crashd (packages/kettle-crash) writes to /var/log/kettle-crash,
# one directory per crash: report.json and the text files beside it. The plugin lists and shows
# them, deletes them, and tells the frontend about each new one as it appears; a toast is only
# for the crashes a player notices (a game, Game Mode itself, the GPU), not every helper process.
# Nothing is sent anywhere.
import asyncio
import json
import os
import re
import shutil

import decky

DIR = "/var/log/kettle-crash"
SEEN = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "seen.json")
POLL_S = 3
# processes whose crash takes Game Mode (or the desktop) down with it
NOTICED = {"gamescope", "gamescope-wl", "steam", "Xwayland", "inputplumber", "kwin_wayland",
           "plasmashell"}
_ID = re.compile(r"\d{8}-\d{6}-[A-Za-z0-9._-]+")


def _path(rid: str) -> str:
    if not _ID.fullmatch(rid):
        raise ValueError(f"not a report: {rid}")
    return os.path.join(DIR, rid)


def _load(rid: str) -> dict | None:
    try:
        with open(os.path.join(_path(rid), "report.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None  # not finished yet, or not readable


def _tail(path: str, lines: int) -> str:
    try:
        with open(path, errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


def _summary(rid: str, r: dict) -> dict:
    game = r.get("game") or {}
    if r.get("kind") == "devcoredump":
        what = {"msm": "GPU", "adreno": "GPU"}.get(r.get("driver") or "", r.get("driver") or "Device")
        title = f"{what} crash"
        detail = r.get("device") or ""
    elif r.get("kind") == "game":
        title = game.get("name") or (f"App {r['app_id']}" if r.get("app_id") else "Game")
        detail = {"wine": "Windows exception", "gpu": "GPU lost"}.get(r.get("reason"), "")
    else:
        name = (game.get("name") or f"App {game.get('app_id')}") if r.get("game_process") else None
        title = name or r.get("comm") or "Unknown"
        detail = r.get("signal") or ""
    noticed = r.get("kind") == "devcoredump" or bool(r.get("game_process")) or \
        r.get("comm") in NOTICED
    return {
        "id": rid,
        "kind": r.get("kind"),
        "title": title,
        "detail": detail,
        "time_ms": (r.get("last_time_us") or r.get("time_us") or 0) // 1000,
        "count": r.get("count", 1),
        # the game running at the time, when it isn't the game itself that crashed
        "during": game.get("name") if game and not r.get("game_process") else None,
        "noticed": noticed,
    }


def _ids() -> list[str]:
    try:
        return sorted((d for d in os.listdir(DIR) if _ID.fullmatch(d)), reverse=True)
    except OSError:
        return []


def _list() -> list[dict]:
    out = []
    for rid in _ids():
        r = _load(rid)
        if r:
            out.append(_summary(rid, r))
    return out


def _seen() -> str:
    try:
        with open(SEEN) as f:
            return json.load(f).get("last", "")
    except (OSError, ValueError, AttributeError):
        return ""


def _set_seen(rid: str):
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    with open(SEEN + ".new", "w") as f:
        json.dump({"last": rid}, f)
    os.replace(SEEN + ".new", SEEN)


class Plugin:
    async def list(self) -> dict:
        reports = await asyncio.to_thread(_list)
        return {"reports": reports, "seen": _seen()}

    async def get(self, rid: str) -> dict | None:
        r = _load(rid)
        if r is None:
            return None
        p = _path(rid)
        return {
            "summary": _summary(rid, r),
            "report": r,
            "backtrace": _tail(os.path.join(p, "backtrace.txt"), 200),
            "output": _tail(os.path.join(p, "output.txt"), 120),
            "journal": _tail(os.path.join(p, "journal.txt"), 80),
            "kernel": _tail(os.path.join(p, "kernel.txt"), 40),
        }

    async def mark_seen(self, rid: str):
        if rid > _seen():
            _set_seen(rid)

    async def delete(self, rid: str):
        await asyncio.to_thread(shutil.rmtree, _path(rid), True)

    async def delete_all(self):
        for rid in _ids():
            await asyncio.to_thread(shutil.rmtree, _path(rid), True)

    async def _main(self):
        # reports appearing from now on; one appears when its report.json is written (last)
        known = {s["id"] for s in await asyncio.to_thread(_list)}
        while True:
            await asyncio.sleep(POLL_S)
            for rid in _ids():
                if rid in known:
                    continue
                r = _load(rid)
                if r is None:
                    continue
                known.add(rid)
                await decky.emit("crash", _summary(rid, r))

    async def _unload(self):
        pass
