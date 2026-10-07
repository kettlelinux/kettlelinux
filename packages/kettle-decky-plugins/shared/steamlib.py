# Steam library lookups shared by the Kettle Linux plugins (installed into each plugin's
# py_modules/ by the PKGBUILD).
import glob
import os
import re
import struct

import decky

STEAM = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "Steam")

# Installed "apps" that aren't games
_TOOLS = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common|SteamVR|Lossless Scaling$)", re.I)
# Non-Steam shortcuts that aren't games: the Desktop in Game Mode (the Welcome plugin's)
_NOT_GAMES = ("/usr/lib/kettle/nested-desktop",)

# A non-Steam shortcut's appid has the top bit set (Steam makes it from a CRC with 0x80000000);
# Steam's own appids never do. Such an appid is only known on this device.
SHORTCUT_MIN = 1 << 31


def is_shortcut(appid: int) -> bool:
    return int(appid) >= SHORTCUT_MIN


def _binary_vdf(data: bytes) -> dict:
    """Steam's binary VDF (shortcuts.vdf): 0x00 map, 0x01 string, 0x02 int32, 0x08 end of map."""
    pos = 0

    def cstr() -> str:
        nonlocal pos
        end = data.index(b"\0", pos)
        v = data[pos:end].decode("utf-8", errors="replace")
        pos = end + 1
        return v

    def read_map() -> dict:
        nonlocal pos
        out = {}
        while pos < len(data):
            t = data[pos]
            pos += 1
            if t == 0x08:
                return out
            key = cstr()
            if t == 0x00:
                out[key] = read_map()
            elif t == 0x01:
                out[key] = cstr()
            elif t == 0x02:
                out[key] = struct.unpack_from("<i", data, pos)[0]
                pos += 4
            else:
                raise ValueError(f"unknown VDF type {t:#x} at {pos - 1}")
        return out

    return read_map()


def shortcuts() -> list[dict]:
    """The non-Steam shortcuts of the accounts on this device: appid (as Steam's UI has it,
    unsigned), name, exe and start dir (without Steam's quotes), and launch options."""
    out = {}
    for path in glob.glob(os.path.join(STEAM, "userdata", "*", "config", "shortcuts.vdf")):
        try:
            with open(path, "rb") as f:
                root = _binary_vdf(f.read())
        except (OSError, ValueError, IndexError, struct.error):
            continue
        table = next((v for k, v in root.items() if k.lower() == "shortcuts" and isinstance(v, dict)), {})
        for entry in table.values():
            if not isinstance(entry, dict):
                continue
            e = {k.lower(): v for k, v in entry.items()}
            if not isinstance(e.get("appid"), int) or not e.get("appname"):
                continue
            appid = e["appid"] & 0xFFFFFFFF
            out[appid] = {"appid": appid, "name": e["appname"], "exe": str(e.get("exe", "")).strip('"'),
                          "dir": str(e.get("startdir", "")).strip('"'), "launch": str(e.get("launchoptions", ""))}
    return list(out.values())


def _shortcut_install(appid: int) -> tuple[str, str] | None:
    """A shortcut's game folder: the .exe's folder for a Windows game, else its start dir when
    that's the player's (home or a removable drive), never a system folder; and the exe's
    modification time in place of a build id."""
    s = next((x for x in shortcuts() if x["appid"] == appid), None)
    if not s:
        return None
    exe, d = s["exe"], s["dir"]
    if exe.lower().endswith(".exe") and os.path.isfile(exe):
        d = os.path.dirname(exe)
    home = os.path.realpath(decky.DECKY_USER_HOME)
    real = os.path.realpath(d) if d else ""
    if not real or not os.path.isdir(real) or not (real.startswith(home + os.sep) or real.startswith("/run/media/")):
        return None
    try:
        build = str(int(os.path.getmtime(exe)))
    except OSError:
        build = ""
    return d, build


def libraries() -> list[str]:
    """Steam library roots from libraryfolders.vdf, the main one first."""
    libs = [STEAM]
    try:
        with open(os.path.join(STEAM, "steamapps", "libraryfolders.vdf"), encoding="utf-8") as f:
            for p in re.findall(r'"path"\s+"([^"]+)"', f.read()):
                if os.path.realpath(p) not in map(os.path.realpath, libs):
                    libs.append(p)
    except OSError:
        pass
    return libs


def _manifest(path: str) -> dict:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return {}
    return dict(re.findall(r'^\s*"(appid|name|installdir|buildid)"\s+"([^"]*)"', text, re.M))


def installed_games() -> list[dict]:
    games = {}
    for lib in libraries():
        d = os.path.join(lib, "steamapps")
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if not (n.startswith("appmanifest_") and n.endswith(".acf")):
                continue
            m = _manifest(os.path.join(d, n))
            if m.get("appid", "").isdigit() and m.get("name") and not _TOOLS.match(m["name"]):
                games[int(m["appid"])] = {"appid": int(m["appid"]), "name": m["name"]}
    # non-Steam shortcuts too (Game Stores games, Battle.net, emulators...): every per-game setting
    # works through launch options and the compat tool, which shortcuts have like any game
    for s in shortcuts():
        if s["exe"] not in _NOT_GAMES:
            games[s["appid"]] = {"appid": s["appid"], "name": s["name"], "shortcut": True}
    return sorted(games.values(), key=lambda g: g["name"].lower())


def install(appid: int) -> tuple[str, str] | None:
    """The game's install folder and Steam build id (which changes with every update); for a
    non-Steam shortcut, see _shortcut_install."""
    if is_shortcut(appid):
        return _shortcut_install(appid)
    for lib in libraries():
        m = _manifest(os.path.join(lib, "steamapps", f"appmanifest_{appid}.acf"))
        if m.get("installdir"):
            d = os.path.join(lib, "steamapps", "common", m["installdir"])
            if os.path.isdir(d):
                return d, m.get("buildid", "")
    return None


def install_dir(appid: int) -> str | None:
    i = install(appid)
    return i[0] if i else None

