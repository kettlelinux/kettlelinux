# Upscaling: per-game SGSR 2 through OptiScaler (ARM64EC build), plus gamescope FSR 1, which
# lives in the frontend (it only drives Steam's own per-game settings).
#
# OptiScaler (system package optiscaler-arm64ec, /usr/share/optiscaler) takes the game's DLSS,
# FSR 2+ or XeSS inputs and runs Qualcomm's Snapdragon GSR 2 instead. It is only ever in a
# game's folder while it is on for that game: turning it on copies OptiScaler.dll next to the
# game's exe under a proxy DLL name (and the frontend adds WINEDLLOVERRIDES=<proxy>=n,b);
# turning it off removes it again. A copy can't just be left inert, since Proton itself sets
# dxgi/d3d12 to native, which loads a dxgi.dll from the game's folder.
# A marker file records what was copied and what was moved aside, so turning it off restores
# the game folder exactly. The game's OptiScaler.ini holds its settings (also those changed in
# OptiScaler's own overlay) and is parked in the plugin's settings while the game is off.
import json
import os
import re
import shutil

import decky
import steamlib

OPTI = "/usr/share/optiscaler"
MARKER = "kettle-optiscaler.json"
BAK = ".kettle-bak"
PARKED = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "optiscaler")  # <appid>.ini, <appid>.json
PROXIES = ["dxgi.dll", "winmm.dll", "version.dll", "dbghelp.dll", "d3d12.dll", "wininet.dll", "winhttp.dll"]
LOGS = ["OptiScaler.log"]  # written next to the DLL; removed with it

RATIOS = ["game", "1.3", "1.5", "1.7", "2.0", "3.0"]
MENU_KEYS = ["0x2D", "0x24", "0x7B", "0x71"]  # Insert, Home, F12, F2

DEFAULTS = {"sharpen": True, "sharpness": 0.3, "ratio": "game", "spoof": True, "menu_key": "0x2D"}

# Always written. SGSR2 is the only backend that runs on ARM64EC (FSR links against stubs,
# XeSS/DLSS runtimes are x86-64); DX11 games go through its 11-on-12 bridge.
BASE = [
    ("Upscalers", "Dx12Upscaler", "sgsr2"),
    ("Upscalers", "Dx11Upscaler", "sgsr2_12"),
    ("Upscalers", "VulkanUpscaler", "sgsr2"),
    ("FrameGen", "Enabled", "false"),              # FSR/XeSS FG libraries aren't shipped
    ("Menu", "UseHQFont", "false"),                # HQ font can assert under Proton
    ("Plugins", "LoadAsiPlugins", "false"),
]


def _to_ini(s: dict) -> list[tuple[str, str, str]]:
    b = lambda v: "true" if v else "false"
    ratio = s["ratio"] != "game"
    return BASE + [
        # SGSR2 has no sharpening of its own; RCAS supplies it
        ("CAS", "Enabled", b(s["sharpen"])), ("Sharpness", "OverrideSharpness", b(s["sharpen"])),
        ("Sharpness", "Sharpness", f"{s['sharpness']:.2f}"),
        ("UpscaleRatio", "UpscaleRatioOverrideEnabled", b(ratio)),
        ("UpscaleRatio", "UpscaleRatioOverrideValue", s["ratio"] if ratio else "auto"),
        ("Spoofing", "Dxgi", b(s["spoof"])),
        ("Menu", "ShortcutKey", s["menu_key"]),
    ]


def _from_ini(ini: str) -> dict:
    v = lambda sec, key: _ini_get(ini, sec, key)
    t = lambda sec, key, dflt: {"true": True, "false": False}.get((v(sec, key) or "").lower(), dflt)
    s = dict(DEFAULTS)
    s["sharpen"] = t("CAS", "Enabled", DEFAULTS["sharpen"])
    try:
        s["sharpness"] = round(float(v("Sharpness", "Sharpness") or "x"), 2)
    except ValueError:
        pass
    r = v("UpscaleRatio", "UpscaleRatioOverrideValue") or ""
    s["ratio"] = r if t("UpscaleRatio", "UpscaleRatioOverrideEnabled", False) and r in RATIOS else "game"
    s["spoof"] = t("Spoofing", "Dxgi", DEFAULTS["spoof"])
    k = (v("Menu", "ShortcutKey") or "").upper().replace("0X", "0x")
    s["menu_key"] = k if k in MENU_KEYS else DEFAULTS["menu_key"]
    return s


