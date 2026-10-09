# Welcome: Game Mode's counterpart of the desktop's Kettle Welcome, shown once on first boot,
# then kept in the Quick Access menu: a tour, Gaming Extras, Android games and remote access.
#
# Gaming Extras lists optional components: software Kettle can't ship in the image (license or no
#    source build), downloaded on request from its official upstream source. components.json,
#    next to this file, lists them; each entry:
#      {"id": "name-like-this", "name": ..., "description": ..., "license": ..., "homepage": ...,
#       "version": ..., "url": "https://...", "sha256": ..., "archive": "zip" | "tar" | "file",
#       "file": "<name to save as, for archive=file>"}
#    or, for several individual files (archive "files"), instead of url/sha256/file:
#       "files": [{"url": "https://...", "sha256": ..., "file": "<name to save as>"}, ...]
#    The pinned sha256 is what makes a download trustworthy: a mismatch is never installed.
#    Components land in ~/.local/share/kettle/components/<id>; what's installed (and which
#    version) is recorded in the plugin's installed.json.
#
# It also offers the community Protons with ARM64 builds (GE-Proton, Proton-CachyOS), through
#    kettle-welcome's welcome-proton: the latest release from the project's own GitHub releases,
#    checked against its published sha512sum, unpacked into Steam's compatibilitytools.d. It runs
#    as a systemd user unit, so the desktop's Kettle Welcome shows the same install and builds.
#
# Gaming Extras: the Flathub apps of the desktop's Kettle Welcome that work with a controller,
#    installed by kettle-welcome's welcome-flatpak (the same systemd user unit, so both show the
#    same install), and added to Steam as shortcuts by the frontend (shortcuts.json records
#    which, by Steam appid).
#
# The desktop in Game Mode (usr/lib/kettle/nested-desktop) is added to the library once per
#    device as "Desktop", with its artwork and the desktop's controls as its layout (src/desktop.ts);
#    welcome.json records the shortcut's appid.
#
# Battle.net: Blizzard's launcher, added to Steam with Proton-CachyOS and its installer started,
#    by kettle-welcome's welcome-battlenet (the desktop's Kettle Welcome uses it too, so both show
#    the same Steam entry); its status also switches the entry to the installed launcher.
#
# Android games, with kettle-lepton: kettle-android-games adds F-Droid apps and APK files to
#    Steam, one command at a time; its download progress comes on stderr.
#
# Welcome also sets what the device starts up in, Game Mode or the desktop: steamos-manager's
#    default login mode, through steamosctl on the user's session bus. And it starts and stops
#    the SSH server: Game Mode has no password prompt, so polkit lets the active local user do
#    that, and only that, for sshd.service (50-kettle-ssh.rules); enabling it at every start-up
#    stays with the desktop's Kettle Welcome.
#
# And it resets the device (kettle-reset, through pkexec: 50-kettle-reset.rules lets Decky's
#    plugin backends do that, Game Mode having no password prompt): every setting back to its
#    default, or everything erased. Erasing is refused while /home holds the Kettle Installer's
#    backup of the internal storage; the desktop's Reset Kettle says what that means first.
import asyncio
import base64
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile

import decky

MANIFEST = os.path.join(decky.DECKY_PLUGIN_DIR, "components.json")
COMPONENTS = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "kettle", "components")
INSTALLED = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")
WELCOME = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "welcome.json")
FIXES = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "fixes.json")  # game fixes applied (src/fixes.ts)
# Steam's accounts on this device, written once someone first signs in
LOGIN_USERS = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "Steam", "config", "loginusers.vdf")
_STEAMID = re.compile(r'^\s*"7656\d{13}"\s*$', re.M)
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_ARCHIVES = ("zip", "tar", "file", "files")
_NAME = re.compile(r"[\w.-]+")
_SHA = re.compile(r"[0-9a-f]{64}")


