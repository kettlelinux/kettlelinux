"""Where Emulation trees live: internal storage (~/Emulation) and every SD card or USB stick
mounted under /run/media/<user>. KETTLE_EMU_HOME and KETTLE_EMU_MEDIA override both, for tests.

The storage manager's two choices (~/.config/kettle/emulation/storage.json, the plugin's Storage
tab writes it): where new games go ("new_games": the upload page and imports) and where the game
data lives ("data": the saves, states and screenshots folders of an Emulation tree, and the
emulator data folders systems.json's "data" lists, such as RPCS3's dev_hdd0). Each is "internal"
or a card's key (its filesystem uuid, else its mount point). Game data on a card lives in that
card's Emulation tree: saves/, states/, screenshots/ and data/<emulator>/; the BIOS files, keys
and firmware always stay internal."""
import getpass
import json
import os

JUNK_DIRS = {"System Volume Information", "$RECYCLE.BIN", ".Trashes", ".Spotlight-V100",
             ".fseventsd", "LOST.DIR", ".Trash-1000"}


# the folders of an Emulation tree that are game data, not games or BIOS files
DATA_DIRS = ("saves", "states", "screenshots")
DEFAULTS = {"new_games": "internal", "new_games_label": "", "data": "internal", "data_label": ""}


def home():
    return os.environ.get("KETTLE_EMU_HOME") or os.path.join(os.path.expanduser("~"), "Emulation")


def user_home():
    """The home folder ~/Emulation is in (the paths systems.json gives are from it)."""
    return os.path.dirname(home().rstrip("/"))


def media_dir():
    return os.environ.get("KETTLE_EMU_MEDIA") or os.path.join("/run/media", getpass.getuser())


def _unescape(field):
    # mountinfo escapes space, tab, newline and backslash as octal
    out, i = [], 0
    while i < len(field):
        if field[i] == "\\" and i + 3 < len(field) and field[i + 1:i + 4].isdigit():
            out.append(chr(int(field[i + 1:i + 4], 8)))
            i += 4
        else:
            out.append(field[i])
            i += 1
    return "".join(out)


def mounts():
    """{mount point: (source device, fstype)} from /proc/self/mountinfo."""
    res = {}
    try:
        with open("/proc/self/mountinfo") as f:
            for line in f:
                left, _, right = line.partition(" - ")
                parts, rparts = left.split(), right.split()
                if len(parts) >= 5 and len(rparts) >= 2:
                    res[_unescape(parts[4])] = (rparts[1], rparts[0])
    except OSError:
        pass
    return res


def _uuids():
    """{device path: filesystem uuid} from /dev/disk/by-uuid."""
    res = {}
    d = "/dev/disk/by-uuid"
    try:
        for u in os.listdir(d):
            res[os.path.realpath(os.path.join(d, u))] = u
    except OSError:
        pass
    return res


def _mount_of(path, table):
    path = os.path.realpath(path)
    best = "/"
    for mp in table:
        if (path == mp or path.startswith(mp.rstrip("/") + "/")) and len(mp) > len(best):
            best = mp
    return best


def cards():
    """Each mounted card or stick (see roots()). A test media dir (KETTLE_EMU_MEDIA) lists its
    subdirectories."""
    media = media_dir()
    table = mounts()
    uuids = _uuids()
    res = []
    try:
        names = sorted(os.listdir(media))
    except OSError:
        return res
    for name in names:
        mp = os.path.join(media, name)
        if not os.path.isdir(mp):
            continue
        if not os.environ.get("KETTLE_EMU_MEDIA") and mp not in table:
            continue
        dev, fstype = table.get(mp, ("", ""))
        res.append({"path": mp, "emulation": os.path.join(mp, "Emulation"), "internal": False,
                    "uuid": (uuids.get(os.path.realpath(dev)) if dev else None) or "",
                    "label": name, "fstype": fstype, "device": dev})
    return res


def internal():
    table = mounts()
    mp = _mount_of(home(), table)
    dev, fstype = table.get(mp, ("", ""))
    return {"path": os.path.dirname(home().rstrip("/")), "emulation": home(), "internal": True,
            "uuid": (_uuids().get(os.path.realpath(dev)) if dev else None) or "",
            "label": "Internal storage", "fstype": fstype, "device": dev}


