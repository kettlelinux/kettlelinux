# Upscaling: per-game OptiScaler (ARM64EC build), plus gamescope's filter, which lives in the
# frontend (it only drives Steam's own per-game settings).
#
# OptiScaler (system package optiscaler-arm64ec, /usr/share/optiscaler) takes the game's DLSS,
# FSR 2+ or XeSS inputs and runs the upscaler chosen here instead: SGSR 2, Arm ASR or FSR 2.2,
# built into it, or FSR 3.1 with optional FSR frame generation from AMD's DLLs, which the
# Welcome plugin downloads on request (component amd-fsr3). Those DLLs are copied into a game's
# folder only while its settings use them, tracked like OptiScaler's own files. It is only ever in a
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
AMD = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "kettle", "components", "amd-fsr3")
AMD_FILES = ["amd_fidelityfx_loader_dx12.dll", "amd_fidelityfx_upscaler_dx12.dll",
             "amd_fidelityfx_framegeneration_dx12.dll"]

RATIOS = ["game", "1.3", "1.5", "1.7", "2.0", "3.0"]
# choice -> (Dx12Upscaler, Dx11Upscaler). DX11 goes through the 11-on-12 bridge (the native
# DX11 FSR2 path is a stub on ARM64EC); Vulkan games always get SGSR2, the only one with a
# Vulkan path here.
UPSCALERS = {"sgsr2": ("sgsr2", "sgsr2_12"), "asr": ("asr", "asr_12"), "fsr22": ("fsr22", "fsr22_12"),
             "fsr31": ("ffx", "ffx_12")}  # fsr31 needs AMD's DLLs
# choice -> ([FrameGen] Enabled, FGInput, FGOutput): FSR frame generation (AMD's DLLs), fed from
# the upscaler's inputs (any game OptiScaler upscales; the HUD may ghost without HUDFix) or from
# the game's own FSR 3 frame generation
FRAMEGEN = {"off": ("false", "nofg", "nofg"), "upscaler": ("true", "upscaler", "fsrfg"),
            "game": ("true", "fsrfg", "fsrfg")}
ASR_QUALITY = ["balanced", "quality"]  # ASR 25.06's performance preset is broken upstream
MENU_KEYS = ["0x2D", "0x24", "0x7B", "0x71"]  # Insert, Home, F12, F2

DEFAULTS = {"upscaler": "sgsr2", "asr_quality": "balanced", "framegen": "off", "hudfix": False, "sharpen": True, "sharpness": 0.3, "ratio": "game", "spoof": True, "menu_key": "0x2D"}

# Always written
BASE = [
    ("Upscalers", "VulkanUpscaler", "sgsr2"),      # the only upscaler with a Vulkan path here
    ("Menu", "UseHQFont", "false"),                # HQ font can assert under Proton
    ("Plugins", "LoadAsiPlugins", "false"),
]


