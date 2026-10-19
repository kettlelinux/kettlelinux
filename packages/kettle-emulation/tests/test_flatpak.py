"""The Flathub emulators: systems.json v2, the per-emulator layouts and key maps, every keeper's
files, the new systems' detection, PS3 game folders, and emu-run's Flatpak side."""
import json
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest import mock

from helpers import PKG, Env, cooked_disc, pvd

import mkvdf  # noqa: E402  (helpers puts the package on sys.path)
from kettle_emulation import identify, importer, keys, run, seed, systems

with open(os.path.join(PKG, "systems.json")) as f:
    DB = json.load(f)


class Schema(unittest.TestCase):
    def test_version_and_kinds(self):
        self.assertEqual(DB["version"], 2)
        for eid, e in DB["emulators"].items():
            self.assertIn(e["kind"], ("libretro", "flatpak"), eid)
            self.assertIsInstance(e["free"], bool, eid)
            self.assertTrue(e["license"], eid)
            self.assertTrue(set(e["hotkeys"]) <= set(keys.STANDARD), eid)
            # xemu's saves live in its hard disk image, which isn't a file to back up or delete
            self.assertTrue(e["saves"] or eid == "xemu", eid)
            for s in e["saves"]:
                self.assertFalse(os.path.isabs(s["dir"]), eid)
                self.assertFalse(s["dir"].startswith("Emulation/bios"), eid)
            if e["kind"] == "libretro":
                self.assertTrue(e["core"], eid)
                self.assertIn(eid, DB["flatpaks"][systems.RETROARCH]["for"])
            else:
                self.assertIn("{rom}", e["exec"], eid)
                self.assertIn(eid, DB["flatpaks"][e["flatpak"]]["for"], eid)
            if "keys" in e:
                self.assertEqual(set(e["keys"]), set(e["hotkeys"]), eid)
            for n in e.get("needs", ()):
                self.assertTrue(isinstance(n, str) or n.get("text"), eid)

    def test_systems_and_flatpaks(self):
        for sid, s in DB["systems"].items():
            self.assertTrue(s["emulators"], sid)
            for e in s["emulators"]:
                self.assertIn(e, DB["emulators"], sid)
        for app, f in DB["flatpaks"].items():
            self.assertTrue(f["name"] and f["license"] and f["for"], app)
            self.assertTrue(all(p.startswith("--") for p in f["permissions"]), app)
            for e in f["for"]:
                self.assertEqual(systems.flatpak_of(DB["emulators"][e]), app)

    def test_licenses(self):
        for core in ("snes9x", "genesis_plus_gx", "picodrive", "fbneo", "mame2003_plus", "bluemsx"):
            self.assertFalse(DB["emulators"]["ra-" + core]["free"], core)
        self.assertTrue(DB["emulators"]["ra-mgba"]["free"])

    def test_new_systems(self):
        s = DB["systems"]
        self.assertEqual(s["ps2"]["emulators"], ["play"])
        self.assertEqual(s["ps3"]["emulators"], ["rpcs3"])
        self.assertEqual(s["xbox"]["emulators"], ["xemu"])
        self.assertEqual(s["switch"]["emulators"], ["ryujinx", "eden"])
        self.assertEqual(s["n3ds"]["emulators"], ["azahar"])
        self.assertEqual(s["nds"]["emulators"][0], "ra-melondsds")
        self.assertEqual(s["ps3"]["game_folders"]["marker"], "PS3_GAME/PARAM.SFO")


