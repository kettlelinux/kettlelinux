# Variable refresh rate (the Power tab's Screen section, under the refresh rate): gamescope's
# adaptive_sync, which Steam's own VRR switch sets but which Steam only offers for an external
# screen. Shown where Game Mode's gamescope says the screen can (GAMESCOPE_VRR_CAPABLE: the
# Portal's panel in MSYNC, kettle,msync in its devicetree, kernel 40-kettle/1444). Set live with
# gamescopectl and kept in ~/.config/kettle/vrr.conf, which gamescope-session reads
# (gamescope_adaptive_sync in gamescope's environment), so it holds across restarts.
import os
import re
import subprocess

import decky
import refresh

CONF = os.path.join(decky.DECKY_USER_HOME, ".config", "kettle", "vrr.conf")


def enabled() -> bool:
    try:
        with open(CONF) as f:
            m = re.search(r"gamescope_adaptive_sync=(\d)", f.read())
    except OSError:
        return False
    return bool(m and m.group(1) == "1")


def capable() -> bool:
    env = refresh.session_env()
    if "DISPLAY" not in env:
        return False
    try:
        r = subprocess.run(["xprop", "-root", "GAMESCOPE_VRR_CAPABLE"], env=env, capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.stdout.strip().endswith("= 1")


def get() -> dict:
    return {"capable": capable(), "enabled": enabled()}


def set_enabled(on: bool) -> dict:
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF + ".new", "w") as f:
        f.write("# Device Settings' variable refresh rate, read by gamescope-session\n"
                f"export gamescope_adaptive_sync={1 if on else 0}\n")
    os.replace(CONF + ".new", CONF)
    env = refresh.session_env()
    if "GAMESCOPE_WAYLAND_DISPLAY" in env:
        subprocess.run(["gamescopectl", "adaptive_sync", "1" if on else "0"], env=env, check=False,
                       timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    decky.logger.info("power: variable refresh %s", "on" if on else "off")
    return get()
