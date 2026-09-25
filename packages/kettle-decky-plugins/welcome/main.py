# Welcome: a page shown once on first boot (a tour of Kettle and a setup checklist), then kept
# in the Quick Access menu.
#
# Setup has two parts:
#  - things the user sets up in Steam themselves (Lossless Scaling for the lsfg-vk engine),
#    which this backend only detects
#  - optional components: software Kettle can't ship in the image (license or no source build),
#    downloaded on request from its official upstream source. components.json, next to this
#    file, lists them; each entry:
#      {"id": "name-like-this", "name": ..., "description": ..., "license": ..., "homepage": ...,
#       "version": ..., "url": "https://...", "sha256": ..., "archive": "zip" | "tar" | "file",
#       "file": "<name to save as, for archive=file>"}
#    The pinned sha256 is what makes a download trustworthy: a mismatch is never installed.
#    Components land in ~/.local/share/kettle/components/<id>; what's installed (and which
#    version) is recorded in the plugin's installed.json.
import asyncio
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import threading
import urllib.request
import zipfile

import decky
import steamlib

MANIFEST = os.path.join(decky.DECKY_PLUGIN_DIR, "components.json")
COMPONENTS = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "kettle", "components")
INSTALLED = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")
WELCOME = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "welcome.json")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_ARCHIVES = ("zip", "tar", "file")

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
        ok = isinstance(c, dict) and _ID.match(str(c.get("id", ""))) and c.get("archive") in _ARCHIVES \
            and str(c.get("url", "")).startswith("https://") and re.fullmatch(r"[0-9a-f]{64}", str(c.get("sha256", ""))) \
            and (c["archive"] != "file" or re.fullmatch(r"[\w.-]+", str(c.get("file", ""))))
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


def _download(c: dict, path: str):
    h = hashlib.sha256()
    req = urllib.request.Request(c["url"], headers={"User-Agent": "kettle-welcome"})
    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if total:
                _jobs[c["id"]]["progress"] = min(done / total, 0.99)
    if h.hexdigest() != c["sha256"]:
        raise ValueError("download doesn't match its pinned checksum; not installed")


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
        archive = os.path.join(tmp, "download")
        _download(c, archive)
        new = os.path.join(tmp, "new")
        os.mkdir(new)
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
                "host": re.sub(r"^https://([^/]+).*", r"\1", c["url"]),
                "installed": have["version"] if have else None,
                "busy": job is not None and job["error"] is None,
                "progress": job["progress"] if job else None,
                "error": job["error"] if job else None,
            })
        ls = steamlib.lossless_scaling()
        return {
            "lossless": {"installed": ls["installed"] is not None, "dll": ls["dll"] is not None},
            "components": comps,
        }

    async def first_run(self) -> bool:
        """True exactly once: the first time this is asked (the welcome page opens then)."""
        if _read_json(WELCOME, {}).get("seen"):
            return False
        _write_json(WELCOME, {"seen": True})
        return True

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
