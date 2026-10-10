# Game Settings' Extras tab: downloads Kettle offers but can't ship in the image. They were Welcome's
# Gaming Extras up to 1.12.0-40.
#
# Optional components: software Kettle can't ship (license or no source build), downloaded on
#    request from its official upstream source. components.json, next to the plugin, lists them;
#    each entry:
#      {"id": "name-like-this", "name": ..., "description": ..., "license": ..., "homepage": ...,
#       "version": ..., "url": "https://...", "sha256": ..., "archive": "zip" | "tar" | "file",
#       "file": "<name to save as, for archive=file>"}
#    or, for several individual files (archive "files"), instead of url/sha256/file:
#       "files": [{"url": "https://...", "sha256": ..., "file": "<name to save as>"}, ...]
#    The pinned sha256 is what makes a download trustworthy: a mismatch is never installed.
#    Components land in ~/.local/share/kettle/components/<id> (upscaling.py looks for AMD's DLLs
#    there); what's installed (and which version) is recorded in installed.json, in the settings
#    of the Welcome plugin they were in before (reset-home keeps it).
#
# The community Protons with ARM64 builds (GE-Proton, Proton-CachyOS), through kettle-welcome's
#    welcome-proton: the latest release from the project's own GitHub releases, checked against
#    its published sha512sum, unpacked into Steam's compatibilitytools.d. It runs as a systemd
#    user unit, so the desktop's Kettle Welcome shows the same install and builds.
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
import time
import urllib.request
import zipfile

import decky

MANIFEST = os.path.join(decky.DECKY_PLUGIN_DIR, "components.json")
COMPONENTS = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "kettle", "components")
INSTALLED = os.path.join(os.path.dirname(decky.DECKY_PLUGIN_SETTINGS_DIR), "kettle-welcome", "installed.json")
PROTON = "/usr/lib/kettle/welcome-proton"  # package kettle-welcome
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_ARCHIVES = ("zip", "tar", "file", "files")
_NAME = re.compile(r"[\w.-]+")
_SHA = re.compile(r"[0-9a-f]{64}")
_PROTON_TOOLS = ("ge", "cachyos")
_latest: tuple[float, dict[str, str]] = (0.0, {})  # when looked up, tool -> newest build


def _session_env() -> dict:
    # Decky starts this backend as the user but without the session's environment
    run = f"/run/user/{os.getuid()}"
    return {**os.environ, "HOME": decky.DECKY_USER_HOME, "XDG_RUNTIME_DIR": run,
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={run}/bus"}


def _helper(path: str, *args: str, timeout: int = 15) -> str:
    r = subprocess.run([path, *args], env=_session_env(), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"{os.path.basename(path)} {args[0]} failed")
    return r.stdout.strip()


def _proton(*args: str, timeout: int = 15) -> str:
    return _helper(PROTON, *args, timeout=timeout)


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


async def status() -> dict:
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


async def install(cid: str):
    c = _component(cid)
    job = _jobs.get(cid)
    if job and job["error"] is None:
        return  # already running
    _jobs[cid] = {"progress": 0, "error": None}
    asyncio.get_running_loop().create_task(_run(c))


async def uninstall(cid: str):
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


async def proton_status() -> dict:
    """welcome-proton's status line (idle | running TOOL download BYTES TOTAL | running TOOL
    unpack | done TOOL NAME | error TOOL MESSAGE) and the installed builds, newest first."""
    if not os.access(PROTON, os.X_OK):
        return {"available": False, "status": "idle", "installed": []}
    status, installed = await asyncio.gather(asyncio.to_thread(_proton, "status"),
                                             asyncio.to_thread(_proton, "installed"))
    return {"available": True, "status": status or "idle",
            "installed": [{"tool": t, "name": n} for t, n in _pairs(installed)]}


async def proton_latest() -> dict[str, str]:
    """Tool -> its newest release's build name ("-" if it couldn't be looked up). Kept for
    ten minutes: GitHub allows 60 lookups an hour without an account."""
    global _latest
    if time.monotonic() - _latest[0] > 600 or "-" in _latest[1].values():
        found = dict(_pairs(await asyncio.to_thread(_proton, "latest", timeout=90)))
        _latest = (time.monotonic(), found)
    return _latest[1]


async def proton_install(tool: str):
    if tool not in _PROTON_TOOLS:
        raise ValueError(f"unknown Proton {tool!r}")
    await asyncio.to_thread(_proton, "start", tool)
    decky.logger.info("installing Proton %s", tool)


async def proton_remove(name: str):
    await asyncio.to_thread(_proton, "remove", name)
    decky.logger.info("removed Proton %s", name)