def _clean(s: dict) -> dict:
    out = dict(DEFAULTS)
    out.update({k: s[k] for k in DEFAULTS if k in s})
    if out["ratio"] not in RATIOS or out["menu_key"] not in MENU_KEYS:
        raise ValueError("invalid OptiScaler setting")
    out["sharpness"] = round(max(0.0, min(1.3, float(out["sharpness"]))), 2)
    for k in ("sharpen", "spoof"):
        out[k] = bool(out[k])
    return out


_BAD = re.compile(r"crash|unins|setup|launcher|updater|bootstrap|redist|prereq|vc_?redist|dotnet|"
                  r"easyanticheat|eac|beclient|battleye|eosbootstrap|benchmark|dxsetup|ue4prereq|cefprocess")


def _exe_dirs(root: str) -> list[str]:
    """Folders holding the game's main exe, best guess first (as Decky-Framegen scores them)."""
    scored = {}
    for dirpath, dirnames, files in os.walk(root):
        if dirpath[len(root):].count(os.sep) > 5:
            dirnames[:] = []
            continue
        for f in files:
            if not f.lower().endswith(".exe"):
                continue
            low = os.path.join(dirpath, f).lower()
            s = 0
            s += 300 if low.endswith("-win64-shipping.exe") else 220 if low.endswith("shipping.exe") else 0
            s += 200 if "/binaries/win64/" in low else 80 if "/win64/" in low or "/x64/" in low else 0
            s -= 200 if _BAD.search(f.lower()) else 0
            s -= 150 if "/engine/" in low[len(root):] else 0
            s -= 10 * dirpath[len(root):].count(os.sep)
            s += os.path.getsize(os.path.join(dirpath, f)) // (50 << 20)  # big exe: likely the game
            scored[dirpath] = max(scored.get(dirpath, -10**9), s)
    return [d for d, _ in sorted(scored.items(), key=lambda kv: -kv[1])]


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def _find_install(appid: int) -> str | None:
    root = steamlib.install_dir(appid)
    if not root:
        return None
    for dirpath, dirnames, files in os.walk(root):
        if MARKER in files:
            return dirpath
        if dirpath[len(root):].count(os.sep) > 5:
            dirnames[:] = []
    return None


def _ini_get(path: str, section: str, key: str) -> str | None:
    cur = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if s.startswith("[") and s.endswith("]"):
                    cur = s[1:-1]
                elif cur == section and "=" in s and not s.startswith(";"):
                    k, v = s.split("=", 1)
                    if k.strip() == key:
                        return v.strip()
    except OSError:
        pass
    return None


