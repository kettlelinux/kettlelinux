# Power: per-game fan and CPU settings and a live readout, through kettle-powerd
# (packages/kettle-power) on the system bus. Steam's own power controls (TDP limit,
# performance profile, GPU clock) are kettle-powerd's too, set per game in Quick Access >
# Performance; this plugin shows them and sets what Steam has no UI for, the charge speed among
# them. The charge limit is here as well as in Steam's settings (the same setting). The frontend tells kettle-powerd which
# game is running, so a game's settings follow it.
import asyncio
import json

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

    async def _main(self):
        try:
            info = await self.info()
            decky.logger.info("power: kettle-powerd up, profiles %s, fan control %s", info["profiles"], info["fan"])
        except GLib.Error as e:
            decky.logger.error("power: kettle-powerd unreachable: %s", e.message)

    async def _unload(self):
        pass
