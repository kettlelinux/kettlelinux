import os
import struct
import tempfile
import unittest

import helpers  # noqa: F401  (the import path)
from kettle_emulation import switch

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:  # pragma: no cover
    Cipher = None

HEADER_KEY = bytes(range(32))  # a test key, not a console's


def xts_encrypt(key, data, sector=0):
    out = b""
    for i in range(0, len(data), 0x200):
        e = Cipher(algorithms.AES(key), modes.XTS((sector + i // 0x200).to_bytes(16, "big"))).encryptor()
        out += e.update(data[i:i + 0x200]) + e.finalize()
    return out


def nca(generation):
    head = bytearray(0xC00)
    head[0x200:0x204] = b"NCA3"
    head[0x206] = min(generation, 2)
    head[0x220] = generation
    return xts_encrypt(HEADER_KEY, bytes(head[:0x400])) + bytes(head[0x400:])


def pfs0(files):
    names = b"".join(n.encode() + b"\0" for n, _ in files)
    entries, off, at = b"", 0, 0
    for n, data in files:
        entries += struct.pack("<QQII", off, len(data), at, 0)
        off += len(data)
        at += len(n) + 1
    return b"PFS0" + struct.pack("<III", len(files), len(names), 0) + entries + names + b"".join(d for _, d in files)


@unittest.skipIf(Cipher is None, "no cryptography")
class Keys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data, mode="wb"):
        p = os.path.join(self.tmp.name, name)
        with open(p, mode) as f:
            f.write(data)
        return p

    def keys(self, upto, extra=()):
        lines = [f"header_key = {HEADER_KEY.hex()}"]
        lines += [f"master_key_{i:02x} = {'11' * 16}" for i in range(upto + 1)]
        lines += [f"master_key_{i:02x} = {'22' * 16}" for i in extra]
        return self.write("prod.keys", "\n".join(lines) + "\n", "w")

    def test_game_newer_than_the_keys(self):
        # the Portal's case: generation 16 needs master key 0f; the keys stop at 0a (and a stray 10)
        game = self.write("Wonder.nsp", pfs0([("a.cnmt.xml", b"x"), ("big.nca", nca(16)), ("small.nca", nca(16))]))
        msg = switch.too_new(game, self.keys(0x0A, extra=[0x10]))
        self.assertIn("key generation 0f", msg)
        self.assertIn("stop at 0a", msg)

    def test_keys_new_enough(self):
        game = self.write("Wonder.nsp", pfs0([("big.nca", nca(16))]))
        self.assertIsNone(switch.too_new(game, self.keys(0x10)))

    def test_ticket_names_the_generation_without_keys(self):
        rights = "0100000000010000" + "0" * 14 + "0b"
        game = self.write("Old.nsp", pfs0([(rights + ".tik", b"t"), ("big.nca", b"\0" * 0x400)]))
        self.assertEqual(switch.needed_key(game, {}), 0x0A)

    def test_unreadable_file_is_left_to_the_emulator(self):
        game = self.write("junk.nsp", b"not a pfs0 at all")
        self.assertIsNone(switch.too_new(game, self.keys(0x0A)))
        self.assertIsNone(switch.too_new(game, os.path.join(self.tmp.name, "missing.keys")))

    def test_xci_secure_partition(self):
        secure = pfs0([("big.nca", nca(16))]).replace(b"PFS0", b"HFS0", 1)
        # HFS0 entries are 0x40 bytes: rebuild with that size
        def hfs0(files):
            names = b"".join(n.encode() + b"\0" for n, _ in files)
            entries, off, at = b"", 0, 0
            for n, data in files:
                entries += struct.pack("<QQII", off, len(data), at, 0) + b"\0" * (0x40 - 24)
                off += len(data)
                at += len(n) + 1
            return b"HFS0" + struct.pack("<III", len(files), len(names), 0) + entries + names + b"".join(d for _, d in files)
        del secure
        root = hfs0([("secure", hfs0([("big.nca", nca(16))]))])
        game = self.write("Game.xci", b"\0" * switch.XCI_HFS0 + root)
        self.assertEqual(switch.needed_key(game, switch.read_keys(self.keys(0x0A))), 0x0F)


class TitleIds(unittest.TestCase):
    """The paths that need no cryptography (run anywhere)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        p = os.path.join(self.tmp.name, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_kinds(self):
        self.assertEqual(switch.kind("010015100b514000"), "game")   # Super Mario Bros. Wonder
        self.assertEqual(switch.kind("010015100b514800"), "update")
        self.assertEqual(switch.kind("010015100b515001"), "dlc")    # (game ^ 0x1000) + 1
        self.assertEqual(switch.kind("0100f2c0115b7012"), "dlc")

    def test_from_a_ticket(self):
        rights = "0100F2C0115B6000" + "0" * 14 + "10"
        game = self.write("Zelda.nsp", pfs0([(rights + ".tik", b"t")]))
        self.assertEqual(switch.title_id(game), "0100f2c0115b6000")

    def test_from_the_file_name(self):
        game = self.write("Pokemon Scarlet [0100A3D008C5C800][v131072] (Update).nsp", b"junk")
        self.assertEqual(switch.title_id(game), "0100a3d008c5c800")
        self.assertEqual(switch.kind(switch.title_id(game)), "update")
        self.assertIsNone(switch.title_id(self.write("Game.nsp", b"junk")))


@unittest.skipIf(Cipher is None, "no cryptography")
class TitleIdsFromHeaders(unittest.TestCase):
    def test_from_the_nca_header(self):
        head = bytearray(0xC00)
        head[0x200:0x204] = b"NCA3"
        struct.pack_into("<Q", head, 0x210, 0x010015100B514000)
        data = xts_encrypt(HEADER_KEY, bytes(head[:0x400])) + bytes(head[0x400:])
        with tempfile.TemporaryDirectory() as d:
            game = os.path.join(d, "Wonder.nsp")
            with open(game, "wb") as f:
                f.write(pfs0([("big.nca", data)]))
            self.assertEqual(switch.title_id(game, {"header_key": HEADER_KEY}), "010015100b514000")
