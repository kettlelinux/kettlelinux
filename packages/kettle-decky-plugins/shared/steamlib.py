# Steam library lookups shared by the Kettle Linux plugins (installed into each plugin's
# py_modules/ by the PKGBUILD).
import os
import re

import decky

STEAM = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "Steam")

# Installed "apps" that aren't games
_TOOLS = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common|SteamVR|Lossless Scaling$)", re.I)


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
    return dict(re.findall(r'^\s*"(appid|name|installdir)"\s+"([^"]*)"', text, re.M))


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
    return sorted(games.values(), key=lambda g: g["name"].lower())


def install_dir(appid: int) -> str | None:
    for lib in libraries():
        m = _manifest(os.path.join(lib, "steamapps", f"appmanifest_{appid}.acf"))
        if m.get("installdir"):
            d = os.path.join(lib, "steamapps", "common", m["installdir"])
            if os.path.isdir(d):
                return d
    return None

