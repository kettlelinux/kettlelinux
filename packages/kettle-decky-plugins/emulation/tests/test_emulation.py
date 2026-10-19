# python3 -m unittest emulation/tests/test_emulation.py (from packages/kettle-decky-plugins)
import json
import os
import re
import sys
import struct
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))
import art  # noqa: E402
import cores  # noqa: E402
import roms  # noqa: E402
import saves  # noqa: E402

SYSTEMS = {
    "psx": {"name": "PlayStation", "folders": ["psx", "ps1"], "extensions": ["cue", "chd", "m3u", "pbp"]},
    "dreamcast": {"name": "Dreamcast", "folders": ["dreamcast"], "extensions": ["gdi", "chd", "cdi"]},
    "snes": {"name": "SNES", "folders": ["snes"], "extensions": ["sfc", "smc"]},
    "megadrive": {"name": "Genesis", "folders": ["megadrive", "genesis"], "extensions": ["md", "bin"]},
}


RA_SAVES = [{"dir": "Emulation/saves/retroarch"}, {"dir": "Emulation/states/retroarch"}]
ALL_KEYS = ["save_state", "load_state", "menu", "fast_forward", "slot_down", "slot_up", "rewind", "screenshot",
            "swap_screens", "quit"]
# systems.json v2 as the plugin reads it: emulators from Flathub, RetroArch's cores from the buildbot
DB_V2 = {
    "version": 2,
    "flatpaks": {
        "org.libretro.RetroArch": {"name": "RetroArch", "permissions": ["~/Emulation", "/run/media"]},
        "org.ppsspp.PPSSPP": {"name": "PPSSPP", "permissions": ["~/Emulation:ro", "--filesystem=/run/media"]},
        "org.purei.Play": {"name": "Play!", "permissions": ["~/Emulation"]},
        "net.rpcs3.RPCS3": {"name": "RPCS3", "permissions": ["~/Emulation"]},
        "io.github.ryubing.Ryujinx": {"name": "Ryujinx", "permissions": []},
        "dev.eden_emu.eden": {"name": "Eden", "permissions": []},
    },
    "emulators": {
        "ra-snes9x": {"name": "Snes9x", "kind": "libretro", "core": "snes9x", "license": "Snes9x (non-commercial)",
                      "free": False, "hotkeys": ALL_KEYS, "saves": RA_SAVES},
        "ra-bsnes": {"name": "bsnes", "kind": "libretro", "core": "bsnes", "license": "GPL-3.0", "free": True,
                     "hotkeys": ALL_KEYS, "saves": RA_SAVES},
        "ra-bluemsx": {"name": "blueMSX", "kind": "libretro", "core": "bluemsx", "license": "GPL-2.0", "free": True,
                       "hotkeys": ALL_KEYS, "saves": RA_SAVES},
        "ppsspp": {"name": "PPSSPP", "kind": "flatpak", "flatpak": "org.ppsspp.PPSSPP", "license": "GPL-2.0", "free": True,
                   "hotkeys": ["save_state", "load_state", "menu", "fast_forward", "slot_down", "slot_up", "screenshot", "quit"],
                   "saves": [{"dir": ".var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP/SAVEDATA"},
                             {"dir": ".var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP/PPSSPP_STATE", "glob": "*.ppst"}]},
        "play": {"name": "Play!", "kind": "flatpak", "flatpak": "org.purei.Play", "license": "BSD-2-Clause", "free": True,
                 "hotkeys": ["quit"], "saves": []},
        "rpcs3": {"name": "RPCS3", "kind": "flatpak", "flatpak": "net.rpcs3.RPCS3", "license": "GPL-2.0", "free": True,
                  "experimental": True, "hotkeys": ["quit"], "needs": ["Install the PS3 firmware in RPCS3 first."]},
        "ryujinx": {"name": "Ryujinx", "kind": "flatpak", "flatpak": "io.github.ryubing.Ryujinx", "license": "MIT", "free": True,
                    "hotkeys": ["quit"], "needs": ["Add your keys and firmware in Ryujinx."]},
        "eden": {"name": "Eden", "kind": "flatpak", "flatpak": "dev.eden_emu.eden", "license": "GPL-3.0", "free": True,
                 "experimental": True, "hotkeys": ["quit"]},
    },
    "systems": {
        "snes": {"name": "SNES", "folders": ["snes"], "extensions": ["sfc", "smc"], "emulators": ["ra-bsnes", "ra-snes9x"],
                 "thumbnails": "Nintendo_-_Super_Nintendo_Entertainment_System", "rewind": True},
        "msx": {"name": "MSX", "folders": ["msx"], "extensions": ["rom"], "emulators": ["ra-bluemsx"]},
        "psp": {"name": "PSP", "folders": ["psp"], "extensions": ["iso"], "emulators": ["ppsspp"]},
        "ps2": {"name": "PlayStation 2", "folders": ["ps2"], "extensions": ["iso"], "emulators": ["play"]},
        "ps3": {"name": "PlayStation 3", "folders": ["ps3"], "extensions": ["pkg"], "emulators": ["rpcs3"]},
        "switch": {"name": "Switch", "folders": ["switch"], "extensions": ["nsp"], "emulators": ["ryujinx", "eden"]},
    },
}