class Layouts(unittest.TestCase):
    def test_files(self):
        out = mkvdf.layouts(DB)
        keyed = {e for e, v in DB["emulators"].items() if "keys" in v}
        self.assertEqual(keyed, {"melonds", "play", "xemu"})
        want = {f"emulation-{f}.vdf" for f in ("xbox", "nintendo")} | {
            f"emulation-{f}-{e}.vdf" for f in ("xbox", "nintendo") for e in keyed}
        self.assertEqual(set(out), want)
        for name, text in out.items():
            self.assertEqual(text.count("{"), text.count("}"), name)

    def test_keyed_layouts_send_their_own_chords(self):
        out = mkvdf.layouts(DB)
        xemu = out["emulation-xbox-xemu.vdf"]
        self.assertIn('"key_press LEFT_SHIFT, , "', xemu)
        self.assertIn('"key_press F5, , "', xemu)
        self.assertNotIn("key_press F6", xemu)  # no state slots in xemu
        self.assertNotIn("key_press F2", xemu)  # F2 opens xemu's popup menu
        play = out["emulation-xbox-play.vdf"]
        self.assertIn('"key_press LEFT_CONTROL, , "', play)
        self.assertNotIn("key_press ESCAPE", play)  # Esc only leaves fullscreen there
        melonds = out["emulation-nintendo-melonds.vdf"]
        self.assertNotIn("key_press F9", melonds)  # its load-from-file shortcut
        self.assertIn("key_press F10", melonds)

    def test_standard_layout_unchanged(self):
        # the layout tested on the Portal: 10 hotkeys, swap screens on both d-pad sides
        self.assertEqual(mkvdf.layout("xbox").count("key_press"), 11)
        self.assertEqual(mkvdf.layout("xbox"), mkvdf.layout("xbox", keys.keymap()))

    @mock.patch.dict(os.environ, KETTLE_EMU_SYSTEMS=os.path.join(PKG, "systems.json"))
    def test_layout_names(self):
        self.assertEqual(systems.layout("xemu", "nintendo"),
                         "local:///usr/share/kettle/emulation/emulation-nintendo-xemu.vdf")
        self.assertEqual(systems.layout("ppsspp", "xbox"),
                         "local:///usr/share/kettle/emulation/emulation-xbox.vdf")


class KeyMaps(unittest.TestCase):
    def test_keymaps(self):
        self.assertEqual(keys.keymap()["quit"], ["ESCAPE"])
        play = keys.keymap(DB["emulators"]["play"])
        self.assertEqual(play["save_state"], ["LEFT_CONTROL", "LEFT_SHIFT", "1"])
        self.assertNotIn("fast_forward", play)
        self.assertEqual(keys.evdev("LEFT_CONTROL"), "KEY_LEFTCTRL")
        self.assertEqual(keys.evdev("ESCAPE"), "KEY_ESC")
        self.assertEqual(keys.ACTIONS["quit"], "KEY_ESC")

    def test_every_key_name_is_an_evdev_key(self):
        try:
            from evdev import ecodes
        except ImportError:
            self.skipTest("python-evdev isn't installed here")
        for e in [None] + list(DB["emulators"].values()):
            for chord in keys.keymap(e).values():
                for k in chord:
                    self.assertTrue(hasattr(ecodes, keys.evdev(k)), k)


KEEPER = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from kettle_emulation import seed
for name in sys.argv[2:]:
    seed.KEEPERS[name]()