def _ini_set(path: str, values: list[tuple[str, str, str]]):
    """Set section/key pairs in an OptiScaler.ini, keeping its comments and layout."""
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        lines = f.read().splitlines(keepends=True)
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    todo = {(s, k): v for s, k, v in values}
    cur = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
        elif "=" in s and not s.startswith(";"):
            k = s.split("=", 1)[0].strip()
            if (cur, k) in todo:
                lines[i] = f"{k}={todo.pop((cur, k))}{nl}"
    for (sec, k), v in todo.items():  # keys missing from this ini version
        lines.append(f"{nl}[{sec}]{nl}{k}={v}{nl}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)
    os.replace(tmp, path)


def _version() -> str | None:
    try:
        with open(os.path.join(OPTI, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return None


def _ini_path(appid: int) -> str:
    """The game's OptiScaler.ini: in its folder while on, parked in the plugin's settings while off."""
    d = _find_install(appid)
    return os.path.join(d, "OptiScaler.ini") if d else os.path.join(PARKED, f"{appid}.ini")


def _stock_ini(path: str, settings: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copyfile(os.path.join(OPTI, "OptiScaler.ini"), path)
    _ini_set(path, _to_ini(settings))


class Plugin:
    async def status(self) -> dict:
        return {"available": os.path.isfile(os.path.join(OPTI, "OptiScaler.dll")), "version": _version(),
                "proxies": PROXIES}

    async def installed_games(self) -> list[dict]:
        return steamlib.installed_games()

    async def get_game(self, appid: int) -> dict:
        root = steamlib.install_dir(appid)
        if not root:
            return {"found": False}
        ini = _ini_path(appid)
        settings = _from_ini(ini) if os.path.isfile(ini) else dict(DEFAULTS)
        d = _find_install(appid)
        if d:
            m = _read_json(os.path.join(d, MARKER)) or {}
            return {"found": True, "on": True, "dir": d, "proxy": m.get("proxy", "dxgi.dll"),
                    "outdated": m.get("version") != _version(), "settings": settings}
        # off: offer the folder and proxy used last time first
        last = _read_json(os.path.join(PARKED, f"{appid}.json")) or {}
        cands = _exe_dirs(root)[:6]
        if last.get("dir") in cands:
            cands.remove(last["dir"])
            cands.insert(0, last["dir"])
        return {"found": True, "on": False, "candidates": cands, "proxy": last.get("proxy", "dxgi.dll"),
                "settings": settings}

    async def enable(self, appid: int, exe_dir: str, proxy: str) -> dict:
        root = steamlib.install_dir(appid)
        if not root or os.path.commonpath([os.path.realpath(root), os.path.realpath(exe_dir)]) != os.path.realpath(root):
            raise ValueError("folder is not inside the game's install directory")
        if proxy not in PROXIES:
            raise ValueError(f"unsupported proxy {proxy}")
        if _find_install(appid):
            await self.disable(appid)

        parked = os.path.join(PARKED, f"{appid}.ini")
        if not os.path.isfile(parked):
            _stock_ini(parked, DEFAULTS)
        copied, backups = [], []
        for src, name in [(os.path.join(OPTI, "OptiScaler.dll"), proxy), (parked, "OptiScaler.ini")]:
            dst = os.path.join(exe_dir, name)
            if os.path.lexists(dst):
                os.replace(dst, dst + BAK)
                backups.append(name)
            shutil.copyfile(src, dst)
            copied.append(name)
        os.remove(parked)
        ini = os.path.join(exe_dir, "OptiScaler.ini")
        _ini_set(ini, _to_ini(_from_ini(ini)))  # BASE may be newer than the parked ini
        _write_json(os.path.join(exe_dir, MARKER), {"appid": appid, "version": _version(), "proxy": proxy,
                                                    "files": copied, "backups": backups})
        _write_json(os.path.join(PARKED, f"{appid}.json"), {"dir": exe_dir, "proxy": proxy})
        decky.logger.info("OptiScaler on for %s in %s as %s", appid, exe_dir, proxy)
        return await self.get_game(appid)

    async def disable(self, appid: int) -> dict:
        d = _find_install(appid)
        if not d:
            return await self.get_game(appid)
        m = _read_json(os.path.join(d, MARKER)) or {}
        ini = os.path.join(d, "OptiScaler.ini")
        if "OptiScaler.ini" in m.get("files", []) and os.path.isfile(ini):
            os.makedirs(PARKED, exist_ok=True)
            shutil.move(ini, os.path.join(PARKED, f"{appid}.ini"))
        for name in m.get("files", []) + LOGS:
            try:
                os.remove(os.path.join(d, name))
            except FileNotFoundError:
                pass
        for name in m.get("backups", []):
            b = os.path.join(d, name + BAK)
            if os.path.lexists(b):
                os.replace(b, os.path.join(d, name))
        os.remove(os.path.join(d, MARKER))
        decky.logger.info("OptiScaler off for %s, removed from %s", appid, d)
        return await self.get_game(appid)

    async def configure(self, appid: int, settings: dict) -> dict:
        ini = _ini_path(appid)
        if not os.path.isfile(ini):
            _stock_ini(ini, DEFAULTS)
        _ini_set(ini, _to_ini(_clean({**_from_ini(ini), **settings})))
        return await self.get_game(appid)

    async def reset(self, appid: int) -> dict:
        """Stock OptiScaler.ini plus our defaults."""
        _stock_ini(_ini_path(appid), DEFAULTS)
        return await self.get_game(appid)

    async def _main(self):
        decky.logger.info("upscaling: OptiScaler %s", _version() or "not installed")

    async def _unload(self):
        pass
