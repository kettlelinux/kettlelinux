# The Lights tab: the RGB rings around the sticks (the Odin 2 Portal's, the Thor's, the Retroid
# Pocket 5's) and the power light, through kettle-ledd (packages/kettle-leds) on the system bus. It
# sets them as root and runs the battery level and the animations, in Desktop Mode too, and keeps
# them dark while the device sleeps.
import asyncio
import json

import decky
from gi.repository import Gio, GLib

BUS_NAME = "org.kettlelinux.Leds1"
OBJ_PATH = "/org/kettlelinux/Leds1"
_bus = None


def _call(method: str, *args: str) -> dict:
    global _bus
    if _bus is None:
        _bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    r = _bus.call_sync(BUS_NAME, OBJ_PATH, BUS_NAME, method,
                       GLib.Variant("(" + "s" * len(args) + ")", args) if args else None,
                       GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 5000, None)
    return json.loads(r.unpack()[0])


async def _leds(method: str, *args: str) -> dict:
    try:
        return await asyncio.to_thread(_call, method, *args)
    except GLib.Error as e:
        decky.logger.error("lights: kettle-ledd: %s", e.message)
        return {"available": False, "power_available": False,
                "error": "The lights service (kettle-ledd) isn't answering."}


async def get() -> dict:
    return await _leds("Get")


async def set(changes: dict) -> dict:
    return await _leds("Set", json.dumps(changes))
