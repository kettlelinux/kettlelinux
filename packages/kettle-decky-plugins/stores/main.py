# Game Stores: the backend of the Game Stores plugin. Epic Games, GOG and Amazon Games in Game
# Mode: signing in, the library, installing, updating and uninstalling, through the store tools
# Heroic uses (legendary, gogdl, nile; packages/heroic-games-launcher). Their logins, libraries
# and installs are Heroic's own (~/.config/heroic), so desktop Heroic shows the same.
#
# Signing in happens in Steam's own browser: the frontend opens the store's login page there,
# and _watch_login follows the page through Steam's browser DevTools port (py_modules/cdp.py)
# until the store redirects to its "logged in" address. The code in that address (or, for Epic,
# on that page) goes to the store tool; the page is then blanked and the frontend leaves the
# browser. Nothing here logs what the tools print while signing in: gogdl prints its tokens.
#
# Installs and updates run one at a time as a user systemd unit (kettle-stores-job), so they
# carry on when Decky restarts; its output goes to job.log, where _progress reads it. A finished
# install is added to Steam by the frontend (src/shortcuts.ts) as a shortcut to the game's .exe
# with Proton and the launch options `kettle-store-run <store> <id> %command%`: kettle-store-run
# adds what the store needs to the command line (Epic's login arguments, the game's own) when it
# starts.
#
# State (stores.json in the plugin's settings dir):
#   shortcuts  "<store>:<id>" -> the Steam shortcut's appid
#   pending    installs finished while the frontend wasn't listening: it adds their shortcuts
#   queue      waiting installs and updates: {"store", "id", "title", "kind": "install"|"update"}
#   job        the one running (same fields)
#   install_dir  where new games go (default ~/Games/Heroic, Heroic's default)
import asyncio, base64, glob, json, os, re, shutil, subprocess, time, urllib.parse, urllib.request

import decky
import cdp

HOME = decky.DECKY_USER_HOME
HEROIC = os.path.join(HOME, ".config", "heroic")
LEGENDARY = os.path.join(HEROIC, "legendaryConfig", "legendary")
NILE_ROOT = os.path.join(HEROIC, "nile_config")
NILE = os.path.join(NILE_ROOT, "nile")
GOG = os.path.join(HEROIC, "gog_store")
GOG_AUTH = os.path.join(GOG, "auth.json")
GOG_CONFIG = os.path.join(GOG, "config.json")        # Heroic's: isLoggedIn, userData
GOG_INSTALLED = os.path.join(GOG, "installed.json")  # Heroic's: {"installed": [...]}
GOGDL = os.path.join(HEROIC, "gogdlConfig")          # gogdl's own (manifests of installed games)
DEFAULT_DIR = os.path.join(HOME, "Games", "Heroic")

SETTINGS = decky.DECKY_PLUGIN_SETTINGS_DIR
STATE = os.path.join(SETTINGS, "stores.json")
JOB_LOG = os.path.join(SETTINGS, "job.log")
UNIT = "kettle-stores-job"
EXIT_MARK = "KETTLE-STORES-EXIT"
# the launch wrapper: the package's, else (a test copy of the plugin) the plugin's own
WRAPPER = "/usr/bin/kettle-store-run"
if not os.path.exists(WRAPPER):
    WRAPPER = os.path.join(decky.DECKY_PLUGIN_DIR, "kettle-store-run")

STORES = ("epic", "gog", "amazon")
NAMES = {"epic": "Epic Games", "gog": "GOG", "amazon": "Amazon Games"}

EPIC_LOGIN = ("https://www.epicgames.com/id/login?redirectUrl=" + urllib.parse.quote(
    "https://www.epicgames.com/id/api/redirect?clientId=34a02cf8f4414e29b15921876da36f9a&responseType=code", safe=""))
EPIC_REDIRECT = "https://www.epicgames.com/id/api/redirect"
GOG_LOGIN = ("https://auth.gog.com/auth?client_id=46899977096215655&redirect_uri="
             "https%3A%2F%2Fembed.gog.com%2Fon_login_success%3Forigin%3Dclient&response_type=code&layout=galaxy")
GOG_REDIRECT = "https://embed.gog.com/on_login_success"
AMAZON_CODE = "openid.oa2.authorization_code="
LOGIN_TIMEOUT = 600


# --- files and commands ------------------------------------------------------------------------

