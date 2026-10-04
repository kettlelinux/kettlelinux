# Which engine a game is built on, from the files in its install folder, and the platform
# (a Windows build, run through Proton, or a native Linux one) and CPU of its main program. Game Settings shows it and sends it with settings shared to the
# game database (server/game-db), so FEX defaults per engine can come from what works;
# kettle-crashd puts it in crash reports. Engine ids and labels: engines.json, next to this.
#
# Only names are looked at (plus the first bytes of programs: PE and ELF headers), at most MAX_DEPTH folders down and
# MAX_ENTRIES entries, so a scan of a big game on an SD card stays well under a second.
# No imports beyond the standard library: kettle-crashd runs it as root outside Decky.
#
#   python3 gameengine.py <install folder>   prints what it found as JSON
import json
import os
import re
import struct
import sys

MAX_DEPTH = 4
MAX_ENTRIES = 20000
MAX_PROBES = 300  # files without an extension whose first bytes are read (a Linux build's program?)
# folders full of assets, never holding an engine's signature files
_SKIP_DIRS = re.compile(
    r"^(streamingassets|paks|movies|videos?|sounds?|audio|music|localization|textures|maps|"
    r"img|fonts|__pycache__|\.git|shadercache|logs|saves?|mods)$", re.I)

# (engine, pattern on a lowercased path relative to the install folder, / separated); the
# first engine with a match wins, so the more specific ones come first. Folders end in /.
_SIGNATURES = [
    ("unity", r"(^|/)unityplayer\.(dll|so)$|(^|/)[^/]+_data/(globalgamemanagers|data\.unity3d|maindata)$"),
    ("unreal-3", r"(^|/)[^/]*game/cookedpc(console)?/$"),
    ("unreal", r"(^|/)engine/binaries/$|-(win64|win32|wingdk)-shipping\.exe$|-linux(arm64)?-shipping$"),
    ("source2", r"(^|/)game/bin/win64/$|(^|/)gameinfo\.gi$"),
    ("source", r"(^|/)bin/(win64/|linux64/)?engine(_client)?\.(dll|so)$"),
    ("gamemaker", r"(^|/)(data\.win|game\.unx)$"),
    ("renpy", r"(^|/)renpy/$"),
    ("rpgmaker-mz", r"(^|/)js/rmmz_core\.js$"),
    ("rpgmaker-mv", r"(^|/)js/rpg_core\.js$"),
    ("rpgmaker-rgss", r"(^|/)rgss\d{2,3}[a-z]?\.dll$|(^|/)game\.rgss(ad|2a|3a)$"),
    ("nwjs", r"(^|/)(nw\.dll|nw_elf\.dll|package\.nw)$"),
    ("electron", r"(^|/)resources/(app|electron)\.asar$|(^|/)resources/app/package\.json$"),
    ("cryengine", r"(^|/)crysystem\.dll$"),
    ("re-engine", r"(^|/)re_chunk_000\.pak$"),
    ("frostbite", r"(^|/)data/layout\.toc$"),
    ("redengine", r"(^|/)archive/pc/content/$|(^|/)content/content0/$"),
    ("creation", r"(^|/)data/[^/]+\.esm$"),
    ("fna", r"(^|/)fna\.dll$"),
    ("monogame", r"(^|/)monogame\.framework\.dll$"),
    ("xna", r"(^|/)microsoft\.xna\.framework[^/]*\.dll$"),
    ("java", r"(^|/)(jre|jdk|java|runtime)[^/]*/bin/javaw?\.exe$"),
    # .NET Core / 5+: the exe is a native app host, without the CLR header older .NET exes have
    ("dotnet", r"(^|/)[^/]+\.runtimeconfig\.json$"),
]
_SIGNATURES = [(e, re.compile(p)) for e, p in _SIGNATURES]
# Godot: a .pck next to an exe of the same name (other .pck files are Wwise sound banks)
_CEF = re.compile(r"(^|/)libcef\.dll$")
_ANTICHEAT = [
    ("eac", re.compile(r"(^|/)easyanticheat[^/]*/$|(^|/)easyanticheat[^/]*\.(exe|dll|sys)$|"
                       r"(^|/)start_protected_game\.exe$")),
    ("battleye", re.compile(r"(^|/)battleye/$|_be\.exe$|(^|/)beclient[^/]*\.dll$")),
]
# exes that aren't the game
_NOT_GAME = re.compile(
    r"unins|setup|install|redist|dxweb|directx|crash|report|uploader|prereq|easyanticheat|"
    r"beservice|battleye|start_protected_game|notification_helper|helper$|oalinst|physx|dotnet|"
    r"touchup|cleanup|^java|^python|^7z|^nwjc|^cefsharp|^qtwebengineprocess|^ue4?prereq|"
    r"subprocess|^crs-|^vc_?redist|^launcherpatcher|_be$|^createdump$|^crashpad_handler$|"
    r"server(\.bin)?$", re.I)

