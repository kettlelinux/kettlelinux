# Device Settings: the device's own settings, a tab each. Power: the battery (charge limit and
# speed, the fan while charging asleep) and the screen's all-games refresh rate, through
# kettle-powerd (packages/kettle-power) on the system bus (powerd.py). Lights: the stick and power
# lights (kettle-ledd, lights.py). Gyro: the motion sensors (kettle-motiond, gyro.py). Screens:
# the Thor's bottom screen (screens.py). System: the start-up mode, the SSH server, resetting the
# device, and updating a ROCKNIX ABL bootloader (system.py). And the Diagnostics window: everything about the device. This was the Power plugin up to 1.12.0-36;
# its refresh-rates.json stays in that plugin's settings (refresh.py). Steam's own power controls (TDP limit, performance profile, GPU
# clock) are kettle-powerd's too, set per game in Quick Access > Performance; the per-game fan, CPU
# and Auto TDP settings, and a game's own refresh rate, are set in Game Settings' Performance tab.
# The frontend tells which game is running (set_active): kettle-powerd, so a game's settings follow
# it, and kettle-motiond, which streams the motion sensors while one runs; and the game's own
# refresh rate is held while it runs.
# The refresh rate on a device whose panel has more than one (refresh.py): Auto (0) holds none:
# Steam's frame limit picks the rate, up to auto_refresh_max_hz when there's no limit (0024).
# Auto TDP holds a game at Steam's frame rate limit, which Steam sets on gamescope's Xwayland
# root window (GAMESCOPE_FPS_LIMIT): the plugin watches it with xprop and passes it on.
import asyncio
import ctypes
import os
import re
import signal
import subprocess

import decky
import gyro
import lights
import refresh
import screens
import system
from gi.repository import GLib
from powerd import BUS_NAME, call, get_json, power

SOM = "com.steampowered.SteamOSManager1."
_active = ""  # the running game's appid as last told to kettle-powerd, sent again with the frame rate limit


def _effective_rate() -> int:
    """The running game's own rate, else the all-games one."""
    return refresh.game_rates().get(_active, refresh.all_games()["hz"])


def _apply_refresh(hz: int):
    """The all-games rate: what gamescope-session starts at, and live unless the running game has its own."""
    os.makedirs(os.path.dirname(refresh.RATE_CONF), exist_ok=True)
    with open(refresh.RATE_CONF + ".new", "w") as f:
        f.write(f"# Device Settings' refresh rate, read by gamescope-session\nexport gamescope_refresh_hz={hz}\n")
    os.replace(refresh.RATE_CONF + ".new", refresh.RATE_CONF)
    refresh.hold(_effective_rate())


def _die_with_parent():
    """In the child, before exec: killed when the backend ends. Decky stops a backend by killing it
    (on a restart too), which _watch_fps_limit's finally doesn't see, and xprop -spy runs forever."""
    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


FPS_LIMIT = re.compile(rb"GAMESCOPE_FPS_LIMIT\(CARDINAL\) = (\d+)")
FPS_LIMIT_RESEND = 30  # s: sent again this often (with the running game), for a kettle-powerd that restarted


async def _watch_fps_limit():
    """Steam's frame rate limit (0: none) to kettle-powerd, for Auto TDP. xprop -spy prints the
    property at start and on every change; it ends with gamescope, and starts again."""
    sent = None
    while True:
        proc = None
        try:
            env = await asyncio.to_thread(refresh.session_env)
            if "DISPLAY" in env:
                # line buffered: xprop's own output to a pipe waits for a full buffer
                proc = await asyncio.create_subprocess_exec(
                    "stdbuf", "-oL", "xprop", "-display", env["DISPLAY"], "-root", "-spy", "GAMESCOPE_FPS_LIMIT",
                    env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    preexec_fn=_die_with_parent)
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
                        await power("SetActiveGame", _active)
                    if line is None or limit != sent:
                        await asyncio.to_thread(call, BUS_NAME, "SetFpsLimit", "(u)", (limit,), False)
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


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip("\0\n ")
    except OSError:
        return None


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024