def _read_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _env() -> dict:
    """The session's environment for the store tools (Decky's backend runs without it), with
    Heroic's config locations, and without Decky's PYTHONPATH."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(HOME=HOME, XDG_RUNTIME_DIR="/run/user/1000",
               DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1000/bus",
               LEGENDARY_CONFIG_PATH=LEGENDARY, NILE_CONFIG_PATH=NILE_ROOT, GOGDL_CONFIG_PATH=GOGDL)
    return env


def _run(*cmd: str, timeout: int = 120, quiet: bool = False) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, env=_env(), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and not quiet:
        decky.logger.warning("stores: %s %s failed (%d): %s", cmd[0], cmd[1], r.returncode, r.stderr[-500:])
    return r


def _get(url: str, token: str | None = None, limit: int = 16 << 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Kettle-Game-Stores"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(limit)


def _get_json(url: str, token: str | None = None):
    return json.loads(_get(url, token))


# --- logins ------------------------------------------------------------------------------------

def _gog_token() -> str:
    """A current GOG access token (gogdl refreshes it). Its output holds the tokens: never log it."""
    r = _run("gogdl", "--auth-config-path", GOG_AUTH, "auth", quiet=True)
    if r.returncode != 0:
        raise RuntimeError("GOG sign-in has expired: sign in again")
    return json.loads(r.stdout)["access_token"]


def _users() -> dict:
    epic = _read_json(os.path.join(LEGENDARY, "user.json"), {}).get("displayName")
    gog = None
    conf = _read_json(GOG_CONFIG, {})
    if conf.get("isLoggedIn") and os.path.exists(GOG_AUTH):
        gog = (conf.get("userData") or {}).get("username") or "signed in"
    amazon = None
    if glob.glob(os.path.join(NILE, "*.enc")):
        amazon = _read_json(os.path.join(NILE, "current_user.json"), {}).get("name") or "signed in"
    return {"epic": epic, "gog": gog, "amazon": amazon}


def _blank_redirects():
    """Blank pages left at a store's redirect (with a used code), so a login can't take them."""
    for t in cdp.targets():
        u = t.get("url", "")
        if t.get("type") == "page" and (u.startswith(EPIC_REDIRECT) or u.startswith(GOG_REDIRECT) or AMAZON_CODE in u):
            try:
                cdp.evaluate(t, "location.replace('about:blank')")
            except Exception:
                pass


def _wait_for(match, deadline: float, cancelled) -> dict:
    while time.time() < deadline:
        if cancelled():
            raise RuntimeError("cancelled")
        try:
            for t in cdp.targets():
                if t.get("type") == "page" and match(t.get("url", "")):
                    return t
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError("timed out waiting for the sign-in")


def _epic_code(t: dict) -> str:
    # read the code and hide the page in one go: it shows the code
    for _ in range(40):
        body = cdp.evaluate(t, "(() => { const s = document.body ? document.body.innerText : '';"
                               " if (s) document.body.style.visibility = 'hidden'; return s; })()")
        if body:
            code = json.loads(body).get("authorizationCode")
            if not code:
                raise RuntimeError("Epic didn't hand over a sign-in code; try again")
            return code
        time.sleep(0.1)
    raise RuntimeError("Epic's sign-in page didn't load")


def _login(store: str, amazon: dict | None, cancelled):
    """Waits for the store's redirect in Steam's browser and signs the store tool in (a thread)."""
    deadline = time.time() + LOGIN_TIMEOUT
    if store == "epic":
        t = _wait_for(lambda u: u.startswith(EPIC_REDIRECT), deadline, cancelled)
        code = _epic_code(t)
    elif store == "gog":
        t = _wait_for(lambda u: u.startswith(GOG_REDIRECT), deadline, cancelled)
        code = urllib.parse.parse_qs(urllib.parse.urlparse(t["url"]).query).get("code", [""])[0]
    else:
        t = _wait_for(lambda u: AMAZON_CODE in u, deadline, cancelled)
        code = urllib.parse.parse_qs(urllib.parse.urlparse(t["url"]).query).get("openid.oa2.authorization_code", [""])[0]
    try:
        cdp.evaluate(t, "location.replace('about:blank')")
    except Exception:
        pass
    if not code:
        raise RuntimeError("the store didn't hand over a sign-in code; try again")

    if store == "epic":
        r = _run("legendary", "auth", "--code", code, quiet=True)
        if r.returncode != 0:
            raise RuntimeError("legendary couldn't sign in with Epic's code")
    elif store == "gog":
        os.makedirs(GOG, exist_ok=True)
        r = _run("gogdl", "--auth-config-path", GOG_AUTH, "auth", "--code", code, quiet=True)
        if r.returncode != 0:
            raise RuntimeError("gogdl couldn't sign in with GOG's code")
        # Heroic counts GOG as signed in only with these in its own config
        conf = _read_json(GOG_CONFIG, {})
        try:
            conf["userData"] = _get_json("https://embed.gog.com/userData.json", _gog_token())
        except Exception as e:
            decky.logger.warning("stores: GOG user data: %s", e)
        conf["isLoggedIn"] = True
        _write_json(GOG_CONFIG, conf)
    else:
        r = _run("nile", "register", "--code", code, "--client-id", amazon["client_id"], "--code-verifier",
                 amazon["code_verifier"], "--serial", amazon["serial"], quiet=True)
        if r.returncode != 0 or not glob.glob(os.path.join(NILE, "*.enc")):
            raise RuntimeError("nile couldn't sign in with Amazon's code")


def _logout(store: str):
    if store == "epic":
        _run("legendary", "auth", "--delete")
    elif store == "gog":
        try:
            os.remove(GOG_AUTH)
        except FileNotFoundError:
            pass
        conf = _read_json(GOG_CONFIG, {})
        conf["isLoggedIn"] = False
        conf.pop("userData", None)
        _write_json(GOG_CONFIG, conf)
    else:
        _run("nile", "auth", "--logout")
    try:
        os.remove(os.path.join(SETTINGS, f"library-{store}.json"))
    except FileNotFoundError:
        pass


# --- libraries ---------------------------------------------------------------------------------

def _epic_image(meta: dict, kind: str) -> str:
    return next((i["url"] for i in meta.get("keyImages", []) if i.get("type") == kind), "")


def _sized(url: str, w: int, h: int) -> str:
    """Epic's image CDN resizes on request."""
    return f"{url}?w={w}&h={h}&resize=1" if url else ""


