"""Where Emulation trees live: internal storage (~/Emulation) and every SD card or USB stick
mounted under /run/media/<user>. KETTLE_EMU_HOME and KETTLE_EMU_MEDIA override both, for tests."""
import getpass
import os

JUNK_DIRS = {"System Volume Information", "$RECYCLE.BIN", ".Trashes", ".Spotlight-V100",
             ".fseventsd", "LOST.DIR", ".Trash-1000"}


def home():
    return os.environ.get("KETTLE_EMU_HOME") or os.path.join(os.path.expanduser("~"), "Emulation")


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


def root_for(dest):
    """The Emulation dir for --dest: "internal" or a card's mount point (or its Emulation dir)."""
    if dest in (None, "", "internal"):
        return home()
    dest = os.path.realpath(dest)
    for c in cards():
        if dest in (os.path.realpath(c["path"]), os.path.realpath(c["emulation"])):
            return c["emulation"]
    raise ValueError(f"not a mounted card: {dest}")
