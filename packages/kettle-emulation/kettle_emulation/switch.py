"""What a Switch game needs of the user's keys, read from the game file before the emulator
starts: a game made for a newer system version than the user's prod.keys came from can't be
opened (Ryujinx only logs "missing key_area_key_application_0f" and starts nothing), so emu-run
says so instead.

The key generation is in each NCA's header, which is encrypted with the user's own header_key
(AES-128-XTS, Nintendo's big-endian sector tweak). An NSP is a PFS0 of NCAs; an XCI holds them
in the "secure" partition of its HFS0. A game with a ticket (title-key crypto) also names its
key generation in the ticket's file name (the rights ID's last byte), which needs no keys.

Nothing here is a secret: keys are read from the user's prod.keys and never written or shown.
"""
import os
import re
import struct

XCI_HFS0 = 0xF000  # the root HFS0 of an XCI


def _pfs(f, base, magic, entry):
    """[(name, offset from base, size)] of a PFS0 or HFS0 at `base`."""
    f.seek(base)
    head = f.read(16)
    if len(head) < 16 or head[:4] != magic:
        return []
    n, strtab = struct.unpack_from("<II", head, 4)
    if n > 4096 or strtab > 1 << 20:
        return []
    raw = f.read(n * entry)
    names = f.read(strtab)
    data = base + 16 + n * entry + strtab
    out = []
    for i in range(n):
        off, size, name_at = struct.unpack_from("<QQI", raw, i * entry)
        end = names.find(b"\0", name_at)
        out.append((names[name_at:end if end >= 0 else None].decode(errors="replace"),
                    data + off, size))
    return out


def ncas(path):
    """[(name, absolute offset, size)] of the NCAs in an NSP or XCI, biggest first; and the
    ticket file names."""
    with open(path, "rb") as f:
        if path.lower().endswith(".xci"):
            root = _pfs(f, XCI_HFS0, b"HFS0", 0x40)
            secure = next(((o, s) for n, o, s in root if n == "secure"), None)
            files = _pfs(f, secure[0], b"HFS0", 0x40) if secure else []
        else:
            files = _pfs(f, 0, b"PFS0", 0x18)
    nca = sorted((x for x in files if x[0].endswith(".nca")), key=lambda x: -x[2])
    tickets = [n for n, _, _ in files if n.endswith(".tik")]
    return nca, tickets


def read_keys(path):
    """{name: bytes} of a prod.keys file."""
    keys = {}
    try:
        with open(path) as f:
            for line in f:
                name, sep, value = line.partition("=")
                if sep:
                    try:
                        keys[name.strip().lower()] = bytes.fromhex(value.strip())
                    except ValueError:
                        pass
    except OSError:
        pass
    return keys