def _epic_installed() -> dict:
    return _read_json(os.path.join(LEGENDARY, "installed.json"), {})


def _gog_installed() -> list[dict]:
    return _read_json(GOG_INSTALLED, {}).get("installed", [])


def _amazon_installed() -> list[dict]:
    return _read_json(os.path.join(NILE, "installed.json"), [])


def _fetch_library(store: str) -> list[dict]:
    """The store's games, as the frontend lists them (a thread; network)."""
    games = []
    if store == "epic":
        r = _run("legendary", "list", "--json", timeout=300)
        if r.returncode != 0:
            raise RuntimeError("legendary couldn't list your Epic games")
        for g in json.loads(r.stdout):
            meta = g.get("metadata") or {}
            win = (g.get("asset_infos") or {}).get("Windows")
            attrs = meta.get("customAttributes") or {}
            note = ""
            if not win:
                note = "No Windows version"
            elif "ThirdPartyManagedApp" in attrs:
                note = f"Needs {attrs['ThirdPartyManagedApp'].get('value', 'another launcher')}"
            games.append({"id": g["app_name"], "title": g["app_title"],
                          "card": _sized(_epic_image(meta, "DieselGameBox"), 480, 270),
                          "version": (win or {}).get("build_version", ""), "note": note})
    elif store == "gog":
        token = _gog_token()
        page = 1
        while True:
            d = _get_json(f"https://embed.gog.com/account/getFilteredProducts?mediaType=1&page={page}", token)
            for p in d.get("products", []):
                img = p.get("image") or ""
                games.append({"id": str(p["id"]), "title": p["title"],
                              "card": f"https:{img}_392.jpg" if img else "",
                              "note": "" if (p.get("worksOn") or {}).get("Windows") else "No Windows version"})
            if page >= d.get("totalPages", 1):
                break
            page += 1
    else:
        r = _run("nile", "library", "sync", timeout=300)
        if r.returncode != 0:
            raise RuntimeError("nile couldn't sync your Amazon games")
        for g in _read_json(os.path.join(NILE, "library.json"), []):
            p = g.get("product") or {}
            det = (p.get("productDetail") or {}).get("details") or {}
            games.append({"id": p.get("id"), "title": p.get("title") or "?",
                          "card": det.get("backgroundUrl1") or det.get("pgCrownImageUrl") or "", "note": ""})
        r = _run("nile", "list-updates", "--json", quiet=True)
        try:
            updates = set(json.loads(r.stdout or "[]"))
        except ValueError:
            updates = set()
        for g in games:
            g["update"] = g["id"] in updates
    games.sort(key=lambda g: g["title"].lower())
    return games


def _installed(store: str) -> dict:
    """id -> {"path", "version"} of the store's installed games."""
    if store == "epic":
        return {k: {"path": v.get("install_path"), "version": v.get("version", "")} for k, v in _epic_installed().items()
                if not v.get("is_dlc")}
    if store == "gog":
        return {g["appName"]: {"path": g.get("install_path"), "version": g.get("buildId", "")} for g in _gog_installed()
                if not g.get("is_dlc")}
    return {g["id"]: {"path": g.get("path"), "version": g.get("version", "")} for g in _amazon_installed()}


