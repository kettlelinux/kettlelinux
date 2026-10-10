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
# Flathub: the apps Flathub builds for ARM64 (its search API, filtered to aarch64), browsed by
# category or searched, installed for the user (flatpak --user, the installation the Welcome
# plugin's Gaming Extras uses) through the same job queue, and added to Steam as native shortcuts
# (`flatpak run <id>`, no Proton). Its jobs, shortcuts and pending entries use the store name
# "flathub"; it has no sign-in.
#
# Battle.net: Blizzard's launcher, added to Steam with Proton-CachyOS and its installer started, by
# kettle-welcome's welcome-battlenet (the desktop's Kettle Welcome uses it too, so both show the
# same Steam entry); its status also switches the entry to the installed launcher. It was in
# Welcome's Gaming Extras up to 1.12.0-39.
#
# Android games, with kettle-lepton (where it's installed): kettle-android-games adds F-Droid apps
# and APK files to Steam, one command at a time; its download progress comes on stderr. Google
# Play is left to the desktop's Kettle Welcome: signing in to it goes through Firefox.
#
# State (stores.json in the plugin's settings dir):
#   shortcuts  "<store>:<id>" -> the Steam shortcut's appid
#   pending    installs finished while the frontend wasn't listening: it adds their shortcuts
#   queue      waiting installs and updates: {"store", "id", "title", "kind": "install"|"update"}
#   job        the one running (same fields)
#   install_dir  where new games go (default ~/Games/Heroic, Heroic's default)
#   cloud_saves  false: kettle-store-run doesn't sync saves (it reads this file; default on)
import asyncio, base64, contextlib, fcntl, glob, html, json, os, re, shlex, shutil, subprocess, time, urllib.parse, urllib.request

import decky
import cdp
import steamlib

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
SOURCES = STORES + ("flathub",)
NAMES = {"epic": "Epic Games", "gog": "GOG", "amazon": "Amazon Games"}
# the store's game IDs (legendary's app names, GOG's product ids, Amazon's amzn1.adg.product.<uuid>):
# they go into launch options Steam runs through a shell, and into file names
GAME_ID = {"epic": re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"), "gog": re.compile(r"[0-9]{1,20}"),
           "amazon": re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")}
# what other plugins keep per game, by Steam appid (forgotten with a store game's shortcut)
DECKY_SETTINGS = os.path.dirname(decky.DECKY_PLUGIN_SETTINGS_DIR)

EPIC_LOGIN = ("https://www.epicgames.com/id/login?redirectUrl=" + urllib.parse.quote(
    "https://www.epicgames.com/id/api/redirect?clientId=34a02cf8f4414e29b15921876da36f9a&responseType=code", safe=""))
EPIC_REDIRECT = "https://www.epicgames.com/id/api/redirect"
GOG_LOGIN = ("https://auth.gog.com/auth?client_id=46899977096215655&redirect_uri="
             "https%3A%2F%2Fembed.gog.com%2Fon_login_success%3Forigin%3Dclient&response_type=code&layout=galaxy")
GOG_REDIRECT = "https://embed.gog.com/on_login_success"
AMAZON_CODE = "openid.oa2.authorization_code="
LOGIN_TIMEOUT = 600

BATTLENET = "/usr/lib/kettle/welcome-battlenet"  # package kettle-welcome
ANDROID = "/usr/bin/kettle-android-games"  # package kettle-lepton
_ANDROID_COMMANDS = ("add", "remove", "fdroid-search", "fdroid-add")
# the running or last kettle-android-games command: {"command", "busy", "done", "total", "result"}
_android: dict = {"command": None, "busy": False, "done": 0, "total": 0, "result": None}

FLATHUB_API = "https://flathub.org/api/v2"
# points Flathub's RetroArch at libretro's aarch64 cores (device/common/overlay)
RETROARCH_CORES = "/usr/lib/kettle/retroarch-cores"
FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"
FLATHUB_ICON = "https://dl.flathub.org/repo/appstream/aarch64/icons/128x128/{}.png"
FLATHUB_PAGE = 48
# Flathub's browse categories: search filters (all: the whole of Flathub)
# the Flathub tab's categories: Flathub's own main categories and its games' subcategories (the
# frontend's CATEGORIES has their names), each a search filter
_GAME_GENRES = ("ActionGame", "AdventureGame", "ArcadeGame", "BoardGame", "CardGame", "KidsGame", "LogicGame",
                "RolePlaying", "Shooter", "Simulation", "SportsGame", "StrategyGame")
_APP_CATEGORIES = ("audiovideo", "graphics", "network", "office", "development", "education", "science", "system",
                   "utility")
FLATHUB_CATEGORIES = {"games": [("main_categories", "game")], "emulators": [("sub_categories", "Emulator")], "all": [],
                      **{g: [("sub_categories", g)] for g in _GAME_GENRES},
                      **{c: [("main_categories", c)] for c in _APP_CATEGORIES}}
APP_ID = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)+$")
FLATPAK = "/usr/bin/flatpak"
FLATPAK_ICONS = os.path.join(HOME, ".local", "share", "flatpak", "exports", "share", "icons", "hicolor")


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


