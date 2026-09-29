# Screens: the AYN Thor's bottom screen from Game Mode's Quick Access, which is on the top screen
# (so it can be turned back on from there). Its setting, ~/.config/kettle/bottom-screen.json,
# is read by bottom-screen (off: the screen stays dark) and bottom-brightness (its brightness,
# which Steam's own slider leaves alone: that one sets the top screen's).
import asyncio
import json
import os
import subprocess

import decky

STATE = os.path.join(decky.DECKY_USER_HOME, ".config", "kettle", "bottom-screen.json")
UNIT = "kettle-bottom-screen.service"
DEFAULT = {"enabled": True, "brightness": 70}


def _load() -> dict:
    s = dict(DEFAULT)
    try:
        with open(STATE) as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULT})
    except (OSError, ValueError, AttributeError):
        pass
    return s


def _save(s: dict):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE + ".new", "w") as f:
        json.dump(s, f)
    os.replace(STATE + ".new", STATE)


def _systemctl(*args: str):
    # the Game Mode user's own manager (the plugin runs as that user, without its session's env)
    uid = os.getuid()
    env = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{uid}",
               DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")
    subprocess.run(["systemctl", "--user", *args], env=env, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


class Plugin:
    async def get(self) -> dict:
        return _load()

    async def set_enabled(self, enabled: bool) -> dict:
        s = _load()
        s["enabled"] = bool(enabled)
        _save(s)
        # off: the bottom gamescope lets go of the screen, which Game Mode's gamescope then blanks
        await asyncio.to_thread(_systemctl, "start" if enabled else "stop", UNIT)
        decky.logger.info("screens: bottom screen %s", "on" if enabled else "off")
        return s

    async def set_brightness(self, percent: int):
        s = _load()
        s["brightness"] = max(2, min(100, int(percent)))
        _save(s)

    async def _main(self):
        pass

    async def _unload(self):
        pass
