# Power: per-game fan and CPU settings and a live readout, through kettle-powerd
# (packages/kettle-power) on the system bus. Steam's own power controls (TDP limit,
# performance profile, GPU clock) are kettle-powerd's too, set per game in Quick Access >
# Performance; this plugin shows them and sets what Steam has no UI for, the charge speed among
# them. The charge limit is here as well as in Steam's settings (the same setting). The frontend tells kettle-powerd which
# game is running, so a game's settings follow it.
# The screen's refresh rate too, on a device whose panel has more than one (/usr/lib/kettle/
# refresh-rates): gamescope holds it (refresh_hz, gamescope 0023), set live through gamescopectl,
# and gamescope-session starts at it from ~/.config/kettle/refresh-rate.conf. Auto (0) holds none:
# Steam's frame limit picks the rate, up to auto_refresh_max_hz when there's no limit (0024).
# A game can have its own rate (or Auto), held while it runs (refresh-rates.json in the plugin's
# settings), told by the frontend's set_active.
# Auto TDP holds a game at Steam's frame rate limit, which Steam sets on gamescope's Xwayland
# root window (GAMESCOPE_FPS_LIMIT): the plugin watches it with xprop and passes it on.
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
_active = ""  # the running game's appid as last told to kettle-powerd, sent again with the frame rate limit


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
# refresh_hz 0: no rate held, Steam's frame limit picks one (Quick Access > Power's Auto)
AUTO = 0
# games with their own refresh rate, {appid: Hz or AUTO}; the others follow the all-games one
GAME_RATES = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "refresh-rates.json")


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
        if m and (int(m.group(1)) in rates or int(m.group(1)) == AUTO):
            hz = int(m.group(1))
    except OSError:
        pass
    return {"rates": rates, "hz": hz}


def _session_env() -> dict:
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


def _game_rates() -> dict:
    try:
        with open(GAME_RATES) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return {}
    ok = set(_rates()) | {AUTO}
    return {str(k): int(v) for k, v in saved.items() if isinstance(v, int) and v in ok}


def _save_game_rates(rates: dict):
    os.makedirs(os.path.dirname(GAME_RATES), exist_ok=True)
    with open(GAME_RATES + ".new", "w") as f:
        json.dump(rates, f, indent=1, sort_keys=True)
    os.replace(GAME_RATES + ".new", GAME_RATES)


def _effective_rate() -> int:
    """The running game's own rate, else the all-games one."""
    return _game_rates().get(_active, _refresh()["hz"])


def _apply_refresh(hz: int):
    """The all-games rate: what gamescope-session starts at, and live unless the running game has its own."""
    os.makedirs(os.path.dirname(RATE_CONF), exist_ok=True)
    with open(RATE_CONF + ".new", "w") as f:
        f.write(f"# Quick Access > Power's refresh rate, read by gamescope-session\nexport gamescope_refresh_hz={hz}\n")
    os.replace(RATE_CONF + ".new", RATE_CONF)
    _hold_refresh(_effective_rate())


def _hold_refresh(hz: int):
    """Live, on Game Mode's gamescope (the same rate again changes nothing)."""
    env = _session_env()
    if "GAMESCOPE_WAYLAND_DISPLAY" not in env:
        return
    subprocess.run(["gamescopectl", "refresh_hz", str(hz)], env=env, check=False, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


FPS_LIMIT = re.compile(rb"GAMESCOPE_FPS_LIMIT\(CARDINAL\) = (\d+)")
FPS_LIMIT_RESEND = 30  # s: sent again this often (with the running game), for a kettle-powerd that restarted


async def _watch_fps_limit():
    """Steam's frame rate limit (0: none) to kettle-powerd, for Auto TDP. xprop -spy prints the
    property at start and on every change; it ends with gamescope, and starts again."""
    sent = None
    while True:
        env = await asyncio.to_thread(_session_env)
        proc = None
        try:
            if "DISPLAY" in env:
                # line buffered: xprop's own output to a pipe waits for a full buffer
                proc = await asyncio.create_subprocess_exec(
                    "stdbuf", "-oL", "xprop", "-display", env["DISPLAY"], "-root", "-spy", "GAMESCOPE_FPS_LIMIT",
                    env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                limit = 0
                while True:
                    try:
                        line = await asyncio.wait_for(proc.stdout.readline(), FPS_LIMIT_RESEND)
                    except asyncio.TimeoutError:
                        line = None
                    if line == b"":
                        break
                    if line is not None:
                        m = FPS_LIMIT.search(line)
                        limit = int(m.group(1)) if m else 0  # "not found": Steam set none
                    if line is None:
                        await _power("SetActiveGame", _active)
                    if line is None or limit != sent:
                        await asyncio.to_thread(_call, BUS_NAME, "SetFpsLimit", "(u)", (limit,), False)
                        if limit != sent:
                            decky.logger.info("power: Steam's frame rate limit %s", limit or "off")
                        sent = limit
        except (OSError, GLib.Error) as e:
            decky.logger.warning("power: frame rate limit: %s", e)
            sent = None
        finally:
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
        await asyncio.sleep(5)


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
        global _active
        _active = str(appid) if appid else ""
        await _power("SetActiveGame", _active)
        # a game with its own refresh rate gets it while it runs, the all-games one after
        if _rates():
            await asyncio.to_thread(_hold_refresh, _effective_rate())

    async def get_game_refresh(self, appid: int) -> dict:
        """hz: the game's own rate (AUTO for Auto), None when it follows the all-games one."""
        return {"hz": _game_rates().get(str(appid))}

    async def set_game_refresh(self, appid: int, hz: int | None) -> dict:
        rates = _game_rates()
        if hz is None:
            rates.pop(str(appid), None)
        elif int(hz) in _rates() or int(hz) == AUTO:
            rates[str(appid)] = int(hz)
        await asyncio.to_thread(_save_game_rates, rates)
        if str(appid) == _active:
            await asyncio.to_thread(_hold_refresh, _effective_rate())
        decky.logger.info("power: game %s refresh %s", appid, "all games'" if hz is None else hz)
        return await self.get_game_refresh(appid)

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
        if int(hz) in _rates() or int(hz) == AUTO:
            await asyncio.to_thread(_apply_refresh, int(hz))
            decky.logger.info("power: screen at %s", f"{int(hz)} Hz" if int(hz) else "auto")
        return _refresh()

    async def _main(self):
        try:
            info = await self.info()
            decky.logger.info("power: kettle-powerd up, profiles %s, fan control %s", info["profiles"], info["fan"])
        except GLib.Error as e:
            decky.logger.error("power: kettle-powerd unreachable: %s", e.message)
        self._fps_limit = asyncio.create_task(_watch_fps_limit())

    async def _unload(self):
        if getattr(self, "_fps_limit", None):
            self._fps_limit.cancel()