def _uptime() -> str:
    s = int(float((_read("/proc/uptime") or "0").split()[0]))
    d, s = divmod(s, 86400)
    return (f"{d} d " if d else "") + f"{s // 3600} h {s % 3600 // 60} min"


def _os() -> dict:
    rel = {}
    for line in (_read("/etc/os-release") or "").splitlines():
        k, _, v = line.partition("=")
        rel[k] = v.strip('"')
    return rel


def _slot() -> str | None:
    m = re.search(r"Booted from: \S+ \((\w+)\)", _run("rauc", "status"))
    return m.group(1) if m else None


def _packages(*names: str) -> dict:
    out = {}
    for line in _run("pacman", "-Q", *names).splitlines():
        name, _, ver = line.partition(" ")
        out[name] = ver
    return out


def _gpu() -> dict:
    v = {}
    for line in _run("vulkaninfo", "--summary").splitlines():
        k, _, val = line.partition("=")
        v.setdefault(k.strip(), val.strip())
    return v


def _cpu() -> list[list[str]]:
    rows = []
    policies = sorted(p for p in os.listdir("/sys/devices/system/cpu/cpufreq") if p.startswith("policy"))
    for p in policies:
        base = f"/sys/devices/system/cpu/cpufreq/{p}"
        cpus = _read(f"{base}/related_cpus") or ""
        top = int(_read(f"{base}/cpuinfo_max_freq") or 0)
        rows.append([f"Cores {cpus.replace(' ', ', ')}", f"up to {top // 1000} MHz"])
    gov = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if gov:
        rows.append(["Governor", gov])
    rows.append(["Load average", " / ".join((_read("/proc/loadavg") or "").split()[:3])])
    return rows


def _memory() -> list[list[str]]:
    mem = {}
    for line in (_read("/proc/meminfo") or "").splitlines():
        k, _, v = line.partition(":")
        mem[k] = int(v.split()[0]) * 1024
    rows = [["RAM", f"{_size(mem['MemTotal'] - mem['MemAvailable'])} used of {_size(mem['MemTotal'])}"]]
    if mem.get("SwapTotal"):
        rows.append(["Swap (zram)", f"{_size(mem['SwapTotal'] - mem['SwapFree'])} used of {_size(mem['SwapTotal'])}"])
    return rows


def _storage() -> list[list[str]]:
    rows = []
    model = " ".join(filter(None, (_read("/sys/block/sda/device/vendor"), _read("/sys/block/sda/device/model"))))
    if model:
        rows.append(["Internal", f"{model} (UFS)"])
    for label, path in (("System", "/"), ("Home", "/home")):
        st = os.statvfs(path)
        total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        rows.append([label, f"{_size(free)} free of {_size(total)}"])
    for mnt in _run("findmnt", "-no", "TARGET", "-S", "/dev/mmcblk0p1").splitlines()[:1]:
        st = os.statvfs(mnt)
        name = _read("/sys/block/mmcblk0/device/name") or "SD card"
        rows.append([f"microSD ({name})", f"{_size(st.f_bavail * st.f_frsize)} free of {_size(st.f_blocks * st.f_frsize)}"])
    return rows


