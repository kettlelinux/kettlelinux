import struct
import unittest
import zipfile

from helpers import Env, chd, cooked_disc, pvd, raw_disc

from kettle_emulation import identify


def sysof(m):
    return m.system if m else None


class Identify(Env):
    def id(self, rel, data, hint=None):
        return identify.identify(self.write(rel, data), hint)

    def test_unique_extension(self):
        m = self.id("a/Game.nes", b"NES\x1a" + b"\0" * 100)
        self.assertEqual((m.system, m.confidence), ("nes", 0.9))

    def test_gb_cgb_only(self):
        rom = bytearray(0x200)
        rom[0x143] = 0xC0
        self.assertEqual(sysof(self.id("x.gb", bytes(rom))), "gbc")
        rom[0x143] = 0x80  # works on both: stays a Game Boy game
        self.assertEqual(sysof(self.id("y.gb", bytes(rom))), "gb")

    def test_bin_genesis(self):
        rom = bytearray(0x80000)
        rom[0x100:0x110] = b"SEGA GENESIS    "
        m = self.id("s.bin", bytes(rom))
        self.assertEqual((m.system, m.confidence), ("megadrive", 1.0))

    def test_bin_32x(self):
        rom = bytearray(0x80000)
        rom[0x100:0x110] = b"SEGA 32X        "
        self.assertEqual(sysof(self.id("s.bin", bytes(rom))), "sega32x")

    def test_bin_atari_by_size(self):
        m = self.id("pitfall.bin", b"\x78\xd8" * 2048)
        self.assertEqual((m.system, m.confidence), ("atari2600", 0.7))

    def test_bin_raw_psx_needs_cue(self):
        m = self.id("ff.bin", raw_disc(pvd("PLAYSTATION")))
        self.assertEqual(m.system, "psx")
        self.assertTrue(m.needs_cue)

    def test_bin_cooked_segacd(self):
        m = self.id("sonic.bin", cooked_disc({0: b"SEGADISCSYSTEM  "}))
        self.assertEqual(m.system, "segacd")
        self.assertTrue(m.needs_cue)

    def test_bin_raw_mode1_segacd(self):
        self.assertEqual(sysof(self.id("cd.bin", raw_disc({0: b"SEGADISCSYSTEM"}, mode=1))), "segacd")

    def test_bin_unknown_small(self):
        self.assertIsNone(sysof(self.id("odd.bin", b"\1" * 100)))

    def test_folder_hint(self):
        m = self.id("roms/atari2600/x.bin", b"\1" * 3000, hint="atari2600")
        self.assertEqual((m.system, m.confidence), ("atari2600", 0.95))

    def test_header_beats_folder(self):
        rom = bytearray(0x40000)
        rom[0x100:0x104] = b"SEGA"
        self.assertEqual(sysof(self.id("x.bin", bytes(rom), hint="atari2600")), "megadrive")

    def test_gc_and_wii_iso(self):
        gc = bytearray(0x400)
        struct.pack_into(">I", gc, 0x1C, identify.GC_MAGIC)
        wii = bytearray(0x400)
        struct.pack_into(">I", wii, 0x18, identify.WII_MAGIC)
        self.assertEqual(sysof(self.id("g.iso", bytes(gc))), "gc")
        self.assertEqual(sysof(self.id("w.iso", bytes(wii))), "wii")

    def test_rvz_gcz_wbfs(self):
        rvz = bytearray(0x100)
        rvz[:4] = b"RVZ\x01"
        struct.pack_into(">I", rvz, 0x48, 2)
        self.assertEqual(sysof(self.id("w.rvz", bytes(rvz))), "wii")
        struct.pack_into(">I", rvz, 0x48, 1)
        self.assertEqual(sysof(self.id("g.rvz", bytes(rvz))), "gc")
        gcz = bytearray(0x100)
        struct.pack_into("<II", gcz, 0, 0xB10BC001, 1)
        self.assertEqual(sysof(self.id("w.gcz", bytes(gcz))), "wii")
        self.assertEqual(sysof(self.id("w.wbfs", b"WBFS" + b"\0" * 300)), "wii")

    def test_ciso_dolphin_vs_psp(self):
        psp = bytearray(0x100)
        psp[:4] = b"CISO"
        struct.pack_into("<I", psp, 4, 0x18)
        self.assertEqual(sysof(self.id("p.ciso", bytes(psp))), "psp")
        dol = bytearray(0x8100)
        dol[:4] = b"CISO"
        struct.pack_into("<I", dol, 4, 0x200000)
        struct.pack_into(">I", dol, 0x8000 + 0x1C, identify.GC_MAGIC)
        self.assertEqual(sysof(self.id("g.ciso", bytes(dol))), "gc")

    def test_psp_iso(self):
        self.assertEqual(sysof(self.id("p.iso", cooked_disc(pvd("PSP GAME")))), "psp")

    def test_psx_iso_vs_ps2(self):
        psx = pvd("PLAYSTATION", files={"SYSTEM.CNF": b"BOOT = cdrom:\\SLUS_000.01;1\r\n"})
        self.assertEqual(sysof(self.id("a.iso", cooked_disc(psx))), "psx")
        ps2 = pvd("PLAYSTATION", files={"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_200.02;1\r\n"})
        self.assertEqual(sysof(self.id("b.iso", cooked_disc(ps2))), "ps2")

    def test_dos_iso_by_folder(self):
        self.assertEqual(sysof(self.id("dos/doom.iso", cooked_disc(pvd("LINUX")), hint="dos")), "dos")

    def test_cue_psx(self):
        self.write("d/Game (Track 1).bin", raw_disc(pvd("PLAYSTATION")))
        self.write("d/Game (Track 2).bin", b"\0" * 2352 * 4)
        cue = self.write("d/Game.cue", 'FILE "Game (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\n'
                         '    INDEX 01 00:00:00\nFILE "Game (Track 2).bin" BINARY\n'
                         '  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n')
        m = identify.identify(cue)
        self.assertEqual(m.system, "psx")
        self.assertEqual(list(m.refs), ["Game (Track 1).bin", "Game (Track 2).bin"])

    def test_cue_pce_cd_data_second(self):
        self.write("p/t1.bin", b"\0" * 2352 * 10)
        self.write("p/t2.bin", raw_disc({1: b"\0" * 32 + b"PC Engine CD-ROM SYSTEM"}, mode=1))
        cue = self.write("p/g.cue", 'FILE "t1.bin" BINARY\n TRACK 01 AUDIO\n  INDEX 01 00:00:00\n'
                         'FILE "t2.bin" BINARY\n TRACK 02 MODE1/2352\n  INDEX 01 00:00:00\n')
        self.assertEqual(sysof(identify.identify(cue)), "pcenginecd")

    def test_cue_single_bin_offset(self):
        audio = b"\0" * 2352 * 150
        self.write("s/all.bin", audio + raw_disc({0: b"SEGA SEGAKATANA"}, mode=1))
        cue = self.write("s/g.cue", 'FILE "all.bin" BINARY\n TRACK 01 AUDIO\n  INDEX 01 00:00:00\n'
                         ' TRACK 02 MODE1/2352\n  INDEX 01 00:02:00\n')
        self.assertEqual(sysof(identify.identify(cue)), "dreamcast")

    def test_gdi(self):
        self.write("dc/track01.raw", b"\0")
        gdi = self.write("dc/g.gdi", '3\n1 0 4 2352 track01.raw 0\n2 600 0 2352 "track 02.raw" 0\n')
        m = identify.identify(gdi)
        self.assertEqual(m.system, "dreamcast")
        self.assertEqual(list(m.refs), ["track01.raw", "track 02.raw"])

    def test_chd(self):
        self.assertEqual(sysof(self.id("a.chd", chd([(b"CHT2", "TRACK:1 TYPE:MODE2_RAW SUBTYPE:NONE FRAMES:100")]))), "psx")
        self.assertEqual(sysof(self.id("b.chd", chd([(b"CHGD", "x"), (b"CHT2", "TRACK:1 TYPE:MODE1")]))), "dreamcast")
        self.assertEqual(sysof(self.id("c.chd", chd([(b"CHT2", "TRACK:1 TYPE:AUDIO"), (b"CHT2", "TRACK:2 TYPE:MODE1_RAW")]))), "pcenginecd")
        self.assertEqual(sysof(self.id("d.chd", chd([(b"CHT2", "TRACK:1 TYPE:MODE1_RAW")]))), "segacd")
        m = self.id("e.chd", chd([(b"CHT2", "TRACK:1 TYPE:MODE1_RAW")]), hint="psx")
        self.assertEqual((m.system, m.confidence), ("psx", 0.95))

    def test_m3u(self):
        self.write("m/d1.bin", raw_disc(pvd("PLAYSTATION")))
        self.write("m/d1.cue", 'FILE "d1.bin" BINARY\n TRACK 01 MODE2/2352\n  INDEX 01 00:00:00\n')
        self.write("m/d2.cue", 'FILE "d2.bin" BINARY\n TRACK 01 MODE2/2352\n')
        self.write("m/d2.bin", raw_disc(pvd("PLAYSTATION")))
        m3u = self.write("m/g.m3u", "#EXTM3U\nd1.cue\nd2.cue\n")
        m = identify.identify(m3u)
        self.assertEqual(m.system, "psx")
        self.assertEqual(list(m.refs), ["d1.cue", "d1.bin", "d2.cue", "d2.bin"])

    def zip(self, rel, members):
        p = self.write(rel, b"")
        with zipfile.ZipFile(p, "w") as z:
            for n, d in members.items():
                z.writestr(n, d)
        return p

    def test_zip_single_rom(self):
        m = identify.identify(self.zip("z/Game.zip", {"Game.gba": b"\0" * 300, "readme.txt": "hi"}))
        self.assertEqual((m.system, m.extract), ("gba", True))

    def test_zip_single_bin_header(self):
        rom = bytearray(0x40000)
        rom[0x100:0x104] = b"SEGA"
        m = identify.identify(self.zip("z/S.zip", {"S.bin": bytes(rom)}))
        self.assertEqual((m.system, m.extract), ("megadrive", True))

    def test_zip_dos_and_arcade(self):
        m = identify.identify(self.zip("z/Doom.zip", {"DOOM.EXE": b"MZ", "DOOM.WAD": b"IWAD"}))
        self.assertEqual((m.system, m.extract), ("dos", False))
        m = identify.identify(self.zip("z/pacman.zip", {"pacman.6e": b"\0", "pacman.6f": b"\0"}))
        self.assertEqual((m.system, m.extract), ("arcade", False))

    def test_zip_in_arcade_folder_kept(self):
        m = identify.identify(self.zip("arcade/sf2.zip", {"sf2.nes": b"x"}), "arcade")
        self.assertEqual((m.system, m.extract), ("arcade", False))


if __name__ == "__main__":
    unittest.main()
