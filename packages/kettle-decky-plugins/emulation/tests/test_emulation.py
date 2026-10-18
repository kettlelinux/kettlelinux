# python3 -m unittest emulation/tests/test_emulation.py (from packages/kettle-decky-plugins)
import json
import os
import re
import sys
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
            env = {"KETTLE_EMU_SYSTEMS": os.path.join(PKGS, "kettle-emulation", "systems.json")}
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
                    json.dump({"pid": os.getpid(), "rom": raw, "system": "snes", "emulator": "ra-snes9x"}, f)
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
    """systems.json's emulators against what Kettle builds and what Extra cores offers."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(PKGS, "kettle-emulation", "systems.json")) as f:
            cls.db = json.load(f)

    def test_every_emulator_is_packaged_downloadable_or_a_flatpak(self):
        built = set()
        for pkg in ("libretro-cores", "libretro-cores-heavy", "melonds", "ppsspp", "dolphin-emu"):
            built |= _pkgnames(pkg)
        with open(os.path.join(PKGS, "kettle-emulation", "PKGBUILD")) as f:
            pkgbuild = f.read()
        for eid, e in self.db["emulators"].items():
            if "package" in e:
                self.assertIn(e["package"], built, eid)
                self.assertIn(f"'{e['package']}: ", pkgbuild, eid)
                self.assertFalse(e.get("download"), eid)
            elif e["kind"] == "flatpak":
                self.assertIn("'flatpak: ", pkgbuild, eid)
            else:
                self.assertTrue(e.get("download"), f"{eid}: not built and not a download")
        for sid, s in self.db["systems"].items():
            self.assertTrue(s["emulators"], sid)

    def test_msx_needs_bluemsx_system_dirs(self):
        self.assertEqual(self.db["systems"]["msx"]["system_dirs"], cores.SYSTEM_FILES["bluemsx"]["dirs"])
        self.assertIn("Emulation/bios", cores.TERMS["bluemsx"])

    def test_downloads_have_their_terms(self):
        listed = {c["core"]: c for c in cores.listing("/nonexistent", self.db)}
        self.assertIn("bluemsx", listed)
        self.assertEqual(listed["bluemsx"]["systems"], ["MSX"])
        for core in listed:
            self.assertIn(core, cores.TERMS, core)
        self.assertIn("MSX emulators only", cores.TERMS["bluemsx"])


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

        db = {"emulators": {"ra-bluemsx": {"name": "blueMSX", "core": "bluemsx", "download": True}},
              "systems": {"msx": {"name": "MSX", "emulators": ["ra-bluemsx"]}}}
        with tempfile.TemporaryDirectory() as home, mock.patch.object(cores, "_fetch", fetch):
            bios = os.path.join(home, "Emulation", "bios")
            cores.download(home, "bluemsx", {"bluemsx"}, bios)
            self.assertEqual(fetched, [f"{cores.BUILDBOT}/bluemsx_libretro.so.zip", cores.SYSTEM_FILES["bluemsx"]["url"]])
            self.assertTrue(os.path.isdir(os.path.join(bios, "Databases")))
            self.assertTrue(os.path.exists(os.path.join(bios, "Machines", "MSX2", "config.ini")))
            self.assertFalse(os.path.exists(os.path.join(bios, "Machines", "Shared Roms")))  # a real BIOS: left out
            (c,) = cores.listing(home, db, bios)
            self.assertTrue(c["installed"])
            import shutil
            shutil.rmtree(os.path.join(bios, "Databases"))
            (c,) = cores.listing(home, db, bios)
            self.assertEqual((c["installed"], c["missing"]), (False, ["Databases"]))
            # a core without system files fetches only itself
            fetched.clear()
            with mock.patch.object(cores, "_fetch", lambda url: fetched.append(url) or _zip([("snes9x_libretro.so", bytes(so))])):
                cores.download(home, "snes9x", {"snes9x"}, bios)
            self.assertEqual(len(fetched), 1)


class Saves(unittest.TestCase):
    def test_listing_backup_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            rom = os.path.join(home, "Emulation", "roms", "snes", "Game (USA).sfc")
            touch(rom)
            touch(os.path.join(home, "Emulation", "saves", "retroarch", "snes", "Game (USA).srm"), b"save")
            touch(os.path.join(home, "Emulation", "states", "retroarch", "snes", "Game (USA).state1"), b"st")
            touch(os.path.join(home, "Emulation", "states", "retroarch", "snes", "Game (USA).state1.png"), b"png")
            games = saves.listing(home, {"r1": {"system": "snes", "path": rom, "title": "Game"}})
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
            self.assertEqual(saves.listing(home, {"r1": {"system": "snes", "path": rom}}), [])
            r = saves.restore(zp, home, [])
            self.assertEqual(r["restored"], 3)
            self.assertEqual(saves.restore(z2, home, []), {"restored": 0, "skipped": 2})
            self.assertFalse(os.path.exists(os.path.join(home, ".bashrc")))
            with self.assertRaises(ValueError):
                saves.delete(["/etc/passwd"], saves.all_paths(games))


if __name__ == "__main__":
    unittest.main()