def _battery() -> list[list[str]]:
    b = "/sys/class/power_supply/battery"
    if not os.path.isdir(b):
        return []

    def num(f: str) -> int | None:
        v = _read(f"{b}/{f}") or ""
        return int(v) if v.lstrip("-").isdigit() else None

    rows = []
    full, design = num("charge_full"), num("charge_full_design")
    if full and design:
        rows.append(["Capacity", f"{full // 1000} of {design // 1000} mAh as made ({round(100 * full / design)}%)"])
    for label, f in (("Health", "health"), ("Technology", "technology")):
        if _read(f"{b}/{f}"):
            rows.append([label, _read(f"{b}/{f}")])
    if num("cycle_count") is not None:
        rows.append(["Charge cycles", str(num("cycle_count"))])
    if num("voltage_now"):
        rows.append(["Voltage", f"{num('voltage_now') / 1e6:.2f} V"])
    cur = num("current_now")
    if cur is not None:
        rows.append(["Current", f"{cur / 1e6:+.2f} A"])
    if num("temp") is not None:
        rows.append(["Temperature", f"{num('temp') / 10:.1f} °C"])
    tte, ttf = num("time_to_empty_avg"), num("time_to_full_avg")
    if ttf and ttf > 0:
        rows.append(["Full in", f"{ttf // 3600} h {ttf % 3600 // 60} min"])
    elif tte and tte > 0:
        rows.append(["Empty in", f"{tte // 3600} h {tte % 3600 // 60} min"])
    for psy in sorted(os.listdir("/sys/class/power_supply")):
        p = f"/sys/class/power_supply/{psy}"
        if _read(f"{p}/type") == "USB" and _read(f"{p}/online") == "1":
            kind = re.search(r"\[(\w+)\]", _read(f"{p}/usb_type") or "")
            rows.append(["Charger", f"{kind.group(1) if kind else 'USB'}, connected"])
            break
    return rows


def _display() -> list[list[str]]:
    rows = []
    for conn in sorted(os.listdir("/sys/class/drm")):
        p = f"/sys/class/drm/{conn}"
        if "-" not in conn or "Writeback" in conn or _read(f"{p}/status") != "connected":
            continue
        mode = (_read(f"{p}/modes") or "").split("\n")[0]
        name = "Built-in screen" if "DSI" in conn or "eDP" in conn else f"External ({conn.split('-', 1)[1]})"
        rows.append([name, mode or "connected"])
    rates = refresh.rates()
    if rates:
        rows.append(["Refresh rates", ", ".join(f"{r} Hz" for r in rates)])
    for bl in sorted(os.listdir("/sys/class/backlight")) if os.path.isdir("/sys/class/backlight") else []:
        cur, top = _read(f"/sys/class/backlight/{bl}/brightness"), _read(f"/sys/class/backlight/{bl}/max_brightness")
        if cur and top and int(top):
            rows.append(["Brightness", f"{round(100 * int(cur) / int(top))}%"])
            break
    return rows


def _network() -> list[list[str]]:
    rows = []
    for dev in sorted(os.listdir("/sys/class/net")):
        if not os.path.isdir(f"/sys/class/net/{dev}/wireless"):
            continue
        link = _run("iw", "dev", dev, "link")
        ssid, sig = re.search(r"SSID: (.+)", link), re.search(r"signal: (-?\d+)", link)
        freq, rate = re.search(r"freq: ([\d.]+)", link), re.search(r"rx bitrate: ([\d.]+ \S+)", link)
        if not ssid:
            rows.append(["Wi-Fi", "not connected"])
            continue
        band = ""
        if freq:
            f = float(freq.group(1))
            band = ", 6 GHz" if f > 5900 else ", 5 GHz" if f > 4900 else ", 2.4 GHz"
        rows.append(["Wi-Fi", f"{ssid.group(1)}{band}"])
        if sig:
            rows.append(["Signal", f"{sig.group(1)} dBm"])
        if rate:
            rows.append(["Link speed", rate.group(1)])
        addr = re.search(r"inet (\S+)/", _run("ip", "-4", "-o", "addr", "show", dev))
        if addr:
            rows.append(["IP address", addr.group(1)])
    if os.path.isdir("/sys/class/bluetooth"):
        blocked = any(_read(f"/sys/class/rfkill/{r}/soft") == "1" for r in os.listdir("/sys/class/rfkill")
                      if _read(f"/sys/class/rfkill/{r}/type") == "bluetooth")
        rows.append(["Bluetooth", "off" if blocked else "on"])
    return rows


