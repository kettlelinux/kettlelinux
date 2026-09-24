# Upscaling: per-game OptiScaler (the gamescope FSR half lives in the frontend; it only
# drives Steam settings).
# OptiScaler (system package, /usr/share/optiscaler) is copied next to the game's exe under
# a proxy DLL name. The frontend turns it on/off per game with WINEDLLOVERRIDES=<proxy>=n,b
# in the launch options: without the override Wine loads its own DLL and the copy is inert.
# Per-game settings are the game's own OptiScaler.ini. A marker file records what was copied
# and what was moved aside, so "Remove" restores the game folder exactly.
import json
import os
import re
import shutil

import decky
import steamlib

OPTI = "/usr/share/optiscaler"
MARKER = "steamportal-optiscaler.json"
BAK = ".steamportal-bak"
PROXIES = ["dxgi.dll", "winmm.dll", "version.dll", "dbghelp.dll", "d3d12.dll", "wininet.dll", "winhttp.dll"]
SUPPORT = ["fakenvapi.dll", "fakenvapi.ini",
           "amd_fidelityfx_dx12.dll", "amd_fidelityfx_framegeneration_dx12.dll",
           "amd_fidelityfx_upscaler_dx12.dll", "amd_fidelityfx_vk.dll",
           "libxess.dll", "libxess_dx11.dll", "libxess_fg.dll", "libxell.dll"]

UPSCALERS = {  # choice -> (Dx12Upscaler, Dx11Upscaler, VulkanUpscaler)
    "fsr31": ("fsr31", "fsr31", "fsr31"),
    "fsr22": ("fsr22", "fsr22", "fsr22"),
    "xess": ("xess", "xess_12", "xess"),  # native DX11 XeSS is Arc-only
}
FRAMEGEN = {  # choice -> ([FrameGen] Enabled, FGInput, FGOutput); output is always FSR FG
    "off": ("false", "nofg", "nofg"),
    "optifg": ("true", "upscaler", "fsrfg"),  # any DX12 game with an upscaler; HUD may ghost
    "fsrfg": ("true", "fsrfg", "fsrfg"),      # game's own FSR 3 frame generation
    "dlssg": ("true", "dlssg", "fsrfg"),      # game's DLSS frame generation (spoofed GPU)
}
RATIOS = ["game", "1.3", "1.5", "1.7", "2.0", "3.0"]
MENU_KEYS = ["0x2D", "0x24", "0x7B", "0x71"]  # Insert, Home, F12, F2

DEFAULTS = {"upscaler": "fsr31", "framegen": "off", "hudfix": False, "sharpen": False, "sharpness": 0.3,
            "ratio": "game", "spoof": True, "menu_key": "0x2D"}

# Always written: settings that matter on ARM64 Proton / Adreno
BASE = [
    ("FSR", "Fsr4Update", "false"),                # FSR 4 needs RDNA; Adreno falls back anyway
    ("Menu", "UseHQFont", "false"),                # HQ font can assert under Proton
    ("Spoofing", "DxgiFactoryWrapping", "true"),   # x64 Detours hooks fail on ARM64EC dxgi
    ("Plugins", "LoadAsiPlugins", "false"),
]


