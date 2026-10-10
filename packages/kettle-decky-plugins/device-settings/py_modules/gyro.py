# The Gyro tab: the motion sensors for Steam Input, through kettle-motiond (packages/kettle-motion)
# on the system bus, on the devices that have it. It streams the gyro and accelerometer into the
# Steam Deck controller only when wanted (to save power): while a game runs (set_game, from the
# plugin's set_active), always, or never.
import asyncio

import decky
from gi.repository import Gio, GLib

BUS_NAME = "org.kettlelinux.Motion1"
OBJ_PATH = "/org/kettlelinux/Motion1"
_bus = None


def _call(method: str, args: GLib.Variant | None = None, reply: str | None = None):
    global _bus
    if _bus is None:
        _bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    r = _bus.call_sync(BUS_NAME, OBJ_PATH, BUS_NAME, method, args,
                       GLib.VariantType(reply) if reply else None, Gio.DBusCallFlags.NONE, 5000, None)
    return r.unpack()[0] if reply else None


async def _motion(method: str, args: GLib.Variant | None = None, reply: str | None = None, quiet: bool = False):
    try:
        return await asyncio.to_thread(_call, method, args, reply)
    except GLib.Error as e:
        if not quiet:
            decky.logger.error("gyro: kettle-motiond: %s", e.message)
        return None


async def get(quiet: bool = False) -> dict:
    """service: kettle-motiond answers (it isn't installed on a device without motion sensors)."""
    state = await _motion("Get", None, "(a{sv})", quiet)
    if state is None:
        return {"available": False, "service": False}
    return {**state, "service": True}


async def set_mode(mode: str) -> dict:
    await _motion("SetMode", GLib.Variant("(s)", (mode,)))
    return await get()


async def set_game(running: bool):
    await _motion("SetGame", GLib.Variant("(b)", (running,)), quiet=True)
