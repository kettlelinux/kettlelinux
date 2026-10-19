# A ROM's library artwork, from libretro-thumbnails: the box art, the in-game snap and the title
# screen of every game in No-Intro/Redump naming, a git repository per system (systems.json's
# "thumbnails"). Each system's list of names comes from one GitHub tree request, cached for a week;
# when GitHub's rate limit (60 an hour without a sign-in) says no, from the directory listing of
# thumbnails.libretro.com. A ROM's name is matched exactly, then by its title without tags, then
# fuzzily (difflib, CUTOFF), a tie going to the ROM's own region, then USA, World, Europe, Japan.
# SteamGridDB, with the user's own API key (off without one), covers what libretro has nothing for.
#
# Pictures are composed for Steam (artcompose.py, a PySide6 process of its own): the box art as the
# portrait capsule on a blurred copy of itself, the snap as the hero, the title screen as the wide
# capsule. Downloads and results are cached under ~/.cache/kettle/emulation. A picture that can't
# be fetched (no network, a server error) raises Offline, so a game offline isn't a game libretro
# has nothing for.
import difflib
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CUTOFF = 0.85
INDEX_DAYS = 7
KINDS = {"box": "Named_Boxarts", "snap": "Named_Snaps", "title": "Named_Titles"}
REGIONS = ("USA", "World", "Europe", "Japan")
UA = "kettle-emulation/1 (+https://github.com/kettlelinux)"
# the characters libretro-thumbnails replaces in a game's name
_BAD = re.compile(r'[&*/:`<>?\\|"]')
_TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")


class Offline(Exception):
    """A picture couldn't be fetched: no network, or the server failed (not a 404)."""


# --- matching (pure) ---------------------------------------------------------------------------
def thumb_name(name: str) -> str:
    return _BAD.sub("_", name)


def normal(name: str) -> str:
    """A title for comparing: no tags, no punctuation, lower case, "The" at either end dropped,
    a leading article moved names ("Legend of Zelda, The") alike."""
    t = _TAGS.sub("", name).lower()
    t = re.sub(r",\s*the\b", "", t)
    t = re.sub(r"^the\s+", "", t)
    t = t.replace("&", "and").replace("_", " ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(ROMAN.get(w, w) for w in t.split())


ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}


def _numbers(title: str) -> list[str]:
    return re.findall(r"\d+", title)


def regions(name: str) -> list[str]:
    tags = re.findall(r"\(([^)]*)\)", name)
    out = []
    for t in tags:
        out += [p.strip() for p in t.split(",")]
    return out


def _rank(rom: str, cand: str) -> tuple:
    mine = regions(rom)
    theirs = regions(cand)
    same = sum(1 for r in theirs if r in mine)
    pref = min((REGIONS.index(r) for r in theirs if r in REGIONS), default=len(REGIONS))
    # fewer extra tags first: "(USA)" over "(USA) (Beta)"
    return (-same, pref, len(theirs), cand)


def match(rom: str, names: list[str], cutoff: float = CUTOFF) -> list[str]:
    """The thumbnail names for a ROM's name (no extension), best first: an exact match alone, else
    those with the same title, else the fuzzy ones."""
    want = thumb_name(rom)
    if want in names:
        return [want]
    n = normal(rom)
    if not n:
        return []
    by_title = {}
    for c in names:
        by_title.setdefault(normal(c), []).append(c)
    same = by_title.get(n)
    if same:
        return sorted(same, key=lambda c: _rank(rom, c))
    # a sequel is never a close match: the numbers in the titles have to be the same
    close = [t for t in difflib.get_close_matches(n, list(by_title), n=5, cutoff=cutoff) if _numbers(t) == _numbers(n)]
    out = []
    for t in close:
        out += sorted(by_title[t], key=lambda c: _rank(rom, c))
    return out