@contextlib.contextmanager
def _heroic_lock(path: str):
    """Holds a lock file next to one of Heroic's files while it's read, changed and written back
    (kettle-store-run reads them too). Heroic itself doesn't lock them: best effort."""
    f = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f = open(path + ".kettle-lock", "a")
        fcntl.flock(f, fcntl.LOCK_EX)
    except OSError as e:
        decky.logger.warning("stores: no lock for %s: %s", path, e)
    try:
        yield
    finally:
        if f:
            f.close()  # releases the lock


def _store(store, sources=SOURCES) -> str:
    if store not in sources:
        raise ValueError(f"unknown store: {store!r}")
    return store


def _gid(store: str, gid) -> str:
    """The game's ID, checked for its store."""
    if store == "flathub":
        return _app_id(gid)
    if not isinstance(gid, str) or not GAME_ID[store].fullmatch(gid):
        raise ValueError(f"not a {NAMES[store]} game ID: {gid!r}")
    return gid


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
        user = None
        try:
            user = _get_json("https://embed.gog.com/userData.json", _gog_token())
        except Exception as e:
            decky.logger.warning("stores: GOG user data: %s", e)
        with _heroic_lock(GOG_CONFIG):
            conf = _read_json(GOG_CONFIG, {})
            if user is not None:
                conf["userData"] = user
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
        with _heroic_lock(GOG_CONFIG):
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
                          "version": (win or {}).get("build_version", ""), "note": note,
                          "dlc": [d.get("app_title") or d.get("app_name") for d in g.get("dlcs") or []]})
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
    if store == "flathub":
        return {k: {"path": "", "version": v["version"]} for k, v in _flatpak_list().items()}
    if store == "epic":
        return {k: {"path": v.get("install_path"), "version": v.get("version", "")} for k, v in _epic_installed().items()
                if not v.get("is_dlc")}
    if store == "gog":
        return {g["appName"]: {"path": g.get("install_path"), "version": g.get("buildId", "")} for g in _gog_installed()
                if not g.get("is_dlc")}
    return {g["id"]: {"path": g.get("path"), "version": g.get("version", "")} for g in _amazon_installed()}


