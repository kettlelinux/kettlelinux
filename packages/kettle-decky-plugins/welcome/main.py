# Welcome: a page shown once on first boot (a tour of Kettle and a setup checklist), then kept
# in the Quick Access menu.
#
# Setup lists optional components: software Kettle can't ship in the image (license or no
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
# Welcome also sets what the device starts up in, Game Mode or the desktop: steamos-manager's
#    default login mode, through steamosctl on the user's session bus.
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.request
import zipfile

import decky

MANIFEST = os.path.join(decky.DECKY_PLUGIN_DIR, "components.json")
COMPONENTS = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "kettle", "components")
INSTALLED = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")
WELCOME = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "welcome.json")
FIXES = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "fixes.json")  # game fixes applied (src/fixes.ts)
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_ARCHIVES = ("zip", "tar", "file", "files")
_NAME = re.compile(r"[\w.-]+")
_SHA = re.compile(r"[0-9a-f]{64}")


_MODES = ("game", "desktop")


def _steamosctl(*args: str) -> str:
    # Decky starts this backend as the user but without the session's environment
    run = f"/run/user/{os.getuid()}"
    env = {**os.environ, "XDG_RUNTIME_DIR": run, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={run}/bus"}
    r = subprocess.run(["steamosctl", *args], env=env, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"steamosctl {args[0]} failed")
    return r.stdout.strip()


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

    async def _main(self):
        decky.logger.info("welcome: %d optional components offered", len(_manifest(log=True)))

    async def _unload(self):
        pass
