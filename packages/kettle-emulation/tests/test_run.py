import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from helpers import Env

from kettle_emulation import run, seed, systems

# exits 0 once the "quit" file appears (what the fake bridge's Esc tap makes), or on SIGTERM
# (default action); "stubborn" ignores Esc
CHILD = r"""
import os, sys, time
quit_file, mode = sys.argv[1], sys.argv[2]
open(quit_file + ".started", "w").close()
while True:
    if mode != "stubborn" and os.path.exists(quit_file):
        sys.exit(0)
    time.sleep(0.02)
"""


class FakeBridge:
    def __init__(self, quit_file):
        self.quit_file = quit_file
        self.taps = []
        self.closed = False

    def serve(self):
        pass

    def tap(self, action):
        self.taps.append(action)
        open(self.quit_file, "w").close()
        return True

    def close(self):
        self.closed = True


class Run(Env):
    def setUp(self):
        super().setUp()
        self.runtime = os.path.join(self.tmp, "runtime")
        os.makedirs(self.runtime)
        self.child = self.write("child.py", CHILD)
        self.quit_file = os.path.join(self.tmp, "quit")
        self.bridge = FakeBridge(self.quit_file)
        self.handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        self.patches = [
            mock.patch.dict(os.environ, XDG_RUNTIME_DIR=self.runtime),
            mock.patch.object(run, "QUIT_GRACE", 2),
            mock.patch.object(run, "POLL", 0.02),
            mock.patch.object(run, "check_rom", lambda rom: None),
            mock.patch.object(run, "check_bios", lambda system: None),
            mock.patch.object(run, "choose", lambda db, s, r: ("ra-fceumm", {"kind": "libretro"})),
            mock.patch.object(seed, "seed", lambda eid=None: None),
            mock.patch.object(seed, "permissions", lambda app: None),
            mock.patch.object(run, "check_needs", lambda emu: None),
            mock.patch.object(run.keys, "Bridge", lambda emu=None: self.bridge),
        ]
        self.mode = "graceful"
        self.patches.append(mock.patch.object(
            run, "command", lambda s, e, r: [sys.executable, self.child, self.quit_file, self.mode]))
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        for s, h in self.handlers.items():
            signal.signal(s, h)
        super().tearDown()

    def signal_when_started(self, count=1, gap=0.0):
        def go():
            for _ in range(500):
                if os.path.exists(self.quit_file + ".started"):
                    break
                time.sleep(0.01)
            for _ in range(count):
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(gap)
        t = threading.Thread(target=go, daemon=True)
        t.start()
        return t

    def last_error(self):
        with open(os.path.join(self.runtime, "kettle-emulation", "last-error.json")) as f:
            return json.load(f)

    def test_quits_on_esc_without_waiting_the_grace(self):
        self.signal_when_started()
        t0 = time.monotonic()
        code = run.run("nes", "/x/game.nes")
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - t0, 1.5)
        self.assertEqual(self.bridge.taps, ["quit"])
        self.assertTrue(self.bridge.closed)
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "kettle-emulation", "running.json")))

    def test_repeated_signals_tap_once(self):
        self.signal_when_started(count=3, gap=0.01)
        self.assertEqual(run.run("nes", "/x/game.nes"), 0)
        self.assertEqual(self.bridge.taps, ["quit"])

    def test_signalled_after_the_grace(self):
        self.mode = "stubborn"
        run.QUIT_GRACE = 0.3
        self.signal_when_started()
        self.assertEqual(run.run("nes", "/x/game.nes"), -signal.SIGTERM)
        self.assertEqual(self.bridge.taps, ["quit"])

    def test_no_bridge_signals_at_once(self):
        def broken(emu=None):
            raise OSError("no uinput")
        with mock.patch.object(run.keys, "Bridge", broken):
            self.signal_when_started()
            t0 = time.monotonic()
            self.assertEqual(run.run("nes", "/x/game.nes"), -signal.SIGTERM)
            self.assertLess(time.monotonic() - t0, 1.5)

    def test_game_exits_by_itself(self):
        open(self.quit_file, "w").close()
        self.assertEqual(run.run("nes", "/x/game.nes"), 0)
        self.assertEqual(self.bridge.taps, [])

    def test_refusal_is_reported(self):
        def refuse(rom):
            raise run.Refused("rom", "The game file is gone: game.nes")
        with mock.patch.object(run, "check_rom", refuse):
            self.assertEqual(run.run("nes", "/x/game.nes"), 1)
        err = self.last_error()
        self.assertEqual((err["reason"], err["message"]), ("rom", "The game file is gone: game.nes"))

    def test_unexpected_error_is_reported(self):
        def full(eid=None):
            raise OSError(28, "No space left on device")
        with mock.patch.object(seed, "seed", full), mock.patch("traceback.print_exc"):
            self.assertEqual(run.run("nes", "/x/game.nes"), 1)
        err = self.last_error()
        self.assertEqual(err["reason"], "internal")
        self.assertIn("No space left", err["message"])
        self.assertEqual(self.bridge.taps, [])

    def test_missing_emulator_binary_is_reported(self):
        with mock.patch.object(run, "command", lambda s, e, r: [os.path.join(self.tmp, "nope")]), \
                mock.patch("traceback.print_exc"):
            self.assertEqual(run.run("nes", "/x/game.nes"), 1)
        self.assertEqual(self.last_error()["reason"], "internal")
        self.assertTrue(self.bridge.closed)