def _shortcut_info(store: str, gid: str) -> dict:
    """What the Steam shortcut starts: the game's .exe and the folder it starts in."""
    if store == "epic":
        g = _epic_installed().get(gid)
        if not g:
            raise RuntimeError("not installed")
        exe = os.path.join(g["install_path"], g["executable"].replace("\\", "/"))
        return {"title": g.get("title") or gid, "exe": exe, "dir": g["install_path"]}
    if store == "gog":
        g = next((g for g in _gog_installed() if g["appName"] == gid), None)
        if not g:
            raise RuntimeError("not installed")
        path = g["install_path"]
        info = _read_json(os.path.join(path, f"goggame-{gid}.info"), {})
        task = next((t for t in info.get("playTasks", []) if t.get("isPrimary")), None)
        if not task or not task.get("path"):
            raise RuntimeError("the game has no play task to start")
        exe = os.path.join(path, task["path"].replace("\\", "/"))
        wd = task.get("workingDir")
        return {"title": info.get("name") or g.get("title") or gid, "exe": exe,
                "dir": os.path.join(path, wd.replace("\\", "/")) if wd else os.path.dirname(exe)}
    g = next((g for g in _amazon_installed() if g["id"] == gid), None)
    if not g:
        raise RuntimeError("not installed")
    fuel = _read_json(os.path.join(g["path"], "fuel.json"), {}).get("Main") or {}
    if not fuel.get("Command"):
        raise RuntimeError("the game has no fuel.json command")
    exe = os.path.join(g["path"], fuel["Command"].replace("\\", "/"))
    wd = fuel.get("WorkingSubdirOverride")
    title = next(((x.get("product") or {}).get("title") for x in _read_json(os.path.join(NILE, "library.json"), [])
                  if (x.get("product") or {}).get("id") == gid), None)
    return {"title": title or gid, "exe": exe,
            "dir": os.path.join(g["path"], wd.replace("\\", "/")) if wd else g["path"]}


def _gamesdb(gid: str, platform: str = "gog") -> dict:
    """GOG's game database entry (artwork, details), or {}. It knows Epic games too, by app name."""
    try:
        return _get_json(f"https://gamesdb.gog.com/platforms/{platform}/external_releases/{gid}").get("game") or {}
    except Exception:
        return {}


def _text(v) -> str:
    """A game database string: plain, or by language ("*" the default)."""
    if isinstance(v, dict):
        return v.get("en-US") or v.get("*") or next(iter(v.values()), "")
    return v or ""


def _details(store: str, gid: str) -> dict:
    """What the game's page shows under its buttons: summary, developer, publisher, release date
    (YYYY-MM-DD), genres and play modes. From GOG's game database for Epic and GOG games, from
    Amazon's library for Amazon's."""
    if store == "amazon":
        p = next(((x.get("product") or {}) for x in _read_json(os.path.join(NILE, "library.json"), [])
                  if (x.get("product") or {}).get("id") == gid), {})
        d = (p.get("productDetail") or {}).get("details") or {}
        return {"summary": p.get("description") or "", "developer": d.get("developer") or "",
                "publisher": d.get("publisher") or "", "released": (d.get("releaseDate") or "")[:10],
                "genres": d.get("genres") or [], "modes": d.get("gameModes") or []}
    db = _gamesdb(gid, "epic" if store == "epic" else "gog")
    out = {"summary": _text(db.get("summary")).strip(),
           "developer": ", ".join(x.get("name", "") for x in db.get("developers") or []),
           "publisher": ", ".join(x.get("name", "") for x in db.get("publishers") or []),
           "released": (db.get("first_release_date") or "")[:10],
           "genres": [_text(x.get("name")) for x in db.get("genres") or []],
           "modes": [_text(x.get("name")) for x in db.get("game_modes") or []]}
    if store == "epic" and not out["developer"]:
        meta = _read_json(os.path.join(LEGENDARY, "metadata", f"{gid}.json"), {}).get("metadata") or {}
        out["developer"] = meta.get("developer") or ""
    return out


