import os
import shutil
import unittest
import zipfile

from helpers import FAKE_BIOS, FAKE_SEGACD, Env, pvd, raw_disc

from kettle_emulation import bios, importer, storage


class Importer(Env):
    def setUp(self):
        super().setUp()
        self.box = os.path.join(self.home, "inbox")
        self.events = []

    def inbox(self):
        return importer.inbox(self.events.append, settle=0)

    def roms(self, *rel):
        return os.path.join(self.home, "roms", *rel)

    def items(self):
        return [e for e in self.events if e["event"] == "item"]

    def test_sorts_and_reports(self):
        self.write("Mario.nes", b"NES\x1a" + b"\0" * 64, self.box)
        self.write("sub/Zelda.gba", b"\0" * 200, self.box)
        self.write("notes.txt", "hello", self.box)
        st = self.inbox()[0]
        self.assertTrue(os.path.isfile(self.roms("nes", "Mario.nes")))
        self.assertTrue(os.path.isfile(self.roms("gba", "Zelda.gba")))
        self.assertFalse(os.path.exists(os.path.join(self.box, "Mario.nes")))
        self.assertEqual(st["games"], {"nes": 1, "gba": 1})
        self.assertEqual(self.events[0]["event"], "inbox")
        self.assertEqual(self.events[-1]["event"], "done")
        self.assertTrue(os.path.isfile(os.path.join(self.box, "notes.txt")))  # junk left alone

    def test_conflict_and_identical(self):
        os.makedirs(self.roms("nes"))
        self.write("Mario.nes", b"NES\x1a old", self.roms("nes"))
        self.write("Mario.nes", b"NES\x1a new", self.box)
        self.inbox()
        self.assertTrue(os.path.isfile(self.roms("nes", "Mario (2).nes")))
        with open(self.roms("nes", "Mario.nes"), "rb") as f:
            self.assertEqual(f.read(), b"NES\x1a old")
        self.write("Mario.nes", b"NES\x1a old", self.box)
        st = self.inbox()[0]
        self.assertEqual(st["identical"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.box, "Mario.nes")))
        self.assertFalse(os.path.exists(self.roms("nes", "Mario (3).nes")))

    def cue_set(self, root, name="Game"):
        self.write(f"{name} (Track 1).bin", raw_disc(pvd("PLAYSTATION")), root)
        self.write(f"{name} (Track 2).bin", b"\0" * 2352, root)
        self.write(f"{name}.cue", f'FILE "{name} (Track 1).bin" BINARY\n TRACK 01 MODE2/2352\n'
                   f'  INDEX 01 00:00:00\nFILE "{name} (Track 2).bin" BINARY\n TRACK 02 AUDIO\n'
                   '  INDEX 01 00:00:00\n', root)

    def test_cue_set_moves_together_and_conflicting_set_gets_folder(self):
        self.cue_set(os.path.join(self.box, "dl"))
        self.inbox()
        for f in ("Game.cue", "Game (Track 1).bin", "Game (Track 2).bin"):
            self.assertTrue(os.path.isfile(self.roms("psx", f)), f)
        self.assertEqual([e["system"] for e in self.items()], ["psx"])
        # a different set by the same name: into "Game (2)/", names untouched
        self.cue_set(self.box)
        with open(os.path.join(self.box, "Game (Track 2).bin"), "wb") as f:
            f.write(b"\1" * 2352)
        self.inbox()
        self.assertTrue(os.path.isfile(self.roms("psx", "Game (2)", "Game.cue")))
        self.assertTrue(os.path.isfile(self.roms("psx", "Game (2)", "Game (Track 2).bin")))

    def test_bare_disc_bin_gets_a_cue(self):
        self.write("Crash.bin", raw_disc(pvd("PLAYSTATION")), self.box)
        self.inbox()
        with open(self.roms("psx", "Crash.cue")) as f:
            cue = f.read()
        self.assertIn('FILE "Crash.bin" BINARY', cue)
        self.assertIn("MODE2/2352", cue)

    def test_unsorted(self):
        self.write("mystery.iso", b"\0" * 40000, self.box)
        st = self.inbox()[0]
        self.assertEqual(st["unsorted"], 1)
        self.assertTrue(os.path.isfile(os.path.join(self.box, "unsorted", "mystery.iso")))
        # the next pass leaves inbox/unsorted alone
        self.events.clear()
        self.inbox()
        self.assertEqual(self.items(), [])

    def test_assign_unsorted(self):
        self.write("mystery.iso", b"\0" * 40000, self.box)
        self.inbox()
        importer.assign(os.path.join(self.box, "unsorted", "mystery.iso"), "psp", emit=self.events.append)
        self.assertTrue(os.path.isfile(self.roms("psp", "mystery.iso")))

    def test_bios_by_md5_any_name(self):
        self.write("random-name.dat", FAKE_BIOS, self.box)
        self.write("cd.bin", FAKE_SEGACD, self.box)  # a .bin BIOS isn't mistaken for a game
        st = self.inbox()[0]
        self.assertTrue(os.path.isfile(os.path.join(self.home, "bios", "scph5501.bin")))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "bios", "bios_CD_U.bin")))
        self.assertEqual(sorted(b["file"] for b in st["bios"]), ["bios_CD_U.bin", "scph5501.bin"])
        self.assertEqual(st["games"], {})
        s = bios.status()
        self.assertEqual(s["segacd"]["state"], "ok" if all(e["found"] for e in s["segacd"]["entries"]) else "missing-optional")
        self.assertEqual(bios.missing_required("segacd"), [])
        self.assertEqual(s["psx"]["entries"][0]["found"], os.path.join(self.home, "bios", "scph5501.bin"))

    def test_bios_status_and_bad(self):
        self.assertEqual(bios.missing_required("segacd"), ["bios_CD_U.bin, bios_CD_E.bin or bios_CD_J.bin"])
        self.assertEqual(bios.missing_required("n64"), [])
        self.assertEqual(bios.status("n64")["n64"]["state"], "none")
        self.write("bios_CD_U.bin", b"wrong", os.path.join(self.home, "bios"))
        e = bios.status("segacd")["segacd"]["entries"][0]
        self.assertIsNone(e["found"])
        self.assertTrue(e["bad"].endswith("bios_CD_U.bin"))
        # on a card it's found, but not where the emulators look until it's installed
        card = os.path.join(self.media, "SD")
        self.write("Emulation/bios/whatever.bin", FAKE_SEGACD, card)
        self.assertEqual(bios.missing_required("segacd"), ["bios_CD_U.bin, bios_CD_E.bin or bios_CD_J.bin"])
        e = bios.status("segacd")["segacd"]["entries"][0]
        self.assertIsNone(e["found"])
        self.assertEqual(e["elsewhere"], os.path.join(card, "Emulation", "bios", "whatever.bin"))
        self.assertEqual(bios.install_found("segacd"), ["bios_CD_U.bin"])
        self.assertEqual(bios.missing_required("segacd"), [])
        dest = os.path.join(self.home, "bios", "bios_CD_U.bin")
        self.assertEqual(bios.status("segacd")["segacd"]["entries"][0]["found"], dest)
        with open(dest + ".old") as f:
            self.assertEqual(f.read(), "wrong")  # the bad one is kept
        self.assertEqual(bios.install_found(), [])

    def test_bios_by_name_and_size(self):
        self.write("firmware.bin", b"\0" * 262144, self.box)
        self.inbox()
        self.assertTrue(os.path.isfile(os.path.join(self.home, "bios", "firmware.bin")))

    def test_zip_extracted_and_removed(self):
        os.makedirs(self.box)
        z = os.path.join(self.box, "Pack.zip")
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("Pack/Game.cue", 'FILE "Game.bin" BINARY\n TRACK 01 MODE2/2352\n  INDEX 01 00:00:00\n')
            f.writestr("Pack/Game.bin", raw_disc(pvd("PLAYSTATION")))
            f.writestr("../../evil.nes", b"NES\x1a")
        self.inbox()
        self.assertTrue(os.path.isfile(self.roms("psx", "Game.cue")))
        self.assertTrue(os.path.isfile(self.roms("psx", "Game.bin")))
        self.assertFalse(os.path.exists(z))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.nes")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "evil.nes")))
        self.assertEqual([d for d in os.listdir(self.box) if d.startswith(".staging")], [])

    def test_zip_kept_for_arcade(self):
        os.makedirs(self.box)
        with zipfile.ZipFile(os.path.join(self.box, "pacman.zip"), "w") as f:
            f.writestr("pacman.6e", b"\0")
        self.inbox()
        self.assertTrue(os.path.isfile(self.roms("arcade", "pacman.zip")))

    @unittest.skipUnless(shutil.which("7z"), "7z not installed")
    def test_7z(self):
        import subprocess
        src = os.path.join(self.tmp, "src")
        self.write("Mario.nes", b"NES\x1a" + b"\0" * 64, src)
        os.makedirs(self.box)
        subprocess.run(["7z", "a", "-bd", os.path.join(self.box, "Mario.7z"), os.path.join(src, "Mario.nes")],
                       check=True, capture_output=True)
        self.inbox()
        self.assertTrue(os.path.isfile(self.roms("nes", "Mario.nes")))
        self.assertFalse(os.path.exists(os.path.join(self.box, "Mario.7z")))

    def test_copy_from_card_to_card(self):
        card = os.path.join(self.media, "STICK")
        self.write("games/snes/Mario World.sfc", b"\0" * 512, card)
        self.write("games/holiday.mp4", b"\0" * 512, card)
        dest = storage.root_for(card)
        self.assertEqual(dest, os.path.join(card, "Emulation"))
        st = importer.Importer(dest, "copy", self.events.append).run(os.path.join(card, "games"))
        self.assertTrue(os.path.isfile(os.path.join(card, "Emulation", "roms", "snes", "Mario World.sfc")))
        self.assertTrue(os.path.isfile(os.path.join(card, "games", "snes", "Mario World.sfc")))  # copied
        self.assertTrue(os.path.isfile(os.path.join(card, "games", "holiday.mp4")))  # left
        self.assertFalse(os.path.exists(os.path.join(card, "Emulation", "inbox", "unsorted")))
        self.assertEqual(st["unsorted"], 1)
        # the tree it just made isn't imported from again
        self.events.clear()
        importer.Importer(dest, "copy", self.events.append).run(card)
        self.assertEqual(sum(1 for e in self.items() if e["action"] == "copied"), 0)

    def test_scan(self):
        card = os.path.join(self.media, "SD")
        self.write("Mario.nes", b"NES\x1a", card)
        self.write("x/scph.bin", FAKE_BIOS, card)
        self.write("x/odd.iso", b"\0" * 40000, card)
        self.write("Emulation/roms/gba/A.gba", b"\0", card)
        s = importer.scan(card)
        self.assertEqual(s["games"], {"nes": 1})
        self.assertEqual(s["bios"][0]["file"], "scph5501.bin")
        self.assertFalse(s["bios"][0]["installed"])
        self.assertEqual(s["unsorted_count"], 1)
        self.assertTrue(s["has_emulation_tree"])

    def test_settle_skips_fresh_files(self):
        self.write("Mario.nes", b"NES\x1a", self.box)
        importer.inbox(self.events.append, settle=3600)
        self.assertTrue(os.path.isfile(os.path.join(self.box, "Mario.nes")))

    def test_free_name(self):
        p = self.write("a/x.nes", b"")
        self.write("a/x (2).nes", b"")
        self.assertTrue(importer.free_name(p).endswith("x (3).nes"))
        self.assertTrue(importer.free_name(os.path.join(self.tmp, "a", "y.nes")).endswith("y.nes"))


if __name__ == "__main__":
    unittest.main()
