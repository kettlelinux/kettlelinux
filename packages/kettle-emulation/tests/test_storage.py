"""The storage manager: storage.json's choices, where the game data is, moving and copying games
between storages (transfer.py), moving the game data, and the emulators pointed at it."""
import json
import os
import sys
import unittest
from unittest import mock

from helpers import PKG, Env

from kettle_emulation import run, seed, storage, systems, transfer


class Base(Env):
    def setUp(self):
        super().setUp()
        self.user = os.path.dirname(self.home)
        self.card = os.path.join(self.media, "SD")
        self.card_emu = os.path.join(self.card, "Emulation")
        os.makedirs(os.path.join(self.card_emu, "roms"))
        os.makedirs(os.path.join(self.home, "roms"))
        self.db = systems.load()
        self.events = []

    def card_root(self):
        return storage.find(self.card)

    def game(self, emu, rel, data=b"rom"):
        return self.write(os.path.join(emu, rel), data)


class Settings(Base):
    def test_defaults_and_saving(self):
        self.assertEqual(storage.settings()["new_games"], "internal")
        storage.save_settings(new_games=self.card)
        self.assertEqual(storage.settings()["new_games"], self.card)
        self.assertTrue(storage.conf_path().startswith(self.user + "/.config/kettle/emulation/"))

    def test_new_games_go_to_the_card_while_it_is_in_and_set_up(self):
        self.assertEqual(storage.new_games_dir(), self.home)
        storage.save_settings(new_games=self.card)
        self.assertEqual(storage.new_games_dir(), self.card_emu)
        os.rmdir(os.path.join(self.card_emu, "roms"))  # not set up
        self.assertEqual(storage.new_games_dir(), self.home)
        storage.save_settings(new_games="/run/media/kettle/gone")
        self.assertEqual(storage.new_games_dir(), self.home)

    def test_dest_by_name_or_path(self):
        self.assertEqual(storage.root_for("internal"), self.home)
        self.assertEqual(storage.root_for(self.home), self.home)  # what new_games_dir() gives
        self.assertEqual(storage.root_for(self.card), self.card_emu)
        with self.assertRaises(ValueError):
            storage.root_for("/run/media/nobody/x")

    def test_data_location(self):
        rpcs3 = ".var/app/net.rpcs3.RPCS3/config/rpcs3/dev_hdd0/home/00000001/savedata"
        ryujinx = ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/bis/user/save"
        self.assertEqual(storage.locate("Emulation/saves/retroarch", self.db), os.path.join(self.home, "saves/retroarch"))
        storage.save_settings(data=self.card, data_label="SD")
        self.assertEqual(storage.locate("Emulation/saves/retroarch", self.db), os.path.join(self.card_emu, "saves/retroarch"))
        self.assertEqual(storage.locate(rpcs3, self.db),
                         os.path.join(self.card_emu, "data/rpcs3/dev_hdd0/home/00000001/savedata"))
        self.assertEqual(storage.locate("Emulation/saves", self.db), os.path.join(self.card_emu, "saves"))
        # what can't move, and the BIOS files, stay internal
        self.assertEqual(storage.locate(ryujinx, self.db), os.path.join(self.user, ryujinx))
        self.assertEqual(storage.locate("Emulation/bios/ps3", self.db), os.path.join(self.home, "bios/ps3"))
        self.assertFalse(storage.movable(ryujinx, self.db))

    def test_data_card_out(self):
        storage.save_settings(data="some-uuid", data_label="Big card")
        with self.assertRaises(storage.DataMissing) as cm:
            storage.data_root()
        self.assertIn("Big card", str(cm.exception))


