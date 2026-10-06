# Power: per-game fan and CPU settings and a live readout, through kettle-powerd
# (packages/kettle-power) on the system bus. Steam's own power controls (TDP limit,
# performance profile, GPU clock) are kettle-powerd's too, set per game in Quick Access >
# Performance; this plugin shows them and sets what Steam has no UI for, the charge speed among
# them. The charge limit is here as well as in Steam's settings (the same setting). The frontend tells kettle-powerd which
# game is running, so a game's settings follow it.
# The screen's refresh rate too, on a device whose panel has more than one (/usr/lib/kettle/
# refresh-rates): gamescope holds it (refresh_hz, gamescope 0023), set live through gamescopectl,
# and gamescope-session starts at it from ~/.config/kettle/refresh-rate.conf.
import asyncio
import json
import os
import re
import subprocess

import decky
import steamlib
from gi.repository import Gio, GLib

BUS_NAME = "org.kettlelinux.Power1"
OBJ_PATH = "/org/kettlelinux/Power1"
SOM = "com.steampowered.SteamOSManager1."
_bus = None


def _call(iface: str, method: str, sig: str | None, args: tuple, out: bool):
    global _bus
    if _bus is None:
        _bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    r = _bus.call_sync(BUS_NAME, OBJ_PATH, iface, method, GLib.Variant(sig, args) if sig else None,
                       None, Gio.DBusCallFlags.NONE, 5000, None)
    return r.unpack()[0] if out else None


async def _power(method: str, *args: str, out: bool = False):
    sig = "(" + "s" * len(args) + ")" if args else None
    return await asyncio.to_thread(_call, BUS_NAME, method, sig, args, out)


def _key(appid) -> str:
    return str(appid) if appid else "default"


RATES_FILE = "/usr/lib/kettle/refresh-rates"
RATE_CONF = os.path.join(decky.DECKY_USER_HOME, ".config", "kettle", "refresh-rate.conf")
# the rate gamescope-session starts at until one is picked (gamescope_refresh_hz)
GAMESCOPE_CONF = "/usr/lib/kettle/gamescope.conf"


def _rates() -> list[int]:
    try:
        with open(RATES_FILE) as f:
            return sorted(int(r) for r in f.read().split())
    except (OSError, ValueError):
        return []


def _default_rate(rates: list[int]) -> int:
    # the device's own, not the highest: the Portal lists 165 Hz, but starts at 120
    try:
        with open(GAMESCOPE_CONF) as f:
            m = re.search(r"^export gamescope_refresh_hz=(\d+)", f.read(), re.M)
        if m and int(m.group(1)) in rates:
            return int(m.group(1))
    except OSError:
        pass
    return rates[-1] if rates else 0


def _refresh() -> dict:
    rates = _rates()
    hz = _default_rate(rates)
    try:
        with open(RATE_CONF) as f:
            m = re.search(r"gamescope_refresh_hz=(\d+)", f.read())
        if m and int(m.group(1)) in rates:
            hz = int(m.group(1))
    except OSError:
        pass
    return {"rates": rates, "hz": hz}


def _apply_refresh(hz: int):
    os.makedirs(os.path.dirname(RATE_CONF), exist_ok=True)
    with open(RATE_CONF + ".new", "w") as f:
        f.write(f"# Quick Access > Power's refresh rate, read by gamescope-session\nexport gamescope_refresh_hz={hz}\n")
    os.replace(RATE_CONF + ".new", RATE_CONF)
    # live, on Game Mode's gamescope: its display is in the user manager's environment
    # (gamescope-onready); the plugin runs as that user, without its session's env
    uid = os.getuid()
    env = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{uid}",
               DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")
    r = subprocess.run(["systemctl", "--user", "show-environment"], env=env, capture_output=True, text=True)
    m = re.search(r"^GAMESCOPE_WAYLAND_DISPLAY=(.+)$", r.stdout, re.M)
    if not m:
        return
    env["GAMESCOPE_WAYLAND_DISPLAY"] = m.group(1)
    subprocess.run(["gamescopectl", "refresh_hz", str(hz)], env=env, check=False, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


class Plugin:
    async def info(self) -> dict:
        return json.loads(await _power("GetInfo", out=True))

    async def status(self) -> dict:
        return json.loads(await _power("GetStatus", out=True))

    async def installed_games(self) -> list[dict]:
        return steamlib.installed_games()

    async def get_game(self, appid: int | None) -> dict:
        return json.loads(await _power("GetGame", _key(appid), out=True))

    async def set_game(self, appid: int | None, settings: dict | None) -> dict:
        """settings None: the game goes back to the all-games settings."""
        await _power("SetGame", _key(appid), json.dumps(settings))
        return await self.get_game(appid)

    async def set_active(self, appid: int | None):
        await _power("SetActiveGame", str(appid) if appid else "")

    async def set_charge_limit(self, limit: int):
        await asyncio.to_thread(_call, "org.freedesktop.DBus.Properties", "Set", "(ssv)",
                                (SOM + "BatteryChargeLimit1", "MaxChargeLevel", GLib.Variant("i", int(limit))), False)

    async def set_charge_speed(self, name: str):
        await _power("SetChargeSpeed", name)

    async def set_charge_current(self, ua: int):
        """The Custom charge speed, at this current (uA)."""
        await asyncio.to_thread(_call, BUS_NAME, "SetChargeCurrent", "(u)", (int(ua),), False)

    async def set_sleep_fan(self, pct: int):
        """The fan's speed while charging asleep, percent; 0 stops it as usual."""
        await asyncio.to_thread(_call, BUS_NAME, "SetSleepFan", "(u)", (int(pct),), False)

    async def get_refresh(self) -> dict:
        return _refresh()

    async def set_refresh(self, hz: int) -> dict:
        if int(hz) in _rates():
            await asyncio.to_thread(_apply_refresh, int(hz))
            decky.logger.info("power: screen at %d Hz", int(hz))
        return _refresh()

    async def _main(self):
        try:
            info = await self.info()
            decky.logger.info("power: kettle-powerd up, profiles %s, fan control %s", info["profiles"], info["fan"])
        except GLib.Error as e:
            decky.logger.error("power: kettle-powerd unreachable: %s", e.message)

    async def _unload(self):
        pass