def _shortcut_info(store: str, gid: str) -> dict:
    """What the Steam shortcut starts: the game's .exe and the folder it starts in (Flathub: flatpak
    itself, started natively with the app's icon)."""
    if store == "flathub":
        app = _flatpak_list().get(gid)
        if not app:
            raise RuntimeError("not installed")
        return {"title": app["title"], "exe": FLATPAK, "dir": "", "native": True, "icon": _flatpak_icon(gid)}
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
    if store == "flathub":  # AppStream has no cover art: the first screenshot
        shot = next(iter(_screenshots(_flathub_appstream(gid), 1920)), "")
        return {1: shot, 3: shot}
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
               "disk": lang.get("disk_size", 0) + common.get("disk_size", 0),
               "dlc": [x.get("title") or str(x.get("id")) for x in d.get("dlcs") or []]}
        g = next((g for g in _gog_installed() if g["appName"] == gid), None)
        if g and d.get("buildId"):
            out["update"] = d["buildId"] != g.get("buildId")
        return out
    r = _run("nile", "install", gid, "--info", "--json", timeout=120)
    try:
        return {"download": json.loads(r.stdout.strip().splitlines()[-1]).get("download_size", 0), "disk": 0}
    except (ValueError, IndexError):
        return {"download": 0, "disk": 0}


# --- Flathub -----------------------------------------------------------------------------------

def _app_id(app: str) -> str:
    if not isinstance(app, str) or not APP_ID.fullmatch(app):
        raise ValueError(f"not a Flatpak app ID: {app!r}")
    return app


def _post_json(url: str, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"User-Agent": "Kettle-Game-Stores", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read(16 << 20))


def _flathub_search(category: str, query: str, page: int) -> dict:
    """A page of Flathub's apps with an ARM64 build, most installed first (a thread; network)."""
    filters = [("arches", "aarch64"), ("type", "desktop-application")] + FLATHUB_CATEGORIES[category]
    d = _post_json(f"{FLATHUB_API}/search", {"query": query.strip(), "page": page, "hits_per_page": FLATHUB_PAGE,
                                             "filters": [{"filterType": k, "value": v} for k, v in filters]})
    apps = [{"id": h["app_id"], "title": h.get("name") or h["app_id"], "summary": h.get("summary") or "",
             "icon": h.get("icon") or "", "developer": h.get("developer_name") or "",
             "verified": bool(h.get("verification_verified"))} for h in d.get("hits", []) if h.get("app_id")]
    return {"apps": apps, "pages": d.get("totalPages", 1), "total": d.get("totalHits", len(apps))}


def _flatpak_list() -> dict:
    """id -> {"title", "version", "origin", "installation"} of the installed Flatpak apps (both
    installations: one Discover installed for all users can't be removed from here)."""
    r = _run(FLATPAK, "list", "--app", "--columns=application,name,version,origin,installation", quiet=True)
    out = {}
    for line in r.stdout.splitlines():
        f = line.split("\t")
        if len(f) == 5 and (f[0] not in out or f[4] == "user"):  # in both: the user's counts
            out[f[0]] = {"title": f[1] or f[0], "version": f[2], "origin": f[3], "installation": f[4]}
    return out


_updates = {"at": 0.0, "apps": set()}


def _flatpak_updates() -> set:
    """The user's Flatpak apps with an update out (network: kept 10 minutes)."""
    if time.time() - _updates["at"] > 600:
        r = _run(FLATPAK, "remote-ls", "--user", "--updates", "--app", "--columns=application", timeout=120, quiet=True)
        if r.returncode == 0:
            _updates.update(at=time.time(), apps=set(r.stdout.split()))
    return _updates["apps"]


def _flathub_installed() -> list[dict]:
    """The installed Flatpak apps, as the Flathub tab lists them."""
    return sorted(({"id": k, "title": v["title"], "summary": f"{v['version']} · {v['origin']}".strip(" ·"),
                    "icon": FLATHUB_ICON.format(k) if v["origin"] == "flathub" else "", "developer": "",
                    "verified": False} for k, v in _flatpak_list().items()), key=lambda a: a["title"].lower())


def _flathub_appstream(app: str) -> dict:
    try:
        return _get_json(f"{FLATHUB_API}/appstream/{app}") or {}
    except Exception:
        return {}


