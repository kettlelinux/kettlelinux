import time
import unittest
from unittest import mock

import helpers  # noqa: F401  (the import path)
from kettle_emulation import awake


class FakeProc:
    started = []

    def __init__(self, argv, **kw):
        self.argv, self.ended = argv, False
        FakeProc.started.append(self)

    def poll(self):
        return 0 if self.ended else None

    def terminate(self):
        self.ended = True

    def wait(self, timeout=None):
        return 0

    kill = terminate


class Awake(unittest.TestCase):
    def setUp(self):
        FakeProc.started = []
        p = mock.patch.object(awake.subprocess, "Popen", FakeProc)
        p.start()
        self.addCleanup(p.stop)

    def test_held_while_any_copy_runs(self):
        a = awake.Awake("test")
        a.hold()
        a.hold()
        a.release()
        self.assertFalse(FakeProc.started[0].ended)
        a.release()
        self.assertTrue(FakeProc.started[0].ended)
        self.assertEqual(len(FakeProc.started), 1)
        argv = FakeProc.started[0].argv
        self.assertIn("--what=sleep:idle", argv)
        self.assertIn("--mode=block", argv)
        # the block ends with this process even if it's killed
        self.assertIn("tail", argv)

    def test_linger_bridges_the_gap_between_files(self):
        a = awake.Awake("test", linger=0.3)
        a.hold()
        a.release()
        a.hold()  # the next file, within the linger
        self.assertEqual(len(FakeProc.started), 1)
        self.assertFalse(FakeProc.started[0].ended)
        a.release()
        time.sleep(0.6)
        self.assertTrue(FakeProc.started[0].ended)

    def test_no_systemd_inhibit_copies_go_on(self):
        with mock.patch.object(awake.subprocess, "Popen", side_effect=OSError):
            with awake.Awake("test"):
                pass
