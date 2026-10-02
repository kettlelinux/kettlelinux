# Crash Reports: the reports kettle-crashd (packages/kettle-crash) writes to /var/log/kettle-crash,
# one directory per crash: report.json and the text files beside it. The plugin lists and shows
# them, deletes them, and tells the frontend about each new one as it appears; a toast is only
# for the crashes a player notices (a game, Game Mode itself, the GPU), not every helper process.
# A game's crash is a coredump, or (a Windows game in Wine, which makes none) a "game" report
# from its output.
# Nothing is sent anywhere unless the user shares a report: that uploads it, after asking, to
# Kettle's crash report server (crash.conf, set when the image is built), with the user's own
# details taken out first (_bundle). The server keeps it under an unguessable id, at a page
# anyone with the link can read.
import asyncio
import gzip
import json
import os
import re
import shutil
import socket
import urllib.request

import decky

DIR = "/var/log/kettle-crash"
SEEN = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "seen.json")
POLL_S = 3
# processes whose crash takes Game Mode (or the desktop) down with it
NOTICED = {"gamescope", "gamescope-wl", "steam", "Xwayland", "inputplumber", "kwin_wayland",
           "plasmashell"}
_ID = re.compile(r"\d{8}-\d{6}-[A-Za-z0-9._-]+")
# Steam's noise in every game's output (its overlay has no arm64 build); the file keeps it
_NOISE = re.compile(r"gameoverlayrenderer\.so' from LD_PRELOAD cannot be preloaded")
SERVER_CONF = "/usr/lib/kettle/crash.conf"  # KETTLE_CRASH_URL=https://...; none: no sharing
SHARED = "shared.json"  # in a report's directory, once it's uploaded
SHARE_FILES = ("backtrace.txt", "output.txt", "kernel.txt", "journal.txt", "environ.txt")
SHARE_FILE_MAX = 256 << 10  # the end of each file
# environment variables worth sharing (graphics, Proton, Wine, FEX, Steam's ids for the game);
# everything else stays on the device
_SHARE_ENV = re.compile(r"(PROTON_|DXVK_|VKD3D_|WINEDLLOVERRIDES|WINEDEBUG|WINE_|MESA_|TU_|FD_|"
                        r"FEX_|VK_|ENABLE_|GAMESCOPE|SDL_|KETTLE_|LSFG|PRESSURE_VESSEL_|"
                        r"STEAM_COMPAT_APP_ID|SteamAppId|SteamGameId|LD_PRELOAD|LANG)")
# journal lines that name networks, devices nearby or logins: left out of a shared report
_PRIVATE_UNITS = re.compile(r"\b(NetworkManager|wpa_supplicant|iwd|bluetoothd|avahi-daemon|"
                            r"sshd|sudo|systemd-resolved|ModemManager|dhcpcd|systemd-logind)\[")


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
            return "".join([l for l in f if not _NOISE.search(l)][-lines:])
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


def _server() -> str:
    try:
        with open(SERVER_CONF) as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == "KETTLE_CRASH_URL" and v:
                    return v.strip().strip('"').rstrip("/")
    except OSError:
        pass
    return ""


def _accounts() -> list[str]:
    """The Steam account and profile names signed in on this device, longest first."""
    vdf = os.path.join(decky.DECKY_USER_HOME, ".local/share/Steam/config/loginusers.vdf")
    try:
        with open(vdf, errors="replace") as f:
            names = re.findall(r'"(?:AccountName|PersonaName)"\s+"([^"]+)"', f.read())
    except OSError:
        names = []
    return sorted({n for n in names if len(n) >= 3}, key=len, reverse=True)


def _redactor():
    subs = [
        (re.compile(r"/home/[^/\s'\"]+"), "~"),
        (re.compile(r"\b7656119\d{10}\b"), "<steamid>"),
        (re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"), "<mac>"),
        (re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)"
                    r"(?![\d.-])"), "<ip>"),
    ]
    host = socket.gethostname()
    if host and host != "kettle":
        subs.append((re.compile(re.escape(host)), "<host>"))
    for name in _accounts():
        subs.append((re.compile(re.escape(name), re.IGNORECASE), "<account>"))

    def redact(text: str) -> str:
        for pattern, by in subs:
            text = pattern.sub(by, text)
        return text
    return redact


def _redact_value(v, redact):
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, dict):
        return {k: _redact_value(x, redact) for k, x in v.items()}
    if isinstance(v, list):
        return [_redact_value(x, redact) for x in v]
    return v


def _bundle(rid: str, r: dict) -> dict:
    """The report as it's shared: the user's details out, the end of each file only. Core files
    and device dumps stay on the device."""
    redact = _redactor()
    report = {k: v for k, v in r.items() if k not in ("core_file", "pid", "uid")}
    files = {}
    for name in SHARE_FILES:
        try:
            with open(os.path.join(_path(rid), name), errors="replace") as f:
                lines = [l for l in f if not _NOISE.search(l)]
        except OSError:
            continue
        if name == "environ.txt":
            lines = [l for l in lines if _SHARE_ENV.match(l)]
        elif name == "journal.txt":
            lines = [l for l in lines if not _PRIVATE_UNITS.search(l)]
        files[name] = redact("".join(lines))[-SHARE_FILE_MAX:]
    return {"version": 1, "id": rid, "report": _redact_value(report, redact), "files": files}


def _upload(rid: str) -> dict:
    server = _server()
    if not server:
        raise RuntimeError("this image has no crash report server")
    r = _load(rid)
    if r is None:
        raise RuntimeError("the report is gone")
    body = gzip.compress(json.dumps(_bundle(rid, r)).encode())
    req = urllib.request.Request(f"{server}/v1/reports", data=body, method="POST", headers={
        "Content-Type": "application/gzip", "User-Agent": "kettle-crash/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.load(resp)
    shared = {"id": out["id"], "url": out["url"]}
    with open(os.path.join(_path(rid), SHARED), "w") as f:
        json.dump(shared, f)
    return shared


def _shared(rid: str) -> dict | None:
    try:
        with open(os.path.join(_path(rid), SHARED)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


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
            "shared": _shared(rid),
            "can_share": bool(_server()),
        }

    async def share(self, rid: str) -> dict:
        """Upload the report; once only: again, it's the same link."""
        shared = _shared(rid)
        if shared:
            return shared
        try:
            shared = await asyncio.to_thread(_upload, rid)
        except Exception as e:
            decky.logger.error("crash: sharing %s failed: %r", rid, e)
            raise RuntimeError(f"Couldn't upload the report: {e}") from e
        decky.logger.info("crash: shared %s as %s", rid, shared["url"])
        return shared

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
