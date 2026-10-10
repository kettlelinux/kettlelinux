# kettle-powerd (packages/kettle-power) on the system bus, for the Power and Game Settings
# plugins. Installed into each plugin's py_modules/ by the PKGBUILD.
import asyncio
import json

from gi.repository import Gio, GLib

BUS_NAME = "org.kettlelinux.Power1"
OBJ_PATH = "/org/kettlelinux/Power1"
_bus = None


def call(iface: str, method: str, sig: str | None, args: tuple, out: bool):
    global _bus
    if _bus is None:
        _bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    r = _bus.call_sync(BUS_NAME, OBJ_PATH, iface, method, GLib.Variant(sig, args) if sig else None,
                       None, Gio.DBusCallFlags.NONE, 5000, None)
    return r.unpack()[0] if out else None


async def power(method: str, *args: str, out: bool = False):
    sig = "(" + "s" * len(args) + ")" if args else None
    return await asyncio.to_thread(call, BUS_NAME, method, sig, args, out)


def key(appid) -> str:
    """kettle-powerd's name for a game's settings: its appid, or "default" for all games."""
    return str(appid) if appid else "default"


async def get_json(method: str, *args: str):
    return json.loads(await power(method, *args, out=True))
