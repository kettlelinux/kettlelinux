# python3 -m unittest shared/test_gameengine.py (from packages/kettle-decky-plugins)
import json
import os
import struct
import tempfile
import unittest

import gameengine

HERE = os.path.dirname(os.path.abspath(__file__))


def pe(machine=0x8664, dotnet=False, size=0):
    """A PE header gameengine.binary_info can read: MZ, PE signature, file and optional header."""
    opt_size = 240 if machine == 0x8664 else 224
    magic = 0x20B if machine == 0x8664 else 0x10B
    dirs = 112 if magic == 0x20B else 96
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, magic)
    if dotnet:
        struct.pack_into("<II", opt, dirs + 14 * 8, 0x2000, 0x48)
    head = bytearray(64)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 64)
    coff = struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, opt_size, 0)
    return bytes(head) + b"PE\0\0" + coff + bytes(opt) + bytes(size)


def elf(machine=0x3E, etype=2, size=0):
    """An ELF header: magic, 64-bit little-endian, type and machine."""
    return b"\x7fELF\x02\x01\x01" + bytes(9) + struct.pack("<HH", etype, machine) + bytes(44 + size)


# engine: (files, which exe is the game's, its arch); an exe's content is its PE header
CASES = {
    "unity-il2cpp": ({"Game.exe": pe(size=100), "GameAssembly.dll": b"", "UnityPlayer.dll": b"",
                      "Game_Data/il2cpp_data/Metadata/global-metadata.dat": b"",
                      "UnityCrashHandler64.exe": pe(size=5000)}, "Game.exe", "x86_64"),
    "unity-mono": ({"Game.exe": pe(), "UnityPlayer.dll": b"", "Game_Data/Managed/Assembly-CSharp.dll": b"",
                    "MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll": b""}, "Game.exe", "x86_64"),
    "unreal": ({"Game.exe": pe(size=10), "Game/Binaries/Win64/Game-Win64-Shipping.exe": pe(size=900),
                "Engine/Binaries/ThirdParty/x.dll": b"", "Engine/Extras/Redist/en-us/UE4PrereqSetup_x64.exe": pe()},
               "Game/Binaries/Win64/Game-Win64-Shipping.exe", "x86_64"),
    "unreal-3": ({"Binaries/Win32/BorderlandsGame.exe": pe(0x14c), "WillowGame/CookedPCConsole/x.upk": b"",
                  "Engine/Config/BaseEngine.ini": b""}, "Binaries/Win32/BorderlandsGame.exe", "x86"),
    "source": ({"hl2.exe": pe(0x14c), "bin/engine.dll": b"", "hl2/gameinfo.txt": b""}, "hl2.exe", "x86"),
    "source2": ({"game/bin/win64/cs2.exe": pe(), "game/csgo/gameinfo.gi": b""}, "game/bin/win64/cs2.exe", "x86_64"),
    "godot": ({"Game.exe": pe(), "Game.pck": b""}, "Game.exe", "x86_64"),
    "gamemaker": ({"Game.exe": pe(0x14c), "data.win": b"", "options.ini": b""}, "Game.exe", "x86"),
    "renpy": ({"Game.exe": pe(0x14c), "renpy/__init__.py": b"", "game/script.rpyc": b""}, "Game.exe", "x86"),
    "rpgmaker-mz": ({"Game.exe": pe(), "nw.dll": b"", "js/rmmz_core.js": b""}, "Game.exe", "x86_64"),
    "rpgmaker-mv": ({"Game.exe": pe(), "nw.dll": b"", "www/js/rpg_core.js": b""}, "Game.exe", "x86_64"),
    "rpgmaker-rgss": ({"Game.exe": pe(0x14c), "System/RGSS301.dll": b"", "Game.rgss3a": b""}, "Game.exe", "x86"),
    "nwjs": ({"Game.exe": pe(), "nw.dll": b"", "package.nw": b""}, "Game.exe", "x86_64"),
    "electron": ({"Game.exe": pe(), "resources/app.asar": b"", "ffmpeg.dll": b""}, "Game.exe", "x86_64"),
    "cryengine": ({"Bin64/Game.exe": pe(), "Bin64/CrySystem.dll": b""}, "Bin64/Game.exe", "x86_64"),
    "re-engine": ({"re2.exe": pe(), "re_chunk_000.pak": b""}, "re2.exe", "x86_64"),
    "frostbite": ({"bf4.exe": pe(), "Data/layout.toc": b""}, "bf4.exe", "x86_64"),
    "redengine": ({"REDprelauncher.exe": pe(size=10), "bin/x64/witcher3.exe": pe(size=900),
                   "content/content0/texture.cache": b""}, "bin/x64/witcher3.exe", "x86_64"),
    "creation": ({"SkyrimSE.exe": pe(size=900), "SkyrimSELauncher.exe": pe(size=10), "Data/Skyrim.esm": b""},
                 "SkyrimSE.exe", "x86_64"),
    "fna": ({"Game.exe": pe(0x14c, dotnet=True), "FNA.dll": b""}, "Game.exe", "x86"),
    "monogame": ({"Game.exe": pe(0x14c, dotnet=True), "MonoGame.Framework.dll": b""}, "Game.exe", "x86"),
    "xna": ({"Game.exe": pe(0x14c, dotnet=True), "Microsoft.Xna.Framework.Game.dll": b""}, "Game.exe", "x86"),
    "dotnet": ({"Game.exe": pe(0x14c, dotnet=True), "Newtonsoft.Json.dll": b""}, "Game.exe", "x86"),
    "java": ({"Game.exe": pe(), "jre/bin/javaw.exe": pe(size=900), "game.jar": b""}, "Game.exe", "x86_64"),
    "cef": ({"Game.exe": pe(), "libcef.dll": b""}, "Game.exe", "x86_64"),
    "unknown": ({"bin/Game.exe": pe(size=900), "unins000.exe": pe(0x14c), "Audio/Banks/Init.pck": b""},
                "bin/Game.exe", "x86_64"),
}


