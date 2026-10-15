# The screen's refresh rate, shared by Device Settings (the all-games rate, and holding a game's
# own while it runs) and Game Settings (a game's own rate): the rates the panel has
# (/usr/lib/kettle/refresh-rates), gamescope holding one (refresh_hz, gamescope 0023, set live
# through gamescopectl), and gamescope-session starting at the all-games one from
# ~/.config/kettle/refresh-rate.conf. Installed into each plugin's py_modules/ by the PKGBUILD.
# While a game runs, the rate held is effective(): Frame Gen's if it's on for the game, else the
# game's own, else the all-games one.
import json
import os
import re
import subprocess

import decky

RATES_FILE = "/usr/lib/kettle/refresh-rates"
RATE_CONF = os.path.join(decky.DECKY_USER_HOME, ".config", "kettle", "refresh-rate.conf")
# the rate gamescope-session starts at until one is picked (gamescope_refresh_hz)
GAMESCOPE_CONF = "/usr/lib/kettle/gamescope.conf"
# refresh_hz 0: no rate held, Steam's frame limit picks one (Device Settings' Auto)
AUTO = 0
# games with their own refresh rate, {appid: Hz or AUTO}; the others follow the all-games one.
# In the settings of the Power plugin (now Device Settings), where they were before Game Settings set them
GAME_RATES = os.path.join(os.path.dirname(decky.DECKY_PLUGIN_SETTINGS_DIR), "kettle-power", "refresh-rates.json")
# Game Settings' Frame Gen tab (framegen.py): each game's settings, in the settings of the Frame
# Generation plugin it was before. A game with frame generation on holds the rate twice its base
# frame rate: the layer presents each generated frame and the real one back to back with FIFO, so
# pacing is only even at refresh = 2 x base, and the display then holds the game at that base.
FRAMEGEN_GAMES = os.path.join(os.path.dirname(decky.DECKY_PLUGIN_SETTINGS_DIR), "kettle-framegen", "games.json")
FRAMEGEN_MIN_FPS = 25  # lower base frame rates warp motion; 25 is the Portal's 50 Hz


def rates() -> list[int]:
    try:
        with open(RATES_FILE) as f:
            return sorted(int(r) for r in f.read().split())
    except (OSError, ValueError):
        return []


def _default_rate(have: list[int]) -> int:
    # the device's own, not the highest: the Portal lists 165 Hz, but starts at Auto
    try:
        with open(GAMESCOPE_CONF) as f:
            m = re.search(r"^export gamescope_refresh_hz=(\d+)", f.read(), re.M)
        if m and (int(m.group(1)) in have or int(m.group(1)) == AUTO):
            return int(m.group(1))
    except OSError:
        pass
    return have[-1] if have else 0


def all_games() -> dict:
    """The rates there are, and the all-games one (AUTO for Auto)."""
    have = rates()
    hz = _default_rate(have)
    try:
        with open(RATE_CONF) as f:
            m = re.search(r"gamescope_refresh_hz=(\d+)", f.read())
        if m and (int(m.group(1)) in have or int(m.group(1)) == AUTO):
            hz = int(m.group(1))
    except OSError:
        pass
    return {"rates": have, "hz": hz}


def valid(hz: int) -> bool:
    return int(hz) in rates() or int(hz) == AUTO


def game_rates() -> dict:
    try:
        with open(GAME_RATES) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return {}
    ok = set(rates()) | {AUTO}
    return {str(k): int(v) for k, v in saved.items() if isinstance(v, int) and v in ok}


def save_game_rates(game: dict):
    os.makedirs(os.path.dirname(GAME_RATES), exist_ok=True)
    with open(GAME_RATES + ".new", "w") as f:
        json.dump(game, f, indent=1, sort_keys=True)
    os.replace(GAME_RATES + ".new", GAME_RATES)


def framegen_rates() -> list[int]:
    """The rates Frame Gen can hold: those whose half is at least FRAMEGEN_MIN_FPS, lowest first.
    A panel with one rate has no list (the RP5's): 60 Hz."""
    return [r for r in rates() if r // 2 >= FRAMEGEN_MIN_FPS] or [60]


def framegen_rate(hz: int, ok: list[int]) -> int:
    """A Frame Gen rate the panel has: hz, else the nearest below it (a rate older versions or
    another device stored), else the lowest. 0: the default, 60 Hz (a 30 fps base)."""
    hz = hz or 2 * 30
    return max([r for r in ok if r <= hz] or [ok[0]])


def framegen_games() -> dict:
    """{appid: Hz} of the games with frame generation on."""
    try:
        with open(FRAMEGEN_GAMES) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return {}
    ok = framegen_rates()
    return {str(k): framegen_rate(v.get("refresh") if isinstance(v.get("refresh"), int) else 0, ok)
            for k, v in saved.items() if isinstance(v, dict) and v.get("enabled")}


def effective(appid: str) -> int:
    """The rate to hold while this game runs ("": none runs)."""
    if appid:
        hz = framegen_games().get(appid) or game_rates().get(appid)
        if hz is not None:
            return hz
    return all_games()["hz"]


def session_env() -> dict:
    """Game Mode's gamescope displays, from the user manager's environment (gamescope-onready):
    the plugin runs as that user, without its session's env."""
    uid = os.getuid()
    env = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{uid}",
               DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")
    try:
        r = subprocess.run(["systemctl", "--user", "show-environment"], env=env, capture_output=True, text=True,
                           timeout=10)
    except subprocess.TimeoutExpired:
        return env
    for k in ("GAMESCOPE_WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"):
        m = re.search(rf"^{k}=(.+)$", r.stdout, re.M)
        if m:
            env[k] = m.group(1)
    return env


def hold(hz: int):
    """Live, on Game Mode's gamescope (the same rate again changes nothing)."""
    env = session_env()
    if "GAMESCOPE_WAYLAND_DISPLAY" not in env:
        return
    subprocess.run(["gamescopectl", "refresh_hz", str(hz)], env=env, check=False, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
