# Frame Generation: per-game settings for Kettle's frame generation layer
# (packages/kettle-framegen). It loads only with KETTLE_FG=1 in a game's launch options, which
# the frontend edits; its settings are in ~/.config/kettle-framegen/<appid>.conf, which it
# rereads while the game runs. Each game's settings live in the plugin's games.json and are
# kept while the game is off.
#
# Automatic frame cap: our mangoapp build writes the focused app's displayed frame rate to
# $XDG_RUNTIME_DIR/kettle-fps. A sampler turns that into each game's real (pre frame
# generation) rate, and autocap picks the next session's cap from it.
import asyncio
import json
import os
import re
import time

import autocap
import decky
import steamlib

CONF_DIR = os.path.join(decky.DECKY_USER_HOME, ".config", "kettle-framegen")
GAMES = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "games.json")
LAYER = "/usr/lib/libVkLayer_kettle_framegen.so"

DEFAULTS = {
    "enabled": False,
    "multiplier": 2,
    "flow_scale": 0.5,          # 0.8 costs twice the motion time on the Adreno 740, no visible gain
    "fifo": True,               # pace generated frames with FIFO
    "preserve_images": False,   # no extra swapchain images for generated frames
    "bypass_wsi": True,         # ENABLE_GAMESCOPE_WSI=0 (launch option, frontend)
    # base frame cap via DXVK_CONFIG/VKD3D_FRAME_RATE (launch option); "auto" = autocap's
    # measured pick (3x/4x from a ~30 base warp visibly, so the multiplier stays the user's)
    "fps_cap": "auto",
}
FPS_CAPS = ("auto", "off", "30", "40", "60")
# kept alongside the settings: measurement state for the automatic cap
STATE = ("measure", "failed_caps")

FPS_FILE = f"/run/user/{os.getuid()}/kettle-fps"
SAMPLE_S = 2
_refresh = 120      # last display refresh mangoapp reported
_session = None     # the running game's measurement, see _Session


def _clamp(s: dict) -> dict:
    out = dict(DEFAULTS)
    out.update({k: s[k] for k in DEFAULTS if k in s})
    out["multiplier"] = max(2, min(4, int(out["multiplier"])))
    out["flow_scale"] = round(max(0.25, min(1.0, float(out["flow_scale"]))), 2)
    for k in ("enabled", "fifo", "preserve_images", "bypass_wsi"):
        out[k] = bool(out[k])
    if out["fps_cap"] not in FPS_CAPS:
        out["fps_cap"] = DEFAULTS["fps_cap"]
    out.update({k: s[k] for k in STATE if k in s})
    return out


def _view(appid: int, s: dict) -> dict:
    """Settings plus what the frontend shows and needs for the launch options."""
    live = _session.summary() if _session and _session.appid == appid else None
    return {**{k: s[k] for k in DEFAULTS}, "refresh": _refresh, "live": live,
            "measure": s.get("measure"),
            "auto_cap": autocap.decide(s.get("measure"), _refresh, s["multiplier"], s.get("failed_caps", []))}


# ---------- per-game store ----------

def _load_games() -> dict[int, dict]:
    """Stored games; settings older versions kept for lsfg-vk (engine, performance mode,
    noubwc) are dropped by _clamp."""
    try:
        with open(GAMES, encoding="utf-8") as f:
            return {int(k): _clamp(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def _save_games(games: dict[int, dict]):
    os.makedirs(os.path.dirname(GAMES), exist_ok=True)
    tmp = GAMES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in sorted(games.items())}, f, indent=1)
    os.replace(tmp, GAMES)


# ---------- kettle-framegen <appid>.conf ----------

def _fmt(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def _sync(games: dict[int, dict]):
    """One settings file per enabled game; the layer rereads it while the game runs."""
    os.makedirs(CONF_DIR, exist_ok=True)
    for appid, s in games.items():
        path = os.path.join(CONF_DIR, f"{appid}.conf")
        if not s["enabled"]:
            if os.path.exists(path):
                os.remove(path)
            continue
        text = ("# Written by the Kettle Linux Frame Generation plugin\n"
                f"multiplier = {s['multiplier']}\nflow_scale = {s['flow_scale']}\n"
                f"fifo = {_fmt(s['fifo'])}\npreserve_images = {_fmt(s['preserve_images'])}\n")
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    continue  # unchanged: don't make the layer reload
        except OSError:
            pass
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)


# ---------- frame rate sampling ----------