def _plain(markup: str) -> str:
    """AppStream's description markup (<p>, <ul><li>, <em>, <code>) as plain text."""
    s = re.sub(r"\s+", " ", markup or "")  # the source's own line breaks mean nothing
    s = re.sub(r"\s*<li>\s*", "\n• ", s)
    s = re.sub(r"\s*</(?:p|ul|ol)>\s*", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = "\n".join(l.strip() for l in s.splitlines())
    return re.sub(r"\n{3,}", "\n\n", html.unescape(s)).strip()


def _screenshots(a: dict, width: int = 752) -> list[str]:
    """The app's screenshots, in the size nearest width each."""
    out = []
    for sh in a.get("screenshots") or []:
        sizes = [x for x in sh.get("sizes") or [] if x.get("src")]
        if sizes:
            out.append(min(sizes, key=lambda x: abs(int(x.get("width") or 0) - width))["src"])
    return out


def _flathub_app(app: str) -> dict:
    """What the app's page shows: Flathub's AppStream data and sizes, and the app installed here."""
    a = _flathub_appstream(app)
    try:
        summary = _get_json(f"{FLATHUB_API}/summary/{app}") or {}
    except Exception:
        summary = {}
    installed = _flatpak_list().get(app)
    if not a and not installed:
        raise RuntimeError("Flathub doesn't know this app")
    release = next(iter(a.get("releases") or []), {})
    urls = a.get("urls") or {}
    return {"id": app, "title": a.get("name") or (installed or {}).get("title") or app,
            "summary": a.get("summary") or "", "description": _plain(a.get("description") or ""),
            "icon": a.get("icon") or (FLATHUB_ICON.format(app) if a else ""),
            "developer": a.get("developer_name") or "", "license": a.get("project_license") or "",
            "free": a.get("is_free_license") is not False, "homepage": urls.get("homepage") or "",
            "verified": bool((a.get("metadata") or {}).get("flathub::verification::verified")),
            "version": release.get("version") or "", "screenshots": _screenshots(a)[:4],
            "arm64": "aarch64" in (summary.get("arches") or ["aarch64"]),
            # Flathub's sizes are its x86_64 build's: near enough for ARM64's
            "download": summary.get("download_size") or 0, "disk": summary.get("installed_size") or 0,
            "installed": installed, "update": bool(installed) and app in _flatpak_updates()}


def _flatpak_icon(app: str) -> str:
    """A PNG icon for the app's Steam shortcut: its largest exported one, unless Flathub's (saved)
    is bigger (some apps export only a 48px PNG next to their SVG)."""
    best = (0, "")
    try:
        sizes = os.listdir(FLATPAK_ICONS)
    except OSError:
        sizes = []
    for d in sizes:
        path = os.path.join(FLATPAK_ICONS, d, "apps", app + ".png")
        px = int(d.split("x")[0]) if re.fullmatch(r"\d+x\d+", d) else 0
        if px > best[0] and os.path.isfile(path):
            best = (px, path)
    if best[0] >= 128:
        return best[1]
    path = os.path.join(SETTINGS, "icons", app + ".png")
    try:
        data = _get(FLATHUB_ICON.format(app))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception:
        return best[1]


def _flathub_shortcut(app: str) -> int | None:
    """A Steam shortcut someone already made for the app (the Welcome plugin's Gaming Extras)."""
    for s in steamlib.shortcuts():
        args = s.get("launch", "").split()
        if os.path.basename(s["exe"]) == "flatpak" and "run" in args and app in args:
            return s["appid"]
    return None


# --- install jobs ------------------------------------------------------------------------------

def _job_commands(job: dict, base: str) -> list[list[str]]:
    """The job's commands, run one after the other (GOG: then the redistributables the game needs)."""
    main = _job_command(job, base)
    if job["store"] == "flathub" and job["kind"] == "install":
        add = [FLATPAK, "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_REPO]
        if job["id"] == "org.libretro.RetroArch" and os.access(RETROARCH_CORES, os.X_OK):
            # before its first start, so its core downloader works from the outset
            return [add, main, ["sh", "-c", f"{RETROARCH_CORES} || true"]]
        return [add, main]
    if job["store"] == "gog":
        return [main, [WRAPPER, "gog-redist", job["id"]]]
    return [main]


def _job_command(job: dict, base: str) -> list[str]:
    store, gid, kind = job["store"], job["id"], job["kind"]
    if store == "flathub":
        # in English, and not --noninteractive (that prints no progress): _flatpak_progress reads
        # its lines; -y answers its questions, and one it can't reads the job's empty stdin and fails
        flatpak = ["env", "LC_ALL=C.UTF-8", FLATPAK]
        if kind == "update":
            return flatpak + ["update", "--user", "-y", gid]
        return flatpak + ["install", "--user", "-y", "flathub", gid]
    if store == "epic":
        # the DLC the player owns comes with the game (and its updates)
        return ["legendary", "-y", "update" if kind == "update" else "install", gid, "--base-path", base, "--skip-sdl",
                "--with-dlcs"]
    if store == "gog":
        auth = ["gogdl", "--auth-config-path", GOG_AUTH]
        if kind == "update":
            g = next((g for g in _gog_installed() if g["appName"] == gid), None)
            if not g:
                raise RuntimeError("GOG doesn't list the game as installed: install it again instead")
            return auth + ["update", gid, "--platform", "windows", "--path", g["install_path"], "--lang",
                           g.get("language") or "en-US", "--with-dlcs"]
        return auth + ["download", gid, "--platform", "windows", "--path", base, "--lang", "en-US", "--with-dlcs"]
    if kind == "update":
        return ["nile", "update", gid]
    return ["nile", "install", gid, "--base-path", base]


def _gog_manifest(gid: str) -> str:
    return os.path.join(GOGDL, "heroic_gogdl", "manifests", gid)


def _start_job(job: dict, base: str):
    if job["store"] != "flathub":  # flatpak keeps its own
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
           "--", "bash", "-c", f'{{ {" && ".join(shlex.join(c) for c in _job_commands(job, base))}; }} >>"$0" 2>&1; '
                               f'echo "{EXIT_MARK} $?" >>"$0"', JOB_LOG]
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


def _flatpak_progress(log: str) -> dict:
    """flatpak's progress, which it prints a line at a time when not on a terminal: "Installing
    2/3… ▌ 45%  1.2 MB/s  00:12" (no "2/3" for a single step, "0 bytes/s" at the start; GLib puts
    a no-break space before the unit); the steps count as equal parts."""
    m = re.findall(r"^(?:Installing|Updating)(?: (\d+)/(\d+))?….*?(\d+)%(?:\s+([\d.]+)\s(bytes|[kMG]B)/s)?(?:\s+([\d:]+))?",
                   log, re.M)
    if not m:
        return {"percent": 0.0, "eta": "", "speed": 0.0}
    i, n, pct, speed, unit, eta = m[-1]
    i, n = int(i or 1), int(n or 1)
    mib = float(speed) * {"bytes": 1, "kB": 1e3, "MB": 1e6, "GB": 1e9}[unit] / 2**20 if speed else 0.0
    return {"percent": round((i - 1 + int(pct) / 100) / n * 100, 1), "eta": eta, "speed": mib}


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
    old = next((g for g in _gog_installed() if g["appName"] == gid), None)
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
             "is_dlc": False, "version": info.get("versionName") or "", "appName": gid,
             "installedDLCs": [str(d.get("id")) for d in info.get("dlcs") or [] if d.get("id")],
             "language": (old or {}).get("language") or "en-US", "versionEtag": info.get("versionEtag") or "",
             "buildId": info.get("buildId") or "", "pinnedVersion": False}
    with _heroic_lock(GOG_INSTALLED):
        data = _read_json(GOG_INSTALLED, {})
        data["installed"] = [g for g in data.get("installed", []) if g["appName"] != gid] + [entry]
        _write_json(GOG_INSTALLED, data)