"""


class Keepers(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="kettle-keepers-")
        self.app = lambda *p: os.path.join(self.home, ".var/app", *p)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.home, ignore_errors=True)

    def keep(self, *names):
        env = dict(os.environ, HOME=self.home, KETTLE_EMU_SYSTEMS=os.path.join(PKG, "systems.json"))
        subprocess.run([sys.executable, "-c", KEEPER, PKG, *names], env=env, check=True)

    def read(self, *p):
        with open(self.app(*p), encoding="utf-8") as f:
            return f.read()

    def test_all_keepers_write_their_files(self):
        self.keep(*seed.KEEPERS)
        for p in ("org.ppsspp.PPSSPP/config/ppsspp/PSP/SYSTEM/controls.ini",
                  "org.DolphinEmu.dolphin-emu/config/dolphin-emu/Hotkeys.ini",
                  "net.kuribo64.melonDS/config/melonDS/melonDS.toml",
                  "org.purei.Play/config/Play Data Files/config.xml",
                  "net.rpcs3.RPCS3/config/rpcs3/GuiConfigs/CurrentSettings.ini",
                  "net.rpcs3.RPCS3/config/rpcs3/config.yml",
                  "app.xemu.xemu/data/xemu/xemu/xemu.toml",
                  "dev.eden_emu.eden/config/eden/qt-config.ini",
                  "org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini"):
            self.assertTrue(os.path.isfile(self.app(p)), p)
        # Ryujinx: nothing until Ryujinx has written its own config
        self.assertFalse(os.path.exists(self.app("io.github.ryubing.Ryujinx/config/Ryujinx/Config.json")))

    def test_qt_hotkeys(self):
        self.keep("eden", "azahar")
        eden = self.read("dev.eden_emu.eden/config/eden/qt-config.ini")
        self.assertIn("Shortcuts\\Main%20Window\\Exit%20Eden\\KeySeq=Esc", eden)
        # a "/" in a name is a group level (AdjustKey): F4 and F2 leave pause and amiibo
        self.assertIn("Shortcuts\\Main%20Window\\Continue\\Pause%20Emulation\\KeySeq=F1", eden)
        self.assertIn("Shortcuts\\Main%20Window\\Load\\Remove%20Amiibo\\KeySeq=\n", eden)
        self.assertIn("Shortcuts\\Main%20Window\\Exit%20Fullscreen\\KeySeq=\n", eden)
        self.assertIn("confirmStop=2", eden)
        az = self.read("org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini")
        self.assertIn("Shortcuts\\Main%20Window\\Quick%20Save\\KeySeq=F2", az)
        self.assertIn("Shortcuts\\Main%20Window\\Restart%20Emulation\\KeySeq=\n", az)
        self.assertIn("confirmClose=false", az)
        self.assertIn("[Miscellaneous]\ncheck_for_update_on_start=false", az)

    def test_melonds_upstream_keys(self):
        self.keep("melonds")
        with open(self.app("net.kuribo64.melonDS/config/melonDS/melonDS.toml"), "rb") as f:
            conf = tomllib.load(f)
        kb = conf["Instance0"]["Keyboard"]
        self.assertEqual(kb["HK_FrameLimitToggle"], 0x20)
        self.assertEqual(kb["HK_SwapScreens"], seed.QT_KEY["F10"])
        self.assertNotIn("HK_SaveState", kb)
        self.assertTrue(conf["Instance0"]["SaveFilePath"].endswith("Emulation/saves/melonds"))

    def test_xemu_and_play_and_rpcs3(self):
        self.keep("xemu", "play", "rpcs3")
        with open(self.app("app.xemu.xemu/data/xemu/xemu/xemu.toml"), "rb") as f:
            x = tomllib.load(f)
        self.assertEqual(x["general"]["snapshots"]["shortcuts"]["f5"], "kettle")
        self.assertTrue(x["display"]["window"]["fullscreen_on_startup"])
        self.assertTrue(x["sys"]["files"]["bootrom_path"].endswith("Emulation/bios/xbox/mcpx_1.0.bin"))
        play = self.read("org.purei.Play/config/Play Data Files/config.xml")
        self.assertIn('Name="ui.showexitconfirmation" Type="boolean" Value="false"', play)
        # Play!'s parser takes double quotes only
        self.assertTrue(play.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<Config>'), play[:60])
        self.assertNotIn("'", play.splitlines()[0])
        ini = self.read("net.rpcs3.RPCS3/config/rpcs3/GuiConfigs/CurrentSettings.ini")
        self.assertIn("game_window_stop=Esc", ini)
        self.assertIn("game_window_savestate=\n", ini)
        self.assertIn("game_window_exit_fullscreen=\n", ini)
        yml = self.read("net.rpcs3.RPCS3/config/rpcs3/config.yml")
        self.assertIn("Miscellaneous:\n  Start games in fullscreen mode: true", yml)

    def test_ryujinx_patched_once_it_exists(self):
        path = self.app("io.github.ryubing.Ryujinx/config/Ryujinx/Config.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            json.dump({"version": 70, "show_confirm_exit": True,
                       "hotkeys": {"toggle_vsync": "F1", "toggle_mute": "F2", "show_ui": "F4",
                                   "pause": "F5", "screenshot": "F8"}}, f)
        self.keep("ryujinx")
        with open(path) as f:
            c = json.load(f)
        self.assertEqual(c["version"], 70)
        self.assertFalse(c["show_confirm_exit"])
        self.assertEqual(c["hotkeys"], {"toggle_vsync": "Unbound", "toggle_mute": "Unbound",
                                        "show_ui": "Unbound", "pause": "F1", "screenshot": "F8",
                                        "turbo_mode": "Space"})

    def test_switch_keys_copied(self):
        os.makedirs(os.path.join(self.home, "Emulation/bios/switch"))
        with open(os.path.join(self.home, "Emulation/bios/switch/prod.keys"), "w") as f:
            f.write("header_key = 00\n")
        self.keep("eden", "ryujinx")
        self.assertTrue(os.path.isfile(self.app("dev.eden_emu.eden/data/eden/keys/prod.keys")))
        self.assertTrue(os.path.isfile(self.app("io.github.ryubing.Ryujinx/config/Ryujinx/system/prod.keys")))


class Toml(unittest.TestCase):
    def test_round_trip_with_arrays_of_tables(self):
        d = {"general": {"show_welcome": False, "snapshots": {"shortcuts": {"f5": "kettle"}}},
             "input": {"bindings": {"port1": "abc"},
                       "gamepad_mappings": [{"gamepad_id": "x", "enable_rumble": True,
                                             "controller_mapping": {"a": 1}},
                                            {"gamepad_id": "y"}]},
             "net": {"nat": {"forward_ports": [{"host": 1, "guest": 2, "protocol": "tcp"}]}},
             "odd key": {"x.y": [1, 2], "inline": [{"a": 1}, 3]}}
        self.assertEqual(tomllib.loads(seed.toml_dump(d)), d)

    def test_xemu_keeps_what_it_doesnt_own(self):
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, "xemu.toml")
            with open(path, "w") as f:
                f.write('[input.bindings]\nport1 = "guid"\n\n[[input.gamepad_mappings]]\n'
                        'gamepad_id = "g"\n\n[net.nat]\n[[net.nat.forward_ports]]\nhost = 80\nguest = 8080\n')
            with mock.patch.object(seed, "XEMU_TOML", path), mock.patch.object(seed, "XBOX", home):
                seed.keep_xemu()
            with open(path, "rb") as f:
                x = tomllib.load(f)
        self.assertEqual(x["input"]["gamepad_mappings"], [{"gamepad_id": "g"}])
        self.assertEqual(x["net"]["nat"]["forward_ports"], [{"host": 80, "guest": 8080}])
        self.assertEqual(x["input"]["bindings"]["port1"], "guid")


class Yaml(unittest.TestCase):
    def test_set_yaml_keeps_other_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.yml")
            with open(p, "w") as f:
                f.write("Core:\n  PPU Decoder: Recompiler (LLVM)\nMiscellaneous:\n"
                        "  Start games in fullscreen mode: false\n  Silence All Logs: false\n"
                        "Log: {}\n")
            seed.set_yaml(p, "Miscellaneous", {"Start games in fullscreen mode": "true",
                                               "Exit RPCS3 when process finishes": "true"})
            with open(p) as f:
                text = f.read()
        self.assertEqual(text, "Core:\n  PPU Decoder: Recompiler (LLVM)\nMiscellaneous:\n"
                               "  Start games in fullscreen mode: true\n  Silence All Logs: false\n"
                               "  Exit RPCS3 when process finishes: true\nLog: {}\n")


class Detect(Env):
    def id(self, rel, data):
        return identify.identify(self.write(rel, data))

    def test_ps3_iso(self):
        m = self.id("g.iso", cooked_disc(pvd("PS3VOLUME", files={"PS3_DISC.SFB": b".SFB"})))
        self.assertEqual(m.system, "ps3")

    def test_xbox_xiso(self):
        data = bytearray(0x10000 + 2048)
        data[0x10000:0x10000 + 20] = b"MICROSOFT*XBOX*MEDIA"
        self.assertEqual(self.id("halo.iso", bytes(data)).system, "xbox")
        self.assertEqual(self.id("halo.xiso", bytes(data)).system, "xbox")

    def test_3ds(self):
        data = bytearray(0x200)
        data[0x100:0x104] = b"NCSD"
        self.assertEqual(self.id("zelda.3ds", bytes(data)).system, "n3ds")
        self.assertEqual(identify.by_extension("game.cia").system, "n3ds")
        self.assertEqual(identify.by_extension("game.nsp").system, "switch")

    def test_ps3_game_right_in_the_inbox(self):
        box = os.path.join(self.home, "inbox")
        sfo = bytearray(0x200)
        sfo[:4] = b"\0PSF"
        struct.pack_into("<IIII", sfo, 4, 0x101, 0x40, 0x100, 1)
        struct.pack_into("<HHIII", sfo, 20, 0, 0x0204, 15, 16, 0)
        sfo[0x40:0x46] = b"TITLE\0"
        sfo[0x100:0x10f] = b"Demon's Souls\0\0"
        self.write("PS3_GAME/PARAM.SFO", bytes(sfo), box)
        self.write("PS3_GAME/USRDIR/EBOOT.BIN", b"SCE\0" * 10, box)
        self.write("PS3_DISC.SFB", b".SFB", box)
        self.write("Mario.nes", b"NES\x1a" + b"\0" * 64, box)
        self.assertEqual(importer.sfo_title(os.path.join(box, "PS3_GAME/PARAM.SFO")), "Demon's Souls")
        events = []
        importer.Importer(self.home, "move", events.append).run(box)
        dst = os.path.join(self.home, "roms", "ps3", "Demon's Souls")
        for rel in ("PS3_GAME/PARAM.SFO", "PS3_GAME/USRDIR/EBOOT.BIN", "PS3_DISC.SFB"):
            self.assertTrue(os.path.isfile(os.path.join(dst, rel)), rel)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "roms", "nes", "Mario.nes")))
        # the inbox itself stays; the game's emptied folders go
        self.assertTrue(os.path.isdir(box))
        self.assertFalse(os.path.exists(os.path.join(box, "PS3_GAME")))
        self.assertEqual(sorted((i["kind"], i["system"]) for i in events if i["event"] == "item"),
                         [("game", "nes"), ("game", "ps3")])

    def test_ps3_folder_kept_whole(self):
        src = os.path.join(self.tmp, "stick", "Demon's Souls")
        self.write("PS3_GAME/PARAM.SFO", b"\0PSF", src)
        self.write("PS3_GAME/USRDIR/EBOOT.BIN", b"SCE\0" * 10, src)
        self.write("PS3_DISC.SFB", b".SFB", src)
        events = []
        importer.Importer(self.home, "copy", events.append).run(os.path.join(self.tmp, "stick"))
        dst = os.path.join(self.home, "roms", "ps3", "Demon's Souls")
        for rel in ("PS3_GAME/PARAM.SFO", "PS3_GAME/USRDIR/EBOOT.BIN", "PS3_DISC.SFB"):
            self.assertTrue(os.path.isfile(os.path.join(dst, rel)), rel)
        items = [e for e in events if e["event"] == "item"]
        self.assertEqual([(i["kind"], i["system"]) for i in items], [("game", "ps3")])
        # again: the same game is there already
        events.clear()
        importer.Importer(self.home, "copy", events.append).run(os.path.join(self.tmp, "stick"))
        self.assertEqual([e["action"] for e in events if e["event"] == "item"], ["identical"])


class Launch(Env):
    def test_commands(self):
        emu = DB["emulators"]["eden"]
        self.assertEqual(run.command("switch", emu, "/r/g.nsp"),
                         ["flatpak", "run", "--die-with-parent", "dev.eden_emu.eden",
                          "-f", "-g", "/r/g.nsp"])
        with mock.patch.object(seed, "append_configs", lambda s: "/a.cfg"), \
                mock.patch.object(run, "core_path", lambda c: f"/c/{c}_libretro.so"):
            argv = run.command("nes", DB["emulators"]["ra-fceumm"], "/r/m.nes")
        self.assertEqual(argv[:4], ["flatpak", "run", "--die-with-parent", "org.libretro.RetroArch"])
        self.assertEqual(argv[4:], ["-f", "--appendconfig", "/a.cfg", "-L",
                                    "/c/fceumm_libretro.so", "/r/m.nes"])

    def test_needs(self):
        emu = DB["emulators"]["ryujinx"]
        with mock.patch.object(seed, "HOME", self.tmp):
            with self.assertRaises(run.Refused) as cm:
                run.check_needs(emu)
            self.assertEqual(cm.exception.reason, "needs")
            self.assertIn("prod.keys", str(cm.exception))
            # its own copy will do as well as Emulation/bios/switch
            self.write(".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/system/prod.keys", "k")
            run.check_needs(emu)
        run.check_needs(DB["emulators"]["play"])  # nothing emu-run can check

    def test_permissions_applied_every_launch(self):
        calls = []
        with mock.patch.object(seed.subprocess, "run", lambda argv, **kw: calls.append(argv)):
            seed.permissions("org.purei.Play")
            seed.permissions("org.purei.Play")
        argv = ["flatpak", "override", "--user", "--filesystem=~/Emulation",
                "--filesystem=/run/media", "org.purei.Play"]
        self.assertEqual(calls, [argv, argv])

    def test_installed_looks_in_retroarchs_cores(self):
        cores = os.path.join(self.tmp, "ra")
        self.write("cores/mgba_libretro.so", b"\x7fELF", cores)
        with mock.patch.object(seed, "RA_DIR", cores), \
                mock.patch.object(run, "flatpak_installed", lambda app: app == "org.libretro.RetroArch"):
            self.assertTrue(run.installed(DB["emulators"]["ra-mgba"]))
            self.assertFalse(run.installed(DB["emulators"]["ra-fceumm"]))
            self.assertFalse(run.installed(DB["emulators"]["dolphin"]))

    def test_app_inside_the_sandbox_gets_the_signal_first(self):
        # flatpak run -> bwrap -> the app: signalling bwrap would end the sandbox (PDEATHSIG)
        # before the app saved; the app traps TERM, saves, exits, and bwrap then exits by itself
        bindir = os.path.join(self.tmp, "bin")
        saved = os.path.join(self.tmp, "saved")
        app = self.write("bin/kettle-test-app", "#!/bin/sh\ntrap 'echo saved > \"$SAVED\"; exit 0' TERM\n"
                                                "while :; do sleep 0.05; done\n")
        bwrap = self.write("bin/bwrap", '#!/bin/sh\n"$1" &\nwait $!\n')
        for p in (app, bwrap):
            os.chmod(p, 0o755)
        child = subprocess.Popen([bwrap, app], env=dict(os.environ, SAVED=saved))
        for _ in range(200):
            if any(run._comm(p) == "kettle-test-app" for p in run.inside(child)):
                break
            time.sleep(0.02)
        self.assertNotIn("bwrap", [run._comm(p) for p in run.inside(child)])
        self.assertTrue(run.signal_tree(child, signal.SIGTERM))
        self.assertEqual(child.wait(timeout=5), 0)  # bwrap itself wasn't signalled
        with open(saved) as f:
            self.assertEqual(f.read().strip(), "saved")
        self.assertTrue(os.path.isdir(bindir))

    def test_signal_reaches_the_app_inside(self):
        # flatpak run -> bwrap -> the app: a parent whose child ignores nothing
        child = subprocess.Popen(["sh", "-c", "sleep 30 & wait"])
        for _ in range(100):
            if run.descendants(child.pid):
                break
            time.sleep(0.02)
        inner = run.descendants(child.pid)
        self.assertTrue(inner)
        run.signal_tree(child, signal.SIGTERM)
        child.wait(timeout=5)
        for p in inner:
            for _ in range(100):
                try:
                    os.kill(p, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail(f"{p} still runs")


if __name__ == "__main__":
    unittest.main()