def _xts_decrypt(key, data, sector):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    out = b""
    for i in range(0, len(data), 0x200):
        tweak = (sector + i // 0x200).to_bytes(16, "big")
        d = Cipher(algorithms.AES(key), modes.XTS(tweak)).decryptor()
        out += d.update(data[i:i + 0x200]) + d.finalize()
    return out


def nca_generation(path, offset, header_key):
    """The key generation of the NCA at `offset`, or None (not an NCA3, no cryptography)."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            raw = f.read(0x400)
        head = _xts_decrypt(header_key, raw, 0)
    except (ImportError, OSError, ValueError):
        return None
    if head[0x200:0x204] not in (b"NCA3", b"NCA2"):
        return None
    return max(head[0x206], head[0x220])


def master_key_index(generation):
    """The master key a key generation uses (generations 0 and 1 both use the first)."""
    return max(0, generation - 1)


def needed_key(path, keys):
    """The master key index this game needs, or None when it can't be told."""
    try:
        nca, tickets = ncas(path)
    except OSError:
        return None
    gens = []
    for t in tickets:  # <rights id: 32 hex>.tik, the last byte the key generation
        stem = t[:-4]
        if len(stem) == 32:
            try:
                gens.append(int(stem[30:], 16))
            except ValueError:
                pass
    header_key = keys.get("header_key")
    if not gens and header_key and len(header_key) == 32:
        for _, off, _ in nca[:2]:
            g = nca_generation(path, off, header_key)
            if g is not None:
                gens.append(g)
    return master_key_index(max(gens)) if gens else None


def have_key(keys, index):
    return f"master_key_{index:02x}" in keys or f"key_area_key_application_{index:02x}" in keys


def newest_key(keys):
    """The last key of the unbroken run from 00: the system version the keys came from (a stray
    later key, seen on the Portal, doesn't open games without the ones before it)."""
    i = -1
    while have_key(keys, i + 1):
        i += 1
    return i if i >= 0 else None


def too_new(path, keys_path):
    """A message when the game needs a newer key than keys_path has; None when it's fine or
    can't be told."""
    keys = read_keys(keys_path)
    if not keys:
        return None
    need = needed_key(path, keys)
    if need is None or have_key(keys, need):
        return None
    newest = newest_key(keys)
    have = f" (yours stop at {newest:02x})" if newest is not None else ""
    return (f"This game needs newer Switch keys than your prod.keys has: key generation "
            f"{need:02x}{have}. Dump prod.keys again from a Switch updated to a recent system "
            "version and put it in Emulation/bios/switch")


# --- the title ID: which game a file is, and whether it's the game, an update or DLC ---------
_TID_TAG = re.compile(r"\[(01[0-9a-fA-F]{14})\]")


def nca_title_id(path, offset, header_key):
    """The program ID in the NCA header at `offset` (u64 at 0x210), or None."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            raw = f.read(0x400)
        head = _xts_decrypt(header_key, raw, 0)
    except (ImportError, OSError, ValueError):
        return None
    if head[0x200:0x204] not in (b"NCA3", b"NCA2"):
        return None
    return f"{struct.unpack_from('<Q', head, 0x210)[0]:016x}"


def title_id(path, keys=None):
    """The file's title ID ("0100…", 16 lowercase hex), or None: a ticket's rights ID names it
    without keys; else the biggest NCA's header (the user's header_key); else a [0100…] tag in
    the file name (how dumps are usually named)."""
    try:
        nca, tickets = ncas(path)
    except OSError:
        nca, tickets = [], []
    for t in tickets:
        stem = t[:-4]
        if len(stem) == 32 and all(c in "0123456789abcdefABCDEF" for c in stem):
            return stem[:16].lower()
    header_key = (keys or {}).get("header_key")
    if header_key and len(header_key) == 32:
        for _, off, _ in nca[:1]:
            tid = nca_title_id(path, off, header_key)
            if tid:
                return tid
    m = _TID_TAG.search(os.path.basename(path))
    return m.group(1).lower() if m else None


def kind(tid):
    """"game", "update" or "dlc" by the title ID's low bits (switchbrew, Title list): a game's
    ID ends in 000 with bit 12 clear; its update is the game's | 0x800; its DLC are
    (game ^ 0x1000) + 1..0x7FF, so bit 12 is set."""
    n = int(tid, 16)
    if n & 0x1000:
        return "dlc"
    low = n & 0xFFF
    if low == 0x800:
        return "update"
    return "game" if low == 0 else "dlc"


# --- firmware -------------------------------------------------------------------------------
# A Switch firmware is the system's NCAs (dozens to a few hundred files, no game in them), as a
# zip or a folder of .nca files. The user's goes in Emulation/bios/switch/firmware; Kettle puts it
# where each emulator's own "Install Firmware" would, so the emulators' desktop windows are never
# needed:
# - Ryujinx (Ryubing src/Ryujinx.HLE/FileSystem/ContentManager.cs, InstallFirmware,
#   InstallFromZip, SaveNca, FinishInstallation): bis/system/Contents/registered, each NCA a
#   folder "<id>.nca" holding the file "00" (".cnmt" dropped from the name); the whole folder is
#   replaced, and LoadEntries reads it at start.
# - Eden (src/qt_common/util/content.cpp, InstallFirmware): nand/system/Contents/registered, the
#   .nca files flat under their own names (".cnmt.nca" kept), after the folder is emptied; it's
#   scanned at start.
FIRMWARE_MIN = 20  # a firmware has dozens of NCAs at least; fewer is something else
MARKER = ".kettle-firmware"  # beside registered: the installed firmware's source and identity


def _zip_ncas(path):
    """The .nca members of a zip ([(member name, file name)]), or None when it isn't a zip;
    fragmented NCAs ("<id>.nca/00") count by their folder's name."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except (OSError, zipfile.BadZipFile, EOFError):
        return None
    out = []
    for n in names:
        parts = [p for p in n.replace("\\", "/").split("/") if p]
        if not parts or ".." in parts:
            continue
        if parts[-1].lower().endswith(".nca"):
            out.append((n, parts[-1]))
        elif parts[-1] == "00" and len(parts) > 1 and parts[-2].lower().endswith(".nca"):
            out.append((n, parts[-2]))
    return out


def _dir_ncas(path):
    """The .nca files of a folder, or of the one folder it holds (a zip's top folder unpacked)."""
    try:
        here = [os.path.join(path, n) for n in sorted(os.listdir(path))]
    except OSError:
        return []
    ncas = [p for p in here if p.lower().endswith(".nca") and os.path.isfile(p)]
    if ncas:
        return ncas
    subs = [p for p in here if os.path.isdir(p) and not os.path.basename(p).startswith(".")]
    return _dir_ncas(subs[0]) if len(subs) == 1 else []