def _gog_folder_ok(path: str, gid: str, bases: list[str]) -> bool:
    """Whether Heroic's install_path is the game's own folder, safe to delete: it has the game's
    goggame-<id>.info and isn't the home folder, one above it, or where games are installed."""
    real = os.path.realpath(path)
    if not os.path.isfile(os.path.join(real, f"goggame-{gid}.info")):
        return False
    for b in [HOME, os.path.join(HOME, "Games")] + bases:
        b = os.path.realpath(b)
        if real == b or b.startswith(real.rstrip("/") + "/"):
            return False
    return True


def _uninstall(store: str, gid: str, bases: list[str]):
    if store == "flathub":
        app = _flatpak_list().get(gid)
        if app and app["installation"] != "user":
            raise RuntimeError("it's installed for all users: remove it in Discover on the desktop")
        r = _run(FLATPAK, "uninstall", "--user", "--noninteractive", "-y", gid, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip().removeprefix("error: ") or "flatpak couldn't uninstall the app")
        # the runtimes nothing uses any more (the app's data stays in ~/.var/app)
        _run(FLATPAK, "uninstall", "--user", "--unused", "--noninteractive", "-y", timeout=600)
    elif store == "epic":
        r = _run("legendary", "-y", "uninstall", gid, timeout=600)
        if r.returncode != 0:
            raise RuntimeError("legendary couldn't uninstall the game")
    elif store == "gog":
        g = next((g for g in _gog_installed() if g["appName"] == gid), None)
        path = (g or {}).get("install_path")
        if path and os.path.isdir(path):
            if _gog_folder_ok(path, gid, bases):
                shutil.rmtree(path)
            else:  # not the game's own folder (a hand-edited or broken record): only the record goes
                decky.logger.warning("stores: GOG %s: not deleting %s, it isn't the game's own folder", gid, path)
        with _heroic_lock(GOG_INSTALLED):
            data = _read_json(GOG_INSTALLED, {})
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
        d = o["path"]
        while not os.path.exists(d) and os.path.dirname(d) != d:  # Games/Heroic may not be there yet
            d = os.path.dirname(d)
        try:
            st = os.statvfs(d)
            o["free"] = st.f_bavail * st.f_frsize
        except OSError:
            o["free"] = 0
    return out