_MODES = ("game", "desktop")
PROTON = "/usr/lib/kettle/welcome-proton"  # package kettle-welcome
FLATPAK = "/usr/lib/kettle/welcome-flatpak"  # package kettle-welcome
BATTLENET = "/usr/lib/kettle/welcome-battlenet"  # package kettle-welcome
ANDROID = "/usr/bin/kettle-android-games"  # package kettle-lepton
SHORTCUTS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "shortcuts.json")  # Flatpak app -> Steam appid
# the Desktop entry's artwork (package kettle-desktop-art), by SetCustomArtworkForApp asset type
DESKTOP_ART = "/usr/share/kettle/nested-desktop/art"
_DESKTOP_ASSETS = {0: "capsule.png", 1: "hero.png", 2: "logo.png", 3: "header.png"}
FLATPAK_ICONS = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "flatpak", "exports", "share", "icons", "hicolor")
PLUGINS = "/usr/share/decky/plugins"  # Kettle's own: kettle-<name>
_APP_ID = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)+$")
_ANDROID_COMMANDS = ("add", "remove", "fdroid-search", "fdroid-add")
# the running or last kettle-android-games command: {"command", "busy", "done", "total", "result"}
_android: dict = {"command": None, "busy": False, "done": 0, "total": 0, "result": None}
_PROTON_TOOLS = ("ge", "cachyos")
RESET = "/usr/bin/kettle-reset"
UFS_BACKUP = "/home/.kettle/ufs-backup"  # the Kettle Installer's (kettle-backup-ufs)
_RESETS = ("settings", "everything")
_latest: tuple[float, dict[str, str]] = (0.0, {})  # when looked up, tool -> newest build