def _art_urls(store: str, gid: str) -> dict:
    """Steam artwork for the shortcut, by SetCustomArtworkForApp's asset type:
    0 grid (portrait), 1 hero, 2 logo, 3 wide grid."""
    if store == "epic":
        lib = _read_json(os.path.join(LEGENDARY, "metadata", f"{gid}.json"), {}).get("metadata") or {}
        tall, wide = _epic_image(lib, "DieselGameBoxTall"), _epic_image(lib, "DieselGameBox")
        return {0: _sized(tall, 600, 900), 1: _sized(wide, 1920, 620), 2: _epic_image(lib, "DieselGameBoxLogo"),
                3: _sized(wide, 920, 430)}
    if store == "gog":
        db = _gamesdb(gid)
        url = lambda k: ((db.get(k) or {}).get("url_format") or "").replace("{formatter}", "").replace("{ext}", "jpg")
        logo = ((db.get("logo") or {}).get("url_format") or "").replace("{formatter}", "").replace("{ext}", "png")
        return {0: url("vertical_cover"), 1: url("background"), 2: logo, 3: url("background")}
    lib = next((x.get("product") or {} for x in _read_json(os.path.join(NILE, "library.json"), [])
                if (x.get("product") or {}).get("id") == gid), {})
    det = (lib.get("productDetail") or {}).get("details") or {}
    return {1: det.get("backgroundUrl1", ""), 2: det.get("logoUrl", ""),
            3: det.get("pgCrownImageUrl") or det.get("backgroundUrl2", "")}


def _art(store: str, gid: str) -> dict:
    out = {}
    for kind, url in _art_urls(store, gid).items():
        if not url:
            continue
        try:
            data = _get(url)
        except Exception as e:
            decky.logger.info("stores: artwork %s: %s", url, e)
            continue
        ext = "png" if data[:4] == b"\x89PNG" else "jpg"
        out[str(kind)] = {"data": base64.b64encode(data).decode(), "ext": ext}
    return out


def _size_info(store: str, gid: str) -> dict:
    """Download and install size, and for an installed GOG game whether a newer build is out."""
    if store == "epic":
        r = _run("legendary", "info", gid, "--json", timeout=120)
        m = (json.loads(r.stdout).get("manifest") or {}) if r.returncode == 0 else {}
        return {"download": m.get("download_size") or 0, "disk": m.get("disk_size") or 0}
    if store == "gog":
        r = _run("gogdl", "--auth-config-path", GOG_AUTH, "info", gid, "--platform", "windows", timeout=120, quiet=True)
        line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("{")), "")
        if r.returncode != 0 or not line:
            raise RuntimeError("couldn't get the game's details from GOG")
        d = json.loads(line)
        size = d.get("size", {})
        lang = size.get("en-US") or next((v for k, v in size.items() if k != "*"), {})
        common = size.get("*", {})
        out = {"download": lang.get("download_size", 0) + common.get("download_size", 0),
               "disk": lang.get("disk_size", 0) + common.get("disk_size", 0)}
        g = next((g for g in _gog_installed() if g["appName"] == gid), None)
        if g and d.get("buildId"):
            out["update"] = d["buildId"] != g.get("buildId")
        return out
    r = _run("nile", "install", gid, "--info", "--json", timeout=120)
    try:
        return {"download": json.loads(r.stdout.strip().splitlines()[-1]).get("download_size", 0), "disk": 0}
    except (ValueError, IndexError):
        return {"download": 0, "disk": 0}


# --- install jobs ------------------------------------------------------------------------------

def _job_command(job: dict, base: str) -> list[str]:
    store, gid, kind = job["store"], job["id"], job["kind"]
    if store == "epic":
        return ["legendary", "-y", "update" if kind == "update" else "install", gid, "--base-path", base, "--skip-sdl"]
    if store == "gog":
        auth = ["gogdl", "--auth-config-path", GOG_AUTH]
        if kind == "update":
            g = next(g for g in _gog_installed() if g["appName"] == gid)
            return auth + ["update", gid, "--platform", "windows", "--path", g["install_path"], "--lang",
                           g.get("language") or "en-US", "--skip-dlcs"]
        return auth + ["download", gid, "--platform", "windows", "--path", base, "--lang", "en-US", "--skip-dlcs"]
    if kind == "update":
        return ["nile", "update", gid]
    return ["nile", "install", gid, "--base-path", base]


def _gog_manifest(gid: str) -> str:
    return os.path.join(GOGDL, "heroic_gogdl", "manifests", gid)