class _Session:
    """One run of one game: its base frame rate samples and the cap it was launched with."""

    def __init__(self, appid: int, pid: int, cap: int | None, fg: bool):
        self.appid, self.pid, self.cap, self.fg = appid, pid, cap, fg
        self.start = time.monotonic()
        self.samples: list[float] = []

    def add(self, fps: float, multiplier: int):
        if time.monotonic() - self.start >= autocap.WARMUP_S and fps > 1:
            self.samples.append(fps / multiplier if self.fg else fps)

    def summary(self) -> dict | None:
        return autocap.summarize(self.samples, self.cap)


def _read_fps() -> dict | None:
    try:
        with open(FPS_FILE, encoding="utf-8") as f:
            d = dict(line.strip().split("=", 1) for line in f if "=" in line)
        return {"pid": int(d["pid"]), "fps": float(d["fps"]), "refresh": int(d["refresh"]),
                "steam": d.get("steam_focused") == "1", "age": time.time() - int(d["time"])}
    except (OSError, KeyError, ValueError):
        return None


def _game_of(pid: int) -> tuple[int, int | None, bool] | None:
    """(appid, cap it was launched with, a frame generation layer loaded) for a game process."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            env = dict(v.split(b"=", 1) for v in f.read().split(b"\0") if b"=" in v)
        with open(f"/proc/{pid}/maps", "rb") as f:
            fg = b"libVkLayer_kettle_framegen" in f.read()
    except OSError:
        return None
    appid = env.get(b"SteamAppId", b"").decode()
    if not appid.isdigit() or appid == "0":
        return None
    m = re.search(rb"maxFrameRate\s*=\s*(\d+)", env.get(b"DXVK_CONFIG", b"")) or \
        re.fullmatch(rb"(\d+)", env.get(b"VKD3D_FRAME_RATE", b""))
    cap = int(m.group(1)) if m and int(m.group(1)) > 0 else None
    return int(appid), cap, fg


def _finish_session():
    """Store the ended session's measurement; the frontend then rewrites the launch options."""
    global _session
    s, _session = _session, None
    summary = s.summary() if s else None
    if not summary:
        return
    games = _load_games()
    g = games.get(s.appid) or _clamp({})
    g["failed_caps"] = autocap.failed_after(summary, g.get("failed_caps", []))
    g["measure"] = summary
    games[s.appid] = g
    _save_games(games)
    decky.logger.info("frame rate %s: %s -> auto cap %s", s.appid, summary,
                      autocap.decide(summary, _refresh, g["multiplier"], g["failed_caps"]))


async def _sampler():
    global _session, _refresh
    while True:
        await asyncio.sleep(SAMPLE_S)
        try:
            if _session and not os.path.exists(f"/proc/{_session.pid}"):
                _finish_session()
            d = _read_fps()
            if not d or d["age"] > 3 * SAMPLE_S or d["steam"]:
                continue  # no frames lately, or Steam's UI in front of the game
            _refresh = d["refresh"] or _refresh
            if not _session or _session.pid != d["pid"]:
                game = _game_of(d["pid"])
                if not game:
                    continue
                if _session:
                    _finish_session()
                _session = _Session(game[0], d["pid"], game[1], game[2])
            g = _load_games().get(_session.appid)
            _session.add(d["fps"], g["multiplier"] if g else 1)
        except Exception as e:  # keep sampling
            decky.logger.warning("frame rate sampler: %s", e)


class Plugin:
    async def status(self) -> dict:
        return {
            "layer": os.path.isfile(LAYER),
            "enabled_games": sorted(a for a, s in _load_games().items() if s["enabled"]),
        }

    async def installed_games(self) -> list[dict]:
        return steamlib.installed_games()

    async def get_game(self, appid: int) -> dict:
        return _view(appid, _load_games().get(appid) or _clamp({}))

    async def set_game(self, appid: int, settings: dict) -> dict:
        games = _load_games()
        games[appid] = _clamp({**games.get(appid, DEFAULTS), **settings})
        _save_games(games)
        _sync(games)
        return _view(appid, games[appid])

    async def reset_game(self, appid: int) -> dict:
        games = _load_games()
        # measurements stay (they describe the game), failed caps get another chance
        old = games.get(appid, DEFAULTS)
        games[appid] = _clamp({"enabled": old["enabled"], "measure": old.get("measure")})
        _save_games(games)
        _sync(games)
        return _view(appid, games[appid])

    async def _main(self):
        games = _load_games()
        if games:
            _save_games(games)  # drops settings of older versions (lsfg-vk)
        _sync(games)  # conf files for games set up by an older plugin version
        decky.logger.info("frame generation: layer %s, %d games on", os.path.isfile(LAYER),
                          sum(s["enabled"] for s in games.values()))
        await _sampler()

    async def _unload(self):
        pass