def _has_game(names):
    return any(n.lower().endswith((".nsp", ".xci")) for n in names)


def is_firmware(path):
    """A zip or folder holding a firmware: FIRMWARE_MIN .nca files or more, and no game."""
    if os.path.isdir(path):
        names = []
        for d, _, files in os.walk(path):
            names += files
        return _has_game(names) is False and len(_dir_ncas(path)) >= FIRMWARE_MIN
    if path.lower().endswith(".zip"):
        ncas = _zip_ncas(path)
        if not ncas or len(ncas) < FIRMWARE_MIN:
            return False
        import zipfile
        with zipfile.ZipFile(path) as z:
            return not _has_game(z.namelist())
    return False


def firmware_dir():
    from . import bios
    return os.path.join(bios.install_dir(), "switch", "firmware")


def find_firmware(folder=None):
    """The user's firmware: (kind "zip"|"dir", path, label) from Emulation/bios/switch/firmware,
    or None. A folder of .nca files wins over a zip; of several zips, the newest."""
    folder = folder or firmware_dir()
    if not os.path.isdir(folder):
        return None
    if len(_dir_ncas(folder)) >= FIRMWARE_MIN:
        d = os.path.dirname(_dir_ncas(folder)[0])
        return ("dir", d, os.path.basename(d) if d != folder else "firmware")
    zips = sorted((os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(".zip")),
                  key=lambda p: os.path.getmtime(p), reverse=True)
    for z in zips:
        if is_firmware(z):
            return ("zip", z, os.path.basename(z)[:-4])
    return None


def _identity(found):
    import hashlib
    kind, path, _ = found
    if kind == "dir":
        items = sorted((os.path.basename(p), os.path.getsize(p)) for p in _dir_ncas(path))
    else:
        import zipfile
        with zipfile.ZipFile(path) as z:
            items = sorted((i.filename, i.file_size) for i in z.infolist())
    return hashlib.sha1(repr(items).encode()).hexdigest()


def _ryujinx_name(name):
    """Ryujinx's folder name for an NCA: "<id>.nca" ("abc.cnmt.nca" -> "abc.nca")."""
    return name.split(".", 1)[0] + ".nca"


def _put(src, dst):
    """A firmware file into place: a hard link when it's on the same disk (it's read only),
    otherwise a copy."""
    import shutil
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def installed_firmware(registered):
    """The label of the firmware Kettle put in `registered` (its marker), "installed" for one
    put there another way, or None."""
    try:
        if not any(os.scandir(registered)):
            return None
    except OSError:
        return None
    try:
        with open(os.path.join(os.path.dirname(registered), MARKER)) as f:
            return f.read().split("\n", 2)[1] or "installed"
    except (OSError, IndexError):
        return "installed"


def install_firmware(layout, registered, folder=None):
    """The user's firmware into an emulator's `registered` folder, laid out as `layout`
    ("ryujinx" or "eden") does it. Staged beside it and swapped in whole, so two versions are
    never mixed; done again only when the firmware changes. Returns the label installed, None
    when there's no firmware to install."""
    import shutil
    import zipfile
    found = find_firmware(folder)
    if not found:
        return None
    ident = _identity(found)
    contents = os.path.dirname(registered)
    marker = os.path.join(contents, MARKER)
    try:
        with open(marker) as f:
            if f.read().split("\n", 1)[0] == ident and any(os.scandir(registered)):
                return found[2]
    except OSError:
        pass
    os.makedirs(contents, exist_ok=True)
    stage, old = os.path.join(contents, ".kettle-firmware-new"), os.path.join(contents, ".kettle-firmware-old")
    for d in (stage, old):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(stage)

    def target(name):
        if layout == "ryujinx":
            d = os.path.join(stage, _ryujinx_name(name))
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, "00")
        return os.path.join(stage, name)

    try:
        if found[0] == "dir":
            for p in _dir_ncas(found[1]):
                _put(p, target(os.path.basename(p)))
        else:
            with zipfile.ZipFile(found[1]) as z:
                for member, name in _zip_ncas(found[1]):
                    with z.open(member) as src, open(target(name), "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
        if os.path.isdir(registered):
            os.rename(registered, old)
        os.rename(stage, registered)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        if os.path.isdir(old) and not os.path.exists(registered):
            os.rename(old, registered)
        raise
    shutil.rmtree(old, ignore_errors=True)
    tmp = marker + ".tmp"
    with open(tmp, "w") as f:
        f.write(f"{ident}\n{found[2]}\n")
    os.replace(tmp, marker)
    return found[2]