def _start_job(job: dict, base: str):
    os.makedirs(base, exist_ok=True)
    if job["store"] == "gog" and job["kind"] == "install" and job["id"] not in _installed("gog"):
        # a manifest left from a game deleted by hand makes gogdl think it's installed ("Nothing to do")
        try:
            os.remove(_gog_manifest(job["id"]))
        except FileNotFoundError:
            pass
    with open(JOB_LOG, "w"):
        pass
    env = _env()
    subprocess.run(["systemctl", "--user", "reset-failed", UNIT], env=env, capture_output=True)
    cmd = ["systemd-run", "--user", "--unit", UNIT, "--collect", "--quiet", "-p", "Nice=10",
           "-p", "IOSchedulingClass=best-effort", "-p", "IOSchedulingPriority=7",
           f"--setenv=LEGENDARY_CONFIG_PATH={LEGENDARY}", f"--setenv=NILE_CONFIG_PATH={NILE_ROOT}",
           f"--setenv=GOGDL_CONFIG_PATH={GOGDL}",
           "--", "bash", "-c", f'"$@" >>"$0" 2>&1; echo "{EXIT_MARK} $?" >>"$0"', JOB_LOG, *_job_command(job, base)]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"couldn't start the download: {r.stderr.strip()}")


def _job_running() -> bool:
    r = subprocess.run(["systemctl", "--user", "is-active", UNIT], env=_env(), capture_output=True, text=True)
    return r.stdout.strip() in ("active", "activating", "deactivating")


def _log_tail(n: int = 16384) -> str:
    try:
        with open(JOB_LOG, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def _progress(log: str) -> dict:
    """What the store tool last reported: percent done, ETA, download speed (MiB/s)."""
    pct = re.findall(r"Progress: ([\d.]+)", log)
    eta = re.findall(r"ETA: ([\d:]+)", log)
    speed = re.findall(r"\+ Download\s*-\s*([\d.]+) MiB/s", log)
    return {"percent": float(pct[-1]) if pct else 0.0, "eta": eta[-1] if eta else "",
            "speed": float(speed[-1]) if speed else 0.0}


def _job_exit(log: str) -> int | None:
    m = re.findall(rf"{EXIT_MARK} (\d+)", log)
    return int(m[-1]) if m else None


def _error_text(log: str) -> str:
    lines = [l for l in log.splitlines() if l.strip() and EXIT_MARK not in l]
    errors = [l for l in lines if "ERROR" in l or "Error" in l or "error:" in l]
    return (errors or lines or ["no output"])[-1][-300:]


def _gog_record(gid: str, base: str, kind: str):
    """Heroic's record of a GOG install (gogdl keeps none), added or brought up to date."""
    r = _run("gogdl", "--auth-config-path", GOG_AUTH, "info", gid, "--platform", "windows", timeout=120, quiet=True)
    line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("{")), "{}")
    info = json.loads(line)
    data = _read_json(GOG_INSTALLED, {})
    installed = data.get("installed", [])
    old = next((g for g in installed if g["appName"] == gid), None)
    path = old["install_path"] if old else os.path.join(base, info.get("folder_name") or gid)
    if not os.path.exists(os.path.join(path, f"goggame-{gid}.info")):
        raise RuntimeError(f"gogdl finished, but the game isn't in {path}")
    size = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                size += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    entry = {"platform": "windows", "executable": "", "install_path": path,
             "install_size": f"{size / 2**30:.2f} GiB" if size >= 2**30 else f"{size / 2**20:.2f} MiB",
             "is_dlc": False, "version": info.get("versionName") or "", "appName": gid, "installedDLCs": [],
             "language": (old or {}).get("language") or "en-US", "versionEtag": info.get("versionEtag") or "",
             "buildId": info.get("buildId") or "", "pinnedVersion": False}
    data["installed"] = [g for g in installed if g["appName"] != gid] + [entry]
    _write_json(GOG_INSTALLED, data)


def _uninstall(store: str, gid: str):
    if store == "epic":
        r = _run("legendary", "-y", "uninstall", gid, timeout=600)
        if r.returncode != 0:
            raise RuntimeError("legendary couldn't uninstall the game")
    elif store == "gog":
        data = _read_json(GOG_INSTALLED, {})
        g = next((g for g in data.get("installed", []) if g["appName"] == gid), None)
        if g and g.get("install_path") and os.path.isdir(g["install_path"]):
            shutil.rmtree(g["install_path"])
        data["installed"] = [x for x in data.get("installed", []) if x["appName"] != gid]
        _write_json(GOG_INSTALLED, data)
        try:  # as Heroic does: else gogdl would patch the game that isn't there next time
            os.remove(_gog_manifest(gid))
        except FileNotFoundError:
            pass
    else:
        r = _run("nile", "uninstall", gid, timeout=600)
        if r.returncode != 0:
            raise RuntimeError("nile couldn't uninstall the game")


