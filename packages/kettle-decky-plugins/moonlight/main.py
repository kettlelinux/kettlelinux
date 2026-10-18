# Moonlight: streaming games from a PC running Sunshine or Apollo, in Game Mode. The hosts on the
# network (mDNS) and the ones paired before, pairing with a PIN shown on the device, each host's
# apps with their box art, and those apps in the Steam library as shortcuts (index.tsx adds them).
# A shortcut runs `kettle-moonlight launch <host uuid> <app name, hex>` (packages/kettle-moonlight),
# which streams with the host's settings from ~/.config/kettle-moonlight/<uuid>.args, written
# here: changing a host's settings changes how every one of its shortcuts streams, without
# touching the shortcuts. Steam runs launch options through a shell, so nothing the host says
# (its name, its apps' names) goes into them as text: the host is its uuid, the app hex.
# moonlight-qt keeps the pairing (its own config, read through mlconf.py); everything else talks
# to the host directly (gamestream.py).
import asyncio
import base64
import json
import os
import re
import secrets
import signal
import tempfile

import decky
import gamestream
import mlconf
import refresh

SETTINGS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
BOXART = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "boxart")
ARGS_DIR = os.path.join(decky.DECKY_USER_HOME, ".config", "kettle-moonlight")
PAIR_TIMEOUT = 120  # s: the time to type the PIN in on the PC
PAIR_SILENT = 15  # s: the PC not answering while pairing: it's gone
# moonlight-qt's pairing failures (nvpairingmanager.cpp, cli/pair.cpp), as the player reads them
PAIR_ERRORS = [
    (re.compile(r"Incorrect PIN"), "The PIN didn't match. Try again and type the new PIN."),
    (re.compile(r"already pairing"), "The PC is already pairing with another device. Try again in a minute."),
    (re.compile(r"Failed pairing at stage|Invalid|MITM|Failed to parse"), "Pairing failed. Try again."),
]

# How a stream looks, by preset. "native": the screen's own resolution; fps 0: the highest
# refresh rate the screen has, up to 120 (more frames: less latency, more bitrate and power).
PRESETS = {
    "latency": {"resolution": "native", "fps": 0, "bitrate": 0},
    "balanced": {"resolution": "native", "fps": 60, "bitrate": 0},
    "battery": {"resolution": "1280x720", "fps": 60, "bitrate": 10000},
}
DEFAULTS = {
    "preset": "balanced",
    "resolution": "native",
    "fps": 60,
    "bitrate": 0,  # kbps; 0: moonlight-qt's own for the resolution and frame rate
    "codec": "auto",  # moonlight-qt picks HEVC where the host can, else H.264
    "audio": "stereo",
    "overlay": False,
    "host_audio": False,
    "quit_after": False,
    "swap_buttons": False,
    # Moonlight reads the device's own controller (InputPlumber's virtual Steam Deck pad) rather
    # than Steam Input's virtual Xbox pad: the gyro reaches the PC, which then emulates a DS4 or
    # DualSense with motion (Sunshine/Apollo's motion_as_ds4); Steam Input layouts don't apply.
    # Off until moonlight's SDL drives InputPlumber's pad (28de:12f0, which SDL doesn't list)
    "raw_pad": False,
}
CODECS = ("auto", "H.264", "HEVC")  # AV1: iris has a decoder, moonlight-qt no v4l2m2m entry for it
AUDIO = ("stereo", "5.1-surround", "7.1-surround")

_pair = {"state": "idle", "address": "", "pin": "", "error": "", "uuid": ""}
_pair_proc: asyncio.subprocess.Process | None = None
# one writer at a time for settings.json and the launcher files (a slider sends a change per step)
_lock = asyncio.Lock()


def _load() -> dict:
    try:
        with open(SETTINGS) as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s.setdefault("hosts", {})  # uuid -> settings
    s.setdefault("shortcuts", {})  # "uuid/app name" -> Steam appid
    s.setdefault("manual", [])  # addresses added by hand
    return s


