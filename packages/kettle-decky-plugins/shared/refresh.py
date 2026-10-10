# The screen's refresh rate, shared by Device Settings (the all-games rate, and holding a game's
# own while it runs) and Game Settings (a game's own rate): the rates the panel has
# (/usr/lib/kettle/refresh-rates), gamescope holding one (refresh_hz, gamescope 0023, set live
# through gamescopectl), and gamescope-session starting at the all-games one from
# ~/.config/kettle/refresh-rate.conf. Installed into each plugin's py_modules/ by the PKGBUILD.
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


def rates() -> list[int]:
    try:
        with open(RATES_FILE) as f:
            return sorted(int(r) for r in f.read().split())
    except (OSError, ValueError):
        return []


def _default_rate(have: list[int]) -> int:
    # the device's own, not the highest: the Portal lists 165 Hz, but starts at 120
    try:
        with open(GAMESCOPE_CONF) as f:
            m = re.search(r"^export gamescope_refresh_hz=(\d+)", f.read(), re.M)
        if m and int(m.group(1)) in have:
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


def session_env() -> dict:
    """Game Mode's gamescope displays, from the user manager's environment (gamescope-onready):
    the plugin runs as that user, without its session's env."""
    uid = os.getuid()
    env = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{uid}",
               DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")
    r = subprocess.run(["systemctl", "--user", "show-environment"], env=env, capture_output=True, text=True)
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