# --- the name lists ----------------------------------------------------------------------------
def _get(url: str, headers: dict | None = None, limit: int = 32 << 20, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{url}: too big")
    return data


def _from_github(repo: str) -> dict:
    data = json.loads(_get(f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/HEAD?recursive=1",
                           {"Accept": "application/vnd.github+json"}))
    out = {k: [] for k in KINDS}
    for e in data.get("tree", []):
        path = e.get("path", "")
        for k, d in KINDS.items():
            if path.startswith(d + "/") and path.endswith(".png"):
                out[k].append(path[len(d) + 1:-4])
    if data.get("truncated") and not any(out.values()):
        raise ValueError("tree truncated")
    return out


def _server_dir(repo: str) -> str:
    # thumbnails.libretro.com names the systems with spaces: "Nintendo - Game Boy"
    return repo.replace("_-_", " - ").replace("_", " ")


def _from_server(repo: str) -> dict:
    out = {}
    for k, d in KINDS.items():
        url = f"https://thumbnails.libretro.com/{urllib.parse.quote(_server_dir(repo))}/{d}/"
        try:
            page = _get(url).decode("utf-8", errors="replace")
        except Exception:
            out[k] = []
            continue
        names = re.findall(r'href="([^"?/]+)\.png"', page)
        out[k] = [html.unescape(urllib.parse.unquote(n)) for n in names]
    return out


def index(repo: str, cache: str) -> dict:
    """{box|snap|title: [names]} of a system's thumbnails (a week's cache; a stale one when both
    sources fail)."""
    path = os.path.join(cache, "index", f"{repo}.json")
    try:
        if time.time() - os.path.getmtime(path) < INDEX_DAYS * 86400:
            with open(path) as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    for source in (_from_github, _from_server):
        try:
            idx = source(repo)
        except Exception:
            continue
        if any(idx.values()):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w") as f:
                json.dump(idx, f)
            os.replace(path + ".tmp", path)
            return idx
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {k: [] for k in KINDS}


def thumb_url(repo: str, kind: str, name: str) -> str:
    return (f"https://raw.githubusercontent.com/libretro-thumbnails/{repo}/master/"
            f"{KINDS[kind]}/{urllib.parse.quote(name)}.png")


def _fetch(url: str, cache: str) -> str | None:
    """The file at url, cached; None if it isn't there (a 404). Offline when it can't be told."""
    import hashlib
    path = os.path.join(cache, "img", hashlib.sha1(url.encode()).hexdigest())
    if os.path.exists(path):
        return path if os.path.getsize(path) else None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        data = _get(url, limit=16 << 20)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            open(path, "wb").close()  # known missing
            return None
        raise Offline(f"{url}: HTTP {e.code}") from e
    except Exception as e:
        raise Offline(f"{url}: {e}") from e
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    return path


def candidates(repo: str, rom_name: str, cache: str, n: int = 5) -> list[str]:
    """The box art names that could be this ROM's, best first (the "Fix artwork" choices)."""
    return match(rom_name, index(repo, cache).get("box", []))[:n]


def pictures(repo: str, rom_name: str, cache: str, chosen: str | None = None) -> dict:
    """{box|snap|title: local file} for a ROM. Without an index entry, the exact name is still
    tried at its raw URL (the index can be stale or unreachable)."""
    idx = index(repo, cache)
    out = {}
    name = chosen
    if not name:
        best = match(rom_name, idx.get("box", [])) or match(rom_name, idx.get("snap", []))
        name = best[0] if best else thumb_name(rom_name)
    for kind in KINDS:
        names = idx.get(kind, [])
        pick = name if (name in names or not names) else (match(name, names) or [None])[0]
        if pick:
            p = _fetch(thumb_url(repo, kind, pick), cache)
            if p:
                out[kind] = p
    return out


# --- SteamGridDB (the user's key) --------------------------------------------------------------
SGDB = "https://www.steamgriddb.com/api/v2"
# Steam's custom artwork types: the portrait capsule, the hero, the logo, the wide capsule
SGDB_ASSETS = ((0, "grids", "dimensions=600x900"), (1, "heroes", ""), (2, "logos", ""),
               (3, "grids", "dimensions=920x430,460x215"))
MIMES = "mimes=image/png,image/jpeg"  # what Steam takes (no webp or animated)


def sgdb_search(key: str, title: str) -> list[dict]:
    """SteamGridDB's games for a title, best first: [{id, name}]."""
    h = {"Authorization": f"Bearer {key}"}
    found = json.loads(_get(f"{SGDB}/search/autocomplete/{urllib.parse.quote(title)}", h)).get("data") or []
    return [{"id": g["id"], "name": g.get("name", "")} for g in found if "id" in g]


def sgdb_assets(key: str, title: str, cache: str, chosen: str | None = None) -> dict:
    """{Steam artwork type: (local file, "png"|"jpg")} from SteamGridDB for a game without
    libretro art (the Switch): its capsule, hero, logo and wide capsule, as they are (SteamGridDB
    makes them in Steam's shapes). `chosen`: a name from sgdb_search (Fix artwork)."""
    h = {"Authorization": f"Bearer {key}"}
    games = sgdb_search(key, chosen or title)
    if chosen:
        games = [g for g in games if g["name"] == chosen] or games
    if not games:
        return {}
    gid = games[0]["id"]
    out = {}
    for kind, path, query in SGDB_ASSETS:
        q = "&".join(x for x in (query, MIMES) if x)
        items = json.loads(_get(f"{SGDB}/{path}/game/{gid}?{q}", h)).get("data") or []
        for item in items[:3]:
            url = item.get("url", "")
            ext = "jpg" if url.lower().endswith((".jpg", ".jpeg")) else "png" if url.lower().endswith(".png") else None
            if not ext:
                continue
            p = _fetch(url, cache)
            if p:
                out[kind] = (p, ext)
                break
    return out


# --- composing ---------------------------------------------------------------------------------
def compose(pics: dict, out_dir: str) -> dict:
    """{Steam asset type: PNG path} made from the pictures (artcompose.py)."""
    if not pics:
        return {}
    os.makedirs(out_dir, exist_ok=True)
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artcompose.py")
    args = [sys.executable, helper, out_dir]
    for k in ("box", "snap", "title"):
        args.append(pics.get(k, ""))
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    try:
        r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
        return {int(k): v for k, v in json.loads(r.stdout or "{}").items()}
    except (subprocess.SubprocessError, ValueError, OSError):
        return {}
