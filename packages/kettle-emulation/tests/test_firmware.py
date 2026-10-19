import os
import unittest
import zipfile
from unittest import mock

from helpers import Env
from kettle_emulation import importer, seed, switch

N = switch.FIRMWARE_MIN + 5


def nca_names(n=N, tag="a"):
    # firmware NCA names: hex ids, some of them metadata (.cnmt.nca)
    return [f"{tag}{i:031x}" + (".cnmt.nca" if i % 4 == 0 else ".nca") for i in range(n)]


class Firmware(Env):
    def setUp(self):
        super().setUp()
        self.box = os.path.join(self.home, "inbox")
        self.fw = os.path.join(self.home, "bios", "switch", "firmware")
        self.events = []

    def folder(self, root, names, data=b"NCA"):
        for n in names:
            self.write(n, data + n.encode(), root)
        return root

    def zipped(self, path, names, extra=()):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with zipfile.ZipFile(path, "w") as z:
            for n in names:
                z.writestr(n, b"NCA" + n.encode())
            for n, data in extra:
                z.writestr(n, data)
        return path

    def registered(self, emu):
        return os.path.join(self.tmp, emu, "Contents", "registered")

    # --- what a firmware is --------------------------------------------------------------
    def test_recognised(self):
        self.assertTrue(switch.is_firmware(self.folder(os.path.join(self.tmp, "fw"), nca_names())))
        self.assertTrue(switch.is_firmware(self.zipped(os.path.join(self.tmp, "fw.zip"), nca_names())))
        # too few NCAs, or a game among them: not a firmware
        self.assertFalse(switch.is_firmware(self.zipped(os.path.join(self.tmp, "few.zip"), nca_names(5))))
        self.assertFalse(switch.is_firmware(self.zipped(os.path.join(self.tmp, "game.zip"), nca_names(),
                                                        extra=[("Game.nsp", b"PFS0")])))

    # --- into the emulators ------------------------------------------------------------------
    def test_ryujinx_layout(self):
        # Ryujinx: registered/<id>.nca/00, ".cnmt" dropped (ContentManager.SaveNca)
        names = nca_names()
        self.folder(self.fw, names)
        reg = self.registered("ryujinx")
        self.assertEqual(switch.install_firmware("ryujinx", reg, self.fw), "firmware")
        got = sorted(os.listdir(reg))
        self.assertEqual(got, sorted(n.split(".", 1)[0] + ".nca" for n in names))
        with open(os.path.join(reg, got[0], "00"), "rb") as f:
            self.assertTrue(f.read().startswith(b"NCA"))

    def test_eden_layout(self):
        # Eden: the .nca files flat under their own names (qt_common content.cpp InstallFirmware)
        names = nca_names()
        self.zipped(os.path.join(self.fw, "Firmware 19.0.1.zip"), names)
        reg = self.registered("eden")
        self.assertEqual(switch.install_firmware("eden", reg, self.fw), "Firmware 19.0.1")
        self.assertEqual(sorted(os.listdir(reg)), sorted(names))
        self.assertEqual(switch.installed_firmware(reg), "Firmware 19.0.1")

    def test_fragmented_and_unsafe_zip_members(self):
        names = nca_names()
        extra = [("Firmware/" + names[0] + "/00", b"NCA frag"), ("../../evil.nca", b"x")]
        self.zipped(os.path.join(self.fw, "fw.zip"), names[1:], extra=extra)
        reg = self.registered("eden")
        switch.install_firmware("eden", reg, self.fw)
        self.assertIn(names[0], os.listdir(reg))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.nca")))
        self.assertTrue(all(os.path.dirname(os.path.realpath(os.path.join(reg, n))) == os.path.realpath(reg)
                            for n in os.listdir(reg)))

    def test_done_once_then_again_when_it_changes(self):
        self.folder(self.fw, nca_names(tag="a"))
        reg = self.registered("ryujinx")
        switch.install_firmware("ryujinx", reg, self.fw)
        first = os.stat(reg).st_ino
        switch.install_firmware("ryujinx", reg, self.fw)
        self.assertEqual(os.stat(reg).st_ino, first)  # unchanged: not copied again
        # a new firmware replaces the old one whole: nothing of the old version is left
        for n in os.listdir(self.fw):
            os.unlink(os.path.join(self.fw, n))
        self.folder(self.fw, nca_names(tag="b"))
        switch.install_firmware("ryujinx", reg, self.fw)
        self.assertTrue(all(n.startswith("b") for n in os.listdir(reg)))
        self.assertEqual(len(os.listdir(reg)), N)

    def test_a_failed_install_keeps_the_old_firmware(self):
        self.folder(self.fw, nca_names(tag="a"))
        reg = self.registered("eden")
        switch.install_firmware("eden", reg, self.fw)
        before = sorted(os.listdir(reg))
        self.folder(self.fw, nca_names(tag="b"))  # a different firmware now (a and b)
        with mock.patch.object(switch, "_put", side_effect=OSError(28, "No space left")):
            with self.assertRaises(OSError):
                switch.install_firmware("eden", reg, self.fw)
        self.assertEqual(sorted(os.listdir(reg)), before)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(reg), ".kettle-firmware-new")))

    def test_nothing_to_install(self):
        self.assertIsNone(switch.install_firmware("eden", self.registered("eden"), self.fw))
        self.assertIsNone(switch.installed_firmware(self.registered("eden")))

    def test_keeper_installs_before_a_launch(self):
        self.folder(self.fw, nca_names())
        reg = self.registered("ryujinx")
        with mock.patch.object(seed, "RYUJINX_FIRMWARE", reg), \
                mock.patch.object(seed, "RYUJINX_DIR", os.path.join(self.tmp, "ryujinx")), \
                mock.patch.object(seed, "SWITCH_KEYS", os.path.join(self.tmp, "nokeys")), \
                mock.patch.object(switch, "firmware_dir", lambda: self.fw):
            seed.keep_ryujinx()
        self.assertEqual(len(os.listdir(reg)), N)

    # --- sorting it in ---------------------------------------------------------------------
    def test_firmware_folder_in_the_inbox(self):
        src = self.folder(os.path.join(self.box, "Firmware 19.0.1"), nca_names())
        self.write("Mario.nes", b"NES\x1a" + b"\0" * 64, self.box)
        importer.inbox(self.events.append, settle=0)
        self.assertEqual(len(os.listdir(self.fw)), N)
        self.assertFalse(os.path.exists(src))  # moved, its folder gone
        self.assertFalse(os.path.exists(os.path.join(self.home, "roms", "switch")) and
                         os.listdir(os.path.join(self.home, "roms", "switch")))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "roms", "nes", "Mario.nes")))
        self.assertIn("firmware", [b["file"] for e in self.events if e["event"] == "done" for b in e["bios"]])

    def test_firmware_zip_replaces_the_old_one(self):
        self.folder(self.fw, nca_names(tag="a"))
        self.zipped(os.path.join(self.box, "Firmware 20.0.0.zip"), nca_names(tag="b"))
        importer.inbox(self.events.append, settle=0)
        self.assertEqual(os.listdir(self.fw), ["Firmware 20.0.0.zip"])
        self.assertEqual(switch.find_firmware(self.fw)[2], "Firmware 20.0.0")

    def test_a_loose_nca_is_no_game(self):
        self.write("stray.nca", b"NCA", self.box)
        importer.inbox(self.events.append, settle=0)
        self.assertTrue(os.path.isfile(os.path.join(self.box, "unsorted", "stray.nca")))
        self.assertFalse(os.path.exists(self.fw))

    def test_scan_reports_the_firmware(self):
        self.folder(os.path.join(self.tmp, "stick", "fw"), nca_names())
        r = importer.scan(os.path.join(self.tmp, "stick"))
        self.assertEqual([b["file"] for b in r["bios"]], ["firmware"])
        self.assertEqual(r["unsorted_count"], 0)
        self.assertEqual(r["games_total"], 0)


if __name__ == "__main__":
    unittest.main()
