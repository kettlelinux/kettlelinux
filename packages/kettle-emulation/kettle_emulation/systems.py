"""The system and emulator definitions, /usr/share/kettle/emulation/systems.json
(KETTLE_EMU_SYSTEMS overrides the path, for tests)."""
import json
import os

PATH = "/usr/share/kettle/emulation/systems.json"

_cache = {}


def load(path=None):
    path = path or os.environ.get("KETTLE_EMU_SYSTEMS") or PATH
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _cache:
        with open(path) as f:
            _cache.clear()
            _cache[key] = json.load(f)
    return _cache[key]


def systems():
    return load()["systems"]


def emulators():
    return load()["emulators"]


def ext_of(name):
    """'Game.NES' -> 'nes'; '' without one."""
    base = os.path.basename(name)
    return base.rpartition(".")[2].lower() if "." in base.lstrip(".") else ""


def by_extension(ext):
    """The ids of the systems that take this extension, in systems.json order."""
    ext = ext.lower().lstrip(".")
    return [sid for sid, s in systems().items() if ext in s.get("extensions", ())]


def by_folder(name):
    """The system whose folder list has this folder name (any case), or None."""
    name = name.lower()
    for sid, s in systems().items():
        if name == sid or name in s.get("folders", ()):
            return sid
    return None


def folder(sid):
    """The folder a system's ROMs are sorted into: its first."""
    return systems()[sid]["folders"][0]


def keeps_archives(sid):
    return bool(systems().get(sid, {}).get("keep_archives"))


def bios_entries():
    """(system id, entry) for every BIOS entry."""
    return [(sid, b) for sid, s in systems().items() for b in s.get("bios", ())]


def rom_extensions():
    """Every extension some system takes."""
    return {e for s in systems().values() for e in s.get("extensions", ())}


def flatpaks():
    return load().get("flatpaks", {})


def flatpak_of(emu):
    """The Flatpak app an emulator runs in: its own, or RetroArch's for a libretro core."""
    return emu["flatpak"] if emu["kind"] == "flatpak" else RETROARCH


RETROARCH = "org.libretro.RetroArch"
LAYOUTS = "/usr/share/kettle/emulation"


def layout(eid, face):
    """The Steam Input layout a game needs (mkvdf.py): the emulator's own when its hotkeys have
    their own keys, else the standard one of the device's face buttons (xbox or nintendo)."""
    face = "nintendo" if face == "nintendo" else "xbox"
    own = "keys" in emulators().get(eid, {})
    return f"local://{LAYOUTS}/emulation-{face}{'-' + eid if own else ''}.vdf"