def _to_ini(s: dict) -> list[tuple[str, str, str]]:
    dx12, dx11, vk = UPSCALERS[s["upscaler"]]
    en, fin, fout = FRAMEGEN[s["framegen"]]
    b = lambda v: "true" if v else "false"
    ratio = s["ratio"] != "game"
    return BASE + [
        ("Upscalers", "Dx12Upscaler", dx12), ("Upscalers", "Dx11Upscaler", dx11), ("Upscalers", "VulkanUpscaler", vk),
        ("FrameGen", "Enabled", en), ("FrameGen", "FGInput", fin), ("FrameGen", "FGOutput", fout),
        ("OptiFG", "HUDFix", b(s["hudfix"] and s["framegen"] == "optifg")),
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
    s["upscaler"] = next((c for c, u in UPSCALERS.items() if u[0] == v("Upscalers", "Dx12Upscaler")), "fsr31")
    fg = (v("FrameGen", "FGInput"), v("FrameGen", "FGOutput"))
    s["framegen"] = next((c for c, f in FRAMEGEN.items() if f[1:] == fg), "off")
    s["hudfix"] = t("OptiFG", "HUDFix", False)
    s["sharpen"] = t("CAS", "Enabled", False)
    try:
        s["sharpness"] = round(float(v("Sharpness", "Sharpness") or "x"), 2)
    except ValueError:
        pass
    r = v("UpscaleRatio", "UpscaleRatioOverrideValue") or ""
    s["ratio"] = r if t("UpscaleRatio", "UpscaleRatioOverrideEnabled", False) and r in RATIOS else "game"
    s["spoof"] = t("Spoofing", "Dxgi", True)
    k = (v("Menu", "ShortcutKey") or "").upper().replace("0X", "0x")
    s["menu_key"] = k if k in MENU_KEYS else "0x2D"
    return s


def _clean(s: dict) -> dict:
    out = dict(DEFAULTS)
    out.update({k: s[k] for k in DEFAULTS if k in s})
    if out["upscaler"] not in UPSCALERS or out["framegen"] not in FRAMEGEN or out["ratio"] not in RATIOS \
            or out["menu_key"] not in MENU_KEYS:
        raise ValueError("invalid OptiScaler setting")
    out["sharpness"] = round(max(0.0, min(1.3, float(out["sharpness"]))), 2)
    for k in ("hudfix", "sharpen", "spoof"):
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


def _read_marker(d: str) -> dict | None:
    try:
        with open(os.path.join(d, MARKER), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


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
        d = _find_install(appid)
        if d:
            m = _read_marker(d) or {}
            return {"found": True, "installed": True, "dir": d, "proxy": m.get("proxy", "dxgi.dll"),
                    "outdated": m.get("version") != _version(),
                    "settings": _from_ini(os.path.join(d, "OptiScaler.ini"))}
        return {"found": True, "installed": False, "candidates": _exe_dirs(root)[:6], "proxy": "dxgi.dll",
                "settings": dict(DEFAULTS)}

    async def install(self, appid: int, exe_dir: str, proxy: str, settings: dict) -> dict:
        root = steamlib.install_dir(appid)
        if not root or os.path.commonpath([os.path.realpath(root), os.path.realpath(exe_dir)]) != os.path.realpath(root):
            raise ValueError("folder is not inside the game's install directory")
        if proxy not in PROXIES:
            raise ValueError(f"unsupported proxy {proxy}")
        settings = _clean(settings)
        old = _find_install(appid)
        if old:
            await self.remove(appid)

        copied, backups = [], []
        for src, name in [("OptiScaler.dll", proxy)] + [(f, f) for f in SUPPORT]:
            dst = os.path.join(exe_dir, name)
            if os.path.lexists(dst):
                os.replace(dst, dst + BAK)
                backups.append(name)
            shutil.copyfile(os.path.join(OPTI, src), dst)
            copied.append(name)
        ini = os.path.join(exe_dir, "OptiScaler.ini")
        if not os.path.exists(ini):  # keep the game's ini from an earlier install: its settings
            shutil.copyfile(os.path.join(OPTI, "OptiScaler.ini"), ini)
            copied.append("OptiScaler.ini")
        with open(os.path.join(exe_dir, MARKER), "w", encoding="utf-8") as f:
            json.dump({"appid": appid, "version": _version(), "proxy": proxy,
                       "files": copied, "backups": backups}, f, indent=1)
        _ini_set(ini, _to_ini(settings))
        decky.logger.info("OptiScaler installed for %s in %s as %s", appid, exe_dir, proxy)
        return await self.get_game(appid)

    async def configure(self, appid: int, settings: dict) -> dict:
        d = _find_install(appid)
        if not d:
            raise ValueError("OptiScaler is not installed for this game")
        ini = os.path.join(d, "OptiScaler.ini")
        _ini_set(ini, _to_ini(_clean({**_from_ini(ini), **settings})))
        return await self.get_game(appid)

    async def reset(self, appid: int) -> dict:
        """Stock OptiScaler.ini plus our defaults."""
        d = _find_install(appid)
        if not d:
            raise ValueError("OptiScaler is not installed for this game")
        ini = os.path.join(d, "OptiScaler.ini")
        shutil.copyfile(os.path.join(OPTI, "OptiScaler.ini"), ini)
        _ini_set(ini, _to_ini(dict(DEFAULTS)))
        return await self.get_game(appid)

    async def remove(self, appid: int) -> dict:
        d = _find_install(appid)
        if not d:
            return await self.get_game(appid)
        m = _read_marker(d) or {}
        for name in m.get("files", []):
            if name == "OptiScaler.ini":
                continue  # keep the game's settings for a later reinstall
            try:
                os.remove(os.path.join(d, name))
            except FileNotFoundError:
                pass
        for name in m.get("backups", []):
            b = os.path.join(d, name + BAK)
            if os.path.lexists(b):
                os.replace(b, os.path.join(d, name))
        os.remove(os.path.join(d, MARKER))
        decky.logger.info("OptiScaler removed for %s from %s", appid, d)
        return await self.get_game(appid)

    async def _main(self):
        pass

    async def _unload(self):
        pass