class Transfer(Base):
    def test_move_a_disc_set_to_a_card_and_back(self):
        cue = self.game(self.home, "roms/psx/Game/Game.cue", 'FILE "Game (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\n')
        self.game(self.home, "roms/psx/Game/Game (Track 1).bin", b"x" * 5000)
        self.assertEqual(transfer.game_size(cue), os.path.getsize(cue) + 5000)
        st = transfer.transfer([cue], self.card_emu, "move", self.events.append)
        self.assertEqual((st["errors"], st["games"]), (0, {"psx": 1}))
        self.assertTrue(os.path.isfile(os.path.join(self.card_emu, "roms/psx/Game/Game (Track 1).bin")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "roms/psx/Game")))
        self.assertTrue(os.path.isdir(os.path.join(self.home, "roms/psx")))  # the system's folder stays
        kinds = [e["event"] for e in self.events]
        self.assertEqual((kinds[0], kinds[-1]), ("start", "done"))
        self.assertEqual([e["action"] for e in self.events if e["event"] == "item"], ["moved"])
        back = transfer.transfer([os.path.join(self.card_emu, "roms/psx/Game/Game.cue")], self.home, "move")
        self.assertEqual(back["errors"], 0)
        self.assertTrue(os.path.isfile(cue))
        self.assertFalse(any(f.endswith(".part") for _, _, fs in os.walk(self.tmp) for f in fs))

    def test_copy_keeps_the_source_and_identical_is_skipped(self):
        rom = self.game(self.home, "roms/snes/A.sfc")
        transfer.transfer([rom], self.card_emu, "copy")
        self.assertTrue(os.path.isfile(rom))
        st = transfer.transfer([rom], self.card_emu, "move")
        self.assertEqual((st["identical"], st["errors"]), (1, 0))
        self.assertFalse(os.path.exists(rom))  # moved: the card has the same file

    def test_a_different_file_there_is_never_overwritten(self):
        rom = self.game(self.home, "roms/snes/A.sfc", b"mine")
        self.game(self.card_emu, "roms/snes/A.sfc", b"other")
        st = transfer.transfer([rom], self.card_emu, "move", self.events.append)
        self.assertEqual(st["errors"], 1)
        self.assertIn("different", [e for e in self.events if e["event"] == "item"][0]["reason"])
        with open(os.path.join(self.card_emu, "roms/snes/A.sfc"), "rb") as f:
            self.assertEqual(f.read(), b"other")
        self.assertTrue(os.path.isfile(rom))

    def test_no_room(self):
        rom = self.game(self.home, "roms/snes/A.sfc", b"x" * 1000)
        # a card is another filesystem (here it's the same: a move would be a rename)
        with mock.patch.object(transfer, "free_space", return_value=transfer.SPARE + 10), \
                mock.patch.object(transfer, "_same_dev", return_value=False):
            with self.assertRaises(ValueError):
                transfer.transfer([rom], self.card_emu, "move")
        self.assertTrue(os.path.isfile(rom))

    def test_fat_card_refuses_a_4gb_file(self):
        rom = self.game(self.home, "roms/ps2/Big.iso", b"x" * 100)
        roots = [storage.internal(), {**self.card_root(), "fstype": "vfat"}]
        with mock.patch.object(transfer, "FAT_MAX", 50):
            st = transfer.transfer([rom], self.card_emu, "move", self.events.append, roots)
        self.assertEqual(st["errors"], 1)
        self.assertIn("FAT32", [e for e in self.events if e["event"] == "item"][0]["reason"])
        self.assertTrue(os.path.isfile(rom))

    def test_a_game_folder_moves_whole(self):
        top = os.path.join(self.home, "roms/ps3/Game")
        self.write("PS3_GAME/PARAM.SFO", b"sfo", top)
        self.write("PS3_GAME/USRDIR/EBOOT.BIN", b"eboot", top)
        st = transfer.transfer([top], self.card_emu, "move")
        self.assertEqual(st["errors"], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.card_emu, "roms/ps3/Game/PS3_GAME/USRDIR/EBOOT.BIN")))
        self.assertFalse(os.path.exists(top))

    def test_cancel_leaves_no_half_game(self):
        cue = self.game(self.home, "roms/psx/G.cue", 'FILE "G1.bin" BINARY\n  TRACK 01 MODE2/2352\nFILE "G2.bin" BINARY\n  TRACK 02 AUDIO\n')
        self.game(self.home, "roms/psx/G1.bin", b"1" * 100)
        self.game(self.home, "roms/psx/G2.bin", b"2" * 100)
        real = transfer.Copier.copy
        calls = []

        def copy(self_, src, dst):
            calls.append(src)
            if src.endswith("G2.bin"):
                raise SystemExit(143)  # SIGTERM mid-game
            real(self_, src, dst)
        with mock.patch.object(transfer.Copier, "copy", copy), mock.patch.object(transfer, "_same_dev", return_value=False), \
                self.assertRaises(SystemExit):
            transfer.transfer([cue], self.card_emu, "move")
        self.assertEqual(os.listdir(os.path.join(self.card_emu, "roms/psx")), [])
        self.assertTrue(all(os.path.isfile(os.path.join(self.home, "roms/psx", n)) for n in ("G.cue", "G1.bin", "G2.bin")))

    def test_delete(self):
        cue = self.game(self.home, "roms/psx/Game/Game.cue", 'FILE "Game.bin" BINARY\n  TRACK 01 MODE2/2352\n')
        self.game(self.home, "roms/psx/Game/Game.bin")
        other = self.game(self.home, "roms/psx/Other.chd")
        self.assertEqual(transfer.delete([cue]), 1)
        self.assertFalse(os.path.exists(os.path.dirname(cue)))
        self.assertTrue(os.path.isfile(other))
        with self.assertRaises(ValueError):
            transfer.delete([os.path.join(self.home, "bios", "x.bin")])

    def test_command_line(self):
        # as the plugin runs it: the games after "--" (a name may start with a dash)
        import importlib.machinery
        import importlib.util
        import io
        from kettle_emulation import awake
        loader = importlib.machinery.SourceFileLoader("kettle_emu_import", os.path.join(PKG, "kettle-emu-import"))
        cli = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cli)
        rom = self.game(self.home, "roms/snes/-dash.sfc")
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["kettle-emu-import", "transfer", self.card, "--copy", "--", rom]), \
                mock.patch.object(awake.Awake, "hold", lambda self: None), mock.patch("sys.stdout", out), \
                mock.patch("signal.signal"):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(json.loads(out.getvalue().splitlines()[-1])["games"], {"snes": 1})
        self.assertTrue(os.path.isfile(os.path.join(self.card_emu, "roms/snes/-dash.sfc")))