def write_db(dirname, db=DB_V2):
    p = os.path.join(dirname, "systems.json")
    with open(p, "w") as f:
        json.dump(db, f)
    return p


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class Roms(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home", "Emulation")
        self.card = os.path.join(self.tmp.name, "card")
        self.roots = [{"path": os.path.dirname(self.home), "emulation": self.home, "uuid": "int", "internal": True},
                      {"path": self.card, "emulation": os.path.join(self.card, "Emulation"), "uuid": "CARD-1", "internal": False}]

    def tearDown(self):
        self.tmp.cleanup()

    def r(self, *p):
        return os.path.join(self.home, "roms", *p)

    def test_ids_are_stable_across_mount_points(self):
        a = roms.rom_id("CARD-1", "roms/snes/Game.sfc")
        self.assertEqual(a, roms.rom_id("CARD-1", "roms/snes/Game.sfc"))
        self.assertNotEqual(a, roms.rom_id("CARD-2", "roms/snes/Game.sfc"))
        touch(os.path.join(self.card, "Emulation", "roms", "snes", "Game (USA).sfc"))
        first = roms.scan(self.roots, SYSTEMS)
        moved = os.path.join(self.tmp.name, "card2")
        os.rename(self.card, moved)
        roots = [self.roots[0], {**self.roots[1], "path": moved, "emulation": os.path.join(moved, "Emulation")}]
        second = roms.scan(roots, SYSTEMS)
        self.assertEqual(list(first), list(second))
        self.assertNotEqual(first[next(iter(first))]["path"], second[next(iter(second))]["path"])

    def test_cue_and_m3u_hide_what_they_list(self):
        touch(self.r("psx", "Game (Disc 1).cue"), b'FILE "Game (Disc 1).bin" BINARY\n  TRACK 01 MODE2/2352\n')
        touch(self.r("psx", "Game (Disc 1).bin"))
        touch(self.r("psx", "Game (Disc 2).cue"), b'FILE "Game (Disc 2).bin" BINARY\n')
        touch(self.r("psx", "Game.m3u"), b"Game (Disc 1).cue\nGame (Disc 2).cue\n")
        touch(self.r("psx", "Other.chd"))
        found = roms.scan(self.roots, SYSTEMS)
        names = sorted(os.path.basename(f["path"]) for f in found.values())
        self.assertEqual(names, ["Game.m3u", "Other.chd"])

    def test_gdi_hides_tracks(self):
        touch(self.r("dreamcast", "Crazy", "disc.gdi"), b'3\n1 0 4 2352 track01.bin 0\n2 600 0 2352 "track 02.raw" 0\n3 45000 4 2352 track03.bin 0\n')
        for t in ("track01.bin", "track 02.raw", "track03.bin"):
            touch(self.r("dreamcast", "Crazy", t))
        found = roms.scan(self.roots, SYSTEMS)
        self.assertEqual([os.path.basename(f["path"]) for f in found.values()], ["disc.gdi"])

    def test_bin_listed_by_cue_hidden_in_megadrive_too(self):
        touch(self.r("megadrive", "Sonic.bin"))
        found = roms.scan(self.roots, SYSTEMS)
        self.assertEqual(len(found), 1)

    def test_internal_wins_over_card(self):
        touch(self.r("snes", "Game (USA).sfc"))
        touch(os.path.join(self.card, "Emulation", "roms", "SNES", "game (usa).sfc"))
        touch(os.path.join(self.card, "Emulation", "roms", "snes", "Only On Card.sfc"))
        found = roms.scan(self.roots, SYSTEMS)
        self.assertEqual(len(found), 2)
        game = next(f for f in found.values() if f["title"] == "Game")
        self.assertEqual(game["storage"], "int")

    def test_folder_aliases_hidden_files_depth(self):
        touch(self.r("genesis", "A.md"))
        touch(self.r("snes", ".hidden.sfc"))
        touch(self.r("snes", "a", "b", "c", "Deep.sfc"))
        touch(self.r("snes", "a", "b", "c", "d", "TooDeep.sfc"))
        touch(self.r("snes", "readme.txt"))
        titles = sorted(f["title"] for f in roms.scan(self.roots, SYSTEMS).values())
        self.assertEqual(titles, ["A", "Deep"])

    def test_titles(self):
        self.assertEqual(roms.title("/x/Super Mario World (USA) [!].sfc"), "Super Mario World")
        touch(self.r("snes", "Game (USA).sfc"))
        touch(self.r("snes", "Game (Japan).sfc"))
        titles = sorted(f["title"] for f in roms.scan(self.roots, SYSTEMS).values())
        self.assertEqual(titles, ["Game (Japan)", "Game (USA)"])

    def test_plan(self):
        touch(self.r("snes", "New.sfc"))
        touch(self.r("snes", "Kept.sfc"))
        found = roms.scan(self.roots, SYSTEMS)
        new = next(k for k, v in found.items() if v["title"] == "New")
        kept = next(k for k, v in found.items() if v["title"] == "Kept")
        state = {
            kept: {**found[kept], "appid": 1},
            "gone-internal": {"system": "snes", "path": self.r("snes", "Gone.sfc"), "storage": "int", "appid": 2},
            "on-pulled-card": {"system": "snes", "path": "/run/media/x/c/Emulation/roms/snes/C.sfc", "storage": "CARD-9", "appid": 3},
            "deleted-in-steam": {"system": "snes", "path": self.r("snes", "Del.sfc"), "storage": "int", "appid": 4, "deleted": True},
        }
        touch(self.r("snes", "Del.sfc"))
        found = roms.scan(self.roots, SYSTEMS)
        deleted_id = next(k for k, v in found.items() if v["title"] == "Del")
        state[deleted_id] = state.pop("deleted-in-steam")
        p = roms.plan(found, state, {"int", "CARD-1"})
        self.assertEqual([a["id"] for a in p["add"]], [new])
        self.assertEqual([r["id"] for r in p["remove"]], ["gone-internal"])
        self.assertEqual(p["update"], [])
        state[kept]["path"] = "/elsewhere/Kept.sfc"
        p = roms.plan(found, state, {"int"})
        self.assertEqual([u["id"] for u in p["update"]], [kept])

    def test_scan_error_keeps_the_storage_games(self):
        touch(os.path.join(self.card, "Emulation", "roms", "snes", "A.sfc"))
        found = roms.scan(self.roots, SYSTEMS)
        state = {rid: {**r, "appid": 1} for rid, r in found.items()}
        sub = os.path.join(self.card, "Emulation", "roms", "snes")
        os.chmod(sub, 0)
        try:
            if os.access(sub, os.R_OK):
                self.skipTest("running as root")
            failed = set()
            found = roms.scan(self.roots, SYSTEMS, failed)
        finally:
            os.chmod(sub, 0o755)
        self.assertEqual(failed, {"CARD-1"})
        self.assertEqual(roms.plan(found, state, {"int", "CARD-1"} - failed)["remove"], [])
        # a folder that just isn't there is no error: its games are gone
        failed = set()
        roms.scan([self.roots[0]], SYSTEMS, failed)
        self.assertEqual(failed, set())

    def test_brought_back_game_offers_its_old_shortcut(self):
        touch(self.r("snes", "A.sfc"))
        found = roms.scan(self.roots, SYSTEMS)
        rid = next(iter(found))
        p = roms.plan(found, {rid: {**found[rid], "appid": None, "was_appid": 7}}, {"int"})
        self.assertEqual([(a["id"], a["was"]) for a in p["add"]], [(rid, 7)])

    def test_game_moved_to_another_storage_keeps_its_shortcut(self):
        card = os.path.join(self.card, "Emulation", "roms", "SNES")
        touch(os.path.join(card, "Sub", "Game.sfc"), b"rom")
        touch(os.path.join(card, "Other.sfc"), b"other")
        touch(os.path.join(card, "Deleted.sfc"), b"del")
        found = roms.scan(self.roots, SYSTEMS)
        ids = {v["title"]: k for k, v in found.items()}
        state = {rid: {**r, "appid": n, "art": True, "layout": True} for n, (rid, r) in enumerate(found.items(), 1)}
        state[ids["Deleted"]]["deleted"] = True
        choices = {ids["Game"]: "snes9x"}
        appid = state[ids["Game"]]["appid"]
        # copied in: the internal copy wins over the card's (same size); Other's differs in size;
        # Deleted moves too and stays deleted
        touch(self.r("snes", "Sub", "Game.sfc"), b"rom")
        touch(self.r("snes", "Other.sfc"), b"changed")
        touch(self.r("snes", "Deleted.sfc"), b"del")
        found = roms.scan(self.roots, SYSTEMS)
        new = {v["title"]: k for k, v in found.items()}
        moves = roms.carry_moves(found, state, choices, {"int", "CARD-1"})
        self.assertEqual(sorted(moves), sorted([(ids["Game"], new["Game"]), (ids["Deleted"], new["Deleted"])]))
        self.assertNotIn(ids["Game"], state)
        g = state[new["Game"]]
        self.assertEqual((g["appid"], g["art"], g["layout"], g["storage"]), (appid, True, True, "int"))
        self.assertEqual(choices, {new["Game"]: "snes9x"})
        self.assertTrue(state[new["Deleted"]]["deleted"])
        p = roms.plan(found, state, {"int", "CARD-1"})
        # the shortcut runs the internal copy now, nothing removed or added for it
        self.assertEqual([(u["id"], u["path"]) for u in p["update"]], [(new["Game"], self.r("snes", "Sub", "Game.sfc"))])
        self.assertEqual([a["id"] for a in p["add"]], [new["Other"]])
        self.assertEqual([r["id"] for r in p["remove"]], [ids["Other"]])
        # a pulled card's games aren't moved
        state2 = {ids["Other"]: {**state[ids["Other"]], "size": 7}}
        self.assertEqual(roms.carry_moves(found, state2, {}, {"int"}), [])

    def test_signature_changes(self):
        touch(self.r("snes", "A.sfc"))
        a = roms.signature(self.roots, SYSTEMS)
        os.utime(self.r("snes"), ns=(1, 1))
        b = roms.signature(self.roots, SYSTEMS)
        self.assertNotEqual(a, b)


    def test_name_not_utf8_is_found_and_ids_follow_its_bytes(self):
        raw = os.fsencode(self.r("snes")) + b"/caf\xe9.sfc"
        touch(raw)
        touch(self.r("snes", "Good.sfc"))
        found = roms.scan(self.roots, SYSTEMS)
        self.assertEqual(len(found), 2)
        bad = roms.rom_id("int", "roms/snes/" + os.fsdecode(b"caf\xe9.sfc"))
        self.assertEqual(os.fsencode(found[bad]["path"]), raw)


class Deletion(unittest.TestCase):
    WAIT = 600

    def state(self):
        return {"a": {"appid": 1, "system": "snes"}, "b": {"appid": 2, "system": "snes"}}

    def test_missing_twice_minutes_apart(self):
        st = self.state()
        self.assertEqual(roms.confirm_missing(st, ["a"], ["b"], 1000, self.WAIT), [])
        self.assertEqual(st["a"]["missing_since"], 1000)
        self.assertEqual(st["b"]["seen"], 1000)
        # missing again, but too soon: not yet
        self.assertEqual(roms.confirm_missing(st, ["a"], ["b"], 1300, self.WAIT), [])
        self.assertNotIn("deleted", st["a"])
        self.assertEqual(roms.confirm_missing(st, ["a"], ["b"], 1600, self.WAIT), ["a"])
        self.assertTrue(st["a"]["deleted"])
        self.assertNotIn("missing_since", st["a"])
        # already deleted: not counted again
        self.assertEqual(roms.confirm_missing(st, ["a"], [], 3000, self.WAIT), [])

    def test_seen_in_between_starts_over(self):
        st = self.state()
        roms.confirm_missing(st, ["a"], [], 1000, self.WAIT)
        roms.confirm_missing(st, [], ["a"], 1200, self.WAIT)
        self.assertNotIn("missing_since", st["a"])
        self.assertEqual(roms.confirm_missing(st, ["a"], [], 1700, self.WAIT), [])
        self.assertEqual(roms.confirm_missing(st, ["a"], [], 2300, self.WAIT), ["a"])

    def test_unready_library_sends_nothing(self):
        # the frontend sends neither list when none of the checked games showed
        st = self.state()
        for t in (1000, 5000, 9000):
            self.assertEqual(roms.confirm_missing(st, [], [], t, self.WAIT), [])
        self.assertFalse(any(r.get("deleted") or r.get("missing_since") for r in st.values()))

    def test_unknown_or_unadded_ids_are_ignored(self):
        st = {"a": {"appid": None, "system": "snes"}}
        roms.confirm_missing(st, ["a", "zz"], ["zz"], 1000, self.WAIT)
        self.assertEqual(roms.confirm_missing(st, ["a", "zz"], [], 2000, self.WAIT), [])
        self.assertNotIn("missing_since", st["a"])


class Choices(unittest.TestCase):
    def test_paths_follow_the_rom(self):
        state = {"a": {"path": "/run/media/u/CARD/Emulation/roms/snes/A.sfc"},
                 "b": {"path": "/run/media/u/OLD/Emulation/roms/psx/B.cue"},
                 "c": {"path": "/home/u/Emulation/roms/snes/C.sfc"}}
        found = {"a": {"path": "/run/media/u/CARD2/Emulation/roms/snes/A.sfc"},
                 "c": {"path": "/home/u/Emulation/roms/snes/C.sfc"}}
        choices = {"a": "snes9x", "b": "duckstation", "c": "", "gone": "x"}
        self.assertEqual(roms.choice_paths(choices, found, state), {
            "/run/media/u/CARD2/Emulation/roms/snes/A.sfc": "snes9x",  # the card's new mount point
            "/run/media/u/OLD/Emulation/roms/psx/B.cue": "duckstation",  # its card is out: last path
        })

    def test_ids_survive_a_card_moving_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mp in ("c1", "c2"):
                touch(os.path.join(tmp, mp, "Emulation", "roms", "snes", "A.sfc"))
            first = roms.scan([{"path": os.path.join(tmp, "c1"), "emulation": os.path.join(tmp, "c1", "Emulation"),
                                "uuid": "U"}], SYSTEMS)
            second = roms.scan([{"path": os.path.join(tmp, "c2"), "emulation": os.path.join(tmp, "c2", "Emulation"),
                                 "uuid": "U"}], SYSTEMS)
            rid = next(iter(first))
            games = roms.choice_paths({rid: "snes9x"}, second, first)
            self.assertEqual(games, {second[rid]["path"]: "snes9x"})


class Matching(unittest.TestCase):
    NAMES = [
        "Super Mario World (USA)",
        "Super Mario World (Europe) (Rev 1)",
        "Super Mario World (Japan)",
        "Legend of Zelda, The - A Link to the Past (USA)",
        "Chrono Trigger (USA)",
        "Street Fighter II Turbo (USA)",
        "Super Metroid (Japan, USA) (En,Ja)",
    ]

    def test_exact(self):
        self.assertEqual(art.match("Chrono Trigger (USA)", self.NAMES), ["Chrono Trigger (USA)"])

    def test_title_and_region(self):
        self.assertEqual(art.match("Super Mario World (Europe)", self.NAMES)[0], "Super Mario World (Europe) (Rev 1)")
        self.assertEqual(art.match("Super Mario World", self.NAMES)[0], "Super Mario World (USA)")
        self.assertEqual(art.match("super mario world (j)", self.NAMES)[0], "Super Mario World (USA)")
        self.assertEqual(art.match("Super Metroid (USA)", self.NAMES)[0], "Super Metroid (Japan, USA) (En,Ja)")

    def test_article_and_fuzzy(self):
        self.assertEqual(art.match("The Legend of Zelda - A Link to the Past", self.NAMES)[0],
                         "Legend of Zelda, The - A Link to the Past (USA)")
        self.assertEqual(art.match("Street Fighter 2 Turbo", self.NAMES), ["Street Fighter II Turbo (USA)"])
        self.assertEqual(art.match("Street Fighter III Turbo", self.NAMES), [])  # a sequel: no guess
        self.assertEqual(art.match("Super Mario World 2", self.NAMES), [])
        self.assertEqual(art.match("Chrono Trigge", self.NAMES)[0], "Chrono Trigger (USA)")
        self.assertEqual(art.match("Totally Unknown Game", self.NAMES), [])

    def test_bad_characters(self):
        self.assertEqual(art.thumb_name("Q*bert: The Game?"), "Q_bert_ The Game_")
        self.assertEqual(art.match("Q*bert", ["Q_bert (USA)"]), ["Q_bert (USA)"])

    def test_server_dir(self):
        self.assertEqual(art._server_dir("Nintendo_-_Super_Nintendo_Entertainment_System"), "Nintendo - Super Nintendo Entertainment System")


class Offline(unittest.TestCase):
    def test_unreachable_is_not_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(art.Offline):
                art._fetch("http://127.0.0.1:9/none.png", tmp)  # nothing listens there


class Plugin(unittest.TestCase):
    """main.py's inbox and job bookkeeping, with decky stubbed."""

    @classmethod
    def setUpClass(cls):
        import types
        cls.tmp = tempfile.TemporaryDirectory()
        d = types.ModuleType("decky")
        d.DECKY_USER_HOME = os.path.join(cls.tmp.name, "home")
        d.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(cls.tmp.name, "settings")
        sys.modules.setdefault("decky", d)
        os.environ["KETTLE_EMU_HOME"] = os.path.join(d.DECKY_USER_HOME, "Emulation")
        os.environ["KETTLE_EMU_MEDIA"] = os.path.join(cls.tmp.name, "media")
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(here, "..", "..", "..", "kettle-emulation"))
        sys.path.insert(0, os.path.join(here, ".."))
        import main
        cls.main = main

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_inbox_waits_only_for_settled_untried_files(self):
        p = self.main.Plugin()
        box = os.path.join(os.environ["KETTLE_EMU_HOME"], "inbox")
        os.makedirs(os.path.join(box, "Emptied folder"), exist_ok=True)
        touch(os.path.join(box, "readme.txt"))
        touch(os.path.join(box, "unsorted", "x.bin"))
        self.assertEqual(p._inbox_files(30), {})
        rom = os.path.join(box, "PS1", "game.chd")
        touch(rom)
        self.assertEqual(p._inbox_files(30), {})  # still being copied in
        os.utime(rom, (1, 1))
        self.assertEqual(list(p._inbox_files(30)), [rom])
        p._inbox_left = {rom: 1}  # tried and left there (it failed)
        self.assertEqual(p._inbox_files(30), {})
        self.assertEqual(list(p._inbox_files(0, False)), [rom])
        os.utime(rom, (2, 2))  # changed: tried again
        self.assertEqual(list(p._inbox_files(30)), [rom])
        os.unlink(rom)
        p._inbox_files(30)
        self.assertEqual(p._inbox_left, {})

    def test_stats_add_up_across_storages(self):
        t = self.main.Plugin._add_stats(None, {"games": {"snes": 5}, "bios": [{"f": 1}], "unsorted": 1, "identical": 0, "errors": 0})
        t = self.main.Plugin._add_stats(t, {"games": {}, "bios": [], "unsorted": 0, "identical": 2, "errors": 1})
        self.assertEqual(t, {"games": {"snes": 5}, "bios": [{"f": 1}], "unsorted": 1, "identical": 2, "errors": 1})


    def test_launch_hex_round_trips_a_name_not_utf8(self):
        from unittest import mock
        from kettle_emulation import run
        raw = b"/run/media/kettle/SD/Emulation/roms/nes/caf\xe9 $(x).nes"
        opts = self.main._launch("nes", os.fsdecode(raw))
        system, arg = opts.split(" ")
        self.assertEqual(system, "nes")
        with mock.patch.object(run, "run", return_value=0) as r:
            run.main([system, arg])
        self.assertEqual(os.fsencode(r.call_args[0][1]), raw)

    def _strict(self, v):
        # what Remora sends: json.dumps(..., ensure_ascii=False).encode() (strict UTF-8)
        return json.dumps(v, ensure_ascii=False).encode()

    def test_names_not_utf8_reach_the_frontend_as_strict_utf8(self):
        import asyncio
        import logging
        from unittest import mock
        m = self.main
        if not hasattr(m.decky, "logger"):
            m.decky.logger = logging.getLogger("emulation-test")
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            emu = os.path.join(home, "Emulation")
            raw = os.fsdecode(os.path.join(os.fsencode(emu), b"roms", b"snes", b"caf\xe9 \"q\"", b"caf\xe9.sfc"))
            touch(raw)
            roots = [{"path": home, "emulation": emu, "uuid": "int", "internal": True, "label": "Internal"}]
            env = {"KETTLE_EMU_SYSTEMS": write_db(tmp)}
            with mock.patch.dict(os.environ, env), mock.patch.object(m, "_roots", return_value=roots), \
                    mock.patch.object(m, "STATE", os.path.join(tmp, "roms.json")), \
                    mock.patch.object(m, "CHOICES", os.path.join(tmp, "choices.json")), \
                    mock.patch.object(m, "HOME", home), \
                    mock.patch.object(m.keys, "runtime_dir", return_value=tmp):
                p = m.Plugin()
                plan = asyncio.run(p.sync_plan())
                self._strict(plan)
                (a,) = plan["add"]
                self.assertEqual(a["title"], "caf\ufffd")
                # the start folder: the nearest one above the ROM's whose name Steam can take
                self.assertEqual(a["dir"], os.path.join(emu, "roms", "snes"))
                self.assertEqual(os.fsdecode(bytes.fromhex(a["launch"].split(" x:")[1])), raw)
                asyncio.run(p.synced({a["id"]: 123}, [], [], []))
                asked = []
                with mock.patch.object(m.art, "candidates", lambda repo, name, cache: asked.append(name) or [name]):
                    self._strict(asyncio.run(p.art_choices(a["id"])))
                asked[0].encode("utf-8")  # quotable into the thumbnail server's URL
                gs = asyncio.run(p.games("snes"))
                self._strict(gs)
                self.assertEqual(gs[0]["title"], "caf\ufffd")
                with open(os.path.join(tmp, "running.json"), "w") as f:
                    json.dump({"pid": os.getpid(), "rom": raw, "system": "snes", "emulator": "ra-bsnes"}, f)
                run = asyncio.run(p.running())
                self._strict(run)
                self.assertEqual(run["id"], a["id"])  # found by the raw path kept in roms.json
                self.assertEqual(run["title"], "caf\ufffd")
                # saves: shown, and named back by id (the path's bytes), not by what was shown
                srm = os.fsdecode(os.path.join(os.fsencode(emu), b"saves", b"retroarch", b"caf\xe9 \"q\"", b"caf\xe9.srm"))
                touch(srm, b"save")
                sv = asyncio.run(p.saves())
                self._strict(sv)
                f = sv[0]["files"][0]
                self.assertNotEqual(f["path"], srm)
                with self.assertRaises(ValueError):
                    asyncio.run(p.save_delete([f["path"]]))  # the shown name is no id
                zp = asyncio.run(p.backup([f["id"]], "internal"))
                self._strict(zp)
                bks = asyncio.run(p.backups())
                self._strict(bks)
                self.assertEqual(asyncio.run(p.save_delete([f["id"]])), 1)
                self.assertFalse(os.path.exists(srm))
                self.assertEqual(asyncio.run(p.restore(bks[0]["id"]))["restored"], 1)
                self.assertTrue(os.path.exists(srm))

    def test_unsorted_is_assigned_by_id(self):
        import asyncio
        from unittest import mock
        m = self.main
        with tempfile.TemporaryDirectory() as tmp:
            emu = os.path.join(tmp, "Emulation")
            raw = os.fsdecode(os.path.join(os.fsencode(emu), b"inbox", b"unsorted", b"caf\xe9.bin"))
            touch(raw)
            roots = [{"path": tmp, "emulation": emu, "uuid": "int", "internal": True, "label": ""}]
            listed = [{"id": m._hex(raw), "path": raw, "name": os.path.basename(raw), "size": 1, "systems": [], "storage": ""}]
            calls = []

            class Proc:
                returncode = 0

                async def communicate(self):
                    return b"", b""

            async def spawn(*args, **kw):
                calls.append(args)
                return Proc()

            async def emit(*a):
                pass

            with mock.patch.object(m, "_roots", return_value=roots), \
                    mock.patch.object(m.Plugin, "_unsorted", staticmethod(lambda: listed)), \
                    mock.patch.object(m.asyncio, "create_subprocess_exec", spawn), \
                    mock.patch.object(m.decky, "emit", emit, create=True):
                p = m.Plugin()
                (u,) = asyncio.run(p.unsorted())
                self._strict(u)
                with self.assertRaises(ValueError):
                    asyncio.run(p.assign(u["path"], "snes"))
                asyncio.run(p.assign(u["id"], "snes"))
            self.assertEqual(calls[0][2], os.path.realpath(raw))

    def test_storage_named_by_its_shown_path(self):
        m = self.main
        raw = os.fsdecode(b"/run/media/kettle/caf\xe9")
        roots = [{"path": "/home/k", "internal": True}, {"path": raw, "internal": False}]
        self.assertIs(m._root_by_path(roots, m._shown(raw)), roots[1])
        self.assertIs(m._root_by_path(roots, raw), roots[1])
        self.assertIsNone(m._root_by_path(roots, "/run/media/kettle/other"))
        self.assertEqual(m._shown("\ud800x"), "\ufffd\ufffd\ufffdx")  # a lone surrogate from JSON
        self.assertEqual(m._start_dir(os.fsdecode(b"/x/caf\xe9/a/g.sfc")), "/x")
        import asyncio
        from unittest import mock
        cmds = []

        async def job(self_, kind, cmd, path):
            cmds.append(cmd)

        with mock.patch.object(m, "_roots", return_value=roots), mock.patch.object(m.Plugin, "_run_job", job):
            asyncio.run(m.Plugin().import_start(m._shown(raw), "copy", "internal"))
        self.assertEqual(cmds[0][2], raw)  # the card's own path, not the one it was shown as

    def test_bios_page_reports_system_dirs(self):
        from unittest import mock
        m = self.main
        db = {"systems": {"msx": {"name": "MSX", "system_dirs": ["Machines", "Databases"]}, "nes": {"name": "NES"}}}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(m, "EMU", tmp):
            st = m._with_system_dirs({"nes": {"state": "none", "entries": []}}, db)
            self.assertEqual(st["msx"]["state"], "missing-required")
            self.assertEqual([e["file"] for e in st["msx"]["entries"]], ["Machines/", "Databases/"])
            self.assertEqual(st["nes"]["state"], "none")
            self.assertTrue(m._needs_only_folders(st["msx"]))  # from Extra cores, not a BIOS file
            os.makedirs(os.path.join(tmp, "bios", "Machines"))
            os.makedirs(os.path.join(tmp, "bios", "Databases"))
            st = m._with_system_dirs({}, db)
            self.assertEqual(st["msx"]["state"], "ok")
            self.assertFalse(m._needs_only_folders(st["msx"]))
            # a system that also misses a real BIOS file needs more than the core's folders
            bfile = {"file": "x.rom", "required": True, "one_of": False, "found": None}
            st = m._with_system_dirs({"msx": {"state": "missing-required", "entries": [bfile]}}, db)
            self.assertFalse(m._needs_only_folders(st["msx"]))

    def test_core_downloads_one_at_a_time(self):
        import asyncio
        import threading
        import time
        from unittest import mock
        m = self.main
        active, peak, lock = [0], [0], threading.Lock()

        def download(*a):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1

        async def emit(*a):
            pass

        async def both():
            p = m.Plugin()
            await asyncio.gather(p.core_download("bluemsx"), p.core_download("bluemsx"), p.core_remove("bluemsx"))

        with mock.patch.object(m.cores, "download", download), mock.patch.object(m.cores, "remove", download), \
                mock.patch.object(m.cores, "listing", lambda *a: []), mock.patch.object(m, "_emit", emit), \
                mock.patch.object(m.systems, "load", lambda: {"emulators": {}, "systems": {}}):
            asyncio.run(both())
        self.assertEqual(peak[0], 1)

    def test_seeded_bluemsx_machine_reaches_c_bios(self):
        from kettle_emulation import seed
        # "Auto" is the only value that falls back to "MSX2+ - C-BIOS" (cores.py)
        self.assertEqual(seed.retroarch_core_options()["bluemsx_msxtype"], "Auto")


PKGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")


def _pkgnames(pkg):
    with open(os.path.join(PKGS, pkg, "PKGBUILD")) as f:
        m = re.search(r"^pkgname=\(([^)]*)\)|^pkgname=(\S+)", f.read(), re.M)
    return set((m.group(1) or m.group(2)).split())


class Packaging(unittest.TestCase):
    """The real systems.json against what the plugin reads (systems.json v2: Flathub emulators)."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(PKGS, "kettle-emulation", "systems.json")) as f:
            cls.db = json.load(f)
        if cls.db.get("version", 1) < 2:
            raise unittest.SkipTest("systems.json isn't v2 yet")

    def test_every_emulator_runs_from_a_known_flatpak(self):
        apps = self.db["flatpaks"]
        self.assertIn(cores.RETROARCH, apps)
        for eid, e in self.db["emulators"].items():
            self.assertIn(e["kind"], ("libretro", "flatpak"), eid)
            if e["kind"] == "libretro":
                self.assertTrue(e.get("core"), eid)
            else:
                self.assertIn(e["flatpak"], apps, eid)
            self.assertIn("free", e, eid)
            for a in e.get("hotkeys") or ():
                self.assertIn(a, ALL_KEYS, eid)
            for sv in e.get("saves") or ():
                self.assertIsNotNone(saves._rel_dir(sv["dir"]), eid)
        for sid, s in self.db["systems"].items():
            self.assertTrue(s["emulators"], sid)
            for eid in s["emulators"]:
                self.assertIn(eid, self.db["emulators"], sid)

    def test_msx_needs_bluemsx_system_dirs(self):
        self.assertEqual(self.db["systems"]["msx"]["system_dirs"], cores.SYSTEM_FILES["bluemsx"]["dirs"])
        self.assertIn("Emulation/bios", cores.TERMS["bluemsx"])

    def test_non_free_cores_have_their_terms(self):
        listed = {c["core"]: c for c in cores.listing("/nonexistent", self.db)}
        self.assertEqual(listed["bluemsx"]["systems"], ["MSX"])
        for core, c in listed.items():
            if not c["free"]:
                self.assertIn(core, cores.TERMS, core)
                self.assertTrue(c["terms"], core)
        self.assertIn("MSX emulators only", cores.TERMS["bluemsx"])

    def test_permissions_are_override_options(self):
        import flatpaks
        for app, f in self.db["flatpaks"].items():
            flatpaks.override_args(f.get("permissions") or [])


def _zip(entries):
    import io
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for name, data in entries:
            if isinstance(data, zipfile.ZipInfo):
                z.writestr(data, name)
            else:
                z.writestr(name, data)
    return b.getvalue()


class SystemFiles(unittest.TestCase):
    """Extra cores' files in RetroArch's system folder (blueMSX's Machines and Databases)."""

    DIRS = ["Machines", "Databases"]
    GOOD = [("Machines/MSX2/config.ini", b"m"), ("Machines/Shared Roms/MSX.rom", b"r"), ("Databases/msxromdb.xml", b"d")]

    def test_unpacks_and_merges(self):
        with tempfile.TemporaryDirectory() as bios:
            touch(os.path.join(bios, "Machines", "mine.ini"), b"user")
            touch(os.path.join(bios, "Machines", "Shared Roms", "MSX2P.rom"), b"user's real BIOS")
            touch(os.path.join(bios, "Machines", "MSX2", "config.ini"), b"old")
            touch(os.path.join(bios, "scph1001.bin"))
            cores.unpack_system_files(_zip(self.GOOD), bios, self.DIRS)
            self.assertTrue(os.path.exists(os.path.join(bios, "Machines", "Shared Roms", "MSX.rom")))
            with open(os.path.join(bios, "Machines", "MSX2", "config.ini"), "rb") as f:
                self.assertEqual(f.read(), b"m")  # a file we ship replaces the one there
            # the user's own files in the same folders stay
            with open(os.path.join(bios, "Machines", "mine.ini"), "rb") as f:
                self.assertEqual(f.read(), b"user")
            with open(os.path.join(bios, "Machines", "Shared Roms", "MSX2P.rom"), "rb") as f:
                self.assertEqual(f.read(), b"user's real BIOS")
            self.assertTrue(os.path.exists(os.path.join(bios, "scph1001.bin")))
            self.assertEqual(sorted(os.listdir(bios)), ["Databases", "Machines", "scph1001.bin"])
            self.assertEqual(cores.missing_system_dirs(bios, "bluemsx"), [])

    def test_bluemsx_installs_only_the_free_files(self):
        sf = cores.SYSTEM_FILES["bluemsx"]
        pack = [("Machines/", b""), ("Machines/MSX2+ - C-BIOS/", b""),
                ("Machines/MSX2+ - C-BIOS/config.ini", b"c"),
                ("Machines/MSX2+ - C-BIOS/cbios_main_msx2+.rom", b"free"),
                ("Machines/MSX2+ - C-BIOS/cbios.txt", b"BSD"),
                ("Machines/MSX2+/config.ini", b"c"),
                ("Machines/Shared Roms/MSX2P.rom", b"real"),
                ("Machines/MSX2+ - European/Msx2pe.rom", b"real"),
                ("Machines/COL - ColecoVision/coleco.rom", b"real"),
                ("Machines/COL - ColecoVision/config.ini", b"c"),
                ("Databases/msxromdb.xml", b"d")]
        with tempfile.TemporaryDirectory() as bios:
            cores.unpack_system_files(_zip(pack), bios, sf["dirs"], sf["keep"])
            got = sorted(os.path.relpath(os.path.join(r, f), bios) for r, _, fs in os.walk(bios) for f in fs)
            self.assertEqual(got, ["Databases/msxromdb.xml", "Machines/COL - ColecoVision/config.ini",
                                   "Machines/MSX2+ - C-BIOS/cbios.txt", "Machines/MSX2+ - C-BIOS/cbios_main_msx2+.rom",
                                   "Machines/MSX2+ - C-BIOS/config.ini", "Machines/MSX2+/config.ini"])
        # a pack whose Machines holds nothing free is refused
        with tempfile.TemporaryDirectory() as bios:
            with self.assertRaises(ValueError):
                cores.unpack_system_files(_zip([("Machines/Shared Roms/MSX.rom", b"r"), ("Databases/d.xml", b"d")]),
                                          bios, sf["dirs"], sf["keep"])
            self.assertEqual(os.listdir(bios), [])

    def test_a_failed_move_undoes_everything(self):
        from unittest import mock
        real = os.rename
        n = [0]

        def rename(a, b):
            if ".kettle-system-files." in a and os.sep + "new" + os.sep in a:
                n[0] += 1
                if n[0] == 3:
                    raise OSError(28, "No space left on device")
            return real(a, b)

        entries = self.GOOD + [("Machines/New/config.ini", b"n")]
        with tempfile.TemporaryDirectory() as bios:
            touch(os.path.join(bios, "Machines", "MSX2", "config.ini"), b"old")
            touch(os.path.join(bios, "Machines", "mine.ini"), b"user")
            before = sorted((r, tuple(sorted(fs))) for r, _, fs in os.walk(bios))
            with mock.patch.object(cores.os, "rename", rename):
                with self.assertRaises(ValueError):
                    cores.unpack_system_files(_zip(entries), bios, self.DIRS)
            self.assertEqual(sorted((r, tuple(sorted(fs))) for r, _, fs in os.walk(bios)), before)
            with open(os.path.join(bios, "Machines", "MSX2", "config.ini"), "rb") as f:
                self.assertEqual(f.read(), b"old")
        # a file where a folder must go: refused before anything is replaced
        with tempfile.TemporaryDirectory() as bios:
            touch(os.path.join(bios, "Databases"), b"a file")
            touch(os.path.join(bios, "Machines", "MSX2", "config.ini"), b"old")
            with self.assertRaises(ValueError):
                cores.unpack_system_files(_zip(self.GOOD), bios, self.DIRS)
            self.assertEqual(sorted(os.listdir(bios)), ["Databases", "Machines"])
            with open(os.path.join(bios, "Machines", "MSX2", "config.ini"), "rb") as f:
                self.assertEqual(f.read(), b"old")
            self.assertFalse(os.path.exists(os.path.join(bios, "Machines", "Shared Roms")))

    def test_concurrent_unpacks_stage_apart(self):
        import threading
        import time
        from unittest import mock
        stages, active, peak = [], [0], [0]
        real_mkdtemp, real_merge = cores.tempfile.mkdtemp, cores._merge

        def mkdtemp(**kw):
            d = real_mkdtemp(**kw)
            stages.append(d)
            return d

        def merge(*a):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            try:
                return real_merge(*a)
            finally:
                active[0] -= 1

        with tempfile.TemporaryDirectory() as bios, mock.patch.object(cores.tempfile, "mkdtemp", mkdtemp), \
                mock.patch.object(cores, "_merge", merge):
            os.makedirs(os.path.join(bios, cores.STAGE_PREFIX + "crashed", "new"))  # a dead unpack's
            errors = []

            def run():
                try:
                    cores.unpack_system_files(_zip(self.GOOD), bios, self.DIRS)
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

            ts = [threading.Thread(target=run) for _ in range(3)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(set(stages)), 3)
            self.assertTrue(all(os.path.dirname(d) == bios for d in stages))
            self.assertEqual(peak[0], 1)
            self.assertEqual(sorted(os.listdir(bios)), ["Databases", "Machines"])

    def test_refuses_bad_zips_and_leaves_the_folder(self):
        link = zipfile.ZipInfo("Machines/link")
        link.external_attr = 0o120777 << 16
        bad = [
            self.GOOD + [("Machines/../../escape", b"x")],
            self.GOOD + [("/abs/Machines/x", b"x")],
            self.GOOD + [("Other/x", b"x")],
            self.GOOD + [("Machines\\..\\x", b"x")],
            self.GOOD + [("/etc/passwd", link)],
            [("Machines/a", b"x")],  # no Databases
            self.GOOD + [("Machines", b"x")],  # a file named like the folder
            [("Machines/a", b"x"), ("Databases", b"x")],
        ]
        for entries in bad:
            with tempfile.TemporaryDirectory() as bios:
                touch(os.path.join(bios, "Machines", "keep"))
                with self.assertRaises(ValueError, msg=str(entries[-1][0])):
                    cores.unpack_system_files(_zip(entries), bios, self.DIRS)
                self.assertEqual(sorted(os.listdir(bios)), ["Machines"])
                self.assertTrue(os.path.exists(os.path.join(bios, "Machines", "keep")))
                self.assertFalse(os.path.exists(os.path.join(os.path.dirname(bios), "escape")))
        with tempfile.TemporaryDirectory() as bios:
            data = bytearray(_zip(self.GOOD))
            i = data.index(b"Databases/msxromdb.xml") + len("Databases/msxromdb.xml")
            data[i] ^= 0xFF  # the file's data, after its local header's name: a bad CRC
            with self.assertRaises(ValueError):
                cores.unpack_system_files(bytes(data), bios, self.DIRS)
            self.assertEqual(os.listdir(bios), [])
            with self.assertRaises(ValueError):
                cores.unpack_system_files(b"not a zip", bios, self.DIRS)

    def test_bluemsx_download_brings_its_folders(self):
        from unittest import mock
        so = bytearray(64)
        so[:5] = b"\x7fELF\x02"
        so[18:20] = (0xB7).to_bytes(2, "little")
        fetched = []

        def fetch(url):
            fetched.append(url)
            return _zip([("bluemsx_libretro.so", bytes(so))]) if url.endswith(".so.zip") else _zip(self.GOOD)

        db = {"emulators": {"ra-bluemsx": {"name": "blueMSX", "kind": "libretro", "core": "bluemsx", "free": True},
                            "ra-snes9x": {"name": "Snes9x", "kind": "libretro", "core": "snes9x", "free": False}},
              "systems": {"msx": {"name": "MSX", "emulators": ["ra-bluemsx"]}}}
        with tempfile.TemporaryDirectory() as home, mock.patch.object(cores, "_fetch", fetch):
            bios = os.path.join(home, "Emulation", "bios")
            cores.download(home, "bluemsx", cores.known(db), bios)
            # into the RetroArch Flatpak's cores folder
            self.assertTrue(os.path.exists(os.path.join(home, ".var/app/org.libretro.RetroArch/config/retroarch/cores/bluemsx_libretro.so")))
            self.assertEqual(fetched, [f"{cores.BUILDBOT}/bluemsx_libretro.so.zip", cores.SYSTEM_FILES["bluemsx"]["url"]])
            self.assertTrue(os.path.isdir(os.path.join(bios, "Databases")))
            self.assertTrue(os.path.exists(os.path.join(bios, "Machines", "MSX2", "config.ini")))
            self.assertFalse(os.path.exists(os.path.join(bios, "Machines", "Shared Roms")))  # a real BIOS: left out
            c = next(c for c in cores.listing(home, db, bios) if c["core"] == "bluemsx")
            self.assertTrue(c["installed"])
            import shutil
            shutil.rmtree(os.path.join(bios, "Databases"))
            c = next(c for c in cores.listing(home, db, bios) if c["core"] == "bluemsx")
            self.assertEqual((c["installed"], c["missing"]), (False, ["Databases"]))
            # a core without system files fetches only itself
            fetched.clear()
            with mock.patch.object(cores, "_fetch", lambda url: fetched.append(url) or _zip([("snes9x_libretro.so", bytes(so))])):
                # a core whose license isn't free: only after a yes to its terms
                with self.assertRaises(ValueError):
                    cores.download(home, "snes9x", cores.known(db), bios)
                self.assertEqual(fetched, [])
                cores.download(home, "snes9x", cores.known(db), bios, accepted=True)
            self.assertEqual(len(fetched), 1)
            with self.assertRaises(ValueError):
                cores.download(home, "nope", cores.known(db), bios, accepted=True)


class Saves(unittest.TestCase):
    def test_listing_backup_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            rom = os.path.join(home, "Emulation", "roms", "snes", "Game (USA).sfc")
            touch(rom)
            touch(os.path.join(home, "Emulation", "saves", "retroarch", "snes", "Game (USA).srm"), b"save")
            touch(os.path.join(home, "Emulation", "states", "retroarch", "snes", "Game (USA).state1"), b"st")
            touch(os.path.join(home, "Emulation", "states", "retroarch", "snes", "Game (USA).state1.png"), b"png")
            games = saves.listing(home, {"r1": {"system": "snes", "path": rom, "title": "Game"}}, DB_V2)
            self.assertEqual(len(games), 1)
            kinds = sorted((f["kind"], f["slot"]) for f in games[0]["files"])
            self.assertEqual(kinds, [("save", ""), ("state", "1")])
            paths = [f["path"] for f in games[0]["files"]]
            zp = saves.backup(paths, os.path.join(home, "Emulation", "backups"), home, [])
            with zipfile.ZipFile(zp) as z:
                self.assertIn("home/Emulation/states/retroarch/snes/Game (USA).state1.png", z.namelist())
                z2 = os.path.join(tmp, "evil.zip")
                with zipfile.ZipFile(z2, "w") as e:
                    e.writestr("home/.bashrc", "x")
                    e.writestr("home/../escape", "x")
            saves.delete(paths, saves.all_paths(games))
            self.assertEqual(saves.listing(home, {"r1": {"system": "snes", "path": rom}}, DB_V2), [])
            allowed = saves.home_save_dirs(DB_V2)
            r = saves.restore(zp, home, [], allowed)
            self.assertEqual(r["restored"], 3)
            self.assertEqual(saves.restore(z2, home, [], allowed), {"restored": 0, "skipped": 2})
            self.assertFalse(os.path.exists(os.path.join(home, ".bashrc")))
            with self.assertRaises(ValueError):
                saves.delete(["/etc/passwd"], saves.all_paths(games))


class FlathubEmulators(unittest.TestCase):
    """The emulators from Flathub: what the games need, the install job, hotkeys, saves."""

    @classmethod
    def setUpClass(cls):
        Plugin.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from unittest import mock
        self.mock = mock
        self.dir = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.dir.name, "home")
        self.patches = [mock.patch.dict(os.environ, {"KETTLE_EMU_SYSTEMS": write_db(self.dir.name)}),
                        mock.patch.object(self.main, "HOME", self.home),
                        mock.patch.object(self.main, "STATE", os.path.join(self.dir.name, "roms.json")),
                        mock.patch.object(self.main, "CHOICES", os.path.join(self.dir.name, "choices.json")),
                        mock.patch.object(self.main, "SETUP_LOG", os.path.join(self.dir.name, "setup.log"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.dir.cleanup()

    def test_what_the_games_need(self):
        need = self.main.needed(DB_V2, {"snes": 2, "ps2": 1, "switch": 1, "psp": 0}, {"systems": {"switch": "eden"}}, {},
                                lambda c: False)
        self.assertEqual(need["flatpaks"], ["org.libretro.RetroArch", "org.purei.Play", "dev.eden_emu.eden"])
        self.assertEqual([c["core"] for c in need["cores"]], ["bsnes"])
        self.assertTrue(need["cores"][0]["free"])
        self.assertEqual(need["systems"], ["snes", "ps2", "switch"])
        inst = {a: {"version": "1", "origin": "flathub", "installation": "user"}
                for a in ("org.libretro.RetroArch", "org.purei.Play")}
        need = self.main.needed(DB_V2, {"snes": 2, "ps2": 1, "switch": 1}, {"systems": {"switch": "eden"}}, inst,
                                lambda c: c == "bsnes")
        self.assertEqual((need["flatpaks"], need["cores"], need["systems"]), (["dev.eden_emu.eden"], [], ["switch"]))
        # a non-free core chosen for a system: its terms go along
        need = self.main.needed(DB_V2, {"snes": 1}, {"systems": {"snes": "ra-snes9x"}}, inst, lambda c: False)
        (c,) = need["cores"]
        self.assertEqual((c["core"], c["free"]), ("snes9x", False))
        self.assertTrue(c["terms"])
        # a choice that isn't the system's emulator falls back to the first
        need = self.main.needed(DB_V2, {"psp": 1}, {"systems": {"psp": "ra-bsnes"}}, {}, lambda c: False)
        self.assertEqual(need["flatpaks"], ["org.ppsspp.PPSSPP"])
        # no choice and another of its emulators installed: emu-run starts that one, nothing needed
        ryu = {"io.github.ryubing.Ryujinx": {"version": "1", "origin": "flathub", "installation": "system"}}
        self.assertEqual(self.main.needed(DB_V2, {"switch": 1}, {}, ryu, lambda c: False)["systems"], [])
        # with Snes9x's core there, SNES needs no bsnes
        need = self.main.needed(DB_V2, {"snes": 1}, {}, inst, lambda c: c == "snes9x")
        self.assertEqual(need["cores"], [])
        # the user's choice, not installed, is what's needed even then
        self.assertEqual(self.main.needed(DB_V2, {"switch": 1}, {"systems": {"switch": "eden"}}, ryu, lambda c: False)["flatpaks"],
                         ["dev.eden_emu.eden"])

    def test_installed_state(self):
        db = DB_V2
        inst = {"org.libretro.RetroArch": {"version": "1.22.2", "origin": "flathub", "installation": "user"}}
        emus = {e["id"]: e for e in self.main._emulators(db, "snes", inst)}
        self.assertFalse(emus["ra-bsnes"]["installed"])  # RetroArch without the core
        touch(os.path.join(self.home, ".var/app/org.libretro.RetroArch/config/retroarch/cores/bsnes_libretro.so"))
        emus = {e["id"]: e for e in self.main._emulators(db, "snes", inst)}
        self.assertTrue(emus["ra-bsnes"]["installed"])
        self.assertEqual((emus["ra-snes9x"]["free"], emus["ra-bsnes"]["flatpak"]), (False, "org.libretro.RetroArch"))
        (rpcs3,) = self.main._emulators(db, "ps3", inst)
        self.assertEqual((rpcs3["installed"], rpcs3["experimental"], rpcs3["needs"]),
                         (False, True, [{"text": "Install the PS3 firmware in RPCS3 first.", "met": None}]))

    def test_running_offers_only_the_emulators_hotkeys(self):
        import asyncio
        m = self.main
        with open(os.path.join(self.dir.name, "running.json"), "w") as f:
            json.dump({"pid": os.getpid(), "rom": "/x/game.iso", "system": "psp", "emulator": "ppsspp"}, f)
        with self.mock.patch.object(m.keys, "runtime_dir", return_value=self.dir.name), \
                self.mock.patch.object(m.flatpaks, "installed", return_value={}):
            r = asyncio.run(m.Plugin().running())
            self.assertNotIn("rewind", r["hotkeys"])
            self.assertNotIn("swap_screens", r["hotkeys"])
            self.assertIn("save_state", r["hotkeys"])
            with open(os.path.join(self.dir.name, "running.json"), "w") as f:
                json.dump({"pid": os.getpid(), "rom": "/x/g.sfc", "system": "snes", "emulator": "ra-bsnes"}, f)
            self.assertEqual(asyncio.run(m.Plugin().running())["hotkeys"], ALL_KEYS)
            # the same core on a system without "rewind": no rewind (seed.py turns it on there alone)
            with open(os.path.join(self.dir.name, "running.json"), "w") as f:
                json.dump({"pid": os.getpid(), "rom": "/x/g.rom", "system": "msx", "emulator": "ra-bluemsx"}, f)
            self.assertNotIn("rewind", asyncio.run(m.Plugin().running())["hotkeys"])

    def test_controls_group_retroarch_cores(self):
        import asyncio
        rows = asyncio.run(self.main.Plugin().controls())
        self.assertEqual(rows[0]["name"], "RetroArch")
        ppsspp = next(r for r in rows if r["name"] == "PPSSPP")
        self.assertNotIn("rewind", ppsspp["hotkeys"])
        self.assertEqual(next(r for r in rows if r["name"] == "Play!")["hotkeys"], ["quit"])
        # blueMSX runs only MSX, which doesn't rewind: its row has no rewind; the SNES cores' has
        ra = [r for r in rows if r["name"] == "RetroArch"]
        self.assertEqual({tuple(sorted(r["emulators"])): "rewind" in r["hotkeys"] for r in ra},
                         {("Snes9x", "bsnes"): True, ("blueMSX",): False})

    def test_flatpak_rows(self):
        p = self.main.Plugin()
        inst = {"org.ppsspp.PPSSPP": {"version": "1.20.4", "origin": "flathub", "installation": "user"},
                "net.rpcs3.RPCS3": {"version": "0.0.38", "origin": "flathub", "installation": "system"}}
        rows = {r["id"]: r for r in p._flatpak_rows(DB_V2, inst, {"org.ppsspp.PPSSPP"})}
        self.assertEqual(list(rows)[0], "org.libretro.RetroArch")  # first: the most systems run in it
        self.assertEqual(sorted(rows["org.libretro.RetroArch"]["systems"]), ["MSX", "SNES"])
        self.assertEqual((rows["org.ppsspp.PPSSPP"]["update"], rows["org.ppsspp.PPSSPP"]["removable"]), (True, True))
        self.assertEqual((rows["net.rpcs3.RPCS3"]["removable"], rows["net.rpcs3.RPCS3"]["experimental"]), (False, True))
        self.assertEqual(rows["io.github.ryubing.Ryujinx"]["needs"], [{"text": "Add your keys and firmware in Ryujinx.", "met": None}])

    def test_setup_job_installs_then_downloads_the_cores(self):
        import asyncio
        import flatpaks
        m = self.main
        events, started, got = [], [], []

        async def emit(ev, *a):
            events.append((ev, dict(a[0]) if a else None))

        def start(home, log, cmds):
            started.append(cmds)
            with open(log, "w") as f:
                f.write("Installing 1/2\u2026 \u258c 50%  1.0\u00a0MB/s  00:10\n")
                f.write(f"Installing 2/2\u2026 100%\n{flatpaks.EXIT_MARK} 0\n")

        async def go(p):
            await p.setup_start("install", ["org.purei.Play"], ["bsnes", "snes9x"], ["snes9x"])
            await asyncio.gather(*p._tasks)
            return p._setup

        with self.mock.patch.object(m.flatpaks, "start", start), self.mock.patch.object(m.flatpaks, "running", return_value=False), \
                self.mock.patch.object(m.cores, "download", lambda home, c, known, bios, accepted: got.append((c, accepted))), \
                self.mock.patch.object(m, "_emit", emit):
            job = asyncio.run(go(m.Plugin()))
        self.assertEqual(job["state"], "done", job)
        self.assertEqual(got, [("bsnes", False), ("snes9x", True)])
        (cmds,) = started
        self.assertEqual(cmds[0][:5], [flatpaks.FLATPAK, "remote-add", "--user", "--if-not-exists", "flathub"])
        self.assertEqual(cmds[1], [flatpaks.FLATPAK, "install", "--user", "-y", "flathub", "org.purei.Play"])
        self.assertEqual(cmds[2], [flatpaks.FLATPAK, "override", "--user", "--filesystem=~/Emulation", "org.purei.Play"])
        self.assertIn("setup", [e for e, _ in events])
        # a non-free core without a yes, or an app systems.json doesn't name: refused before anything runs
        with self.assertRaises(ValueError):
            asyncio.run(m.Plugin().setup_start("install", [], ["snes9x"], []))
        with self.assertRaises(ValueError):
            asyncio.run(m.Plugin().setup_start("install", ["org.evil.App"], [], []))

    def test_setup_job_failure_is_reported(self):
        import asyncio
        import flatpaks
        m = self.main

        async def emit(*a):
            pass

        def start(home, log, cmds):
            with open(log, "w") as f:
                f.write(f"error: No remote refs found for 'org.purei.Play'\n{flatpaks.EXIT_MARK} 1\n")

        async def go(p):
            await p.setup_start("install", ["org.purei.Play"], ["bsnes"], [])
            await asyncio.gather(*p._tasks)
            return p._setup

        got = []
        with self.mock.patch.object(m.flatpaks, "start", start), self.mock.patch.object(m.flatpaks, "running", return_value=False), \
                self.mock.patch.object(m.cores, "download", lambda *a: got.append(a)), self.mock.patch.object(m, "_emit", emit):
            job = asyncio.run(go(m.Plugin()))
        self.assertEqual(job["state"], "failed")
        self.assertIn("No remote refs", job["error"])
        self.assertEqual(got, [])  # no cores after a failed install

    def test_install_needed_leaves_out_unaccepted_cores(self):
        import asyncio
        m = self.main
        calls = []

        async def setup_start(self_, kind, apps, core_list, accepted):
            calls.append((kind, apps, core_list, accepted))
            return {}

        with open(m.STATE, "w") as f:
            json.dump({"roms": {"a": {"system": "snes", "path": "/x/a.sfc"}, "b": {"system": "ps2", "path": "/x/b.iso"}}}, f)
        with open(m.CHOICES, "w") as f:
            json.dump({"systems": {"snes": "ra-snes9x"}}, f)
        with self.mock.patch.object(m.flatpaks, "installed", return_value={}), \
                self.mock.patch.object(m.Plugin, "setup_start", setup_start):
            asyncio.run(m.Plugin().install_needed([]))
            asyncio.run(m.Plugin().install_needed(["snes9x"]))
        self.assertEqual(calls[0], ("install", ["org.libretro.RetroArch", "org.purei.Play"], [], []))
        self.assertEqual(calls[1][2], ["snes9x"])


class SwitchArt(unittest.TestCase):
    """Switch games: updates and DLC left out, artwork from SteamGridDB with the user's key."""

    @classmethod
    def setUpClass(cls):
        Plugin.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from unittest import mock
        self.mock = mock
        self.dir = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.dir.name, "home")
        self.events = []

        async def emit(ev, *a):
            self.events.append(ev)

        self.patches = [mock.patch.dict(os.environ, {"KETTLE_EMU_SYSTEMS": write_db(self.dir.name)}),
                        mock.patch.object(self.main, "HOME", self.home),
                        mock.patch.object(self.main, "STATE", os.path.join(self.dir.name, "roms.json")),
                        mock.patch.object(self.main, "SETTINGS", os.path.join(self.dir.name, "settings.json")),
                        mock.patch.object(self.main, "SWITCH_IDS", os.path.join(self.dir.name, "switch-ids.json")),
                        mock.patch.object(self.main, "_emit", emit),
                        mock.patch.object(self.main.decky, "logger", mock.Mock(), create=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.dir.cleanup()

    def test_drop_extras(self):
        found = {"a": {"system": "switch", "path": "/g/Wonder.nsp"}, "b": {"system": "switch", "path": "/g/Wonder Update.nsp"},
                 "c": {"system": "switch", "path": "/g/Wonder DLC.nsp"}, "d": {"system": "switch", "path": "/g/unknown.nsp"},
                 "e": {"system": "snes", "path": "/g/x.sfc"}}
        kinds = {"/g/Wonder.nsp": "game", "/g/Wonder Update.nsp": "update", "/g/Wonder DLC.nsp": "dlc"}
        out = roms.drop_extras(found, lambda r: kinds.get(r["path"]))
        self.assertEqual(sorted(found), ["a", "d", "e"])
        self.assertEqual(sorted(r["kind"] for r in out), ["dlc", "update"])

    def test_switch_kinds_cached_and_updates_left_out(self):
        game = os.path.join(self.home, "Emulation/roms/switch/Wonder [010015100B514000].nsp")
        upd = os.path.join(self.home, "Emulation/roms/switch/Wonder [010015100B514800][v65536].nsp")
        touch(game)
        touch(upd)
        found = {"g": {"system": "switch", "path": game}, "u": {"system": "switch", "path": upd}}
        p = self.main.Plugin()
        p._switch_kinds(found)
        self.assertEqual(list(found), ["g"])
        with open(self.main.SWITCH_IDS) as f:
            self.assertEqual(json.load(f)[upd][2], "010015100b514800")
        # from the cache: no file is read again
        found = {"g": {"system": "switch", "path": game}, "u": {"system": "switch", "path": upd}}
        with self.mock.patch("kettle_emulation.switch.title_id", side_effect=AssertionError("read again")):
            p._switch_kinds(found)
        self.assertEqual(list(found), ["g"])

    def test_sgdb_assets(self):
        urls = []

        def get(url, headers=None, **kw):
            urls.append(url)
            self.assertEqual(headers, {"Authorization": "Bearer KEY"})
            if "/search/autocomplete/" in url:
                return json.dumps({"data": [{"id": 7, "name": "Super Mario Bros. Wonder"}]}).encode()
            if "/grids/" in url and "600x900" in url:
                return json.dumps({"data": [{"url": "https://cdn/x.webp"}, {"url": "https://cdn/grid.png"}]}).encode()
            if "/grids/" in url:
                return json.dumps({"data": [{"url": "https://cdn/wide.jpg"}]}).encode()
            if "/heroes/" in url:
                return json.dumps({"data": [{"url": "https://cdn/hero.png"}]}).encode()
            return json.dumps({"data": []}).encode()  # no logo

        with self.mock.patch.object(art, "_get", get), \
                self.mock.patch.object(art, "_fetch", lambda url, cache: "/c/" + url.rsplit("/", 1)[1]):
            out = art.sgdb_assets("KEY", "Super Mario Bros. Wonder", self.dir.name)
        self.assertEqual(out, {0: ("/c/grid.png", "png"), 1: ("/c/hero.png", "png"), 3: ("/c/wide.jpg", "jpg")})
        self.assertTrue(all("mimes=image/png,image/jpeg" in u for u in urls if "/game/7" in u))

    def test_a_new_key_retries_the_games_without_artwork(self):
        with open(self.main.STATE, "w") as f:
            json.dump({"roms": {"a": {"system": "switch", "art": False, "art_tries": 3},
                                "b": {"system": "snes", "art": True, "art_tries": 0}}}, f)
        asyncio_run = __import__("asyncio").run
        asyncio_run(self.main.Plugin().set_settings({"sgdb_key": "KEY"}))
        with open(self.main.STATE) as f:
            st = json.load(f)
        self.assertEqual(st["roms"]["a"]["art_tries"], 0)
        self.assertIn("roms_changed", self.events)
        self.events.clear()
        asyncio_run(self.main.Plugin().set_settings({"sgdb_key": "KEY"}))  # the same key again
        self.assertNotIn("roms_changed", self.events)

    def test_fix_artwork_offers_steamgriddb_names(self):
        with open(self.main.STATE, "w") as f:
            json.dump({"roms": {"a": {"system": "switch", "path": "/g/Wonder.nsp", "title": "Wonder"}}}, f)
        with open(self.main.SETTINGS, "w") as f:
            json.dump({"sgdb_key": "KEY"}, f)
        found = [{"id": i, "name": f"Game {i}"} for i in range(8)]
        with self.mock.patch.object(art, "sgdb_search", lambda key, title: found):
            names = __import__("asyncio").run(self.main.Plugin().art_choices("a"))
        self.assertEqual(names, [f"Game {i}" for i in range(5)])

    def test_overview_says_where_art_comes_from(self):
        ov = __import__("asyncio").run(self.main.Plugin().overview())
        src = {s["id"]: s["art_source"] for s in ov["systems"]}
        self.assertEqual((src["snes"], src["switch"]), ("libretro", "sgdb"))


class SetupJobs(unittest.TestCase):
    """The setup job: installed apps left out, declined cores, a restart halfway, layouts."""

    setUpClass = classmethod(lambda cls: Plugin.setUpClass.__func__(cls))
    tearDownClass = classmethod(lambda cls: cls.tmp.cleanup())

    def setUp(self):
        FlathubEmulators.setUp(self)
        self.patches.append(self.mock.patch.object(self.main, "SETUP_JOB", os.path.join(self.dir.name, "setup.json")))
        self.patches[-1].start()
        self.events = []

        async def emit(ev, *a):
            self.events.append(ev)

        self.patches.append(self.mock.patch.object(self.main, "_emit", emit))
        self.patches[-1].start()

    tearDown = FlathubEmulators.tearDown

    def inst(self, *apps, where="user"):
        return {a: {"version": "1", "origin": "flathub", "installation": where} for a in apps}

    def test_installed_apps_are_left_out(self):
        import asyncio
        m = self.main
        with self.mock.patch.object(m.flatpaks, "installed", return_value=self.inst("org.purei.Play", where="system")):
            st = asyncio.run(m.Plugin().setup_start("install", ["org.purei.Play"], [], []))
        self.assertEqual(st, {"state": "idle"})
        with self.mock.patch.object(m.flatpaks, "installed", return_value=None):
            with self.assertRaises(ValueError):
                asyncio.run(m.Plugin().setup_start("install", ["org.purei.Play"], [], []))

    def test_only_declined_cores_is_no_error(self):
        import asyncio
        m = self.main
        with open(m.STATE, "w") as f:
            json.dump({"roms": {"a": {"system": "snes", "path": "/x/a.sfc"}}}, f)
        with open(m.CHOICES, "w") as f:
            json.dump({"systems": {"snes": "ra-snes9x"}}, f)
        with self.mock.patch.object(m.flatpaks, "installed", return_value=self.inst("org.libretro.RetroArch")):
            st = asyncio.run(m.Plugin().install_needed([]))
        self.assertEqual(st, {"state": "idle", "left_out": ["snes9x"]})

    def test_counts_come_from_the_scan(self):
        m = self.main
        p = m.Plugin()
        with open(m.STATE, "w") as f:
            json.dump({"roms": {"a": {"system": "snes", "path": "/x/a.sfc", "deleted": True}}}, f)
        p._found = {"a": {"system": "snes"}, "b": {"system": "ps2"}, "c": {"system": "ps2"}}
        self.assertEqual(p._counts(), {"ps2": 2})
        p._found = {}
        self.assertEqual(p._counts(), {})

    def test_a_restart_halfway_finishes_the_cores(self):
        import asyncio
        m = self.main
        got = []
        with open(m.SETUP_JOB, "w") as f:
            json.dump({"kind": "install", "apps": ["org.purei.Play"], "cores": ["bsnes", "snes9x"], "accepted": ["snes9x"],
                       "flatpak": True, "done_cores": ["bsnes"]}, f)
        with open(m.SETUP_LOG, "w") as f:
            f.write(f"Installing\u2026 100%\n{m.flatpaks.EXIT_MARK} 0\n")

        async def go():
            p = m.Plugin()
            await p._resume_setup(m._read_json(m.SETUP_JOB, {}))
            return p._setup

        with self.mock.patch.object(m.flatpaks, "running", return_value=False), \
                self.mock.patch.object(m.cores, "download", lambda home, c, known, bios, accepted: got.append((c, accepted))):
            job = asyncio.run(go())
        self.assertEqual(job["state"], "done", job)
        self.assertEqual(got, [("snes9x", True)])  # bsnes was done before the restart
        self.assertFalse(os.path.exists(m.SETUP_JOB))
        self.assertIn("roms_changed", self.events)

    def test_a_restart_after_a_failed_install(self):
        import asyncio
        m = self.main
        with open(m.SETUP_JOB, "w") as f:
            json.dump({"kind": "install", "apps": ["x.y.Z"], "cores": ["bsnes"], "accepted": [], "flatpak": True, "done_cores": []}, f)
        with open(m.SETUP_LOG, "w") as f:
            f.write(f"error: boom\n{m.flatpaks.EXIT_MARK} 1\n")
        got = []

        async def go():
            p = m.Plugin()
            await p._resume_setup(m._read_json(m.SETUP_JOB, {}))
            return p._setup

        with self.mock.patch.object(m.flatpaks, "running", return_value=False), \
                self.mock.patch.object(m.cores, "download", lambda *a: got.append(a)):
            job = asyncio.run(go())
        self.assertEqual((job["state"], got), ("failed", []))
        self.assertIn("boom", job["error"])

    def test_setup_start_saves_the_job(self):
        import asyncio
        m = self.main
        seen = {}

        def start(home, log, cmds):
            seen.update(m._read_json(m.SETUP_JOB, {}))
            with open(log, "w") as f:
                f.write(f"{m.flatpaks.EXIT_MARK} 0\n")

        async def go():
            p = m.Plugin()
            await p.setup_start("install", ["org.purei.Play"], ["snes9x"], ["snes9x"])
            await asyncio.gather(*p._tasks)

        with self.mock.patch.object(m.flatpaks, "installed", return_value={}), self.mock.patch.object(m.flatpaks, "start", start), \
                self.mock.patch.object(m.flatpaks, "running", return_value=False), \
                self.mock.patch.object(m.cores, "download", lambda *a: None):
            asyncio.run(go())
        self.assertEqual((seen["apps"], seen["cores"], seen["accepted"], seen["flatpak"]), (["org.purei.Play"], ["snes9x"], ["snes9x"], True))
        self.assertFalse(os.path.exists(m.SETUP_JOB))

    def test_core_remove_resyncs(self):
        import asyncio
        m = self.main
        with self.mock.patch.object(m.cores, "remove", lambda *a: None), self.mock.patch.object(m.cores, "listing", lambda *a: []):
            asyncio.run(m.Plugin().core_remove("bsnes"))
        self.assertIn("roms_changed", self.events)

    def test_no_layouts_on_a_failed_list_nor_for_the_running_game(self):
        import asyncio
        m = self.main
        with open(m.STATE, "w") as f:
            json.dump({"roms": {"a": {"system": "snes", "path": "/x/a.sfc", "appid": 3000000001},
                                "b": {"system": "snes", "path": "/x/b.sfc", "appid": 3000000002}}, "collections": {}}, f)
        with self.mock.patch.object(m, "_face", return_value="xbox"), self.mock.patch.object(m.flatpaks, "installed", return_value=None):
            self.assertEqual(asyncio.run(m.Plugin().library_state())["layout"], [])
        with open(os.path.join(self.dir.name, "running.json"), "w") as f:
            # SteamGameId of a shortcut: its appid in the top 32 bits
            json.dump({"pid": os.getpid(), "appid": str((3000000001 << 32) | 0x02000000)}, f)
        with self.mock.patch.object(m, "_face", return_value="xbox"), self.mock.patch.object(m.flatpaks, "installed", return_value={}), \
                self.mock.patch.object(m.keys, "runtime_dir", return_value=self.dir.name):
            lay = asyncio.run(m.Plugin().library_state())["layout"]
        self.assertEqual([x["appid"] for x in lay], [3000000002])

    def test_files_under_a_game_folder(self):
        d = os.path.join(self.dir.name, "inbox", "Game")
        touch(os.path.join(d, "PS3_GAME", "PARAM.SFO"))
        touch(os.path.join(d, "PS3_GAME", "USRDIR", "EBOOT.BIN"))
        self.assertEqual(sorted(os.path.relpath(p, d) for p in self.main._files_under(d)),
                         ["PS3_GAME/PARAM.SFO", "PS3_GAME/USRDIR/EBOOT.BIN"])


class FlatpakHelpers(unittest.TestCase):
    def test_failed_list_is_none(self):
        import flatpaks
        from unittest import mock
        with mock.patch.object(flatpaks, "_run", return_value=mock.Mock(stdout="", returncode=1)):
            self.assertIsNone(flatpaks.installed("/h"))
        with mock.patch.object(flatpaks, "_run", side_effect=OSError("no flatpak")):
            self.assertIsNone(flatpaks.installed("/h"))

    def test_forget_updates_clears_them(self):
        import flatpaks
        flatpaks._updates.update(at=1e18, apps={"a.b.C"})
        flatpaks.forget_updates()
        self.assertEqual(flatpaks._updates["apps"], set())
        self.assertEqual(flatpaks._updates["at"], 0.0)

    def test_the_unit_runs_in_english(self):
        import flatpaks
        from unittest import mock
        calls = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(flatpaks.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or mock.Mock(returncode=0, stderr="")):
            flatpaks.start(tmp, os.path.join(tmp, "log"), [["true"]])
        run = next(c for c in calls if c[0] == "systemd-run")
        self.assertIn("--setenv=LC_ALL=C.UTF-8", run)


class SavesKeepOutOfBios(unittest.TestCase):
    def test_bios_is_never_a_save(self):
        db = {"emulators": {"x": {"kind": "flatpak", "name": "xemu", "saves": [{"dir": "Emulation/bios/xbox", "glob": "*.qcow2"}]},
                            "y": {"kind": "flatpak", "name": "Y", "saves": [{"dir": "Emulation", "glob": "*"}]}}}
        with tempfile.TemporaryDirectory() as home:
            touch(os.path.join(home, "Emulation", "bios", "xbox", "xbox_hdd.qcow2"), b"hdd")
            touch(os.path.join(home, "Emulation", "bios", "scph5501.bin"), b"bios")
            touch(os.path.join(home, "Emulation", "saves", "y", "game.sav"), b"save")
            self.assertEqual(saves.save_dirs(db)[1][0]["dir"], "Emulation")  # the bios dir isn't one
            games = saves.listing(home, {}, db)
            files = [f["path"] for g in games for f in g["files"]]
            self.assertTrue(files)
            self.assertFalse([p for p in files if "/bios/" in p])
            bios = os.path.join(home, "Emulation", "bios", "scph5501.bin")
            with self.assertRaises(ValueError):
                saves.delete([bios], {bios}, home)
            zp = saves.backup([bios], os.path.join(home, "Emulation", "backups"), home, [])
            with zipfile.ZipFile(zp) as z:
                self.assertEqual(z.namelist(), [])
            evil = os.path.join(home, "evil.zip")
            with zipfile.ZipFile(evil, "w") as z:
                z.writestr("home/Emulation/bios/scph5501.bin", "overwritten")
                z.writestr("storage/U/Emulation/bios/x.bin", "x")
            r = saves.restore(evil, home, [{"uuid": "U", "path": os.path.join(home, "card")}], ("Emulation/",))
            self.assertEqual(r, {"restored": 0, "skipped": 2})
            with open(bios, "rb") as f:
                self.assertEqual(f.read(), b"bios")


class Flatpaks(unittest.TestCase):
    def test_progress(self):
        import flatpaks
        log = "Looking for matches\u2026\nInstalling 2/4\u2026 \u258c 45%  1.2\u00a0MB/s  00:12\n"
        p = flatpaks.progress(log)
        self.assertEqual((p["percent"], p["eta"]), (36.2, "00:12"))
        self.assertAlmostEqual(p["speed"], 1.2e6 / 2**20)
        self.assertEqual(flatpaks.progress("nothing")["percent"], 0.0)
        self.assertEqual(flatpaks.exit_code(f"x\n{flatpaks.EXIT_MARK} 3\n"), 3)
        self.assertIsNone(flatpaks.exit_code("still going"))

    def test_commands(self):
        import flatpaks
        self.assertEqual(flatpaks.commands("update", ["a.b.C"], {}), [[flatpaks.FLATPAK, "update", "--user", "-y", "a.b.C"]])
        self.assertEqual(flatpaks.commands("remove", ["a.b.C"], {})[0][:3], [flatpaks.FLATPAK, "uninstall", "--user"])
        self.assertEqual(flatpaks.override_args(["~/Emulation", "--filesystem=/run/media:ro", "--device=input"]),
                         ["--filesystem=~/Emulation", "--filesystem=/run/media:ro", "--device=input"])
        for bad in (["a b; rm"], ["--x"] * 0 + ["$(id)"], []):
            with self.assertRaises(ValueError):
                flatpaks.commands("install", bad, {})
        with self.assertRaises(ValueError):
            flatpaks.override_args(["ok", "two\nlines"])

    def test_installed_listing(self):
        import flatpaks
        from unittest import mock
        out = "org.ppsspp.PPSSPP\t1.20.4\tflathub\tsystem\norg.ppsspp.PPSSPP\t1.20.4\tflathub\tuser\nbroken line\n"
        with mock.patch.object(flatpaks, "_run", return_value=mock.Mock(stdout=out, returncode=0)):
            self.assertEqual(flatpaks.installed("/h"), {"org.ppsspp.PPSSPP": {"version": "1.20.4", "origin": "flathub", "installation": "user"}})


class StandaloneSaves(unittest.TestCase):
    def test_saves_where_systems_json_says(self):
        with tempfile.TemporaryDirectory() as home:
            psp = os.path.join(home, ".var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP")
            touch(os.path.join(psp, "SAVEDATA", "ULUS10041DATA00", "DATA.BIN"), b"s")
            touch(os.path.join(psp, "SAVEDATA", "ULUS10041DATA00", "ICON0.PNG"), b"i")
            touch(os.path.join(psp, "PPSSPP_STATE", "ULUS10041_1.00_0.ppst"), b"st")
            touch(os.path.join(psp, "PPSSPP_STATE", "notes.txt"), b"n")  # not its glob
            os.symlink("/etc", os.path.join(psp, "SAVEDATA", "evil"))
            games = {g["title"]: g for g in saves.listing(home, {}, DB_V2)}
            self.assertEqual(set(games), {"ULUS10041DATA00", "ULUS10041_1.00_0.ppst"})
            self.assertEqual(sorted(f["kind"] for f in games["ULUS10041DATA00"]["files"]), ["save", "save"])
            self.assertEqual([f["kind"] for f in games["ULUS10041_1.00_0.ppst"]["files"]], ["state"])
            self.assertEqual(games["ULUS10041DATA00"]["emulator"], "PPSSPP")
            allowed = saves.home_save_dirs(DB_V2)
            self.assertIn(".var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP/SAVEDATA/", allowed)
            zp = saves.backup([f["path"] for g in games.values() for f in g["files"]], os.path.join(home, "Emulation", "backups"), home, [])
            import shutil
            shutil.rmtree(os.path.join(psp, "SAVEDATA", "ULUS10041DATA00"))
            self.assertEqual(saves.restore(zp, home, [], allowed)["restored"], 3)
            self.assertTrue(os.path.exists(os.path.join(psp, "SAVEDATA", "ULUS10041DATA00", "DATA.BIN")))

    def test_bad_save_dirs_are_ignored(self):
        db = {"emulators": {"x": {"kind": "flatpak", "name": "X", "saves": [{"dir": "../etc"}, {"dir": "~/.ssh"}, {"dir": ""}]}}}
        self.assertEqual(saves.save_dirs(db), ([], []))
        self.assertEqual(saves.home_save_dirs(db), ("Emulation/",))


class Layouts(unittest.TestCase):
    """Each shortcut gets the layout of the emulator it starts with, again when that changes."""

    @classmethod
    def setUpClass(cls):
        Plugin.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from unittest import mock
        self.mock = mock
        self.dir = tempfile.TemporaryDirectory()
        db = json.loads(json.dumps(DB_V2))
        db["emulators"]["melonds"] = {"name": "melonDS", "kind": "flatpak", "flatpak": "net.kuribo64.melonDS", "free": True,
                                      "hotkeys": ["save_state", "load_state"], "keys": {"save_state": "LEFT_SHIFT+F1", "load_state": "F1"}}
        db["emulators"]["ra-melondsds"] = {"name": "melonDS DS", "kind": "libretro", "core": "melondsds", "free": True}
        db["flatpaks"]["net.kuribo64.melonDS"] = {"name": "melonDS", "permissions": []}
        db["systems"]["nds"] = {"name": "DS", "folders": ["nds"], "extensions": ["nds"], "emulators": ["ra-melondsds", "melonds"]}
        self.db = db
        self.patches = [mock.patch.dict(os.environ, {"KETTLE_EMU_SYSTEMS": write_db(self.dir.name, db)}),
                        mock.patch.object(self.main, "HOME", os.path.join(self.dir.name, "home")),
                        mock.patch.object(self.main, "STATE", os.path.join(self.dir.name, "roms.json")),
                        mock.patch.object(self.main, "CHOICES", os.path.join(self.dir.name, "choices.json")),
                        mock.patch.object(self.main, "_face", return_value="xbox")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.dir.cleanup()

    def inst(self, *apps):
        return {a: {"version": "1", "origin": "flathub", "installation": "user"} for a in apps}

    def test_effective_matches_emu_runs_choice(self):
        eff = self.main.effective
        db = self.db
        # nothing installed: the first listed (its layout waits for it)
        self.assertEqual(eff(db, "nds", None, None, {}), "ra-melondsds")
        # only melonDS installed: the first installed, as emu-run starts it
        self.assertEqual(eff(db, "nds", None, None, self.inst("net.kuribo64.melonDS")), "melonds")
        # the game's choice before the system's; a choice that isn't installed is passed over
        both = self.inst("net.kuribo64.melonDS", "org.libretro.RetroArch")
        touch(os.path.join(self.main.HOME, ".var/app/org.libretro.RetroArch/config/retroarch/cores/melondsds_libretro.so"))
        self.assertEqual(eff(db, "nds", "melonds", "ra-melondsds", both), "melonds")
        self.assertEqual(eff(db, "nds", None, "melonds", both), "melonds")
        self.assertEqual(eff(db, "nds", "melonds", None, self.inst("org.libretro.RetroArch")), "ra-melondsds")
        self.assertEqual(eff(db, "nds", "ra-bsnes", None, both), "ra-melondsds")  # not one of the system's

    def test_layout_follows_the_emulator(self):
        import asyncio
        from kettle_emulation import systems
        m = self.main
        st = {"roms": {"g": {"system": "nds", "path": "/x/g.nds", "appid": 7}, "s": {"system": "snes", "path": "/x/s.sfc", "appid": 8,
                                                                                  "layout": True}},
              "collections": {}}
        with open(m.STATE, "w") as f:
            json.dump(st, f)
        own = systems.layout("melonds", "xbox")
        std = systems.layout("ra-melondsds", "xbox")
        self.assertNotEqual(own, std)
        self.assertTrue(own.endswith("emulation-xbox-melonds.vdf"), own)
        events = []

        async def emit(ev, *a):
            events.append(ev)

        p = m.Plugin()
        with self.mock.patch.object(m.flatpaks, "installed", return_value=self.inst("net.kuribo64.melonDS")), \
                self.mock.patch.object(m, "_emit", emit):
            lay = asyncio.run(p.library_state())["layout"]
            # the DS game starts with melonDS (the only one installed): its own layout; the SNES
            # game laid out before (True, the standard one) needs nothing
            self.assertEqual(lay, [{"appid": 7, "path": own}])
            asyncio.run(p.layout_done({"7": own}))
            self.assertEqual(asyncio.run(p.library_state())["layout"], [])
            # the system's emulator changed: laid out again, and a sync is asked for
            with open(m.CHOICES, "w") as f:
                json.dump({}, f)
            asyncio.run(p.set_choice("nds", "ra-melondsds"))
            self.assertIn("roms_changed", events)
        with self.mock.patch.object(m.flatpaks, "installed", return_value=self.inst("net.kuribo64.melonDS", "org.libretro.RetroArch")):
            touch(os.path.join(m.HOME, ".var/app/org.libretro.RetroArch/config/retroarch/cores/melondsds_libretro.so"))
            self.assertEqual(asyncio.run(p.library_state())["layout"], [{"appid": 7, "path": std}])
            # a path that isn't a layout isn't recorded
            asyncio.run(p.layout_done({"7": "/etc/passwd"}))
            self.assertEqual(len(asyncio.run(p.library_state())["layout"]), 1)

    def test_needs_checks(self):
        m = self.main
        e = {"needs": ["Map the pad", {"text": "keys", "check": ["Emulation/bios/switch/prod.keys", "other/prod.keys"]},
                       {"text": "hdd", "check": "Emulation/bios/xbox/xbox_hdd.qcow2"}, {"text": "sneaky", "check": "../../etc/passwd"}]}
        touch(os.path.join(m.HOME, "other", "prod.keys"))
        self.assertEqual(m._needs(e), [{"text": "Map the pad", "met": None}, {"text": "keys", "met": True},
                                      {"text": "hdd", "met": False}, {"text": "sneaky", "met": False}])


def _sfo(title):
    keys = b"TITLE\0TITLE_ID\0"
    t = title.encode() + b"\0"
    tid = b"BLUS30443\0"
    data = t.ljust(128, b"\0") + tid.ljust(16, b"\0")
    n = 2
    keys_off = 20 + 16 * n
    data_off = keys_off + len(keys)
    entries = struct.pack("<HHIII", 0, 0x0204, len(t), 128, 0) + struct.pack("<HHIII", 6, 0x0204, len(tid), 16, 128)
    return struct.pack("<4sIIII", b"\0PSF", 0x101, keys_off, data_off, n) + entries + keys + data


class GameFolders(unittest.TestCase):
    SYS = {"ps3": {"name": "PS3", "folders": ["ps3"], "extensions": ["iso"], "game_folders": {"marker": "PS3_GAME/PARAM.SFO"}},
           "snes": SYSTEMS["snes"]}

    def test_a_folder_with_the_marker_is_one_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            emu = os.path.join(tmp, "Emulation")
            game = os.path.join(emu, "roms", "ps3", "Demon's Souls (USA) v1.00")
            touch(os.path.join(game, "PS3_GAME", "PARAM.SFO"), _sfo("Demon's Souls\nTM"))
            touch(os.path.join(game, "PS3_GAME", "USRDIR", "EBOOT.BIN"), b"e")
            touch(os.path.join(game, "PS3_GAME", "USRDIR", "data.iso"), b"not a game")  # inside a game: not listed
            touch(os.path.join(emu, "roms", "ps3", "Other v2.5", "PS3_GAME", "PARAM.SFO"), b"broken sfo")
            touch(os.path.join(emu, "roms", "ps3", "Disc.iso"), b"iso")
            touch(os.path.join(emu, "roms", "ps3", "not a game", "readme.txt"), b"r")
            found = roms.scan([{"path": tmp, "emulation": emu, "uuid": "U", "internal": True}], self.SYS)
            by = {os.path.relpath(r["path"], os.path.join(emu, "roms", "ps3")): r for r in found.values()}
            self.assertEqual(set(by), {"Demon's Souls (USA) v1.00", "Other v2.5", "Disc.iso"})
            self.assertEqual(by["Demon's Souls (USA) v1.00"]["title"], "Demon's Souls TM")
            self.assertEqual(by["Other v2.5"]["title"], "Other v2.5")  # the folder's name, dots kept
            self.assertEqual(by["Disc.iso"]["title"], "Disc")
            self.assertEqual(by["Demon's Souls (USA) v1.00"]["size"], len(_sfo("Demon's Souls\nTM")))

    def test_sfo_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "PARAM.SFO")
            touch(p, _sfo("Ratchet & Clank"))
            self.assertEqual(roms.sfo_title(p), "Ratchet & Clank")
            touch(p, b"\0PSF" + b"\xff" * 30)
            self.assertIsNone(roms.sfo_title(p))


if __name__ == "__main__":
    unittest.main()
