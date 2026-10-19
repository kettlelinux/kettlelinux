import http.client
import json
import os
import socket
import threading
import time
import unittest
from unittest import mock

from helpers import Env

from kettle_emulation import upload


class Upload(Env):
    def start(self, idle=30):
        self.events = []
        self.ready = threading.Event()

        def emit(ev):
            self.events.append(ev)
            if ev["event"] == "listening":
                self.port = ev["port"]
                self.ready.set()

        self.thread = threading.Thread(target=upload.serve, kwargs=dict(
            port=0, idle_timeout=idle, emit=emit, pin="123456", host="127.0.0.1"), daemon=True)
        self.thread.start()
        self.assertTrue(self.ready.wait(5))

    def tearDown(self):
        # the servers here go idle in a second; let them finish before their home goes
        t = getattr(self, "thread", None)
        if t:
            t.join(10)
        super().tearDown()

    def req(self, method, path, body=None, headers=None, source=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10,
                                       source_address=(source, 0) if source else None)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def login(self, pin="123456", source=None):
        r, _ = self.req("POST", "/api/login", json.dumps({"pin": pin}), {"Content-Type": "application/json"},
                        source)
        return r

    def test_page_and_pin(self):
        self.start(idle=1)
        r, page = self.req("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"Add games to Kettle", page)
        r, _ = self.req("PUT", "/api/upload?name=a.nes", b"x")
        self.assertEqual(r.status, 403)
        r = self.login()
        self.assertEqual(r.status, 200)
        cookie = r.getheader("Set-Cookie").split(";")[0]
        r, data = self.req("PUT", "/api/upload?name=" + "..%2F..%2Fevil.nes", b"NES\x1a" + b"\0" * 32,
                           {"Cookie": cookie})
        self.assertEqual(r.status, 200, data)
        self.assertEqual(json.loads(data)["name"], "evil.nes")
        self.assertTrue(os.path.isfile(os.path.join(self.home, "inbox", "evil.nes")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.nes")))
        r, data = self.req("POST", "/api/done", b"", {"Cookie": cookie})
        res = json.loads(data)["results"]
        self.assertEqual([(x["system"], x["action"]) for x in res], [("nes", "moved")])
        self.assertTrue(os.path.isfile(os.path.join(self.home, "roms", "nes", "evil.nes")))
        # the header PIN works too
        r, _ = self.req("PUT", "/api/upload?name=b.gba", b"\0" * 8, {"X-Kettle-Pin": "123456"})
        self.assertEqual(r.status, 200)

    def test_lockout(self):
        self.start(idle=1)
        for _ in range(upload.MAX_BAD_PINS - 1):
            self.assertEqual(self.login("000000").status, 403)
        self.assertEqual(self.login("000000").status, 429)
        self.assertEqual(self.login().status, 429)
        # another address isn't locked out by this one
        self.assertEqual(self.login(source="127.0.0.2").status, 200)
        self.assertNotIn({"event": "locked"}, self.events)
        # until enough wrong PINs from everywhere
        n = upload.MAX_BAD_PINS
        for i in range(2, 10):
            for _ in range(upload.MAX_BAD_PINS):
                if n < upload.MAX_BAD_PINS_ALL:
                    self.login("000000", source=f"127.0.0.{i + 1}")
                    n += 1
        self.assertIn({"event": "locked"}, self.events)
        self.assertEqual(self.login(source="127.0.0.99").status, 429)

    def test_no_length_rejected(self):
        self.start(idle=1)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.putrequest("PUT", "/api/upload?name=a.nes")
        c.putheader("X-Kettle-Pin", "123456")
        c.putheader("Transfer-Encoding", "chunked")
        c.endheaders()
        r = c.getresponse()
        self.assertEqual(r.status, 411)
        c.close()

    def test_idle_exit_sorts_leftovers(self):
        self.start(idle=0.3)
        self.req("PUT", "/api/upload?name=z.gba", b"\0" * 8, {"X-Kettle-Pin": "123456"})
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.events[-1], {"event": "exit", "reason": "idle"})
        self.assertTrue(os.path.isfile(os.path.join(self.home, "roms", "gba", "z.gba")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "inbox", ".upload-tmp")))

    def raw(self, data, wait=True):
        """Send raw bytes on a new connection; the response's status line, or b"" if it closed."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        sock.sendall(data)
        try:
            return sock.recv(4096).split(b"\r\n", 1)[0] if wait else sock
        finally:
            if wait:
                sock.close()

    def test_login_length_checked(self):
        self.start(idle=1)
        self.assertIn(b"411", self.raw(b"POST /api/login HTTP/1.1\r\nContent-Length: -1\r\n\r\n"))
        self.assertIn(b"411", self.raw(b"POST /api/login HTTP/1.1\r\nContent-Length: x\r\n\r\n"))
        self.assertIn(b"413", self.raw(b"POST /api/login HTTP/1.1\r\nContent-Length: 5000\r\n\r\n"))
        self.assertIn(b"404", self.raw(b"POST /nope HTTP/1.1\r\nContent-Length: -5\r\n\r\n"))

    def test_body_not_read_without_the_pin(self):
        # a client without the PIN can't hold a thread by trickling a body it announced
        self.start(idle=1)
        for path, code in ((b"/api/done", b"403"), (b"/nope", b"404")):
            req = b"POST " + path + b" HTTP/1.1\r\nContent-Length: 100000000\r\n\r\n"
            sock = self.raw(req, wait=False)
            sock.settimeout(5)
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break  # answered and closed, not waiting for the body
                data += chunk
            sock.close()
            self.assertEqual(data.split(b"\r\n", 1)[0].split()[1], code)
        # with the PIN, a small body is read past and the connection kept
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        for _ in range(2):
            c.request("POST", "/api/done", b"{}", {"X-Kettle-Pin": "123456"})
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            r.read()
        c.close()

    def test_idle_timer_needs_the_pin(self):
        self.start(idle=0.6)
        end = time.monotonic() + 1.5
        while time.monotonic() < end and self.thread.is_alive():
            try:
                self.req("GET", "/")
            except OSError:
                break  # it stopped while answering
            time.sleep(0.1)
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())

    def test_stalled_connection_closed(self):
        with mock.patch.object(upload, "TIMEOUT", 0.3), mock.patch.object(upload.Handler, "timeout", 0.3):
            self.start(idle=2)
            sock = self.raw(b"GET / HTTP/1.1\r\n", wait=False)
            sock.settimeout(5)
            self.assertEqual(sock.recv(10), b"")  # closed by the server, not left hanging
            sock.close()

    def test_same_name_uploads_both_kept(self):
        box = os.path.join(self.home, "inbox")
        srv = upload.Server(("127.0.0.1", 0), box, self.home, lambda ev: None)
        try:
            tmps = []
            for i in range(8):
                t = os.path.join(srv.tmpdir, f"{i}.part")
                with open(t, "w") as f:
                    f.write(str(i))
                tmps.append(t)
            threads = [threading.Thread(target=srv.claim, args=(t, "Game.nes")) for t in tmps]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            names = sorted(n for n in os.listdir(box) if not n.startswith("."))
            self.assertEqual(len(names), 8)
            contents = set()
            for n in names:
                with open(os.path.join(box, n)) as f:
                    contents.add(f.read())
            self.assertEqual(contents, {str(i) for i in range(8)})
        finally:
            srv.server_close()

    def test_page_summary_survives_failed_bios(self):
        # the page's result summary skips failed items (dest null) before reading dest
        self.assertIn('if (x.action === "error") failed.push', upload.PAGE)
        self.assertIn('x.kind === "bios" && x.dest', upload.PAGE)

    def test_safe_path(self):
        self.assertEqual(upload.safe_path("FF7/Disc1/FF7 (Disc 1).cue"), "FF7/Disc1/FF7 (Disc 1).cue")
        self.assertEqual(upload.safe_path("Mario.nes"), "Mario.nes")
        self.assertEqual(upload.safe_path("../../etc/passwd"), "etc/passwd")
        self.assertEqual(upload.safe_path("/abs/./x/../y.bin"), "abs/x/y.bin")
        self.assertEqual(upload.safe_path("a\\b\\c.iso"), "a/b/c.iso")
        self.assertEqual(upload.safe_path(".git/.config"), "git/config")
        self.assertIsNone(upload.safe_path("/".join(["d"] * 40) + "/f.bin"))
        self.assertEqual(upload.safe_path("/".join(["d"] * 20) + "/f.bin").count("/"), 20)

    def test_folder_upload_kept_in_its_folders(self):
        box = os.path.join(self.home, "inbox")
        srv = upload.Server(("127.0.0.1", 0), box, self.home, lambda ev: None)
        try:
            t = os.path.join(srv.tmpdir, "x.part")
            with open(t, "w") as f:
                f.write("cue")
            dest = srv.claim(t, upload.safe_path("FF7/Disc1/FF7 (Disc 1).cue"))
            self.assertEqual(os.path.relpath(dest, box), "FF7/Disc1/FF7 (Disc 1).cue")
            self.assertTrue(os.path.realpath(dest).startswith(os.path.realpath(box) + os.sep))
        finally:
            srv.server_close()

    def test_page_takes_drops_anywhere_as_copies(self):
        # Firefox opens a file dropped outside a handler, and refuses a drop left on "move"
        self.assertIn('window.addEventListener("drop"', upload.PAGE)
        self.assertIn('dropEffect = ready() ? "copy"', upload.PAGE)
        self.assertIn("webkitGetAsEntry", upload.PAGE)

    def test_safe_name(self):
        self.assertEqual(upload.safe_name("C:\\games\\Mario.nes"), "Mario.nes")
        self.assertEqual(upload.safe_name("../.hidden"), "hidden")
        self.assertEqual(upload.safe_name("a\x00b\n.nes"), "ab.nes")
        self.assertEqual(upload.safe_name(".."), "upload")
        long = upload.safe_name("x" * 300 + ".chd")
        self.assertTrue(long.endswith(".chd"))
        self.assertLessEqual(len(long.encode()), 200)


if __name__ == "__main__":
    unittest.main()