class DataMove(Base):
    def test_to_a_card_and_back(self):
        srm = self.write("saves/retroarch/snes/A.srm", b"save", self.home)
        hdd = self.write(".var/app/net.rpcs3.RPCS3/config/rpcs3/dev_hdd0/game/X/EBOOT.BIN", b"game", self.user)
        st = transfer.move_data(self.card_root(), self.db, self.events.append)
        self.assertTrue(st["switched"])
        self.assertEqual(storage.settings()["data"], self.card)
        self.assertTrue(os.path.isfile(os.path.join(self.card_emu, "saves/retroarch/snes/A.srm")))
        self.assertTrue(os.path.isfile(os.path.join(self.card_emu, "data/rpcs3/dev_hdd0/game/X/EBOOT.BIN")))
        self.assertFalse(os.path.exists(srm) or os.path.exists(hdd))
        self.assertTrue(os.path.isdir(os.path.join(self.home, "saves")))
        st = transfer.move_data(storage.internal(), self.db)
        self.assertTrue(st["switched"])
        self.assertEqual(storage.settings()["data"], "internal")
        self.assertTrue(os.path.isfile(srm) and os.path.isfile(hdd))

    def test_a_newer_file_there_is_kept(self):
        self.write("saves/retroarch/snes/A.srm", b"old", self.home)
        os.utime(os.path.join(self.home, "saves/retroarch/snes/A.srm"), (1000, 1000))
        theirs = self.write("saves/retroarch/snes/A.srm", b"newer", self.card_emu)
        st = transfer.move_data(self.card_root(), self.db)
        self.assertEqual((st["kept"], st["switched"]), (1, True))
        with open(theirs, "rb") as f:
            self.assertEqual(f.read(), b"newer")
        self.assertTrue(os.path.isfile(os.path.join(self.home, "saves/retroarch/snes/A.srm")))  # left there

    def test_a_failed_copy_switches_nothing(self):
        srm = self.write("saves/retroarch/snes/A.srm", b"save", self.home)
        with mock.patch.object(transfer.Copier, "copy", side_effect=OSError("card full")):
            st = transfer.move_data(self.card_root(), self.db)
        self.assertEqual((st["errors"], st["switched"]), (1, False))
        self.assertEqual(storage.settings()["data"], "internal")
        self.assertTrue(os.path.isfile(srm))

    def test_already_there(self):
        with self.assertRaises(ValueError):
            transfer.move_data(storage.internal(), self.db)