def _forget_game(appid: int):
    """A removed store game's own settings in Game Settings: its profile, Frame Gen's settings and
    the layer's file, and OptiScaler's parked .ini, all by appid. A shortcut made for the game
    again can get the same appid, and would start with settings for launch options it hasn't."""
    if not appid or not steamlib.is_shortcut(appid):
        return
    for path in (os.path.join(DECKY_SETTINGS, "kettle-game-settings", "games.json"),
                 os.path.join(DECKY_SETTINGS, "kettle-framegen", "games.json")):
        data = _read_json(path, None)
        if isinstance(data, dict) and data.pop(str(appid), None) is not None:
            _write_json(path, data)
    for path in (os.path.join(HOME, ".config", "kettle-framegen", f"{appid}.conf"),
                 os.path.join(DECKY_SETTINGS, "kettle-upscaling", "optiscaler", f"{appid}.ini"),
                 os.path.join(DECKY_SETTINGS, "kettle-upscaling", "optiscaler", f"{appid}.json")):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    decky.logger.info("stores: forgot game settings of shortcut %s", appid)


async def _android_run(command: str, arg: str):
    """Runs kettle-android-games, following its PROGRESS lines; the JSON result ends up in _android."""
    try:
        p = await asyncio.create_subprocess_exec(ANDROID, command, arg, env=_env(),
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        err = []

        async def follow():
            async for line in p.stderr:
                parts = line.decode(errors="replace").split()
                if len(parts) == 3 and parts[0] == "PROGRESS" and parts[1].isdigit() and parts[2].isdigit():
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
            log = _log_tail()
            job = dict(job, **(_flatpak_progress(log) if job["store"] == "flathub" else _progress(log)))
        return {"users": _users(), "job": job, "queue": s.get("queue", []), "login": self.login,
                "cloud_saves": s.get("cloud_saves", True) is not False}

    async def login_start(self, store: str) -> str:
        """The store's login page (the frontend opens it in Steam's browser); a task waits for the sign-in."""
        _store(store, STORES)
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
        await asyncio.to_thread(_logout, _store(store, STORES))

    # libraries

    async def library(self, store: str, refresh: bool) -> dict:
        """The store's games ({"games", "fetched"}); from the cache unless refresh or it's a day old."""
        _store(store, STORES)
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
        gid = _gid(_store(store, STORES), gid)
        info = await asyncio.to_thread(_size_info, store, gid)
        info["installed"] = (await asyncio.to_thread(_installed, store)).get(gid)
        return info

    async def details(self, store: str, gid: str) -> dict:
        gid = _gid(_store(store, STORES), gid)
        key = f"{store}:{gid}"
        if key not in self.details_cache:
            self.details_cache[key] = await asyncio.to_thread(_details, store, gid)
        return self.details_cache[key]

    # Flathub

    async def flathub_browse(self, category: str, query: str, page: int) -> dict:
        """A page of Flathub's ARM64 apps ({"apps", "pages", "total"}) in a category ("games",
        "emulators", "all") or matching query; "installed": the Flatpak apps installed here."""
        if category == "installed":
            apps = await asyncio.to_thread(_flathub_installed)
            q = query.strip().lower()
            apps = [a for a in apps if not q or q in a["title"].lower() or q in a["id"].lower()]
            return {"apps": apps, "pages": 1, "total": len(apps)}
        if category not in FLATHUB_CATEGORIES:
            raise ValueError(f"no such category: {category!r}")
        return await asyncio.to_thread(_flathub_search, category, query, max(1, int(page)))

    async def flathub_app(self, app: str) -> dict:
        """The app's page: Flathub's details, its install here, and its Steam shortcut (ours, or
        one the Welcome plugin's Gaming Extras made)."""
        info = await asyncio.to_thread(_flathub_app, _app_id(app))
        s = self._state()
        info["appid"] = s["shortcuts"].get(f"flathub:{app}") or await asyncio.to_thread(_flathub_shortcut, app)
        info["busy"] = next((j["kind"] for j in s.get("queue", []) + ([s["job"]] if s.get("job") else [])
                             if j["store"] == "flathub" and j["id"] == app), None)
        return info

    async def locations(self) -> dict:
        return {"locations": await asyncio.to_thread(_locations),
                "current": self._state().get("install_dir") or DEFAULT_DIR}

    async def set_cloud_saves(self, on: bool):
        async with self.lock:
            s = self._state()
            s["cloud_saves"] = bool(on)
            self._save(s)

    async def set_location(self, path: str):
        async with self.lock:
            s = self._state()
            s["install_dir"] = path
            self._save(s)

    # installing

    async def install(self, store: str, gid: str, title: str, kind: str):
        """Queues an install or update ("install"|"update"); the main loop starts it."""
        gid = _gid(_store(store), gid)
        if kind not in ("install", "update"):
            raise ValueError(f"unknown job kind: {kind!r}")
        title = str(title)[:200]
        async with self.lock:
            s = self._state()
            if any(j["store"] == store and j["id"] == gid for j in s["queue"] + ([s["job"]] if s.get("job") else [])):
                return
            s["queue"].append({"store": store, "id": gid, "title": title, "kind": kind})
            self._save(s)
        await self._next()

    async def cancel(self, store: str, gid: str):
        """Takes a game off the queue, or stops its running download (it resumes if started again)."""
        gid = _gid(_store(store), gid)
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
        gid = _gid(_store(store), gid)
        s = self._state()
        bases = [s.get("install_dir") or DEFAULT_DIR] + [l["path"] for l in await asyncio.to_thread(_locations)]
        await asyncio.to_thread(_uninstall, store, gid, bases)
        async with self.lock:
            s = self._state()
            appid = s["shortcuts"].pop(f"{store}:{gid}", None)
            if store == "flathub" and not appid:
                appid = await asyncio.to_thread(_flathub_shortcut, gid)
            s["pending"] = [k for k in s["pending"] if k != f"{store}:{gid}"]
            self._save(s)
        try:
            await asyncio.to_thread(_forget_game, appid)
        except Exception as e:  # the game is gone either way
            decky.logger.warning("stores: forgetting %s's settings: %s", appid, e)
        return appid

    # Steam shortcuts (added by the frontend)

    async def shortcut_info(self, store: str, gid: str) -> dict:
        gid = _gid(_store(store), gid)
        info = await asyncio.to_thread(_shortcut_info, store, gid)
        info["launch"] = f"run {gid}" if store == "flathub" else f"{WRAPPER} {store} {gid} %command%"
        return info

    async def artwork(self, store: str, gid: str) -> dict:
        return await asyncio.to_thread(_art, _store(store), _gid(store, gid))

    async def remember_shortcut(self, store: str, gid: str, appid: int):
        gid = _gid(_store(store), gid)
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
        """Installs finished without a shortcut yet (the frontend wasn't listening then), with the
        shortcut the game had before (appid), which the frontend brings up to date."""
        out = []
        s = self._state()
        for k in s.get("pending", []):
            store, _, gid = k.partition(":")
            if store not in SOURCES:
                continue
            if gid in await asyncio.to_thread(_installed, store):
                out.append({"store": store, "id": gid, "appid": await self._known_appid(s, store, gid)})
        return out

    async def _known_appid(self, s: dict, store: str, gid: str) -> int | None:
        """The game's Steam shortcut as far as the plugin knows (Flathub: also one made elsewhere)."""
        appid = s["shortcuts"].get(f"{store}:{gid}")
        if not appid and store == "flathub":
            appid = await asyncio.to_thread(_flathub_shortcut, gid)
        return appid

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
            cur = s.get("job")
            if not cur or cur.get("started") != job.get("started") or cur["id"] != job["id"]:
                return  # cancelled meanwhile (cancel cleared it; the next may have started)
            s["job"] = None
            key = f"{job['store']}:{job['id']}"
            if ok and job["kind"] == "install" and key not in s["pending"]:
                s["pending"].append(key)
            self._save(s)
        decky.logger.info("stores: %s %s: %s", job["kind"], job["id"], "done" if ok else error)
        # with the game's shortcut, if it has one already: a reinstall brings that one up to date
        appid = await self._known_appid(s, job["store"], job["id"]) if ok else None
        await decky.emit("job", dict(job, appid=appid), ok, error)
        await self._next()

    async def battlenet_status(self) -> dict:
        """welcome-battlenet status: {proton, steam, appid, in_steam, ready}; available: it's installed."""
        if not os.access(BATTLENET, os.X_OK):
            return {"available": False}
        r = await asyncio.to_thread(_run, BATTLENET, "status", timeout=30)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "welcome-battlenet status failed")
        return {**json.loads(r.stdout), "available": True}

    async def battlenet_install(self):
        """Downloads Battle.net's installer, adds it to Steam and starts it; raises with the reason."""
        r = await asyncio.to_thread(_run, BATTLENET, "install", timeout=180, quiet=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "welcome-battlenet install failed")
        decky.logger.info("Battle.net added to Steam, installer started")

    async def android_info(self) -> dict:
        """available: kettle-lepton is installed; files: where to look for an APK file first."""
        downloads = os.path.join(HOME, "Downloads")
        return {"available": os.access(ANDROID, os.X_OK), "files": downloads if os.path.isdir(downloads) else HOME}

    async def android_list(self) -> dict:
        r = await asyncio.create_subprocess_exec(ANDROID, "list", env=_env(), stdout=asyncio.subprocess.PIPE,
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
