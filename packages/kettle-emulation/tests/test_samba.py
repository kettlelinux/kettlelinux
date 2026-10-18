import importlib.machinery
import importlib.util
import io
import os
import pwd
import subprocess
import sys
import unittest
from unittest import mock

from helpers import PKG, Env

from kettle_emulation import samba


def load_helper():
    loader = importlib.machinery.SourceFileLoader("kettle_emu_share", os.path.join(PKG, "kettle-emu-share"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Share(Env):
    def setUp(self):
        super().setUp()
        etc = os.path.join(self.tmp, "etc")
        self.paths = dict(SMB_CONF=os.path.join(etc, "samba/smb.conf"),
                          SHARE_CONF=os.path.join(etc, "samba/kettle-emulation.conf"),
                          AVAHI_SERVICE=os.path.join(etc, "avahi/services/kettle-smb.service"),
                          STATE=os.path.join(etc, "samba/kettle-emulation.state"))
        self.patches = [mock.patch.object(samba, k, v) for k, v in self.paths.items()]
        self.patches.append(mock.patch.object(samba, "INCLUDE", f"include = {self.paths['SHARE_CONF']}"))
        for p in self.patches:
            p.start()
        self.helper = load_helper()
        self.calls = []

        def fake(cmd, *a, **kw):
            self.calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 1 if cmd[:2] == ["systemctl", "is-enabled"] else 0, "", "")

        self.patches.append(mock.patch.object(self.helper.subprocess, "run", fake))
        self.patches[-1].start()
        home = os.path.join(self.tmp, "home")
        self.user = pwd.struct_passwd(("kettle", "x", 1000, 1000, "", home, "/bin/bash"))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def enable(self, password="hunter22!"):
        with mock.patch.object(sys, "stdin", io.StringIO(password + "\n")), \
             mock.patch.object(self.helper.os.path, "exists",
                               lambda p: p == "/usr/bin/avahi-daemon" or os.path.lexists(p)), \
             mock.patch.object(self.helper.os, "chown", lambda *a: None):
            self.helper.enable(self.user)

    def test_enable_and_disable(self):
        self.enable()
        with open(self.paths["SMB_CONF"]) as f:
            conf = f.read()
        self.assertTrue(conf.startswith(samba.MARK))
        self.assertIn(samba.INCLUDE, conf)
        with open(self.paths["SHARE_CONF"]) as f:
            share = f.read()
        self.assertIn("[Kettle]", share)
        self.assertIn("valid users = kettle", share)
        self.assertIn(os.path.join(self.tmp, "home", "Emulation"), share)
        self.assertIn(["smbpasswd", "-s", "-a", "kettle"], self.calls)
        self.assertIn(["systemctl", "enable", "--now", "smb.service", "nmb.service"], self.calls)
        self.assertIn(["systemctl", "enable", "--now", "avahi-daemon.service"], self.calls)
        self.assertTrue(os.path.isfile(self.paths["AVAHI_SERVICE"]))
        # the password went to smbpasswd on stdin, never in argv
        self.assertFalse(any("hunter22!" in " ".join(c) for c in self.calls))
        self.calls.clear()
        self.helper.disable(self.user)
        for k in ("SMB_CONF", "SHARE_CONF", "AVAHI_SERVICE", "STATE"):
            self.assertFalse(os.path.exists(self.paths[k]), k)
        self.assertIn(["systemctl", "disable", "--now", "avahi-daemon.service"], self.calls)
        self.assertIn(["smbpasswd", "-d", "kettle"], self.calls)

    def test_own_smb_conf_is_left_alone(self):
        os.makedirs(os.path.dirname(self.paths["SMB_CONF"]))
        with open(self.paths["SMB_CONF"], "w") as f:
            f.write("[global]\n workgroup = MINE\n")
        with self.assertRaises(SystemExit) as e:
            self.enable()
        self.assertEqual(e.exception.code, 3)
        with open(self.paths["SMB_CONF"]) as f:
            self.assertEqual(f.read(), "[global]\n workgroup = MINE\n")

    def test_missing_folder_not_made_as_root(self):
        os.rmdir(self.home)
        with self.assertRaises(SystemExit) as e:
            self.enable()
        self.assertEqual(e.exception.code, 4)
        self.assertFalse(os.path.lexists(self.home))
        self.assertFalse(os.path.exists(self.paths["SHARE_CONF"]))

    def test_polkit_rule_allows_decky(self):
        with open(os.path.join(PKG, "50-kettle-emulation-share.rules")) as f:
            rules = f.read()
        self.assertIn("function fromDecky(subject)", rules)
        self.assertIn("|| fromDecky(subject)", rules)

    def test_short_password(self):
        with self.assertRaises(SystemExit) as e:
            self.enable("short")
        self.assertEqual(e.exception.code, 2)
        self.assertRaises(ValueError, samba.enable, "short")


if __name__ == "__main__":
    unittest.main()