def _to_ini(s: dict) -> list[tuple[str, str, str]]:
    b = lambda v: "true" if v else "false"
    ratio = s["ratio"] != "game"
    dx12, dx11 = UPSCALERS[s["upscaler"]]
    fg, fg_in, fg_out = FRAMEGEN[s["framegen"]]
    return BASE + [
        ("Upscalers", "Dx12Upscaler", dx12), ("Upscalers", "Dx11Upscaler", dx11),
        ("FrameGen", "Enabled", fg), ("FrameGen", "FGInput", fg_in), ("FrameGen", "FGOutput", fg_out),
        ("OptiFG", "HUDFix", b(s["hudfix"] and s["framegen"] == "upscaler")),
        ("ASR", "ShaderQuality", s["asr_quality"]),
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
    s["upscaler"] = next((c for c, u in UPSCALERS.items() if u[0] == v("Upscalers", "Dx12Upscaler")), DEFAULTS["upscaler"])
    fg = ((v("FrameGen", "Enabled") or "").lower(), v("FrameGen", "FGInput"))
    s["framegen"] = next((c for c, f in FRAMEGEN.items() if f[:2] == fg), DEFAULTS["framegen"])
    s["hudfix"] = t("OptiFG", "HUDFix", DEFAULTS["hudfix"])
    q = (v("ASR", "ShaderQuality") or "").lower()
    s["asr_quality"] = q if q in ASR_QUALITY else DEFAULTS["asr_quality"]
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


def _needs_amd(s: dict) -> bool:
    return s["upscaler"] == "fsr31" or s["framegen"] != "off"


def _amd_available() -> bool:
    return all(os.path.isfile(os.path.join(AMD, f)) for f in AMD_FILES)


def _clean(s: dict) -> dict:
    out = dict(DEFAULTS)
    out.update({k: s[k] for k in DEFAULTS if k in s})
    if out["ratio"] not in RATIOS or out["menu_key"] not in MENU_KEYS or out["upscaler"] not in UPSCALERS \
            or out["asr_quality"] not in ASR_QUALITY or out["framegen"] not in FRAMEGEN:
        raise ValueError("invalid OptiScaler setting")
    out["sharpness"] = round(max(0.0, min(1.3, float(out["sharpness"]))), 2)
    for k in ("sharpen", "spoof", "hudfix"):
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
            try:
                s += os.path.getsize(os.path.join(dirpath, f)) // (50 << 20)  # big exe: likely the game
            except OSError:  # broken symlink
                pass
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


def _inside(root: str, d: str) -> bool:
    root = os.path.realpath(root)
    return os.path.commonpath([root, os.path.realpath(d)]) == root


def _find_install(appid: int, root: str | None = None) -> str | None:
    """The folder OptiScaler is on in (it holds the marker), or None while it's off."""
    root = root or steamlib.install_dir(appid)
    if not root:
        return None
    last = (_read_json(os.path.join(PARKED, f"{appid}.json")) or {}).get("dir")
    if last and _inside(root, last) and os.path.isfile(os.path.join(last, MARKER)):
        return last
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
    if lines and not lines[-1].endswith(("\r", "\n")):
        lines[-1] += nl
    todo = {(s, k): v for s, k, v in values}
    cur = None
    ends = {}  # section -> index after its last key
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
            ends.setdefault(cur, i + 1)
        elif "=" in s and not s.startswith(";"):
            k = s.split("=", 1)[0].strip()
            ends[cur] = i + 1
            if (cur, k) in todo:
                lines[i] = f"{k}={todo.pop((cur, k))}{nl}"
    # keys missing from this ini version: at the end of their section, or in a new one
    adds = {}
    for (sec, k), v in todo.items():
        adds.setdefault(sec, []).append(f"{k}={v}{nl}")
    for sec in sorted((x for x in adds if x in ends), key=ends.get, reverse=True):
        lines[ends[sec]:ends[sec]] = adds[sec]
    for sec, keys in adds.items():
        if sec not in ends:
            lines += [nl, f"[{sec}]{nl}", *keys]
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


def _ini_path(d: str | None, appid: int) -> str:
    """The game's OptiScaler.ini: in its folder d while on, parked in the plugin's settings while off."""
    return os.path.join(d, "OptiScaler.ini") if d else os.path.join(PARKED, f"{appid}.ini")


def _place(d: str, m: dict, name: str, src: str):
    """Copy src into game folder d as name, moving a game file of that name aside; recorded in m."""
    dst = os.path.join(d, name)
    if name not in m["files"]:
        if os.path.lexists(dst + BAK):  # left by an interrupted run: that one is the original
            m["backups"].append(name)
        elif os.path.lexists(dst):
            os.replace(dst, dst + BAK)
            m["backups"].append(name)
    shutil.copyfile(src, dst)
    if name not in m["files"]:
        m["files"].append(name)


def _unplace(d: str, m: dict, name: str):
    """Undo _place: remove our copy, put the game's file back."""
    try:
        os.remove(os.path.join(d, name))
    except FileNotFoundError:
        pass
    m["files"].remove(name)
    if name in m["backups"]:
        b = os.path.join(d, name + BAK)
        if os.path.lexists(b):
            os.replace(b, os.path.join(d, name))
        m["backups"].remove(name)


def _sync_amd(d: str, settings: dict):
    """AMD's DLLs in the game folder exactly while its settings use them."""
    path = os.path.join(d, MARKER)
    m = _read_json(path) or {}
    m.setdefault("files", [])
    m.setdefault("backups", [])
    need = _needs_amd(settings)
    try:
        for name in AMD_FILES:
            if need and name not in m["files"] and _amd_available():
                _place(d, m, name, os.path.join(AMD, name))
            elif not need and name in m["files"]:
                _unplace(d, m, name)
    finally:
        _write_json(path, m)


def _has_amd_copies(d: str | None) -> bool:
    m = _read_json(os.path.join(d, MARKER)) if d else None
    return bool(m) and all(f in m.get("files", []) for f in AMD_FILES)


def _stock_ini(path: str, settings: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copyfile(os.path.join(OPTI, "OptiScaler.ini"), path)
    _ini_set(path, _to_ini(settings))


class Plugin:
    async def status(self) -> dict:
        return {"available": os.path.isfile(os.path.join(OPTI, "OptiScaler.dll")), "version": _version(),
                "proxies": PROXIES, "amd": _amd_available()}

    async def installed_games(self) -> list[dict]:
        return steamlib.installed_games()

    async def get_game(self, appid: int) -> dict:
        root = steamlib.install_dir(appid)
        if not root:
            return {"found": False}
        d = _find_install(appid, root)
        ini = _ini_path(d, appid)
        settings = _from_ini(ini) if os.path.isfile(ini) else dict(DEFAULTS)
        if d:
            m = _read_json(os.path.join(d, MARKER)) or {}
            return {"found": True, "on": True, "dir": d, "proxy": m.get("proxy", "dxgi.dll"),
                    "outdated": m.get("version") != _version(), "settings": settings}
        # off: offer the folder and proxy used last time first
        last = _read_json(os.path.join(PARKED, f"{appid}.json")) or {}
        cands = _exe_dirs(root)[:6]
        if last.get("dir") and os.path.isdir(last["dir"]) and _inside(root, last["dir"]):
            cands = [last["dir"]] + [c for c in cands if c != last["dir"]][:5]
        return {"found": True, "on": False, "candidates": cands, "proxy": last.get("proxy", "dxgi.dll"),
                "settings": settings}

    async def enable(self, appid: int, exe_dir: str, proxy: str) -> dict:
        root = steamlib.install_dir(appid)
        if not root or not os.path.isdir(exe_dir) or not _inside(root, exe_dir):
            raise ValueError("folder is not inside the game's install directory")
        if proxy not in PROXIES:
            raise ValueError(f"unsupported proxy {proxy}")
        if _find_install(appid):
            await self.disable(appid)

        parked = os.path.join(PARKED, f"{appid}.ini")
        if not os.path.isfile(parked):
            _stock_ini(parked, DEFAULTS)
        settings = _from_ini(parked)
        if _needs_amd(settings) and not _amd_available():
            raise ValueError("this game is set to use AMD FSR 3.1, which isn't installed: install it in "
                             "the Welcome panel, or pick another upscaler first")
        # the marker is kept current, so a failure part-way is undone by disable
        m = {"appid": appid, "version": _version(), "proxy": proxy, "files": [], "backups": []}
        _write_json(os.path.join(PARKED, f"{appid}.json"), {"dir": exe_dir, "proxy": proxy})
        try:
            try:
                _place(exe_dir, m, proxy, os.path.join(OPTI, "OptiScaler.dll"))
                _place(exe_dir, m, "OptiScaler.ini", parked)
            finally:
                _write_json(os.path.join(exe_dir, MARKER), m)
            os.remove(parked)
            ini = os.path.join(exe_dir, "OptiScaler.ini")
            _ini_set(ini, _to_ini(_from_ini(ini)))  # BASE may be newer than the parked ini
            _sync_amd(exe_dir, settings)
        except Exception:
            decky.logger.exception("OptiScaler on for %s failed, undoing", appid)
            await self.disable(appid)
            raise
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
        d = _find_install(appid)
        ini = _ini_path(d, appid)
        if not os.path.isfile(ini):
            _stock_ini(ini, DEFAULTS)
        old = _from_ini(ini)
        new = _clean({**old, **settings})
        # a game already set to use AMD's DLLs keeps its choice while the other settings change
        if _needs_amd(new) and not _needs_amd(old) and not (_amd_available() or _has_amd_copies(d)):
            raise ValueError("FSR 3.1 and frame generation need AMD FSR 3.1: install it in the Welcome panel")
        _ini_set(ini, _to_ini(new))
        if d:
            _sync_amd(d, new)
        return await self.get_game(appid)

    async def reset(self, appid: int) -> dict:
        """Stock OptiScaler.ini plus our defaults."""
        d = _find_install(appid)
        _stock_ini(_ini_path(d, appid), DEFAULTS)
        if d:
            _sync_amd(d, DEFAULTS)
        return await self.get_game(appid)

    async def _main(self):
        decky.logger.info("upscaling: OptiScaler %s", _version() or "not installed")

    async def _unload(self):
        pass