def _session_env() -> dict:
    # Decky starts this backend as the user but without the session's environment
    run = f"/run/user/{os.getuid()}"
    return {**os.environ, "HOME": decky.DECKY_USER_HOME, "XDG_RUNTIME_DIR": run,
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={run}/bus"}


def _steamosctl(*args: str) -> str:
    r = subprocess.run(["steamosctl", *args], env=_session_env(), capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"steamosctl {args[0]} failed")
    return r.stdout.strip()


def _helper(path: str, *args: str, timeout: int = 15) -> str:
    r = subprocess.run([path, *args], env=_session_env(), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"{os.path.basename(path)} {args[0]} failed")
    return r.stdout.strip()


def _proton(*args: str, timeout: int = 15) -> str:
    return _helper(PROTON, *args, timeout=timeout)


def _flatpak_icon(app: str) -> str:
    """The app's largest exported PNG icon, for its Steam shortcut ("" if none)."""
    best = (0, "")
    try:
        sizes = os.listdir(FLATPAK_ICONS)
    except OSError:
        return ""
    for d in sizes:
        path = os.path.join(FLATPAK_ICONS, d, "apps", app + ".png")
        px = int(d.split("x")[0]) if re.fullmatch(r"\d+x\d+", d) else 0
        if px > best[0] and os.path.isfile(path):
            best = (px, path)
    return best[1]


def _addresses() -> list[str]:
    """This device's IPv4 addresses, for "ssh user@address"."""
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    # "2: wlan0    inet 192.168.1.5/24 ...", leaving out container networks (Lepton's podman)
    return [a for i, a in re.findall(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)/", out, re.M)
            if not i.startswith(("podman", "docker", "br-", "veth", "virbr", "cni"))]


def _systemctl(*args: str) -> int:
    return subprocess.run(["systemctl", *args, "sshd.service"], capture_output=True, timeout=30).returncode


async def _android_run(command: str, arg: str):
    """Runs kettle-android-games, following its PROGRESS lines; the JSON result ends up in _android."""
    try:
        p = await asyncio.create_subprocess_exec(ANDROID, command, arg, env=_session_env(),
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        err = []

        async def follow():
            async for line in p.stderr:
                parts = line.decode(errors="replace").split()
                if len(parts) == 3 and parts[0] == "PROGRESS":
                    _android["done"], _android["total"] = int(parts[1]), int(parts[2])
                else:
                    err.append(" ".join(parts))

        out, _ = await asyncio.gather(p.stdout.read(), follow())
        await p.wait()
        try:
            result = json.loads(out)
        except ValueError:
            result = {"ok": False, "error": (err[-1] if err else "") or "kettle-android-games failed."}
    except OSError as e:
        result = {"ok": False, "error": str(e)}
    if not result.get("ok"):
        decky.logger.warning("kettle-android-games %s: %s", command, result.get("error"))
    _android.update(busy=False, result=result)


def _pairs(out: str) -> list[tuple[str, str]]:
    return [tuple(l.split(" ", 1)) for l in out.splitlines() if l.count(" ") == 1]


def _valid_download(d) -> bool:
    return isinstance(d, dict) and str(d.get("url", "")).startswith("https://") \
        and bool(_SHA.fullmatch(str(d.get("sha256", ""))))

_jobs: dict[str, dict] = {}  # id -> {"progress": 0..1, "error": str | None}; running or failed
_state_lock = threading.Lock()  # installed.json: downloads finish on worker threads


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


def _manifest(log: bool = False) -> list[dict]:
    """The valid entries of components.json; bad ones are skipped (and logged, with log)."""
    out = []
    for c in _read_json(MANIFEST, []):
        ok = isinstance(c, dict) and _ID.match(str(c.get("id", ""))) and c.get("archive") in _ARCHIVES
        if ok and c["archive"] == "files":
            fs = c.get("files")
            ok = isinstance(fs, list) and len(fs) > 0 and all(
                _valid_download(f) and _NAME.fullmatch(str(f.get("file", ""))) for f in fs) \
                and len({f["file"] for f in fs}) == len(fs)
        elif ok:
            ok = _valid_download(c) and (c["archive"] != "file" or bool(_NAME.fullmatch(str(c.get("file", "")))))
        if ok:
            out.append(c)
        elif log:
            decky.logger.warning("components.json: skipping invalid entry %r", c)
    return out


def _component(cid: str) -> dict:
    for c in _manifest():
        if c["id"] == cid:
            return c
    raise ValueError(f"unknown component {cid!r}")


def _download(c: dict, d: dict, path: str, part: tuple[int, int] = (0, 1)):
    """Fetch d["url"] to path and check it against d["sha256"]; part = (index, count) of the
    component's downloads, for the progress bar."""
    h = hashlib.sha256()
    req = urllib.request.Request(d["url"], headers={"User-Agent": "kettle-welcome"})
    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if total:
                _jobs[c["id"]]["progress"] = min((part[0] + done / total) / part[1], 0.99)
    if h.hexdigest() != d["sha256"]:
        raise ValueError(f"{os.path.basename(d['url'])} doesn't match its pinned checksum; not installed")


def _unpack(c: dict, archive: str, into: str):
    if c["archive"] == "file":
        shutil.move(archive, os.path.join(into, c["file"]))
    elif c["archive"] == "tar":
        with tarfile.open(archive) as t:
            t.extractall(into, filter="data")  # refuses absolute paths, .. and device files
    else:
        root = os.path.realpath(into)
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                if not os.path.realpath(os.path.join(root, n)).startswith(root + os.sep):
                    raise ValueError(f"archive entry outside its folder: {n}")
            z.extractall(into)


def _install(c: dict):
    """Download, verify and unpack into a staging folder, then swap it in place of the old one."""
    os.makedirs(COMPONENTS, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=COMPONENTS, prefix=".staging-") as tmp:
        new = os.path.join(tmp, "new")
        os.mkdir(new)
        if c["archive"] == "files":
            for i, d in enumerate(c["files"]):
                _download(c, d, os.path.join(new, d["file"]), (i, len(c["files"])))
        else:
            archive = os.path.join(tmp, "download")
            _download(c, c, archive)
            _unpack(c, archive, new)
        dest = os.path.join(COMPONENTS, c["id"])
        old = os.path.join(tmp, "old")
        with _state_lock:
            if os.path.exists(dest):
                os.rename(dest, old)
            os.rename(new, dest)
            installed = _read_json(INSTALLED, {})
            installed[c["id"]] = {"version": c.get("version")}
            _write_json(INSTALLED, installed)


async def _run(c: dict):
    try:
        await asyncio.to_thread(_install, c)
        del _jobs[c["id"]]
        decky.logger.info("installed %s %s", c["id"], c.get("version"))
    except Exception as e:
        decky.logger.error("installing %s failed: %s", c["id"], e)
        _jobs[c["id"]] = {"progress": 0, "error": str(e)}


class Plugin:
    async def status(self) -> dict:
        installed = _read_json(INSTALLED, {})
        comps = []
        for c in _manifest():
            have = installed.get(c["id"])
            job = _jobs.get(c["id"])
            comps.append({
                **{k: c.get(k) for k in ("id", "name", "description", "license", "homepage", "version")},
                "host": re.sub(r"^https://([^/]+).*", r"\1", c["files"][0]["url"] if c["archive"] == "files" else c["url"]),
                "installed": have["version"] if have else None,
                "busy": job is not None and job["error"] is None,
                "progress": job["progress"] if job else None,
                "error": job["error"] if job else None,
            })
        return {"components": comps}

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

    async def boot_mode(self) -> str | None:
        """What the device starts up in: "game", "desktop", or None if steamos-manager can't say."""
        try:
            out = await asyncio.to_thread(_steamosctl, "get-default-login-mode")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            decky.logger.warning("reading the start-up mode: %s", e)
            return None
        return next((m for m in _MODES if m in out.lower()), None)

    async def set_boot_mode(self, mode: str):
        if mode not in _MODES:
            raise ValueError(f"unknown start-up mode {mode!r}")
        await asyncio.to_thread(_steamosctl, "set-default-login-mode", mode)
        decky.logger.info("start-up mode set to %s", mode)

    async def install(self, cid: str):
        c = _component(cid)
        job = _jobs.get(cid)
        if job and job["error"] is None:
            return  # already running
        _jobs[cid] = {"progress": 0, "error": None}
        asyncio.get_running_loop().create_task(_run(c))

    async def uninstall(self, cid: str):
        if not _ID.match(cid):
            raise ValueError(f"unknown component {cid!r}")
        job = _jobs.get(cid)
        if job and job["error"] is None:
            raise ValueError("still downloading")
        with _state_lock:
            shutil.rmtree(os.path.join(COMPONENTS, cid), ignore_errors=True)
            installed = _read_json(INSTALLED, {})
            installed.pop(cid, None)
            _write_json(INSTALLED, installed)
        _jobs.pop(cid, None)

    async def proton_status(self) -> dict:
        """welcome-proton's status line (idle | running TOOL download BYTES TOTAL | running TOOL
        unpack | done TOOL NAME | error TOOL MESSAGE) and the installed builds, newest first."""
        if not os.access(PROTON, os.X_OK):
            return {"available": False, "status": "idle", "installed": []}
        status, installed = await asyncio.gather(asyncio.to_thread(_proton, "status"),
                                                 asyncio.to_thread(_proton, "installed"))
        return {"available": True, "status": status or "idle",
                "installed": [{"tool": t, "name": n} for t, n in _pairs(installed)]}

    async def proton_latest(self) -> dict[str, str]:
        """Tool -> its newest release's build name ("-" if it couldn't be looked up). Kept for
        ten minutes: GitHub allows 60 lookups an hour without an account."""
        global _latest
        if time.monotonic() - _latest[0] > 600 or "-" in _latest[1].values():
            found = dict(_pairs(await asyncio.to_thread(_proton, "latest", timeout=90)))
            _latest = (time.monotonic(), found)
        return _latest[1]

    async def proton_install(self, tool: str):
        if tool not in _PROTON_TOOLS:
            raise ValueError(f"unknown Proton {tool!r}")
        await asyncio.to_thread(_proton, "start", tool)
        decky.logger.info("installing Proton %s", tool)

    async def proton_remove(self, name: str):
        await asyncio.to_thread(_proton, "remove", name)
        decky.logger.info("removed Proton %s", name)

    async def battlenet_status(self) -> dict:
        """welcome-battlenet status: {proton, steam, appid, in_steam, ready}."""
        return json.loads(await asyncio.to_thread(_helper, BATTLENET, "status", timeout=30))

    async def battlenet_install(self):
        """Downloads Battle.net's installer, adds it to Steam and starts it; raises with the reason."""
        await asyncio.to_thread(_helper, BATTLENET, "install", timeout=180)
        decky.logger.info("Battle.net added to Steam, installer started")

    async def features(self) -> dict:
        """What this device has: Kettle's Decky plugins (by name, e.g. "screens"), whether the
        Flatpak installs and Android games are there, and where to look for an APK file."""
        try:
            plugins = sorted(d[len("kettle-"):] for d in os.listdir(PLUGINS) if d.startswith("kettle-"))
        except OSError:
            plugins = []
        downloads = os.path.join(decky.DECKY_USER_HOME, "Downloads")
        return {"plugins": plugins, "extras": os.access(FLATPAK, os.X_OK), "android": os.access(ANDROID, os.X_OK),
                "files": downloads if os.path.isdir(downloads) else decky.DECKY_USER_HOME}

    async def extras_status(self) -> dict:
        """welcome-flatpak's status line (idle | running I N ID | done N | error ID MESSAGE), the
        user's installed Flatpak apps, and the Steam shortcuts added for them (app -> appid)."""
        status, installed = await asyncio.gather(asyncio.to_thread(_helper, FLATPAK, "status"),
                                                 asyncio.to_thread(_helper, FLATPAK, "installed"))
        return {"status": status or "idle", "installed": installed.split(), "shortcuts": _read_json(SHORTCUTS, {})}

    async def extras_install(self, app: str):
        if not _APP_ID.match(app):
            raise ValueError(f"not an app ID: {app!r}")
        await asyncio.to_thread(_helper, FLATPAK, "start", app)
        decky.logger.info("installing %s from Flathub", app)

    async def flatpak_icon(self, app: str) -> str:
        return _flatpak_icon(app) if _APP_ID.match(app) else ""

    async def remember_shortcut(self, app: str, appid: int):
        """Records the Steam shortcut added for app (appid 0: none any more)."""
        if not _APP_ID.match(app):
            raise ValueError(f"not an app ID: {app!r}")
        with _state_lock:
            shortcuts = _read_json(SHORTCUTS, {})
            if appid:
                shortcuts[app] = int(appid)
            else:
                shortcuts.pop(app, None)
            _write_json(SHORTCUTS, shortcuts)

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

    async def android_list(self) -> dict:
        r = await asyncio.create_subprocess_exec(ANDROID, "list", env=_session_env(), stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.DEVNULL)
        out, _ = await r.communicate()
        try:
            return json.loads(out)
        except ValueError:
            return {"ok": False, "games": []}

    async def android_start(self, command: str, arg: str):
        """Starts a kettle-android-games command (add FILE, remove PACKAGE, fdroid-search TEXT,
        fdroid-add PACKAGE); android_job says how it goes. One at a time."""
        if command not in _ANDROID_COMMANDS:
            raise ValueError(f"unknown command {command!r}")
        if command == "add" and not os.path.isfile(arg):
            raise ValueError(f"no such file: {arg}")
        if _android["busy"]:
            raise ValueError("busy with another game")
        _android.update(command=command, busy=True, done=0, total=0, result=None)
        asyncio.get_running_loop().create_task(_android_run(command, arg))

    async def android_job(self) -> dict:
        return _android

    async def ssh_status(self) -> dict:
        """The SSH server: running now, and enabled at start-up (set from the desktop)."""
        active, enabled = await asyncio.gather(asyncio.to_thread(_systemctl, "is-active", "-q"),
                                               asyncio.to_thread(_systemctl, "is-enabled", "-q"))
        return {"active": active == 0, "enabled": enabled == 0, "user": pwd.getpwuid(os.getuid()).pw_name,
                "addresses": await asyncio.to_thread(_addresses)}

    async def set_ssh(self, on: bool):
        if await asyncio.to_thread(_systemctl, "start" if on else "stop") != 0:
            raise RuntimeError("systemd refused")
        decky.logger.info("SSH server %s", "started" if on else "stopped")

    async def reset_status(self) -> dict:
        """What's set to be reset on the next start ("none", "settings", "everything"), and
        whether erasing everything would erase a backup of the internal storage."""
        out = await asyncio.to_thread(subprocess.run, [RESET, "status"], capture_output=True, text=True, timeout=15)
        try:
            backup = bool(os.listdir(UFS_BACKUP))
        except OSError:
            backup = os.path.isdir(UFS_BACKUP)  # there, but not readable here: assume it holds one
        return {"pending": out.stdout.split(":", 1)[0].strip() or "none", "ufs_backup": backup}

    async def reset(self, what: str):
        """Resets on the next start, and restarts the device now."""
        if what not in _RESETS:
            raise ValueError(f"unknown reset {what!r}")
        r = await asyncio.to_thread(subprocess.run, ["pkexec", RESET, what, "--no-reboot"],
                                    capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip() or f"kettle-reset failed ({r.returncode})")
        decky.logger.info("reset %s on the next start; restarting", what)
        await asyncio.to_thread(subprocess.run, ["systemctl", "reboot"], timeout=30)

    async def _main(self):
        decky.logger.info("welcome: %d optional components offered", len(_manifest(log=True)))

    async def _unload(self):
        pass