def _temperatures() -> list[list[str]]:
    """Every thermal zone, grouped by part (cpu3-top-thermal, cpu3-bottom-thermal: CPU), the hottest of each."""
    groups = {}
    base = "/sys/class/thermal"
    for z in os.listdir(base):
        if not z.startswith("thermal_zone"):
            continue
        name, t = _read(f"{base}/{z}/type"), _read(f"{base}/{z}/temp")
        if not name or not t or not t.lstrip("-").isdigit():
            continue
        part = re.sub(r"\d.*$", "", name.split("-")[0]) or name
        groups[part] = max(groups.get(part, -1e9), int(t) / 1000)
    LABELS = {"cpu": "CPU", "cpuss": "CPU subsystem", "gpuss": "GPU", "mem": "Memory", "aoss": "Always-on",
              "video": "Video", "camera": "Camera", "modem": "Modem", "cdsp": "DSP", "battery": "Battery", "pm": "Power chips"}
    return [[LABELS.get(k, k.capitalize()), f"{v:.0f} °C"]
            for k, v in sorted(groups.items(), key=lambda kv: -kv[1])]


def _diagnostics() -> list[dict]:
    rel = _os()
    soc = "/sys/bus/soc/devices/soc0"
    gpu = _gpu()
    pkgs = _packages("linux-kettle", "deckard-mesa", "mesa", "gamescope", "steam", "decky-loader", "fex-emu-wine",
                     "kettle-power")
    slot = _slot()
    device = [
        ["Model", _read("/proc/device-tree/model") or rel.get("VARIANT", "")],
        ["Chip", " ".join(filter(None, (_read(f"{soc}/family"), _read(f"{soc}/machine"))))
         + (f" rev {_read(f'{soc}/revision')}" if _read(f"{soc}/revision") else "")],
        ["GPU", gpu.get("deviceName", "")],
        ["Uptime", _uptime()],
    ]
    software = [
        ["Kettle Linux", f"{rel.get('VERSION_ID', '')} build {rel.get('BUILD_ID', '?')}"
         + (f", slot {slot}" if slot else "")],
        ["Update branch", rel.get("STEAMOS_DEFAULT_UPDATE_BRANCH", "")],
        ["Kernel", os.uname().release],
        ["Graphics driver", gpu.get("driverInfo", "") or pkgs.get("deckard-mesa") or pkgs.get("mesa", "")],
        ["Vulkan", gpu.get("apiVersion", "")],
    ]
    for label, name in (("gamescope", "gamescope"), ("Steam bootstrap", "steam"), ("FEX", "fex-emu-wine"),
                        ("Decky Loader", "decky-loader"), ("kettle-power", "kettle-power")):
        if name in pkgs:
            software.append([label, pkgs[name]])
    sections = [
        ("Device", device), ("Software", software), ("CPU", _cpu()), ("Memory", _memory()),
        ("Storage", _storage()), ("Battery", _battery()), ("Display", _display()), ("Network", _network()),
        ("Temperatures", _temperatures()),
    ]
    return [{"title": t, "rows": [r for r in rows if r[1]]} for t, rows in sections if rows]


