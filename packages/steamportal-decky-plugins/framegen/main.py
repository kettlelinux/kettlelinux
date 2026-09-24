# Frame Generation: per-game lsfg-vk settings.
# Each game's settings live in the plugin's games.json and are kept while the game is off.
# Games that are on get an lsfg-vk profile in ~/.config/lsfg-vk/conf.toml, matched by
# SteamAppId. The layer itself stays off (DISABLE_LSFGVK=1, environment.d) except in games
# whose launch options unset it; the frontend edits those. The layer watches conf.toml:
# multiplier, flow scale and performance mode change live, the rest on the game's next start.
import json
import os
import tomllib

import decky
import steamlib

CONF = os.path.join(decky.DECKY_USER_HOME, ".config", "lsfg-vk", "conf.toml")
GAMES = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "games.json")
LAYER = "/usr/lib/liblsfg-vk-layer.so"
PREFIX = "steam-"  # names of the profiles this plugin owns: steam-<appid>

DEFAULTS = {
    "enabled": False,
    "multiplier": 2,
    "flow_scale": 0.8,
    "performance_mode": True,
    "fifo": True,               # lsfg override_present_mode: pace generated frames with FIFO
    "preserve_images": False,   # lsfg preserve_swapchain_image_count
    "bypass_wsi": True,         # ENABLE_GAMESCOPE_WSI=0 (launch option, frontend)
}


def _clamp(s: dict) -> dict:
    out = dict(DEFAULTS)
    out.update({k: s[k] for k in DEFAULTS if k in s})
    out["multiplier"] = max(2, min(4, int(out["multiplier"])))
    out["flow_scale"] = round(max(0.25, min(1.0, float(out["flow_scale"]))), 2)
    for k in ("enabled", "performance_mode", "fifo", "preserve_images", "bypass_wsi"):
        out[k] = bool(out[k])
    return out


def _find_dll() -> dict:
    for lib in steamlib.libraries():
        d = os.path.join(lib, "steamapps", "common", "Lossless Scaling")
        if os.path.isfile(os.path.join(d, "lsfg-vk.dll")):
            return {"path": os.path.join(d, "lsfg-vk.dll"), "lib": lib}
        if os.path.isdir(d):
            # installed, but not the "lsfg-vk" beta branch that carries lsfg-vk.dll
            return {"path": None, "installed": d}
    return {"path": None, "installed": None}


# ---------- lsfg-vk conf.toml ----------

def _load_conf() -> dict:
    try:
        with open(CONF, "rb") as f:
            conf = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        if os.path.exists(CONF):
            decky.logger.warning("unreadable %s (%s); rewriting it", CONF, e)
        conf = {}
    conf.setdefault("global", {})
    profiles = conf.get("profile", [])
    conf["profile"] = profiles if isinstance(profiles, list) else []
    return conf


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _save_conf(conf: dict):
    # lsfg-vk rejects unknown keys, so only its own keys are written
    out = ["# Managed in part by the Steam Portal Frame Generation plugin: it owns the",
           f'# profiles named "{PREFIX}<appid>"; other profiles are kept as they are.',
           "version = 2", "", "[global]"]
    out += [f"{k} = {_fmt(v)}" for k, v in conf["global"].items()]
    for p in conf["profile"]:
        out += ["", "[[profile]]"] + [f"{k} = {_fmt(v)}" for k, v in p.items()]
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, CONF)  # IN_MOVED_TO: the layer reloads


def _profile(appid: int, s: dict) -> dict:
    return {
        "name": f"{PREFIX}{appid}",
        "active_in": [str(appid)],  # matched against SteamAppId
        "multiplier": s["multiplier"],
        "flow_scale": s["flow_scale"],
        "performance_mode": s["performance_mode"],
        "override_present_mode": s["fifo"],
        "preserve_swapchain_image_count": s["preserve_images"],
    }


# ---------- per-game store ----------

def _load_games() -> dict[int, dict]:
    try:
        with open(GAMES, encoding="utf-8") as f:
            return {int(k): _clamp(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        pass
    # first run: adopt profiles an earlier version of the plugin wrote
    games = {}
    for p in _load_conf()["profile"]:
        name = str(p.get("name", ""))
        if name.startswith(PREFIX) and name[len(PREFIX):].isdigit():
            games[int(name[len(PREFIX):])] = _clamp({
                "enabled": True, "multiplier": p.get("multiplier", 2), "flow_scale": p.get("flow_scale", 0.8),
                "performance_mode": p.get("performance_mode", True),
                "fifo": p.get("override_present_mode", True),
                "preserve_images": p.get("preserve_swapchain_image_count", False)})
    return games


def _save_games(games: dict[int, dict]):
    os.makedirs(os.path.dirname(GAMES), exist_ok=True)
    tmp = GAMES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in sorted(games.items())}, f, indent=1)
    os.replace(tmp, GAMES)


def _sync(games: dict[int, dict]):
    """Rewrite our profiles in conf.toml from the store (enabled games only)."""
    conf = _load_conf()
    ours = lambda p: str(p.get("name", "")).startswith(PREFIX)
    conf["profile"] = [p for p in conf["profile"] if not ours(p)] + \
        [_profile(a, s) for a, s in sorted(games.items()) if s["enabled"]]
    # lsfg-vk searches only the main Steam library itself; point it at other libraries
    dll = _find_dll()
    if dll["path"] and os.path.realpath(dll["lib"]) != os.path.realpath(steamlib.STEAM):
        conf["global"]["dll"] = dll["path"]
    elif conf["global"].get("dll") and not os.path.isfile(os.path.expanduser(conf["global"]["dll"])):
        del conf["global"]["dll"]
    _save_conf(conf)


class Plugin:
    async def status(self) -> dict:
        dll = _find_dll()
        return {
            "layer": os.path.isfile(LAYER),
            "dll": dll["path"],
            "lossless_installed": dll.get("installed") is not None or dll["path"] is not None,
            "allow_fp16": _load_conf()["global"].get("allow_fp16", True),
            "enabled_games": sorted(a for a, s in _load_games().items() if s["enabled"]),
        }

    async def installed_games(self) -> list[dict]:
        return steamlib.installed_games()

    async def get_game(self, appid: int) -> dict:
        return _load_games().get(appid, dict(DEFAULTS))

    async def set_game(self, appid: int, settings: dict) -> dict:
        games = _load_games()
        games[appid] = _clamp({**games.get(appid, DEFAULTS), **settings})
        _save_games(games)
        _sync(games)
        return games[appid]

    async def reset_game(self, appid: int) -> dict:
        games = _load_games()
        games[appid] = _clamp({"enabled": games.get(appid, DEFAULTS)["enabled"]})
        _save_games(games)
        _sync(games)
        return games[appid]

    async def set_fp16(self, allow: bool):
        conf = _load_conf()
        conf["global"]["allow_fp16"] = bool(allow)
        _save_conf(conf)

    async def _main(self):
        games = _load_games()
        if games and not os.path.exists(GAMES):
            _save_games(games)
        decky.logger.info("frame generation: layer %s, dll %s, %d games on",
                          os.path.isfile(LAYER), _find_dll()["path"], sum(s["enabled"] for s in games.values()))

    async def _unload(self):
        pass