def _atomic_write(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def _save(s: dict):
    _atomic_write(SETTINGS, json.dumps(s, indent=1).encode())


def _panel() -> tuple[int, int]:
    """The built-in screen's resolution, landscape: the first connected DSI/eDP panel's first mode."""
    base = "/sys/class/drm"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        names = []
    for n in names:
        if not re.search(r"-(DSI|eDP)-", n):
            continue
        try:
            with open(f"{base}/{n}/status") as f:
                if f.read().strip() != "connected":
                    continue
            with open(f"{base}/{n}/modes") as f:
                w, h = map(int, f.readline().strip().split("x")[:2])
            return max(w, h), min(w, h)
        except (OSError, ValueError):
            continue
    return 1920, 1080


def _device() -> dict:
    w, h = _panel()
    rates = refresh.rates() or [60]
    return {"width": w, "height": h, "rates": rates, "max_fps": max([r for r in rates if r <= 120] or [60])}


def _host_settings(s: dict, host_uuid: str) -> dict:
    return {**DEFAULTS, **s["hosts"].get(host_uuid, {})}


def _effective(hs: dict, dev: dict) -> dict:
    """The resolution, frame rate and bitrate a stream gets: the preset's, or the host's own (custom)."""
    v = {k: hs[k] for k in ("resolution", "fps", "bitrate")} if hs["preset"] == "custom" else dict(PRESETS[hs["preset"]])
    if v["resolution"] == "native":
        v["resolution"] = f"{dev['width']}x{dev['height']}"
    if not v["fps"]:
        v["fps"] = dev["max_fps"]
    return v


# a line of the launcher's file that kettle-moonlight takes itself, not moonlight
RAW_PAD = "--kettle-raw-controller"


def _args(hs: dict, dev: dict) -> list[str]:
    v = _effective(hs, dev)
    toggle = lambda on, name: f"--{name}" if on else f"--no-{name}"
    a = ["--resolution", v["resolution"], "--fps", str(v["fps"])]
    if v["bitrate"]:
        a += ["--bitrate", str(v["bitrate"])]
    a += [
        "--display-mode", "fullscreen",
        "--video-codec", hs["codec"] if hs["codec"] in CODECS else "auto",
        "--audio-config", hs["audio"] if hs["audio"] in AUDIO else "stereo",
        toggle(hs["overlay"], "performance-overlay"),
        toggle(hs["host_audio"], "audio-on-host"),
        toggle(hs["quit_after"], "quit-after"),
        toggle(hs["swap_buttons"], "swap-gamepad-buttons"),
        # the screen keeps its touch input as a trackpad, like a laptop's
        "--touchscreen-trackpad",
        "--keep-awake",
    ]
    if hs["raw_pad"]:
        a.append(RAW_PAD)
    return a


def _write_args(host_uuid: str, hs: dict):
    """The launcher's file: one moonlight `stream` option per line (the host and app are the
    shortcut's), and RAW_PAD for the launcher."""
    _atomic_write(os.path.join(ARGS_DIR, f"{host_uuid}.args"), ("\n".join(_args(hs, _device())) + "\n").encode())


def _check_uuid(host_uuid: str):
    if not re.fullmatch(r"[0-9A-Fa-f-]{8,64}", host_uuid):
        raise ValueError(f"not a host: {host_uuid}")


def _known(host_uuid: str) -> dict:
    _check_uuid(host_uuid)
    for h in mlconf.hosts():
        if h["uuid"] == host_uuid:
            return h
    raise ValueError("Moonlight doesn't know this PC: pair with it first")


def _client(h: dict) -> gamestream.Client:
    ident = mlconf.identity()
    if not ident or not h["srvcert"]:
        raise ValueError("not paired with this PC")
    return gamestream.Client(*ident, h["srvcert"])


def _reach(h: dict):
    """The paired host's first address that answers: (address, https port, serverinfo)."""
    client = _client(h)
    last = None
    for address, port in h["addresses"]:
        try:
            info = gamestream.serverinfo(address, port)
            return address, info["https_port"], client
        except gamestream.HostError as e:
            last = e
    raise gamestream.HostError(f"{h['name']} isn't answering ({last})" if last else f"{h['name']} has no address")


PROBE_TIMEOUT = 1.5  # s: a host on the network answers in milliseconds; the list waits for the slowest


def _probe(address: str, port: int) -> dict | None:
    try:
        return {**gamestream.serverinfo(address, port, timeout=PROBE_TIMEOUT), "address": address}
    except gamestream.HostError:
        return None


async def _hosts(discover: bool) -> list[dict]:
    s = _load()
    known = await asyncio.to_thread(mlconf.hosts)
    found = await asyncio.to_thread(gamestream.discover) if discover else []
    # every address worth asking, each once: the known hosts', what mDNS found, those added by hand
    addresses = {}
    for h in known:
        for a, p in h["addresses"]:
            addresses.setdefault(a, p)
    for f in found:
        addresses.setdefault(f["address"], f["port"])
    for a in s["manual"]:
        addresses.setdefault(a, gamestream.HTTP_PORT)
    infos = await asyncio.gather(*(asyncio.to_thread(_probe, a, p) for a, p in addresses.items()))
    online = {}
    for i in infos:
        if i and i["uuid"] and i["uuid"] not in online:
            online[i["uuid"]] = i
    out = []
    for h in known:
        i = online.pop(h["uuid"], None)
        out.append({
            "uuid": h["uuid"], "name": h["name"], "paired": bool(h["srvcert"]), "online": bool(i),
            "address": i["address"] if i else (h["addresses"][0][0] if h["addresses"] else ""),
            "busy": bool(i and i["busy"]), "apollo": bool(i and i["apollo"]),
            "can_wake": bool(h["mac"] and h["mac"] != "00:00:00:00:00:00"),
        })
    for i in online.values():  # on the network, not yet paired
        out.append({"uuid": i["uuid"], "name": i["name"], "paired": False, "online": True, "address": i["address"],
                    "busy": i["busy"], "apollo": i["apollo"], "can_wake": False})
    out.sort(key=lambda h: (not h["paired"], not h["online"], h["name"].lower()))
    return out


async def _watch_pair(address: str, before: set[str], proc: asyncio.subprocess.Process):
    """Pairing ends in a dialog moonlight-qt never closes (offscreen): success shows as a newly
    pinned host in its config, failure as a "Qt Critical" line. Some failures it only shows in that
    dialog (the PC stops answering), so the PC is asked every few seconds too. Either way the
    process is stopped."""
    lines: list[str] = []

    async def read():
        while proc.stdout:
            line = await proc.stdout.readline()
            if not line:
                return
            lines.append(line.decode(errors="replace").rstrip())

    reader = asyncio.create_task(read())
    silent = 0  # s the PC hasn't answered
    try:
        for tick in range(PAIR_TIMEOUT * 2):
            await asyncio.sleep(0.5)
            if _pair["state"] != "waiting" or proc is not _pair_proc:
                return  # cancelled, or a new attempt
            new = [h for h in await asyncio.to_thread(mlconf.hosts) if h["srvcert"] and h["uuid"] not in before]
            if new:
                h = new[0]
                async with _lock:
                    await asyncio.to_thread(_write_args, h["uuid"], _host_settings(_load(), h["uuid"]))
                _pair.update(state="done", uuid=h["uuid"], error="")
                decky.logger.info("moonlight: paired with %s (%s)", h["name"], address)
                break
            critical = [l for l in lines if "Qt Critical" in l]
            if critical or proc.returncode is not None:
                text = " ".join(critical) or "\n".join(lines[-3:])
                msg = next((m for r, m in PAIR_ERRORS if r.search(text)), "Pairing failed. Try again.")
                _pair.update(state="failed", error=msg)
                decky.logger.warning("moonlight: pairing with %s failed: %s", address, text[-300:])
                break
            if tick % 10 == 9:  # every 5 s
                up = await asyncio.to_thread(_probe, address, gamestream.HTTP_PORT)
                silent = 0 if up else silent + 5
                if silent >= PAIR_SILENT:
                    _pair.update(state="failed", error="The PC stopped answering. Check that it's on and Sunshine or Apollo is running.")
                    break
        else:
            _pair.update(state="failed", error="The PIN wasn't entered on the PC in time. Try again.")
        if proc is _pair_proc:
            await decky.emit("pair", dict(_pair))
    finally:
        reader.cancel()
        await _stop(proc)


async def _stop(proc: asyncio.subprocess.Process | None):
    if proc and proc.returncode is None:
        proc.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), 3)
        except asyncio.TimeoutError:
            proc.kill()