# native Linux builds: (engine, files, the game's program, its arch)
LINUX = [
    ("unity-il2cpp", {"ClearedHot": elf(), "ClearedHot_Data/globalgamemanagers": b"", "GameAssembly.so": elf(etype=3),
                      "UnityPlayer.so": elf(etype=3), "libdecor-0.so.0": elf(etype=3)}, "ClearedHot", "x86_64"),
    ("godot", {"Game.x86_64": elf(size=900), "Game.pck": b"", "crashpad_handler": elf()}, "Game.x86_64", "x86_64"),
    ("unreal", {"Game.sh": b"#!/bin/sh", "Game/Binaries/Linux/Game-Linux-Shipping": elf()},
     "Game/Binaries/Linux/Game-Linux-Shipping", "x86_64"),
    ("gamemaker", {"runner": elf(0x03), "assets/game.unx": b""}, "runner", "x86"),
    # Stardew Valley 1.6: .NET 6, the app host smaller than .NET's createdump next to it
    ("monogame", {"Stardew Valley": elf(size=100), "Stardew Valley.runtimeconfig.json": b"", "StardewValley": b"#!/bin/sh",
                  "createdump": elf(size=900), "MonoGame.Framework.dll": b""}, "Stardew Valley", "x86_64"),
    ("dotnet", {"Game": elf(size=10), "Game.runtimeconfig.json": b"", "Game.dll": b"", "Tool": elf(size=900)},
     "Game", "x86_64"),
    # Terraria: Mono runs the .NET exe from a native program named like it; a server next to it
    ("fna", {"Terraria": b"#!/bin/bash", "Terraria.bin.x86_64": elf(size=500), "Terraria.exe": pe(0x14c, dotnet=True, size=900),
             "TerrariaServer.bin.x86_64": elf(size=500), "TerrariaServer.exe": pe(0x14c, dotnet=True), "FNA.dll": b""},
     "Terraria.bin.x86_64", "x86_64"),
    ("unknown", {"game.arm64": elf(0xB7), "readme": b"plain text"}, "game.arm64", "arm64"),
]


class Detect(unittest.TestCase):
    def tree(self, files):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        for rel, data in files.items():
            p = os.path.join(d, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
        return d

    def test_engines(self):
        for engine, (files, exe, arch) in CASES.items():
            with self.subTest(engine):
                r = gameengine.detect(self.tree(files))
                self.assertEqual((r["engine"], r["exe"], r["arch"], r["platform"]), (engine, exe, arch, "windows"))

    def test_linux_builds(self):
        for engine, files, exe, arch in LINUX:
            with self.subTest(engine):
                r = gameengine.detect(self.tree(files))
                self.assertEqual((r["engine"], r["exe"], r["arch"], r["platform"]), (engine, exe, arch, "linux"))

    def test_windows_build_over_linux_helpers(self):
        r = gameengine.detect(self.tree({"Game.exe": pe(), "helper": elf()}))
        self.assertEqual((r["exe"], r["platform"]), ("Game.exe", "windows"))

    def test_windows_dotnet_build_without_linux_programs(self):
        r = gameengine.detect(self.tree({"Terraria.exe": pe(0x14c, dotnet=True), "FNA.dll": b""}))
        self.assertEqual((r["exe"], r["platform"], r["arch"]), ("Terraria.exe", "windows", "x86"))

    def test_every_engine_has_a_case_and_a_label(self):
        with open(os.path.join(HERE, "engines.json"), encoding="utf-8") as f:
            known = {e["id"] for e in json.load(f)["engines"]}
        self.assertEqual(set(CASES), known)

    def test_anticheat(self):
        r = gameengine.detect(self.tree({"Game.exe": pe(), "EasyAntiCheat/EasyAntiCheat_EOS_Setup.exe": pe(),
                                         "BattlEye/BEClient_x64.dll": b"", "Game_BE.exe": pe()}))
        self.assertEqual((r["anticheat"], r["exe"]), (["eac", "battleye"], "Game.exe"))

    def test_nested_one_folder_down(self):
        r = gameengine.detect(self.tree({"Game/Game.exe": pe(), "Game/UnityPlayer.dll": b"",
                                         "Game/Game_Data/Managed/x.dll": b""}))
        self.assertEqual((r["engine"], r["exe"]), ("unity-mono", "Game/Game.exe"))

    def test_nothing_there(self):
        self.assertEqual(gameengine.detect(self.tree({"readme.txt": b""})),
                         {"engine": "unknown", "platform": "", "arch": "", "exe": None, "anticheat": []})

    def test_not_a_pe(self):
        self.assertEqual(gameengine.binary_info(os.path.join(self.tree({"x.exe": b"MZ"}), "x.exe")),
                         {"platform": "", "arch": "", "dotnet": False})


if __name__ == "__main__":
    unittest.main()
