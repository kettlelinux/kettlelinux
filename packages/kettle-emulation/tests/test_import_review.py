"""The importer's and BIOS lookup's edge cases: arcade sets, clashing sets, broken archives, files
still being copied in, sheets that point outside their folder, and the rest of review 1."""
import itertools
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
import zipfile
from unittest import mock

from helpers import FAKE_BIOS, FAKE_SEGACD, PKG, Env, chd, pvd, raw_disc

from kettle_emulation import bios, identify, importer


def cue(*tracks):
    return "".join(f'FILE "{t}" BINARY\n TRACK {i:02d} {"MODE2/2352" if i == 1 else "AUDIO"}\n'
                   "  INDEX 01 00:00:00\n" for i, t in enumerate(tracks, 1))


class Review(Env):
    def setUp(self):
        super().setUp()
        self.box = os.path.join(self.home, "inbox")
        os.makedirs(self.box)
        self.events = []

    def inbox(self):
        return importer.inbox(self.events.append, settle=0)

    def roms(self, *rel):
        return os.path.join(self.home, "roms", *rel)

    def items(self):
        return [e for e in self.events if e["event"] == "item"]

    def read(self, p):
        with open(p, "rb") as f:
            return f.read()

    # --- BIOS: found only where the emulators look --------------------------------------------

    def test_bios_under_another_name_is_elsewhere_until_installed(self):
        bdir = os.path.join(self.home, "bios")
        self.write("PSX BIOS (USA).bin", FAKE_BIOS, bdir)
        self.write("sub/whatever.bin", FAKE_SEGACD, bdir)
        st = bios.status()
        psx = next(e for e in st["psx"]["entries"] if e["file"] == "scph5501.bin")
        self.assertIsNone(psx["found"])
        self.assertEqual(psx["elsewhere"], os.path.join(bdir, "PSX BIOS (USA).bin"))
        self.assertEqual(st["segacd"]["state"], "missing-required")
        self.assertEqual(sorted(bios.install_found()), ["bios_CD_U.bin", "scph5501.bin"])
        self.assertEqual(self.read(os.path.join(bdir, "scph5501.bin")), FAKE_BIOS)
        self.assertTrue(os.path.isfile(os.path.join(bdir, "PSX BIOS (USA).bin")))  # copied
        self.assertEqual(bios.missing_required("segacd"), [])
        psx = next(e for e in bios.status("psx")["psx"]["entries"] if e["file"] == "scph5501.bin")
        self.assertEqual((psx["found"], psx["elsewhere"]), (os.path.join(bdir, "scph5501.bin"), None))

    def test_bios_install_keeps_every_old_file(self):
        entry = next(b for sid, b in bios.systems.bios_entries() if b["file"] == "scph5501.bin")
        bdir = os.path.join(self.home, "bios")
        self.write("scph5501.bin", b"mine 1", bdir)
        bios.install(self.write("a.bin", FAKE_BIOS), entry)
        self.write("scph5501.bin", b"mine 2", bdir)
        bios.install(self.write("b.bin", FAKE_BIOS), entry)
        self.assertEqual(self.read(os.path.join(bdir, "scph5501.bin.old")), b"mine 1")
        self.assertEqual(self.read(os.path.join(bdir, "scph5501.bin (2).old")), b"mine 2")
        self.assertEqual([f for f in os.listdir(bdir) if f.endswith(".part")], [])

    # --- arcade sets ---------------------------------------------------------------------------

    def zip(self, name, members):
        p = os.path.join(self.box, name)
        with zipfile.ZipFile(p, "w") as z:
            for n, data in members.items():
                z.writestr(n, data)
        return p

    def test_arcade_set_with_bin_chips_kept_whole(self):
        self.zip("dkong.zip", {"c_5et_g.bin": b"\1" * 4096, "c_5ct_g.bin": b"\2" * 4096,
                               "l_4m_b.bin": b"\3" * 4096, "c-2k.bpr": b"\4" * 256})
        self.inbox()
        self.assertTrue(os.path.isfile(self.roms("arcade", "dkong.zip")))
        self.assertFalse(os.path.exists(self.roms("atari2600")))

    def test_bin_only_chip_set_left_to_the_user(self):
        z = self.zip("set.zip", {"a.bin": b"\1" * 4096, "b.bin": b"\2" * 4096})
        m = identify.identify(z)
        self.assertEqual(m.system, "arcade")
        self.assertLess(m.confidence, identify.SORT_AT)
        self.assertFalse(m.extract)
        self.inbox()
        self.assertTrue(os.path.isfile(os.path.join(self.box, "unsorted", "set.zip")))
        self.assertFalse(os.path.exists(self.roms("atari2600")))

    def test_pack_of_games_still_unpacked(self):
        self.zip("pack.zip", {"Mario.nes": b"NES\x1a" + b"\0" * 64, "Zelda.gba": b"\0" * 200})
        self.inbox()
        self.assertTrue(os.path.isfile(self.roms("nes", "Mario.nes")))
        self.assertTrue(os.path.isfile(self.roms("gba", "Zelda.gba")))

    def test_neogeo_style_set_kept_whole(self):
        # .rom is msx's alone, so no member is "unsure": the set must not be unpacked as MSX games
        members = {"uni-bios_4_0.rom": b"\1" * 131072, "vs-bios.rom": b"\2" * 131072,
                   "sm1.sm1": b"\3" * 131072, "000-lo.lo": b"\4" * 65536}
        z = self.zip("neogeo.zip", members)
        m = identify.identify(z)
        self.assertEqual((m.system, m.extract), ("arcade", False))
        self.assertGreaterEqual(m.confidence, identify.SORT_AT)
        self.inbox()
        self.assertTrue(os.path.isfile(self.roms("arcade", "neogeo.zip")))
        with zipfile.ZipFile(self.roms("arcade", "neogeo.zip")) as zz:
            self.assertEqual(sorted(zz.namelist()), sorted(members))
        self.assertFalse(os.path.exists(self.roms("msx")))
        self.assertFalse(os.path.exists(os.path.join(self.box, "unsorted")))

    def test_rom_only_chip_set_left_to_the_user(self):
        z = self.zip("set.zip", {"a.rom": b"\1" * 8192, "b.rom": b"\2" * 8192})
        m = identify.identify(z)
        self.assertEqual(m.system, "arcade")
        self.assertLess(m.confidence, identify.SORT_AT)
        self.assertFalse(m.extract)
        self.inbox()
        self.assertTrue(os.path.isfile(os.path.join(self.box, "unsorted", "set.zip")))
        self.assertFalse(os.path.exists(self.roms("msx")))

    def test_zipped_chd_guess_isnt_promoted(self):
        # the CHD's 0.4 guess must not become the unpacked file's folder hint (0.95)
        z = os.path.join(self.box, "Saturn Game.zip")
        with zipfile.ZipFile(z, "w") as zz:
            zz.writestr("Saturn Game.chd", chd([(b"CHT2", "TRACK:1 TYPE:MODE1_RAW")]))
        m = identify.identify(z)
        self.assertTrue(m.extract)
        self.assertLess(m.confidence, identify.SORT_AT)
        self.inbox()
        self.assertFalse(os.path.exists(self.roms("segacd")))
        self.assertTrue(os.path.isfile(os.path.join(self.box, "unsorted", "Saturn Game.chd")))

    def test_zipped_weak_guess_claims_no_system(self):
        # scan() must list it as unsorted, and the item event must not name the CHD's guess
        z = os.path.join(self.box, "Saturn Game.zip")
        with zipfile.ZipFile(z, "w") as zz:
            zz.writestr("Saturn Game.chd", chd([(b"CHT2", "TRACK:1 TYPE:MODE1_RAW")]))
        s = importer.scan(self.box)
        self.assertEqual(s["games"], {})
        self.assertEqual(s["unsorted"], [z])
        self.inbox()
        ev = [e for e in self.items() if e["src"] == z]
        self.assertEqual([(e["kind"], e["system"]) for e in ev], [("extract", None)])

    def test_one_chip_with_a_file_beside_it_unpacked(self):
        # a 4 KiB .bin and its .cfg, a .rom and its .ips: one game each, not an arcade set
        for name, members in (("Pitfall.zip", {"Pitfall.bin": b"\1" * 4096, "Pitfall.cfg": b"x"}),
                              ("Game.zip", {"Game.rom": b"\2" * 32768, "Game.ips": b"PATCH"})):
            m = identify.identify(self.zip(name, members))
            self.assertTrue(m.extract, name)
            self.assertNotEqual(m.system, "arcade", name)
        self.inbox()
        self.assertFalse(os.path.exists(self.roms("arcade")))
        self.assertTrue(os.path.isfile(self.roms("atari2600", "Pitfall.bin")))
        self.assertTrue(os.path.isfile(self.roms("msx", "Game.rom")))

    def test_two_chips_and_a_file_beside_them_still_an_arcade_set(self):
        m = identify.identify(self.zip("set.zip", {"a.bin": b"\1" * 4096, "b.bin": b"\2" * 4096,
                                                   "c.prom": b"\3" * 256}))
        self.assertEqual((m.system, m.extract), ("arcade", False))
        self.assertGreaterEqual(m.confidence, identify.SORT_AT)

    def test_one_bin_among_board_position_chips_is_an_arcade_set(self):
        m = identify.identify(self.zip("galaga.zip", {"51xx.bin": b"\1" * 1024, "gg1_1b.3p": b"\2" * 4096,
                                                      "gg1_2b.3m": b"\3" * 4096, "prom-1.1d": b"\4" * 256}))
        self.assertEqual((m.system, m.extract), ("arcade", False))
        self.assertGreaterEqual(m.confidence, identify.SORT_AT)
        m = identify.identify(self.zip("x.zip", {"51xx.bin": b"\1" * 4096, "gg1_1b.3p": b"\2" * 4096}))
        self.assertEqual((m.system, m.extract), ("arcade", False))

    # --- sets that clash -----------------------------------------------------------------------

    def gdi(self, root, name, fill):
        self.write(f"{name}.gdi", "2\n1 0 4 2352 track01.bin 0\n2 600 0 2352 track02.raw 0\n", root)
        self.write("track01.bin", fill * 2352, root)
        self.write("track02.raw", fill * 2352, root)

    def test_tracks_with_the_same_names_go_in_their_own_folder(self):
        self.gdi(os.path.join(self.box, "a"), "Crazy Taxi", b"\1")
        self.gdi(os.path.join(self.box, "b"), "Sonic Adventure", b"\2")
        self.inbox()
        dc = self.roms("dreamcast")
        self.assertEqual(self.read(os.path.join(dc, "track01.bin")), b"\1" * 2352)
        self.assertTrue(os.path.isfile(os.path.join(dc, "Crazy Taxi.gdi")))
        self.assertEqual(self.read(os.path.join(dc, "Sonic Adventure", "track01.bin")), b"\2" * 2352)
        self.assertTrue(os.path.isfile(os.path.join(dc, "Sonic Adventure", "Sonic Adventure.gdi")))
        self.assertFalse(os.path.exists(os.path.join(self.box, "b", "track01.bin")))

    def test_clashing_set_folder_keeps_the_dots_in_its_name(self):
        self.gdi(os.path.join(self.box, "a"), "Super Mario Bros. 3", b"\1")
        self.gdi(os.path.join(self.box, "b"), "Super Mario Bros. 3", b"\2")
        self.inbox()
        dc = self.roms("dreamcast")
        self.assertEqual(sorted(os.listdir(dc)), ["Super Mario Bros. 3 (2)", "Super Mario Bros. 3.gdi",
                                                  "track01.bin", "track02.raw"])
        self.assertEqual(self.read(os.path.join(dc, "Super Mario Bros. 3 (2)", "track01.bin")),
                         b"\2" * 2352)
        self.assertEqual(list(itertools.islice(importer.numbered("/x/A. B", ext=False), 2)),
                         ["/x/A. B (2)", "/x/A. B (3)"])
        self.assertEqual(next(importer.numbered("/x/A. B.gdi")), "/x/A. B (2).gdi")

    def test_reimport_finds_the_numbered_copy(self):
        card = os.path.join(self.media, "SD")
        os.makedirs(self.roms("nes"))
        self.write("Mario.nes", b"NES\x1a mine", self.roms("nes"))
        self.write("games/Mario.nes", b"NES\x1a card", card)
        for name, fill in (("USA", b"\1"), ("Europe", b"\2")):
            d = os.path.join(card, "games", name)
            self.write("Game (Track 1).bin", raw_disc(pvd("PLAYSTATION")), d)
            self.write("Game (Track 2).bin", fill * 2352, d)
            self.write("Game.cue", cue("Game (Track 1).bin", "Game (Track 2).bin"), d)
        for _ in range(2):
            importer.Importer(self.home, "copy", self.events.append).run(os.path.join(card, "games"))
        self.assertEqual(sorted(os.listdir(self.roms("nes"))), ["Mario (2).nes", "Mario.nes"])
        self.assertEqual(sorted(os.listdir(self.roms("psx"))),
                         ["Game (2)", "Game (Track 1).bin", "Game (Track 2).bin", "Game.cue"])
        last = self.items()[-3:]
        self.assertEqual([e["action"] for e in last], ["identical"] * 3)

    def test_move_over_a_roms_folder_deletes_nothing(self):
        os.makedirs(self.roms("nes"))
        p = self.write("Mario.nes", b"NES\x1a", self.roms("nes"))
        with self.assertRaises(ValueError):
            importer.Importer(self.home, "move", self.events.append).run(self.roms())
        with self.assertRaises(ValueError):
            importer.Importer(self.home, "move", self.events.append).run(p)
        # and should a file in its place get there anyway, it's left alone
        imp = importer.Importer(self.home, "move", self.events.append)
        imp.run_items([importer.Item("game", p, "nes", identify.Match("nes", 1.0, "x"), size=4)])
        self.assertTrue(os.path.isfile(p))
        self.assertEqual(self.items()[-1]["action"], "identical")

    # --- broken and huge archives --------------------------------------------------------------

    def test_corrupt_zip_goes_to_unsorted_and_the_rest_is_sorted(self):
        z = os.path.join(self.box, "Broken.zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zz:
            zz.writestr("Game.bin", os.urandom(4096) * 60)
        with open(z, "r+b") as f:
            data = bytearray(f.read())
            for i in range(100, 2000):
                data[i] = 0xFF
            f.seek(0)
            f.write(data)
        self.write("Mario.nes", b"NES\x1a" + b"\0" * 64, self.box)
        st = self.inbox()[0]
        self.assertTrue(os.path.isfile(self.roms("nes", "Mario.nes")))
        self.assertEqual(st["errors"], 1)
        self.assertTrue(os.path.isfile(os.path.join(self.box, "unsorted", "Broken.zip")))
        self.assertEqual(self.events[-1]["event"], "done")
        self.assertEqual([d for d in os.listdir(self.box) if d.startswith(".staging")], [])

    def test_archive_bigger_than_the_free_space_isnt_unpacked(self):
        self.zip("Big.zip", {"Game.cue": cue("Game.bin"), "Game.bin": raw_disc(pvd("PLAYSTATION"))})
        full = shutil._ntuple_diskusage(10 << 30, 10 << 30, 1 << 20)
        with mock.patch.object(importer.shutil, "disk_usage", lambda p: full):
            st = self.inbox()[0]
        self.assertEqual(st["errors"], 1)
        self.assertIn("MiB free", self.items()[-1]["reason"])
        self.assertFalse(os.path.exists(self.roms("psx")))
        self.assertEqual([d for d in os.listdir(self.box) if d.startswith(".staging")], [])

    # --- copies in progress and leftovers ------------------------------------------------------

    def settled_inbox(self, *fresh, hours=1):
        """inbox() with settle=30, `hours` after the newest change in the test's tree, with the
        `fresh` files and folders changed then (a ctime can't be set back: everything else is
        old by that clock). The clock comes from the files' own times, not the wall clock, so
        a slow run can't make anything fresh or settled."""
        newest = 0
        for d, dirs, files in os.walk(self.tmp):
            for p in [d] + [os.path.join(d, f) for f in files]:
                st = os.lstat(p)
                newest = max(newest, st.st_mtime, st.st_ctime)
        later = newest + 3600 * hours
        for p in fresh:
            os.utime(p, (later, later))
        with mock.patch.object(importer.time, "time", lambda: later):
            return importer.inbox(self.events.append, settle=30)

    def test_settle_skips_a_folder_still_being_copied_into(self):
        d = os.path.join(self.box, "Game")
        t1 = self.write("Game (Track 01).bin", raw_disc(pvd("PLAYSTATION")), d)
        part = self.write("Game (Track 02).bin.part", b"\0" * 100, d)  # still coming
        self.write("Mario.nes", b"NES\x1a" + b"\0" * 64, os.path.join(self.box, "other"))
        self.settled_inbox(part)
        self.assertTrue(os.path.isfile(t1))
        self.assertFalse(os.path.exists(self.roms("psx")))
        self.assertTrue(os.path.isfile(self.roms("nes", "Mario.nes")))

    def test_settle_counts_the_ctime(self):
        # a copy over SMB sets the finished file's mtime back to the source's: its ctime is now
        old = time.time() - 3600
        p = self.write("Mario.nes", b"NES\x1a" + b"\0" * 64, os.path.join(self.box, "other"))
        os.utime(p, (old, old))
        importer.inbox(self.events.append, settle=30)
        self.assertTrue(os.path.isfile(p))
        self.assertFalse(os.path.exists(self.roms("nes")))

    def test_settle_counts_the_folder_itself(self):
        # between one file closing and the next being created, the folder's own times say
        d = os.path.join(self.box, "Game")
        t1 = self.write("Game (Track 01).bin", raw_disc(pvd("PLAYSTATION")), d)
        self.settled_inbox(d)
        self.assertTrue(os.path.isfile(t1))
        self.assertFalse(os.path.exists(self.roms("psx")))
        self.settled_inbox(hours=2)
        self.assertFalse(os.path.exists(t1))
        self.assertTrue(os.path.isfile(self.roms("psx", "Game (Track 01).bin")))

    def test_settle_holds_a_playlist_whose_disc_is_still_coming(self):
        d = os.path.join(self.box, "FF7")
        self.write("FF7.m3u", "Disc1/FF7 (Disc 1).cue\n", d)
        t1 = self.write("FF7 (Disc 1).bin", raw_disc(pvd("PLAYSTATION")), os.path.join(d, "Disc1"))
        c = self.write("FF7 (Disc 1).cue", cue("FF7 (Disc 1).bin"), os.path.join(d, "Disc1"))
        self.settled_inbox(c)
        self.assertTrue(os.path.isfile(os.path.join(d, "FF7.m3u")))
        self.assertFalse(os.path.exists(self.roms("psx")))
        # once it's all there, the playlist and its disc are sorted together
        self.settled_inbox(hours=2)
        self.assertTrue(os.path.isfile(self.roms("psx", "FF7.m3u")))
        self.assertTrue(os.path.isfile(self.roms("psx", "Disc1", "FF7 (Disc 1).cue")))
        self.assertFalse(os.path.exists(t1))

    def test_settle_holds_a_whole_multi_disc_copy(self):
        # FF7/ was just touched and Disc2/ is still coming: the settled Disc1/ must not go alone
        d = os.path.join(self.box, "FF7")
        m3u = self.write("FF7.m3u", "Disc1/FF7 (Disc 1).cue\nDisc2/FF7 (Disc 2).cue\n", d)
        t1 = self.write("FF7 (Disc 1).bin", raw_disc(pvd("PLAYSTATION")), os.path.join(d, "Disc1"))
        c1 = self.write("FF7 (Disc 1).cue", cue("FF7 (Disc 1).bin"), os.path.join(d, "Disc1"))
        part = self.write("FF7 (Disc 2).bin.part", b"\0" * 100, os.path.join(d, "Disc2"))
        self.settled_inbox(d, part)
        for p in (m3u, t1, c1, part):
            self.assertTrue(os.path.isfile(p), p)
        self.assertFalse(os.path.exists(self.roms("psx")))
        self.assertFalse(os.path.exists(os.path.join(self.box, "unsorted")))
        self.assertEqual(self.items(), [])

    def test_settle_holds_a_game_whose_second_disc_is_still_coming(self):
        # FF7/ itself is old (a long copy into Disc2/ doesn't touch it): Disc1/ still waits
        d = os.path.join(self.box, "FF7")
        m3u = self.write("FF7.m3u", "Disc1/FF7 (Disc 1).cue\nDisc2/FF7 (Disc 2).cue\n", d)
        t1 = self.write("FF7 (Disc 1).bin", raw_disc(pvd("PLAYSTATION")), os.path.join(d, "Disc1"))
        c1 = self.write("FF7 (Disc 1).cue", cue("FF7 (Disc 1).bin"), os.path.join(d, "Disc1"))
        part = self.write("FF7 (Disc 2).bin.part", b"\0" * 100, os.path.join(d, "Disc2"))
        self.settled_inbox(part)
        for p in (m3u, t1, c1, part):
            self.assertTrue(os.path.isfile(p), p)
        self.assertFalse(os.path.exists(self.roms("psx")))
        self.assertEqual(self.items(), [])

    def test_settle_a_fresh_file_beside_a_game_holds_only_itself(self):
        mario = self.write("Mario.nes", b"NES\x1a" + b"\0" * 64, os.path.join(self.box, "other"))
        new = self.write("Zelda.nes", b"NES\x1a" + b"\1" * 64, self.box)
        self.settled_inbox(new, self.box)
        self.assertTrue(os.path.isfile(self.roms("nes", "Mario.nes")))
        self.assertFalse(os.path.exists(mario))
        self.assertTrue(os.path.isfile(new))

    def test_failed_copy_leaves_no_part_file(self):
        src = self.write("src/Mario.nes", b"NES\x1a" + b"\0" * 64)
        with mock.patch.object(importer.shutil, "copystat", side_effect=OSError(28, "No space left")):
            st = importer.Importer(self.home, "copy", self.events.append).run(src)
        self.assertEqual(st["errors"], 1)
        self.assertEqual(os.listdir(self.roms("nes")), [])

    def test_stale_leftovers_cleaned(self):
        old = time.time() - 2 * importer.STALE
        stale = os.path.join(self.box, ".staging-old")
        p = self.write("x.bin", b"\0", stale)
        part = self.write("Game.iso.part", b"\0", self.roms("psp"))
        fresh = self.write("Now.iso.part", b"\0", self.roms("psp"))
        for x in (p, stale, part):
            os.utime(x, (old, old))
        self.inbox()
        self.assertFalse(os.path.exists(stale))
        self.assertFalse(os.path.exists(part))
        self.assertTrue(os.path.exists(fresh))  # another run's, perhaps

    def test_sigterm_removes_the_part_file(self):
        # a PSP image, sparse: 2 GiB to copy, which takes long enough to be stopped in the middle
        big = self.write("src/Big.iso", b"".join(
            pvd("PSP GAME").get(i, b"").ljust(2048, b"\0") for i in range(24)))
        os.truncate(big, 2 << 30)
        p = subprocess.Popen([sys.executable, os.path.join(PKG, "kettle-emu-import"), "run",
                              os.path.dirname(big), "--copy"], stdout=subprocess.PIPE, text=True)
        for line in p.stdout:
            if json.loads(line)["event"] == "progress":
                break  # copying
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=30)
        self.assertEqual(p.returncode, 143)
        self.assertFalse(os.path.exists(self.roms("psp", "Big.iso")))
        for d, _, fs in os.walk(self.home):
            self.assertEqual([f for f in fs if f.endswith(".part")], [], d)

    # --- sheets ---------------------------------------------------------------------------------

    def test_bom_cue_and_m3u(self):
        d = os.path.join(self.box, "g")
        self.write("Game.bin", raw_disc(pvd("PLAYSTATION")), d)
        self.write("Game.cue", "﻿" + cue("Game.bin"), d)
        self.write("Two.bin", raw_disc(pvd("PLAYSTATION")), d)
        self.write("Two.cue", cue("Two.bin"), d)
        self.write("Two.m3u", "﻿Two.cue\n", d)
        self.assertEqual(identify.refs_of(os.path.join(d, "Game.cue")), ["Game.bin"])
        self.assertEqual(identify.refs_of(os.path.join(d, "Two.m3u")), ["Two.cue", "Two.bin"])
        self.inbox()
        self.assertEqual(sorted(os.listdir(self.roms("psx"))),
                         ["Game.bin", "Game.cue", "Two.bin", "Two.cue", "Two.m3u"])
        self.assertEqual(len(self.items()), 2)

    def test_cue_naming_its_bin_in_another_case(self):
        # a FAT/exFAT card finds GAME.BIN for Game.bin: the same file (a hard link here)
        d = os.path.join(self.box, "g")
        b = self.write("Game.bin", raw_disc(pvd("PLAYSTATION")), d)
        os.link(b, os.path.join(d, "GAME.BIN"))
        self.write("Game.cue", cue("GAME.BIN"), d)
        self.inbox()
        self.assertEqual([e["src"] for e in self.items()], [os.path.join(d, "Game.cue")])
        self.assertEqual(sorted(os.listdir(self.roms("psx"))), ["GAME.BIN", "Game.cue"])

    def test_sheet_pointing_outside_its_folder(self):
        secret = self.write("home/.ssh/id_ed25519", b"KEY")
        outside = self.write("victim.txt", b"precious")
        d = os.path.join(self.box, "a", "b")
        self.write("Game.cue", cue("../../../.ssh/id_ed25519"), d)
        self.write("Two.cue", cue(outside), d)
        self.write("Disc.m3u", "../../../victim.txt\n", d)
        for name in ("Game.cue", "Two.cue", "Disc.m3u"):
            self.assertEqual(identify.refs_of(os.path.join(d, name)), [], name)
        self.assertFalse(identify.safe_ref("..\\x.bin"))
        self.assertTrue(identify.safe_ref("disc 1/x.bin"))
        self.inbox()
        self.inbox()
        self.assertEqual(self.read(secret), b"KEY")
        self.assertEqual(self.read(outside), b"precious")

    def test_chd_guess_isnt_sorted(self):
        self.write("Saturn Game.chd", chd([(b"CHT2", "TRACK:1 TYPE:MODE1_RAW")]), self.box)
        self.write("psx/Crash.chd", chd([(b"CHT2", "TRACK:1 TYPE:MODE2_RAW")]), self.box)
        self.inbox()
        self.assertFalse(os.path.exists(self.roms("segacd")))
        self.assertTrue(os.path.isfile(os.path.join(self.box, "unsorted", "Saturn Game.chd")))
        self.assertTrue(os.path.isfile(self.roms("psx", "Crash.chd")))  # its folder says

    # --- progress -------------------------------------------------------------------------------

    def test_progress_counts_on_through_archives_and_storages(self):
        card = os.path.join(self.media, "SD")
        self.zip("Pack.zip", {f"G{i}.nes": b"NES\x1a" + os.urandom(1 << 16) for i in range(4)})
        self.write("Mario.nes", b"NES\x1a" + b"\0" * 64, self.box)
        self.write("Emulation/inbox/Zelda.gba", b"\0" * 300, card)
        with mock.patch.object(importer, "PROGRESS_EVERY", 0):
            self.inbox()
        files = total = 0
        last_done = last_bytes = 0
        for e in self.events:
            if e["event"] == "start":
                files += e["files"]
                total += e["bytes"]
            elif e["event"] == "item":
                self.assertGreaterEqual(e["done"], last_done)
                self.assertLessEqual(e["done"], files)
                last_done = e["done"]
            elif e["event"] == "progress":
                self.assertGreaterEqual(e["bytes_done"], last_bytes)
                self.assertLessEqual(e["bytes_done"], total)
                last_bytes = e["bytes_done"]
        self.assertEqual((last_done, files), (3, 3))
        self.assertEqual(last_bytes, total)

    # --- unsorted on every storage --------------------------------------------------------------

    def test_unsorted_on_cards_and_in_set_folders(self):
        card = os.path.join(self.media, "SD")
        cbox = os.path.join(card, "Emulation", "inbox")
        self.write("odd.iso", b"\0" * 40000, cbox)
        self.write("mine.iso", b"\0" * 40000, self.box)
        # an unrecognised cue set, twice: the second goes into unsorted/Odd (2)/
        for fill in (b"\1", b"\2"):
            d = os.path.join(self.box, "d")
            self.write("Odd.bin", fill * 2352, d)
            self.write("Odd (2).bin", fill * 2352, d)
            self.write("Odd.cue", 'FILE "Odd.bin" BINARY\n TRACK 01 MODE1/2352\n  INDEX 01 00:00:00\n'
                       'FILE "Odd (2).bin" BINARY\n TRACK 02 AUDIO\n  INDEX 01 00:00:00\n', d)
            self.inbox()
        listed = importer.unsorted()
        names = sorted((x["name"], x["internal"]) for x in listed)
        self.assertEqual(names, [("Odd (2)/Odd.cue", True), ("Odd.cue", True), ("mine.iso", True),
                                 ("odd.iso", False)])
        odd = next(x for x in listed if x["name"] == "odd.iso")
        self.assertEqual(odd["root"], os.path.join(card, "Emulation"))
        cue_set = next(x for x in listed if x["name"] == "Odd.cue")
        self.assertEqual(cue_set["size"], os.path.getsize(cue_set["path"]) + 2 * 2352)
        # assigned into the tree of the card it's on
        importer.assign(odd["path"], "psp", emit=self.events.append)
        self.assertTrue(os.path.isfile(os.path.join(card, "Emulation", "roms", "psp", "odd.iso")))
        out = subprocess.run([sys.executable, os.path.join(PKG, "kettle-emu-import"), "unsorted"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(len(json.loads(out)), 3)


if __name__ == "__main__":
    unittest.main()