_PE_MACHINES = {0x14c: "x86", 0x8664: "x86_64", 0xaa64: "arm64", 0xa641: "arm64ec"}
_ELF_MACHINES = {0x03: "x86", 0x3E: "x86_64", 0xB7: "arm64"}
# what a native Linux build's executable is called: no extension, or one of these
_LINUX_EXE = re.compile(r"^[^.]+$|\.(x86_64|x86|bin|aarch64|arm64)$", re.I)
_STEM = re.compile(r"\.(exe|x86_64|x86|bin|aarch64|arm64)$", re.I)


def _is_elf_exe(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            h = f.read(18)
    except OSError:
        return False
    return len(h) == 18 and h[:4] == b"\x7fELF" and h[5] == 1 and struct.unpack_from("<H", h, 16)[0] in (2, 3)


def _listing(root: str) -> tuple[list[str], dict[str, tuple[int, str]]]:
    """Paths under root, lowercased and relative (folders end in /), and the programs in it:
    {path: (size, "windows" or "linux")}."""
    paths, bins = [], {}
    probes = MAX_PROBES
    stack = [("", 0)]
    while stack and len(paths) < MAX_ENTRIES:
        rel, depth = stack.pop()
        try:
            it = os.scandir(os.path.join(root, rel))
        except OSError:
            continue
        with it:
            for e in it:
                r = f"{rel}{e.name}"
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    paths.append(r.lower() + "/")
                    if depth + 1 < MAX_DEPTH and not _SKIP_DIRS.match(e.name):
                        stack.append((r + "/", depth + 1))
                else:
                    paths.append(r.lower())
                    kind = None
                    if e.name.lower().endswith(".exe"):
                        kind = "windows"
                    elif probes and _LINUX_EXE.search(e.name):
                        probes -= 1
                        kind = "linux" if _is_elf_exe(e.path) else None
                    if kind:
                        try:
                            bins[r] = (e.stat(follow_symlinks=False).st_size, kind)
                        except OSError:
                            pass
                if len(paths) >= MAX_ENTRIES:
                    break
    return paths, bins


def binary_info(path: str) -> dict:
    """A program's platform (windows: PE, linux: ELF), machine, and whether it's .NET."""
    none = {"platform": "", "arch": "", "dotnet": False}
    try:
        with open(path, "rb") as f:
            head = f.read(64)
            if head[:4] == b"\x7fELF":
                if len(head) < 20 or head[5] != 1:  # little-endian only
                    return none
                machine = struct.unpack_from("<H", head, 18)[0]
                return {"platform": "linux", "arch": _ELF_MACHINES.get(machine, ""), "dotnet": False}
            if len(head) < 64 or head[:2] != b"MZ":
                return none
            f.seek(struct.unpack_from("<I", head, 0x3C)[0])
            hdr = f.read(24 + 240)
    except OSError:
        return none
    if len(hdr) < 26 or hdr[:4] != b"PE\0\0":
        return none
    machine = struct.unpack_from("<H", hdr, 4)[0]
    opt = hdr[24:]
    magic = struct.unpack_from("<H", opt, 0)[0] if len(opt) >= 2 else 0
    dirs = {0x10B: 96, 0x20B: 112}.get(magic)
    dotnet = False
    if dirs is not None and len(opt) >= dirs + 15 * 8:
        dotnet = struct.unpack_from("<II", opt, dirs + 14 * 8)[1] > 0  # CLR runtime header
    return {"platform": "windows", "arch": _PE_MACHINES.get(machine, ""), "dotnet": dotnet}


def _stem(rel: str) -> str:
    return _STEM.sub("", rel.lower())


def _main_exe(root: str, paths: list[str], bins: dict[str, tuple[int, str]], engine: str) -> str | None:
    """The game's own program: the engine's, else the biggest one nearest the top that isn't an
    installer, crash reporter, server or anti-cheat. A Windows build's when there's one (that's
    what Steam runs through Proton), else a native Linux build's. .NET exes next to native Linux
    programs are a Linux build's (Mono runs them: Terraria's Terraria.bin.x86_64 runs
    Terraria.exe), so the Linux program is the one named like them."""
    game = lambda rs: [r for r in rs if not _NOT_GAME.search(os.path.basename(_stem(r)))]
    win = [r for r, (_, k) in bins.items() if k == "windows"]
    linux = [r for r, (_, k) in bins.items() if k == "linux"]
    cands = win if game(win) else linux or win
    if game(win) and game(linux) and all(binary_info(os.path.join(root, r))["dotnet"] for r in game(win)):
        stems = {_stem(r) for r in game(win)}
        cands = [r for r in game(linux) if _stem(r).split(".")[0] in stems] or linux
    if not cands:
        return None
    size = lambda r: bins[r][0]
    have = set(paths)
    picks = {
        "unreal": lambda r: re.search(r"-(win64|win32|wingdk|linux|linuxarm64)-shipping(\.exe)?$", r, re.I)
        and not r.lower().startswith("engine/"),
        "unity": lambda r: f"{_stem(r)}_data/" in have,
        "gamemaker": lambda r: any(f"{os.path.dirname(r.lower())}/{d}".lstrip("/") in have
                                   for d in ("data.win", "assets/game.unx", "game.unx")),
        "godot": lambda r: _stem(r) + ".pck" in have,
        "source2": lambda r: re.search(r"(^|/)game/bin/(win64|linuxsteamrt64)/[^/]+$", r, re.I),
    }
    pick = picks.get(engine.split("-")[0] if engine.startswith("unity") else engine)
    # a .NET Core / 5+ program has its <name>.runtimeconfig.json next to it
    dotnet = lambda r: f"{_stem(r)}.runtimeconfig.json" in have
    for p in (pick, dotnet):
        own = [r for r in cands if p and p(r)]
        if own:
            return max(own, key=size)
    # a launcher is often the exe at the top, with the game's own further down
    return min(game(cands) or cands, key=lambda r: ("launcher" in r.lower(), _depth(r), -size(r)))


def _depth(rel: str) -> int:
    return rel.count("/")


def detect(root: str) -> dict:
    """{"engine": id (engines.json), "platform": windows or linux (or "": no program found),
    "arch": the main program's machine, "exe": it, relative to root, or None,
    "anticheat": [ids]}."""
    paths, bins = _listing(root)
    engine = None
    for e, rx in _SIGNATURES:
        if any(rx.search(p) for p in paths):
            engine = e
            break
    if engine is None and any(p.endswith(".pck") and p[:-4] in {_stem(b) for b in bins} for p in paths):
        engine = "godot"
    if engine == "unity":
        il2cpp = any(re.search(r"(^|/)gameassembly\.(dll|so)$|_data/il2cpp_data/$", p) for p in paths)
        engine = "unity-il2cpp" if il2cpp else "unity-mono"
    exe = _main_exe(root, paths, bins, engine or "")
    info = binary_info(os.path.join(root, exe)) if exe else {"platform": "", "arch": "", "dotnet": False}
    if engine is None:
        if info["dotnet"]:
            engine = "dotnet"
        elif any(_CEF.search(p) for p in paths):
            engine = "cef"
        else:
            engine = "unknown"
    return {
        "engine": engine,
        "platform": info["platform"],
        "arch": info["arch"],
        "exe": exe,
        "anticheat": [a for a, rx in _ANTICHEAT if any(rx.search(p) for p in paths)],
    }


if __name__ == "__main__":
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        sys.exit("usage: gameengine.py <install folder>")
    print(json.dumps(detect(sys.argv[1])))