def roots():
    """Internal storage first, then the cards: {path (the home folder or the card's mount point),
    emulation (its Emulation folder), internal, uuid (the filesystem's, "" if unknown), label,
    fstype, device}."""
    return [internal()] + cards()


def emulation_dir(root):
    """A root's Emulation folder: ~/Emulation or <card>/Emulation."""
    return root.get("emulation") or os.path.join(root["path"], "Emulation")


def root_of(dest):
    """The storage for --dest: "internal" or a card's mount point (or its Emulation dir)."""
    if dest in (None, "", "internal") or os.path.realpath(dest) == os.path.realpath(home()):
        return internal()
    dest = os.path.realpath(dest)
    for c in cards():
        if dest in (os.path.realpath(c["path"]), os.path.realpath(c["emulation"])):
            return c
    raise ValueError(f"not a mounted card: {dest}")


def root_for(dest):
    """The Emulation dir for --dest: "internal" or a card's mount point (or its Emulation dir)."""
    return emulation_dir(root_of(dest))


def key(root):
    """A storage's key in storage.json: "internal", or its filesystem uuid (its mount point when
    that's unknown), so a card is the same card in any slot."""
    return "internal" if root.get("internal") else (root.get("uuid") or root["path"])


def conf_path():
    return os.environ.get("KETTLE_EMU_STORAGE") or os.path.join(
        user_home(), ".config/kettle/emulation/storage.json")


def settings():
    try:
        with open(conf_path()) as f:
            got = json.load(f)
    except (OSError, ValueError):
        got = {}
    return {**DEFAULTS, **{k: v for k, v in got.items() if isinstance(v, str)}} \
        if isinstance(got, dict) else dict(DEFAULTS)


def save_settings(**values):
    s = settings()
    s.update(values)
    p = conf_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, p)
    return s


def find(k, roots=None):
    """The storage whose key is `k` ("internal" or a card's), or None when it isn't in."""
    if k in (None, "", "internal"):
        return internal()
    for r in cards() if roots is None else roots:
        if not r.get("internal") and key(r) == k:
            return r
    return None


def is_set_up(root):
    return os.path.isdir(os.path.join(emulation_dir(root), "roms"))


def new_games_dir():
    """The Emulation folder new games go to: the chosen card's when it's in and set up, else
    internal storage's."""
    r = find(settings()["new_games"])
    if r and not r["internal"] and is_set_up(r):
        return emulation_dir(r)
    return home()


class DataMissing(Exception):
    """The game data is on a card that isn't in."""

    def __init__(self, label):
        super().__init__(f"Your saves are on {label or 'a card'}, which isn't in")
        self.label = label


def data_root():
    """The storage the game data is on (raises DataMissing when it's a card that isn't in: an
    emulator must never start on an empty internal folder, which would look like lost saves)."""
    s = settings()
    r = find(s["data"])
    if r is None:
        raise DataMissing(s.get("data_label", ""))
    return r


def data_items(db):
    """What moves with the game data: [(path from the home folder, path from a card's
    Emulation folder, emulator id or "")]: the Emulation tree's data folders, then each
    emulator's "data" (a folder or a file)."""
    out = [(f"Emulation/{d}", d, "") for d in DATA_DIRS]
    for eid, e in db.get("emulators", {}).items():
        for item in e.get("data") or ():
            out.append((item["dir"].strip("/"), item["card"].strip("/"), eid))
    return out


def locate(rel, db, root=None):
    """Where the path `rel` (from the home folder, as systems.json gives it) is with the game
    data on `root` (the data storage by default): on a card, a path in one of data_items() is in
    that card's Emulation folder; anything else, and everything with the data internal, is under
    the home folder."""
    rel = rel.strip("/")
    root = data_root() if root is None else root
    if not root.get("internal"):
        for src, card, _ in data_items(db):
            if rel == src or rel.startswith(src + "/"):
                tail = rel[len(src):].lstrip("/")
                at = os.path.join(emulation_dir(root), card)
                return os.path.join(at, tail) if tail else at
    return os.path.join(user_home(), rel)


def movable(rel, db):
    """Whether a path from the home folder moves with the game data."""
    rel = rel.strip("/")
    return any(rel == src or rel.startswith(src + "/") for src, _, _ in data_items(db))
