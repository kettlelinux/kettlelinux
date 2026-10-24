import os
import struct
import unittest

from helpers import Env
from kettle_emulation import bios, importer, ps2, run


def fake_ps2_bios(romver=b"0230AC20040602", size=4 << 20, romdir_at=0x2700):
    """A PS2 BIOS laid out as PCSX2's BiosTools.cpp reads one: RESET's file from 0 to the ROM
    directory, the ROMDIR, then ROMVER's 14-byte version and zone."""
    data = bytearray(size)
    entries = [(b"RESET", romdir_at), (b"ROMDIR", 0x40), (b"ROMVER", 0x10)]
    for i, (name, fsize) in enumerate(entries):
        struct.pack_into("<10sHI", data, romdir_at + 16 * i, name, 0, fsize)
    data[romdir_at + 0x40:romdir_at + 0x40 + 14] = romver  # RESET ends at the dir, ROMDIR is 0x40
    return bytes(data)


class Bios(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        p = os.path.join(self.tmp.name, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_a_console_dump_is_recognised(self):
        info = ps2.bios_info(self.write("scph39001.bin", fake_ps2_bios()))
        self.assertEqual(info, {"version": "2.30", "zone": "A", "date": "20040602"})

    def test_not_a_bios(self):
        self.assertIsNone(ps2.bios_info(self.write("arcade.bin", fake_ps2_bios(b"0100TZ20000901"))))
        self.assertIsNone(ps2.bios_info(self.write("small.bin", fake_ps2_bios(size=2 << 20, romdir_at=0x100))))
        self.assertIsNone(ps2.bios_info(self.write("zeros.bin", bytes(4 << 20))))
        # a RESET off an entry boundary is no ROM directory
        self.assertIsNone(ps2.bios_info(self.write("odd.bin", b"\0" * 3 + fake_ps2_bios()[:-3])))


class Installed(Env):
    def test_found_elsewhere_then_installed_where_armsx2_looks(self):
        bdir = os.path.join(self.home, "bios")
        self.write("PS2 BIOS (USA) v2.30.bin", fake_ps2_bios(), bdir)
        st = bios.status("ps2")["ps2"]
        self.assertEqual(st["state"], "missing-required")
        self.assertTrue(st["entries"][0]["elsewhere"])
        self.assertEqual(bios.install_found("ps2"), ["your PS2's BIOS dump"])
        dest = os.path.join(bdir, "pcsx2", "bios", "PS2 BIOS (USA) v2.30.bin")
        self.assertTrue(os.path.isfile(dest))
        self.assertEqual(bios.status("ps2")["ps2"]["state"], "ok")
        self.assertEqual(bios.missing_required("ps2"), [])

    def test_no_dump_is_missing(self):
        self.assertEqual(bios.missing_required("ps2"), ["your PS2's BIOS dump"])

    def test_importer_sorts_a_dump_by_its_contents(self):
        box = os.path.join(self.home, "inbox")
        self.write("scph70012.bin", fake_ps2_bios(), box)
        importer.inbox(lambda ev: None, settle=0)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "bios", "pcsx2", "bios", "scph70012.bin")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "roms", "megadrive", "scph70012.bin")))

    def test_emu_run_refuses_a_ps2_game_without_a_dump(self):
        with self.assertRaises(run.Refused) as cm:
            run.check_bios("ps2")
        self.assertEqual(cm.exception.reason, "bios")
        self.assertIn("your PS2's BIOS dump", str(cm.exception))
        self.write("scph39001.bin", fake_ps2_bios(), os.path.join(self.home, "bios"))
        run.check_bios("ps2")  # found elsewhere in Emulation/bios: installed, then fine
        self.assertTrue(os.path.isfile(os.path.join(self.home, "bios", "pcsx2", "bios", "scph39001.bin")))