def _launch(host_uuid: str, app_name: str) -> str:
    """The shortcut's launch options: no host text (Steam runs them through a shell)."""
    return f"launch {host_uuid} {app_name.encode().hex()}"


class Plugin:
    async def device(self) -> dict:
        return await asyncio.to_thread(_device)

    async def hosts(self, discover: bool = True) -> list[dict]:
        return await _hosts(discover)

    async def add_host(self, address: str) -> dict:
        address = address.strip()
        if not re.fullmatch(r"[A-Za-z0-9.:\-\[\]]{1,253}", address):
            raise ValueError("that isn't an IP address or a PC name")
        info = await asyncio.to_thread(gamestream.serverinfo, address)
        async with _lock:
            s = _load()
            if address not in s["manual"]:
                s["manual"].append(address)
                _save(s)
        return {"uuid": info["uuid"], "name": info["name"], "address": address}

    async def pair(self, address: str) -> str:
        """Starts pairing with the host; returns the PIN to type in on the PC ("" when it's paired
        already). The outcome comes as a "pair" event (and from pair_status)."""
        global _pair_proc
        # this attempt's state first: a poll from the dialog never sees the last attempt's
        _pair.update(state="starting", address=address, pin="", error="", uuid="")
        await self.pair_cancel()
        info = await asyncio.to_thread(_probe, address, gamestream.HTTP_PORT)
        if not info:
            _pair.update(state="failed", error="The PC didn't answer. Check that it's on and Sunshine or Apollo is running.")
            return ""
        paired = {h["uuid"] for h in await asyncio.to_thread(mlconf.hosts) if h["srvcert"]}
        if info["uuid"] in paired:
            _pair.update(state="done", uuid=info["uuid"])
            return ""
        pin = f"{secrets.randbelow(10000):04d}"
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "HOME": decky.DECKY_USER_HOME}
        _pair_proc = proc = await asyncio.create_subprocess_exec(
            "moonlight", "pair", address, "--pin", pin, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        _pair.update(state="waiting", pin=pin)
        asyncio.create_task(_watch_pair(address, paired, proc))
        return pin

    async def pair_status(self) -> dict:
        return dict(_pair)

    async def pair_cancel(self):
        global _pair_proc
        proc, _pair_proc = _pair_proc, None
        if _pair["state"] == "waiting":
            _pair.update(state="idle")
        await _stop(proc)

    async def apps(self, host_uuid: str) -> list[dict]:
        h = await asyncio.to_thread(_known, host_uuid)
        address, port, client = await asyncio.to_thread(_reach, h)
        apps = await asyncio.to_thread(client.applist, address, port)
        shortcuts = _load()["shortcuts"]
        for a in apps:
            a["shortcut"] = shortcuts.get(f"{host_uuid}/{a['name']}")
        return apps

    async def boxart(self, host_uuid: str, app_id: int) -> str:
        """The app's box art as a data: URL ("" if the host has none)."""
        path = os.path.join(BOXART, host_uuid, f"{int(app_id)}.png")
        if not os.path.exists(path):
            h = await asyncio.to_thread(_known, host_uuid)
            address, port, client = await asyncio.to_thread(_reach, h)
            try:
                data = await asyncio.to_thread(client.boxart, address, port, int(app_id))
            except gamestream.HostError:
                return ""
            if not data.startswith(b"\x89PNG"):
                return ""
            await asyncio.to_thread(_atomic_write, path, data)
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()

    async def settings(self, host_uuid: str) -> dict:
        _check_uuid(host_uuid)
        dev = await asyncio.to_thread(_device)
        hs = _host_settings(_load(), host_uuid)
        return {"settings": hs, "effective": _effective(hs, dev), "device": dev}

    async def set_settings(self, host_uuid: str, changes: dict) -> dict:
        _check_uuid(host_uuid)
        await asyncio.to_thread(_known, host_uuid)
        for k, v in changes.items():
            if k not in DEFAULTS:
                raise ValueError(f"no such setting: {k}")
            if k == "preset" and v not in (*PRESETS, "custom"):
                raise ValueError(f"no such preset: {v}")
            if k in ("fps", "bitrate") and (not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 500000):
                raise ValueError(f"{k} out of range")
            if k == "resolution" and not (v == "native" or re.fullmatch(r"\d{3,4}x\d{3,4}", str(v))):
                raise ValueError(f"not a resolution: {v}")
            if k == "codec" and v not in CODECS or k == "audio" and v not in AUDIO:
                raise ValueError(f"no such {k}: {v}")
            if isinstance(DEFAULTS[k], bool) and not isinstance(v, bool):
                raise ValueError(f"{k} is on or off")
        async with _lock:
            s = _load()
            hs = {**_host_settings(s, host_uuid), **changes}
            s["hosts"][host_uuid] = hs
            _save(s)
            await asyncio.to_thread(_write_args, host_uuid, hs)
        return await self.settings(host_uuid)

    async def shortcut_info(self, host_uuid: str, app_name: str) -> dict:
        h = await asyncio.to_thread(_known, host_uuid)
        async with _lock:
            if not os.path.exists(os.path.join(ARGS_DIR, f"{host_uuid}.args")):
                await asyncio.to_thread(_write_args, host_uuid, _host_settings(_load(), host_uuid))
        return {"title": app_name, "exe": "/usr/bin/kettle-moonlight", "dir": decky.DECKY_USER_HOME,
                "launch": _launch(host_uuid, app_name), "host": h["name"]}

    async def remember_shortcut(self, host_uuid: str, app_name: str, appid: int | None):
        _check_uuid(host_uuid)
        async with _lock:
            s = _load()
            key = f"{host_uuid}/{app_name}"
            if appid:
                s["shortcuts"][key] = appid
            else:
                s["shortcuts"].pop(key, None)
            _save(s)

    async def streams(self) -> dict:
        """Every Moonlight shortcut: {Steam appid: {uuid, app, launch}}, to tell a running stream
        apart and to bring older shortcuts' launch options up to date."""
        out = {}
        for key, appid in _load()["shortcuts"].items():
            host_uuid, _, app = key.partition("/")
            out[str(appid)] = {"uuid": host_uuid, "app": app, "launch": _launch(host_uuid, app)}
        return out

    async def wake(self, host_uuid: str):
        h = await asyncio.to_thread(_known, host_uuid)
        await asyncio.to_thread(gamestream.wake, h["mac"])

    async def forget(self, host_uuid: str) -> list[int]:
        """Unpairs: the host leaves moonlight-qt's list. Returns its shortcuts' appids (the frontend
        takes them out of the library)."""
        _check_uuid(host_uuid)
        await self.pair_cancel()
        await asyncio.to_thread(mlconf.forget, host_uuid)
        async with _lock:
            s = _load()
            gone = [v for k, v in s["shortcuts"].items() if k.startswith(f"{host_uuid}/")]
            s["shortcuts"] = {k: v for k, v in s["shortcuts"].items() if not k.startswith(f"{host_uuid}/")}
            s["hosts"].pop(host_uuid, None)
            _save(s)
            try:
                os.remove(os.path.join(ARGS_DIR, f"{host_uuid}.args"))
            except OSError:
                pass
        if _pair["uuid"] == host_uuid:
            _pair.update(state="idle", uuid="")
        return gone

    async def fps_limit(self) -> int:
        """Steam's frame rate limit in effect (gamescope 0025), 0: none."""
        env = await asyncio.to_thread(refresh.session_env)
        if "DISPLAY" not in env:
            return 0
        proc = await asyncio.create_subprocess_exec(
            "xprop", "-display", env["DISPLAY"], "-root", "GAMESCOPE_FPS_LIMIT_FEEDBACK",
            env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        m = re.search(rb"= (\d+)", out)
        return int(m.group(1)) if m else 0

    async def _main(self):
        # files written by an older version, or a device swapped under them: rewrite every paired
        # host's launcher file with this version's format and this device's screen
        async with _lock:
            s = _load()
            for h in await asyncio.to_thread(mlconf.hosts):
                if h["srvcert"]:
                    await asyncio.to_thread(_write_args, h["uuid"], _host_settings(s, h["uuid"]))

    async def _unload(self):
        await self.pair_cancel()