class Choose(Env):
    def setUp(self):
        super().setUp()
        self.db = systems.load()
        self.choices = os.path.join(self.tmp, "choices.json")
        self.have = set()
        self.patches = [mock.patch.object(run, "CHOICES", self.choices),
                        mock.patch.object(run, "installed", lambda emu: emu["name"] in self.have)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_order(self):
        self.have = {"FCEUmm", "Nestopia UE"}
        self.assertEqual(run.choose(self.db, "nes", "/r/a.nes")[0], "ra-fceumm")
        with open(self.choices, "w") as f:
            json.dump({"systems": {"nes": "ra-nestopia"}, "games": {"/r/b.nes": "ra-fceumm"}}, f)
        self.assertEqual(run.choose(self.db, "nes", "/r/a.nes")[0], "ra-nestopia")
        self.assertEqual(run.choose(self.db, "nes", "/r/b.nes")[0], "ra-fceumm")
        # a choice that isn't installed falls through
        self.have = {"FCEUmm"}
        self.assertEqual(run.choose(self.db, "nes", "/r/a.nes")[0], "ra-fceumm")

    def test_choice_of_another_system_is_ignored(self):
        self.have = {"FCEUmm", "mGBA"}
        with open(self.choices, "w") as f:
            json.dump({"systems": {"nes": "ra-mgba"}}, f)
        self.assertEqual(run.choose(self.db, "nes", "/r/a.nes")[0], "ra-fceumm")

    def refusal(self, system):
        with self.assertRaises(run.Refused) as cm:
            run.choose(self.db, system, "/r/x")
        return cm.exception

    def test_refusals(self):
        self.assertEqual(self.refusal("nosuch").reason, "system")
        with mock.patch.object(run, "flatpak_installed", lambda app: False):
            err = self.refusal("switch")
            self.assertEqual(err.reason, "emulator")
            self.assertIn("needs Ryujinx: install it in Emulation > Emulators", str(err))
            self.assertIn("RetroArch and its FCEUmm core", str(self.refusal("nes")))
        with mock.patch.object(run, "flatpak_installed", lambda app: True):
            self.assertIn("needs the FinalBurn Neo core: install it in Emulation > Emulators",
                          str(self.refusal("arcade")))


class CheckBios(unittest.TestCase):
    def test_installs_found_files_before_checking(self):
        from kettle_emulation import bios
        calls = []
        with mock.patch.object(bios, "install_found", create=True,
                               side_effect=lambda sid: calls.append("install") or ["syscard3.pce"]), \
                mock.patch.object(bios, "missing_required",
                                  side_effect=lambda sid: calls.append("check") or []), \
                mock.patch("sys.stderr"):
            run.check_bios("pcenginecd")
        self.assertEqual(calls, ["install", "check"])

    def test_missing_is_refused(self):
        from kettle_emulation import bios
        with mock.patch.object(bios, "install_found", create=True, return_value=[]), \
                mock.patch.object(bios, "missing_required", return_value=["lynxboot.img"]):
            with self.assertRaises(run.Refused) as cm:
                run.check_bios("lynx")
        self.assertEqual(cm.exception.reason, "bios")
        self.assertIn("lynxboot.img", str(cm.exception))

    def test_system_dirs_needed_by_a_core(self):
        emu = {"kind": "libretro", "name": "blueMSX"}
        sysdef = {"system_dirs": ["Machines", "Databases"]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(seed, "EMU", tmp) as emu_dir:
            with self.assertRaises(run.Refused) as cm:
                run.check_system_dirs(sysdef, emu)
            self.assertIn("Machines, Databases", str(cm.exception))
            for d in ("Machines", "Databases"):
                os.makedirs(os.path.join(emu_dir, "bios", d), exist_ok=True)
            run.check_system_dirs(sysdef, emu)
            run.check_system_dirs(sysdef, {"kind": "standalone", "name": "x"})


class Main(unittest.TestCase):
    def test_hex_path(self):
        path = "/run/media/kettle/SD/Emulation/roms/nes/It's \"a\" $(game) ü.nes"
        with mock.patch.object(run, "run", return_value=0) as r:
            self.assertEqual(run.main(["nes", "x:" + path.encode().hex()]), 0)
        r.assert_called_once_with("nes", path)

    def test_hex_path_not_utf8(self):
        raw = b"/roms/nes/caf\xe9.nes"
        with mock.patch.object(run, "run", return_value=0) as r:
            run.main(["nes", "x:" + raw.hex()])
        self.assertEqual(os.fsencode(r.call_args[0][1]), raw)

    def test_bad_hex_and_usage(self):
        with mock.patch.object(run, "run") as r, mock.patch("sys.stderr"):
            self.assertEqual(run.main(["nes", "x:zz"]), 2)
            self.assertEqual(run.main(["nes"]), 2)
        r.assert_not_called()


# RetroArch's default keyboard hotkeys (config.def.keybinds.h, desktop) as cfg names
RA_DEFAULT_HOTKEYS = {
    "input_menu_toggle": "f1", "input_exit_emulator": "escape", "input_reset": "h",
    "input_toggle_fast_forward": "space", "input_hold_fast_forward": "l",
    "input_hold_slowmotion": "e", "input_rewind": "r", "input_pause_toggle": "p",
    "input_frame_advance": "k", "input_audio_mute": "f9", "input_volume_up": "add",
    "input_volume_down": "subtract", "input_load_state": "f4", "input_save_state": "f2",
    "input_state_slot_increase": "f7", "input_state_slot_decrease": "f6",
    "input_shader_toggle": "comma", "input_shader_next": "m", "input_shader_prev": "n",
    "input_cheat_toggle": "u", "input_cheat_index_plus": "y", "input_cheat_index_minus": "t",
    "input_screenshot": "f8", "input_grab_mouse_toggle": "f11", "input_game_focus_toggle": "scroll_lock",
    "input_toggle_fullscreen": "f", "input_desktop_menu_toggle": "f5", "input_fps_toggle": "f3",
    "input_netplay_game_watch": "i", "input_netplay_player_chat": "tilde",
}
# the keys mkvdf.py's layer and keys.ACTIONS send
LAYER_KEYS = {"f1", "f2", "f4", "f6", "f7", "f8", "f9", "space", "r", "escape"}


class Seed(unittest.TestCase):
    def test_layer_keys_bound_once(self):
        effective = dict(RA_DEFAULT_HOTKEYS)
        effective.update({k: v for k, v in seed.retroarch_kept().items() if k.startswith("input_")})
        for key in LAYER_KEYS:
            users = [k for k, v in effective.items() if v == key]
            self.assertLessEqual(len(users), 1, f"{key} is bound to {users}")
        self.assertEqual(effective["input_audio_mute"], "nul")

    def test_rewind_only_where_flagged(self):
        self.assertEqual(seed.retroarch_seeded()["rewind_enable"], "false")
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "systems.json")) as f:
            data = json.load(f)
        flagged = {sid for sid, s in data["systems"].items() if s.get("rewind")}
        self.assertIn("snes", flagged)
        self.assertNotIn("psx", flagged)
        for sid, s in data["systems"].items():
            on = s.get("retroarch", {}).get("rewind_enable") == "true"
            self.assertEqual(on, sid in flagged, sid)
            if on:
                self.assertTrue(all(data["emulators"][e]["kind"] == "libretro"
                                    for e in s["emulators"]), sid)


if __name__ == "__main__":
    unittest.main()


class Dirs(unittest.TestCase):
    def test_emulator_folders_exist_before_a_launch(self):
        # RetroArch falls back to its own folders when a configured one is missing
        db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "systems.json")
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"KETTLE_EMU_SYSTEMS": db}), \
                mock.patch.object(seed, "HOME", home), \
                mock.patch.object(seed, "EMU", os.path.join(home, "Emulation")), \
                mock.patch.object(seed, "RA_DIR", os.path.join(home, "ra")):
            seed.ensure_dirs(seed.EMU)
            for key, d in seed.retroarch_kept().items():
                if key.endswith("_directory") and d.startswith(seed.EMU):
                    self.assertTrue(os.path.isdir(d), key)
            self.assertTrue(os.path.isdir(os.path.join(home, "Emulation/saves/retroarch")))

    def test_kept_audio_and_no_screensaver_inhibit(self):
        kept = seed.retroarch_kept()
        self.assertEqual(kept["audio_driver"], "pulse")
        self.assertEqual(kept["suspend_screensaver_enable"], "false")
