# The Screens tab: the AYN Thor's bottom screen from Game Mode's Quick Access, which is on the top
# screen (so it can be turned back on from there); only where the image has bottom-screen. It was
# the Screens plugin up to 1.12.0-38. Its setting, ~/.config/kettle/bottom-screen.json,
# is read by bottom-screen (off: the screen stays dark; its refresh rate) and bottom-brightness
# (its brightness, which Steam's own slider leaves alone: that one sets the top screen's).
import json
import os
import subprocess
import threading

import decky

STATE = os.path.join(decky.DECKY_USER_HOME, ".config", "kettle", "bottom-screen.json")
UNIT = "kettle-bottom-screen.service"
BOTTOM_SCREEN = "/usr/lib/kettle/bottom-screen"  # device/thor/overlay
DEFAULT = {"enabled": True, "brightness": 70, "refresh_hz": 60}
REFRESH_RATES = (60, 30)  # 30: bottom-screen offers it (gamescope 0022)


def _load() -> dict:
    s = dict(DEFAULT)
    try:
        with open(STATE) as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULT})
    except (OSError, ValueError, AttributeError):
        pass
    return s


_save_lock = threading.Lock()  # the brightness slider saves beside the toggles' threads


def _save(s: dict):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with _save_lock:
        with open(STATE + ".new", "w") as f:
            json.dump(s, f)
        os.replace(STATE + ".new", STATE)


def _user_env() -> dict:
    # the Game Mode user's session (the plugin runs as that user, without its session's env)
    uid = os.getuid()
    return dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{uid}",
                DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")


def _systemctl(*args: str):
    subprocess.run(["systemctl", "--user", *args], env=_user_env(), check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _apply_refresh(hz: int):
    # live, on the bottom screen's gamescope (bottom-shell names it); a screen that's off or
    # starting picks the setting up from the file instead
    env = _user_env()
    try:
        with open(os.path.join(env["XDG_RUNTIME_DIR"], "kettle-bottom-gamescope")) as f:
            display = f.read().strip()
    except OSError:
        return
    if not display:
        return
    env["GAMESCOPE_WAYLAND_DISPLAY"] = display
    # a fixed rate (gamescope 0023), which switches at once
    subprocess.run(["gamescopectl", "refresh_hz", str(hz)], env=env, check=False, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def available() -> bool:
    return os.path.exists(BOTTOM_SCREEN)


def get() -> dict:
    return _load()


def set_enabled(enabled: bool) -> dict:
    s = _load()
    s["enabled"] = bool(enabled)
    _save(s)
    # off: the bottom gamescope lets go of the screen, which Game Mode's gamescope then blanks
    _systemctl("start" if enabled else "stop", UNIT)
    decky.logger.info("screens: bottom screen %s", "on" if enabled else "off")
    return s


def set_brightness(percent: int):
    s = _load()
    s["brightness"] = max(2, min(100, int(percent)))
    _save(s)


def set_refresh(hz: int) -> dict:
    s = _load()
    s["refresh_hz"] = int(hz) if int(hz) in REFRESH_RATES else 60
    _save(s)
    _apply_refresh(s["refresh_hz"])
    decky.logger.info("screens: bottom screen at %d Hz", s["refresh_hz"])
    return s
