# Welcome: Game Mode's counterpart of the desktop's Kettle Welcome, shown once on first boot,
# then kept in the Quick Access menu: a tour of Kettle in Game Mode, with links to where things are.
#
# The desktop in Game Mode (usr/lib/kettle/nested-desktop) is added to the library once per
#    device as "Desktop", with its artwork and the desktop's controls as its layout (src/desktop.ts);
#    welcome.json records the shortcut's appid. Game fixes (src/fixes.ts) are recorded in fixes.json.
#
# What else was here moved to the plugins it belongs with: the start-up mode, the SSH server and
# resetting the device to Device Settings' System tab (up to 1.12.0-38); Gaming Extras' Flathub
# apps and Battle.net to Game Stores (up to 1.12.0-39); its Proton versions and optional components
# to Game Settings' Extras tab (up to 1.12.0-40), which keeps their installed.json here.
import base64
import json
import os
import re
import threading

import decky

WELCOME = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "welcome.json")
FIXES = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "fixes.json")  # game fixes applied (src/fixes.ts)
# Steam's accounts on this device, written once someone first signs in
LOGIN_USERS = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "Steam", "config", "loginusers.vdf")
_STEAMID = re.compile(r'^\s*"7656\d{13}"\s*$', re.M)
ANDROID = "/usr/bin/kettle-android-games"  # package kettle-lepton: Game Stores' Android tab
BOTTOM_SCREEN = "/usr/lib/kettle/bottom-screen"  # the Thor's (device/thor/overlay)
# the Desktop entry's artwork (package kettle-desktop-art), by SetCustomArtworkForApp asset type
DESKTOP_ART = "/usr/share/kettle/nested-desktop/art"
_DESKTOP_ASSETS = {0: "capsule.png", 1: "hero.png", 2: "logo.png", 3: "header.png"}
PLUGINS = "/usr/share/decky/plugins"  # Kettle's own: kettle-<name>
_state_lock = threading.Lock()  # welcome.json


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


class Plugin:
    async def signed_in(self) -> bool:
        """True once an account has signed in to Steam on this device (it is then in
        loginusers.vdf). Steam's UI can't say: App.m_CurrentUser is set during first-time setup,
        before sign-in, and the welcome page opened on top of it."""
        try:
            with open(LOGIN_USERS, encoding="utf-8", errors="replace") as f:
                return bool(_STEAMID.search(f.read()))
        except OSError:
            return False

    async def first_run(self) -> bool:
        """True exactly once: the first time this is asked (the welcome page opens then)."""
        state = _read_json(WELCOME, {})
        if state.get("seen"):
            return False
        state["seen"] = True   # keeping the rest (claim_default's record)
        _write_json(WELCOME, state)
        return True

    async def claim_default(self, name: str) -> bool:
        """True the first time a Kettle default for a Steam setting is asked for: the frontend
        applies it then, once, so a later change in Steam's Settings sticks."""
        state = _read_json(WELCOME, {})
        done = state.get("defaults", [])
        if not isinstance(done, list):
            done = []
        if name in done:
            return False
        state["defaults"] = done + [name]
        _write_json(WELCOME, state)
        return True

    async def applied_fixes(self) -> list[str]:
        return _read_json(FIXES, [])

    async def mark_fix_applied(self, fid: str):
        applied = _read_json(FIXES, [])
        if fid not in applied:
            _write_json(FIXES, applied + [fid])
        decky.logger.info("applied game fix %s", fid)

    async def features(self) -> dict:
        """What this device has: Kettle's Decky plugins (by name, e.g. "stores"), whether
        Android games (Game Stores' Android tab) are there, and a second screen (the Thor's)."""
        try:
            plugins = sorted(d[len("kettle-"):] for d in os.listdir(PLUGINS) if d.startswith("kettle-"))
        except OSError:
            plugins = []
        return {"plugins": plugins, "android": os.access(ANDROID, os.X_OK),
                "bottom_screen": os.path.exists(BOTTOM_SCREEN)}

    async def desktop_art(self) -> dict:
        """The Desktop entry's library artwork (asset type -> PNG as base64) and icon path."""
        art = {}
        for kind, name in _DESKTOP_ASSETS.items():
            try:
                with open(os.path.join(DESKTOP_ART, name), "rb") as f:
                    art[str(kind)] = base64.b64encode(f.read()).decode()
            except OSError:
                pass
        icon = os.path.join(DESKTOP_ART, "icon.png")
        return {"art": art, "icon": icon if os.path.isfile(icon) else ""}

    async def remember_desktop(self, appid: int):
        """Records the Steam shortcut added for the desktop in Game Mode (src/desktop.ts)."""
        with _state_lock:
            state = _read_json(WELCOME, {})
            state["desktop"] = int(appid)
            _write_json(WELCOME, state)

    async def desktop_appid(self) -> int | None:
        appid = _read_json(WELCOME, {}).get("desktop")
        return appid if isinstance(appid, int) else None

    async def _main(self):
        pass

    async def _unload(self):
        pass