class Plugin:
    async def diagnostics(self) -> list[dict]:
        """Everything about the device, for the Diagnostics window: [{title, rows: [[label, value]]}]."""
        return await asyncio.to_thread(_diagnostics)

    async def info(self) -> dict:
        return await get_json("GetInfo")

    async def status(self) -> dict:
        return await get_json("GetStatus")

    async def set_active(self, appid: int | None):
        global _active
        _active = str(appid) if appid else ""
        await gyro.set_game(bool(appid))
        await power("SetActiveGame", _active)
        # a game with its own refresh rate gets it while it runs, the all-games one after
        if refresh.rates():
            await asyncio.to_thread(refresh.hold, _effective_rate())

    async def set_charge_limit(self, limit: int):
        await asyncio.to_thread(call, "org.freedesktop.DBus.Properties", "Set", "(ssv)",
                                (SOM + "BatteryChargeLimit1", "MaxChargeLevel", GLib.Variant("i", int(limit))), False)

    async def set_charge_speed(self, name: str):
        await power("SetChargeSpeed", name)

    async def set_charge_current(self, ua: int):
        """The Custom charge speed, at this current (uA)."""
        await asyncio.to_thread(call, BUS_NAME, "SetChargeCurrent", "(u)", (int(ua),), False)

    async def set_sleep_fan(self, pct: int):
        """The fan's speed while charging asleep, percent; 0 stops it as usual."""
        await asyncio.to_thread(call, BUS_NAME, "SetSleepFan", "(u)", (int(pct),), False)

    async def get_refresh(self) -> dict:
        return refresh.all_games()

    async def set_refresh(self, hz: int) -> dict:
        if refresh.valid(hz):
            await asyncio.to_thread(_apply_refresh, int(hz))
            decky.logger.info("power: screen at %s", f"{int(hz)} Hz" if int(hz) else "auto")
        return refresh.all_games()

    async def lights_get(self) -> dict:
        return await lights.get()

    async def lights_set(self, changes: dict) -> dict:
        return await lights.set(changes)

    async def gyro_get(self) -> dict:
        # the Gyro tab asks several times a second: an error is logged when kettle-motiond goes away, not on every ask
        r = await gyro.get(quiet=getattr(self, "_gyro_down", False))
        self._gyro_down = not r.get("service")
        return r

    async def gyro_set_mode(self, mode: str) -> dict:
        return await gyro.set_mode(mode)

    async def screens_get(self) -> dict:
        return screens.get()

    async def screens_set_enabled(self, enabled: bool) -> dict:
        return await asyncio.to_thread(screens.set_enabled, enabled)

    async def screens_set_brightness(self, percent: int):
        screens.set_brightness(percent)

    async def screens_set_refresh(self, hz: int) -> dict:
        return await asyncio.to_thread(screens.set_refresh, hz)

    async def boot_mode(self) -> str | None:
        return await asyncio.to_thread(system.boot_mode)

    async def set_boot_mode(self, mode: str):
        await asyncio.to_thread(system.set_boot_mode, mode)

    async def ssh_status(self) -> dict:
        return await asyncio.to_thread(system.ssh_status)

    async def set_ssh(self, on: bool):
        await asyncio.to_thread(system.set_ssh, on)

    async def reset_status(self) -> dict:
        return await asyncio.to_thread(system.reset_status)

    async def reset(self, what: str):
        await asyncio.to_thread(system.reset, what)

    async def abl_status(self) -> dict:
        return await asyncio.to_thread(system.abl_status)

    async def abl_update(self) -> dict:
        return await asyncio.to_thread(system.abl_update)

    async def tabs(self) -> dict:
        """Which tabs this device has: lights and gyro only where their service answers, screens
        where there's a bottom screen."""
        led = await lights.get()
        motion = await gyro.get(quiet=True)
        return {"lights": bool(led.get("available") or led.get("power_available")), "gyro": motion["service"],
                "screens": screens.available()}

    async def _main(self):
        try:
            info = await self.info()
            decky.logger.info("power: kettle-powerd up, profiles %s, fan control %s", info["profiles"], info["fan"])
        except GLib.Error as e:
            decky.logger.error("power: kettle-powerd unreachable: %s", e.message)
        led = await lights.get()
        decky.logger.info("lights: %s stick LEDs, mode %s", led.get("leds"), led.get("mode"))
        motion = await gyro.get(quiet=True)
        decky.logger.info("gyro: service %s, sensors %s, mode %s", motion["service"], motion.get("available"), motion.get("mode"))
        self._fps_limit = asyncio.create_task(_watch_fps_limit())

    async def _unload(self):
        if getattr(self, "_fps_limit", None):
            self._fps_limit.cancel()