def _locations() -> list[dict]:
    """Where games can go: the home folder and each mounted SD card or USB drive."""
    out = [{"path": DEFAULT_DIR, "label": "Internal storage"}]
    for m in sorted(glob.glob("/run/media/*/*")):
        if os.path.ismount(m) and os.access(m, os.W_OK):
            out.append({"path": os.path.join(m, "Games", "Heroic"), "label": os.path.basename(m)})
    for o in out:
        try:
            st = os.statvfs(os.path.dirname(o["path"]) if not os.path.exists(o["path"]) else o["path"])
            o["free"] = st.f_bavail * st.f_frsize
        except OSError:
            o["free"] = 0
    return out


class Plugin:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.login = {"store": None, "state": "idle", "error": ""}
        self.login_task = None
        self.login_cancel = False
        self.details_cache = {}

    def _state(self) -> dict:
        return _read_json(STATE, {"shortcuts": {}, "pending": [], "queue": [], "job": None})

    def _save(self, s: dict):
        _write_json(STATE, s)

    # signing in

    async def status(self) -> dict:
        """Who's signed in where, the running download and the queue."""
        s = self._state()
        job = s.get("job")
        if job:
            job = dict(job, **_progress(_log_tail()))
        return {"users": _users(), "job": job, "queue": s.get("queue", []), "login": self.login}

    async def login_start(self, store: str) -> str:
        """The store's login page (the frontend opens it in Steam's browser); a task waits for the sign-in."""
        if self.login_task and not self.login_task.done():
            self.login_cancel = True
            await asyncio.wait([self.login_task], timeout=2)
        amazon = None
        if store == "amazon":
            r = await asyncio.to_thread(_run, "nile", "auth", "--login", "--non-interactive")
            amazon = json.loads(r.stdout)
            url = amazon["url"]
        else:
            url = EPIC_LOGIN if store == "epic" else GOG_LOGIN
        await asyncio.to_thread(_blank_redirects)
        self.login_cancel = False
        self.login = {"store": store, "state": "waiting", "error": ""}
        self.login_task = asyncio.get_running_loop().create_task(self._watch_login(store, amazon))
        return url

    async def _watch_login(self, store: str, amazon: dict | None):
        try:
            await asyncio.to_thread(_login, store, amazon, lambda: self.login_cancel)
            self.login = {"store": store, "state": "done", "error": ""}
            decky.logger.info("stores: signed in to %s", store)
            await decky.emit("login", store, True, "")
        except Exception as e:
            self.login = {"store": store, "state": "failed", "error": str(e)}
            decky.logger.warning("stores: %s sign-in: %s", store, e)
            if str(e) != "cancelled":
                await decky.emit("login", store, False, str(e))

    async def login_cancel_wait(self):
        self.login_cancel = True

    async def logout(self, store: str):
        await asyncio.to_thread(_logout, store)

    # libraries

    async def library(self, store: str, refresh: bool) -> dict:
        """The store's games ({"games", "fetched"}); from the cache unless refresh or it's a day old."""
        path = os.path.join(SETTINGS, f"library-{store}.json")
        cache = _read_json(path, None)
        if refresh or not cache or time.time() - cache.get("fetched", 0) > 86400:
            games = await asyncio.to_thread(_fetch_library, store)
            cache = {"games": games, "fetched": time.time()}
            _write_json(path, cache)
        installed = await asyncio.to_thread(_installed, store)
        s = self._state()
        busy = {(j["store"], j["id"]): j["kind"] for j in s.get("queue", []) + ([s["job"]] if s.get("job") else [])}
        games = []
        for g in cache["games"]:
            i = installed.get(g["id"])
            g = dict(g, installed=bool(i), appid=s["shortcuts"].get(f"{store}:{g['id']}"),
                     busy=busy.get((store, g["id"])))
            if i and store == "epic":
                g["update"] = bool(g.get("version")) and i["version"] != g["version"]
            g["update"] = bool(i) and bool(g.get("update"))
            games.append(g)
        return {"games": games, "fetched": cache["fetched"]}

    async def game_info(self, store: str, gid: str) -> dict:
        info = await asyncio.to_thread(_size_info, store, gid)
        info["installed"] = (await asyncio.to_thread(_installed, store)).get(gid)
        return info

    async def details(self, store: str, gid: str) -> dict:
        key = f"{store}:{gid}"
        if key not in self.details_cache:
            self.details_cache[key] = await asyncio.to_thread(_details, store, gid)
        return self.details_cache[key]

    async def locations(self) -> dict:
        return {"locations": await asyncio.to_thread(_locations),
                "current": self._state().get("install_dir") or DEFAULT_DIR}

    async def set_location(self, path: str):
        async with self.lock:
            s = self._state()
            s["install_dir"] = path
            self._save(s)

    # installing

    async def install(self, store: str, gid: str, title: str, kind: str):
        """Queues an install or update ("install"|"update"); the main loop starts it."""
        async with self.lock:
            s = self._state()
            if any(j["store"] == store and j["id"] == gid for j in s["queue"] + ([s["job"]] if s.get("job") else [])):
                return
            s["queue"].append({"store": store, "id": gid, "title": title, "kind": kind})
            self._save(s)
        await self._next()

    async def cancel(self, store: str, gid: str):
        """Takes a game off the queue, or stops its running download (it resumes if started again)."""
        async with self.lock:
            s = self._state()
            s["queue"] = [j for j in s["queue"] if not (j["store"] == store and j["id"] == gid)]
            job = s.get("job")
            stop = job and job["store"] == store and job["id"] == gid
            if stop:
                s["job"] = None
            self._save(s)
        if stop:
            await asyncio.to_thread(subprocess.run, ["systemctl", "--user", "stop", UNIT], env=_env(),
                                    capture_output=True)
            await self._next()

    async def uninstall(self, store: str, gid: str) -> int | None:
        """Removes the game; returns its Steam shortcut's appid for the frontend to remove."""
        await asyncio.to_thread(_uninstall, store, gid)
        async with self.lock:
            s = self._state()
            appid = s["shortcuts"].pop(f"{store}:{gid}", None)
            s["pending"] = [k for k in s["pending"] if k != f"{store}:{gid}"]
            self._save(s)
        return appid

    # Steam shortcuts (added by the frontend)

    async def shortcut_info(self, store: str, gid: str) -> dict:
        info = await asyncio.to_thread(_shortcut_info, store, gid)
        info["launch"] = f"{WRAPPER} {store} {gid} %command%"
        return info

    async def artwork(self, store: str, gid: str) -> dict:
        return await asyncio.to_thread(_art, store, gid)

    async def remember_shortcut(self, store: str, gid: str, appid: int):
        async with self.lock:
            s = self._state()
            key = f"{store}:{gid}"
            if appid:
                s["shortcuts"][key] = int(appid)
            else:
                s["shortcuts"].pop(key, None)
            s["pending"] = [k for k in s["pending"] if k != key]
            self._save(s)

    async def pending(self) -> list[dict]:
        """Installs finished without a shortcut yet (the frontend wasn't listening then)."""
        out = []
        for k in self._state().get("pending", []):
            store, gid = k.split(":", 1)
            if gid in await asyncio.to_thread(_installed, store):
                out.append({"store": store, "id": gid})
        return out

    # the loop

    async def _next(self):
        """Starts the next queued job when none is running."""
        async with self.lock:
            s = self._state()
            if s.get("job") or not s["queue"]:
                return
            job = s["queue"].pop(0)
            base = s.get("install_dir") or DEFAULT_DIR
            try:
                await asyncio.to_thread(_start_job, job, base)
            except Exception as e:
                self._save(s)
                decky.logger.error("stores: %s", e)
                await decky.emit("job", job, False, str(e))
                return
            s["job"] = dict(job, base=base, started=time.time())
            self._save(s)
            decky.logger.info("stores: %s %s:%s", job["kind"], job["store"], job["id"])

    async def _finish(self):
        """A running job that has ended: record it, tell the frontend, start the next."""
        s = self._state()
        job = s.get("job")
        if not job or await asyncio.to_thread(_job_running):
            return
        log = _log_tail()
        code = _job_exit(log)
        ok = code == 0
        error = "" if ok else (_error_text(log) if code is not None else "the download stopped")
        if ok and job["store"] == "gog":
            try:
                await asyncio.to_thread(_gog_record, job["id"], job["base"], job["kind"])
            except Exception as e:
                ok, error = False, f"couldn't record the install: {e}"
        async with self.lock:
            s = self._state()
            s["job"] = None
            key = f"{job['store']}:{job['id']}"
            if ok and job["kind"] == "install" and key not in s["pending"]:
                s["pending"].append(key)
            self._save(s)
        decky.logger.info("stores: %s %s: %s", job["kind"], job["id"], "done" if ok else error)
        await decky.emit("job", job, ok, error)
        await self._next()

    async def _main(self):
        os.makedirs(SETTINGS, exist_ok=True)
        while True:
            try:
                await self._finish()
                await self._next()
            except Exception as e:
                decky.logger.error("stores: loop: %s", e)
            await asyncio.sleep(2)

    async def _unload(self):
        # running downloads carry on (a user unit); _main picks them up again
        self.login_cancel = True
