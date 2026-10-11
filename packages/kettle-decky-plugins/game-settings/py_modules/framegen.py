# Game Settings' Frame Gen tab: per-game settings for Kettle's frame generation layer
# (github.com/kettlelinux/kettle-framegen). It loads only with KETTLE_FG=1 in a game's launch
# options, which the frontend edits; its settings are in ~/.config/kettle-framegen/<appid>.conf, which it
# rereads while the game runs. Each game's settings live in games.json, in the settings of the
# Frame Generation plugin this was before (kettle-framegen), and are kept while the game is off.
#
# Frame generation is always 2x. The game's base frame rate is half the refresh rate held while it
# runs (refresh.py): with FIFO pacing the display holds the game there, so no frame cap in the
# game is needed, and the rate changes live. Turned off while the game runs, the layer (loaded at
# launch) gets multiplier 1.
import json
import os

import decky
import refresh

CONF_DIR = os.path.join(decky.DECKY_USER_HOME, ".config", "kettle-framegen")
GAMES = refresh.FRAMEGEN_GAMES
LAYER = "/usr/lib/libVkLayer_kettle_framegen.so"

DEFAULTS = {
    "enabled": False,
    "flow_scale": 0.5,          # 0.8 costs twice the motion time on the Adreno 740, no visible gain
    "preserve_images": False,   # no extra swapchain images for generated frames
    "bypass_wsi": True,         # ENABLE_GAMESCOPE_WSI=0 (launch option, frontend)
    "refresh": 0,               # Hz held while the game runs, twice its base frame rate; 0: 60 Hz
}
MULTIPLIER = 2


def _clamp(s: dict) -> dict:
    out = dict(DEFAULTS)
    out.update({k: s[k] for k in DEFAULTS if k in s})
    if "refresh" not in s and str(s.get("fps_cap", "")).isdigit():  # older versions capped the game
        out["refresh"] = 2 * int(s["fps_cap"])
    out["refresh"] = refresh.framegen_rate(int(out["refresh"]), refresh.framegen_rates())
    out["flow_scale"] = round(max(0.25, min(1.0, float(out["flow_scale"]))), 2)
    for k in ("enabled", "preserve_images", "bypass_wsi"):
        out[k] = bool(out[k])
    return out


def _view(s: dict) -> dict:
    """Settings, and the rates the device has for them."""
    return {**{k: s[k] for k in DEFAULTS}, "rates": refresh.framegen_rates()}


# ---------- per-game store ----------

def _load_games() -> dict[int, dict]:
    """Stored games; settings older versions kept (lsfg-vk's engine, performance mode and
    noubwc, the multiplier, fifo, low latency, the frame cap and its measurements) are dropped
    by _clamp."""
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
    """A settings file per game it's been on for; the layer rereads it while the game runs, so
    turning it off there gives multiplier 1. FIFO pacing is what holds the game at its base rate.
    No latency line (normal): with the display full at refresh = 2 x base there's no queue to cut,
    and latency = low only made the game stutter."""
    os.makedirs(CONF_DIR, exist_ok=True)
    for appid, s in games.items():
        path = os.path.join(CONF_DIR, f"{appid}.conf")
        if not s["enabled"] and not os.path.exists(path):
            continue
        text = ("# Written by the Kettle Linux Game Settings plugin (Frame Gen)\n"
                f"multiplier = {MULTIPLIER if s['enabled'] else 1}\nflow_scale = {s['flow_scale']}\n"
                f"fifo = true\npreserve_images = {_fmt(s['preserve_images'])}\n")
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


def status() -> dict:
    return {
        "layer": os.path.isfile(LAYER),
        "enabled_games": sorted(a for a, s in _load_games().items() if s["enabled"]),
    }


def get_game(appid: int) -> dict:
    return _view(_load_games().get(appid) or _clamp({}))


def _store(appid: int, g: dict, running: bool) -> dict:
    games = _load_games()
    games[appid] = g
    _save_games(games)
    _sync(games)
    if running:
        refresh.hold(refresh.effective(str(appid)))
    return _view(g)


def set_game(appid: int, settings: dict, running: bool) -> dict:
    """running: the game is running, its refresh rate changes now."""
    return _store(appid, _clamp({**(_load_games().get(appid) or DEFAULTS), **settings}), running)


def reset_game(appid: int, running: bool) -> dict:
    return _store(appid, _clamp({"enabled": (_load_games().get(appid) or DEFAULTS)["enabled"]}), running)


def setup():
    """Settings files up to date at plugin start."""
    games = _load_games()
    if games:
        _save_games(games)  # drops settings of older versions
    _sync(games)  # conf files for games set up by an older plugin version
    decky.logger.info("frame generation: layer %s, %d games on", os.path.isfile(LAYER),
                      sum(s["enabled"] for s in games.values()))