class Emulators(Base):
    """seed.py and emu-run with the game data on a card."""

    def setUp(self):
        super().setUp()
        self.patches = [mock.patch.object(seed, "HOME", self.user), mock.patch.object(seed, "EMU", self.home)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_retroarch_and_melonds_saves_follow_the_data(self):
        self.assertEqual(seed.retroarch_kept()["savefile_directory"], os.path.join(self.home, "saves/retroarch"))
        storage.save_settings(data=self.card)
        kept = seed.retroarch_kept()
        self.assertEqual(kept["savefile_directory"], os.path.join(self.card_emu, "saves/retroarch"))
        self.assertEqual(kept["system_directory"], os.path.join(self.home, "bios"))  # BIOS internal
        seed.ensure_dirs(self.home)
        self.assertTrue(os.path.isdir(os.path.join(self.card_emu, "states/retroarch")))

    def test_rpcs3_hdd0_on_the_card_and_back(self):
        vfs = os.path.join(self.tmp, "vfs.yml")
        self.write("vfs.yml", '$(EmulatorDir): ""\n/dev_hdd0/: $(EmulatorDir)dev_hdd0/\n/dev_flash/: $(EmulatorDir)dev_flash/\n')
        with mock.patch.object(seed, "RPCS3_VFS", vfs):
            seed._keep_rpcs3_hdd0()
            with open(vfs) as f:
                self.assertIn("/dev_hdd0/: $(EmulatorDir)dev_hdd0/", f.read())
            storage.save_settings(data=self.card)
            seed._keep_rpcs3_hdd0()
            self.assertEqual(seed._yaml_top(vfs, "/dev_hdd0/"), os.path.join(self.card_emu, "data/rpcs3/dev_hdd0") + "/")
            with open(vfs) as f:
                self.assertIn("/dev_flash/: $(EmulatorDir)dev_flash/", f.read())
            storage.save_settings(data="internal")
            seed._keep_rpcs3_hdd0()
            self.assertEqual(seed._yaml_top(vfs, "/dev_hdd0/"), "$(EmulatorDir)dev_hdd0/")

    def test_azahar_custom_storage(self):
        ini = os.path.join(self.tmp, "qt-config.ini")
        with mock.patch.object(seed, "AZAHAR_INI", ini):
            storage.save_settings(data=self.card)
            seed.keep_azahar()
            with open(ini) as f:
                text = f.read()
            self.assertIn("[Data%20Storage]", text)
            self.assertIn(f"sdmc_directory={self.card_emu}/data/azahar/sdmc/", text)
            self.assertIn("use_custom_storage=true", text)
            storage.save_settings(data="internal")
            seed.keep_azahar()
            with open(ini) as f:
                self.assertIn("use_custom_storage=false", f.read())

    def test_xemu_hard_disk_follows_the_data(self):
        storage.save_settings(data=self.card)
        self.assertEqual(seed.data_path(seed.XEMU_HDD), os.path.join(self.card_emu, "data/xemu/xbox_hdd.qcow2"))
        self.write("data/xemu/xbox_hdd.qcow2", b"hdd", self.card_emu)
        run.check_needs(self.db["emulators"]["xemu"])

    def test_launch_refused_while_the_data_card_is_out(self):
        storage.save_settings(data="gone-uuid", data_label="Big card")
        with self.assertRaises(run.Refused) as cm:
            run.check_data(self.db["emulators"]["ra-snes9x"])
        self.assertEqual(cm.exception.reason, "storage")
        self.assertIn("Big card", str(cm.exception))
        run.check_data(self.db["emulators"]["ryujinx"])  # keeps its data internal: starts


if __name__ == "__main__":
    unittest.main()
