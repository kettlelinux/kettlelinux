"""The upload page: a small web server on the local network that a phone or PC browser sends
ROMs and BIOS files to, for the Emulation plugin's "Upload from phone or PC" (a QR code of the
address). It runs only while the plugin asks for it, and quits after `idle_timeout` seconds
without a request that had the PIN.

Access needs the 6-digit PIN shown on the device; after 10 wrong PINs from one address it isn't
asked again from there, and after 30 from anywhere nothing is accepted until the server is
started again. That last one is a trade-off: anyone on the network can lock the real user out
with 30 wrong PINs from 3 addresses (they then restart the page on the device, which shows a new
PIN), but no one can try the million PINs from many addresses. A connection that sends nothing
for TIMEOUT seconds is closed, and at most MAX_CONNS are served at a time; a request body is read
only after the PIN (or a session) checks out, so no one without it can hold a connection open by
trickling one. A file is streamed to <inbox>/.upload-tmp, renamed into the inbox
when it's complete, and sorted (importer.py) when the page says the batch is done, so a .cue and
its tracks arrive before they're sorted together. Names are reduced to a plain file name.
"""
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import importer, storage

MAX_SIZE = 64 << 30
MAX_BAD_PINS = 10       # from one address
MAX_BAD_PINS_ALL = 30   # from all of them: then nothing is accepted
MAX_CONNS = 32
TIMEOUT = 30
COOKIE = "kettle_upload"
CHUNK = 1 << 20
DRAIN_MAX = 1 << 16  # a bigger body than this where none is needed closes the connection
SPARE = 256 << 20  # left free on the disk


MAX_DEPTH = 32  # folders a dropped folder's file may sit in (a PS3 game nests deep)


def safe_path(path):
    """A relative path under the inbox from what the browser sent for a file of a dropped
    folder ("FF7/Disc1/FF7 (Disc 1).cue"): each folder made a plain name as safe_name does,
    ".", ".." and empty parts dropped. A plain file name otherwise; None when it's nested
    deeper than MAX_DEPTH (cut short, a game's layout would be wrong)."""
    parts = [p for p in path.replace("\\", "/").split("/") if p.strip() not in ("", ".", "..")]
    if len(parts) <= 1:
        return safe_name(path)
    if len(parts) - 1 > MAX_DEPTH:
        return None
    return os.path.join(*(safe_name(p) for p in parts))


def safe_name(name):
    """A plain file name from whatever the browser sent: no folders, control characters or
    leading dots, at most 200 bytes (keeping the extension)."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().lstrip(".").strip()
    if not name:
        return "upload"
    b = name.encode()
    if len(b) > 200:
        stem, dot, ext = name.rpartition(".")
        if not dot or len(ext.encode()) > 16:
            stem, ext = name, ""
        keep = 200 - len(ext.encode()) - (1 if ext else 0)
        stem = stem.encode()[:keep].decode(errors="ignore")
        name = stem + ("." + ext if ext else "")
    return name


def lan_addresses():
    """This device's IPv4 addresses other than loopback."""
    try:
        out = subprocess.run(["ip", "-j", "-4", "addr", "show", "scope", "global"],
                             capture_output=True, text=True, timeout=5).stdout
        addrs = [a["local"] for i in json.loads(out or "[]") for a in i.get("addr_info", ())
                 if a.get("local")]
        if addrs:
            return addrs
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent
            return [s.getsockname()[0]]
    except OSError:
        return []


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, inbox, emulation, emit, idle_timeout=600, pin=None):
        super().__init__(addr, Handler)
        self.inbox = inbox
        self.emulation = emulation
        self.tmpdir = os.path.join(inbox, importer.UPLOAD_TMP)
        os.makedirs(self.tmpdir, exist_ok=True)
        self.emit = emit
        self.pin = pin or f"{secrets.randbelow(10 ** 6):06d}"
        self.tokens = set()
        self.bad = 0
        self.bad_from = {}
        self.conns = threading.BoundedSemaphore(MAX_CONNS)
        self.lock = threading.Lock()
        self.import_lock = threading.Lock()
        self.idle_timeout = idle_timeout
        self.last = time.monotonic()
        self.active = 0
        self.uploaded = []

    @property
    def locked(self):
        return self.bad >= MAX_BAD_PINS_ALL

    def locked_out(self, client):
        return self.locked or self.bad_from.get(client, 0) >= MAX_BAD_PINS

    def check_pin(self, pin, client=None):
        with self.lock:
            if self.locked_out(client):
                return False
            if isinstance(pin, str) and hmac.compare_digest(pin.encode(), self.pin.encode()):
                return True
            self.bad += 1
            self.bad_from[client] = self.bad_from.get(client, 0) + 1
            if self.locked:
                self.emit({"event": "locked"})
            return False

    def process_request(self, request, client_address):
        # one thread a connection, at most MAX_CONNS of them
        if not self.conns.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.conns.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.conns.release()

    def claim(self, tmp, name):
        """Rename a finished upload into the inbox under a name nothing else has (another upload
        of the same name, or a file copied in over the share), never over one."""
        with self.lock:
            os.makedirs(os.path.dirname(os.path.join(self.inbox, name)), exist_ok=True)
            while True:
                dest = importer.free_name(os.path.join(self.inbox, name))
                try:
                    os.link(tmp, dest)
                except FileExistsError:
                    continue
                except OSError:
                    os.replace(tmp, dest)  # no hard links there (a card's FAT): the lock covers it
                    return dest
                os.unlink(tmp)
                return dest

    def touch(self):
        self.last = time.monotonic()

    def watch_idle(self):
        while True:
            time.sleep(min(5, max(self.idle_timeout / 4, 0.05)))
            if self.active == 0 and time.monotonic() - self.last > self.idle_timeout:
                self.emit({"event": "exit", "reason": "idle"})
                self.shutdown()
                return

    def sort_inbox(self):
        """Sort the inbox; [{src, kind, system, action, dest}] of what was done."""
        results = []

        def collect(ev):
            if ev.get("event") == "item":
                results.append({k: ev.get(k) for k in ("src", "kind", "system", "action", "dest", "archive")})

        with self.import_lock:
            importer.Importer(self.emulation, "move", collect).run(self.inbox)
        return results

    def cleanup(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def _length(headers):
    """Content-Length as a number, or None when it's missing or not a plain one."""
    v = (headers.get("Content-Length") or "").strip()
    return int(v) if v.isdigit() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "KettleUpload"
    protocol_version = "HTTP/1.1"
    timeout = TIMEOUT  # a socket timeout: an idle or stalled connection gives its thread back

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", headers=()):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if not ctype.endswith("json") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        c = cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            pass
        tok = c.get(COOKIE)
        if tok and any(hmac.compare_digest(tok.value, t) for t in list(self.server.tokens)):
            return True
        pin = self.headers.get("X-Kettle-Pin")
        return pin is not None and self.server.check_pin(pin, self.client_address[0])

    def _deny(self):
        if self.server.locked_out(self.client_address[0]):
            self._send(429, {"error": "locked: too many wrong PINs; restart the upload page on the device"})
        else:
            self._send(403, {"error": "PIN needed"})

    def _drain(self):
        """Read past a small body to keep the connection; a missing or big one closes it."""
        n = _length(self.headers)
        if n is None or n > DRAIN_MAX:
            self.close_connection = True
            return
        while n > 0:
            chunk = self.rfile.read(min(n, CHUNK))
            if not chunk:
                break
            n -= len(chunk)

    # the idle timer counts only requests with the PIN (or a session): anyone on the network
    # can fetch the page, and that mustn't keep the server up
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            self._send(200, PAGE, "text/html")
        elif path == "/api/status":
            if not self._authed():
                return self._deny()
            self.server.touch()
            self._send(200, {"uploaded": self.server.uploaded[-200:]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/login":
            n = _length(self.headers)
            if n is None or n > 1024:
                self.close_connection = True
                return self._send(413 if n else 411, {"error": "too big" if n else "Content-Length needed"})
            try:
                pin = json.loads(self.rfile.read(n) or b"{}").get("pin")
            except (ValueError, AttributeError):
                pin = None
            if not self.server.check_pin(pin if isinstance(pin, str) else "", self.client_address[0]):
                return self._deny()
            self.server.touch()
            tok = secrets.token_urlsafe(24)
            self.server.tokens.add(tok)
            return self._send(200, {"ok": True}, headers=[
                ("Set-Cookie", f"{COOKIE}={tok}; HttpOnly; SameSite=Strict; Path=/")])
        if path == "/api/done":
            if not self._authed():
                self.close_connection = True
                return self._deny()
            self._drain()
            self.server.touch()
            results = self.server.sort_inbox()
            self.server.emit({"event": "sorted", "results": results})
            return self._send(200, {"results": results})
        self.close_connection = True
        self._send(404, {"error": "not found"})

    def do_PUT(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path != "/api/upload":
            self.close_connection = True
            return self._send(404, {"error": "not found"})
        if not self._authed():
            self.close_connection = True
            return self._deny()
        self.server.touch()
        length = _length(self.headers)
        if length is None:
            self.close_connection = True
            return self._send(411, {"error": "Content-Length needed"})
        if length > MAX_SIZE:
            self.close_connection = True
            return self._send(413, {"error": "file too big"})
        if shutil.disk_usage(self.server.inbox).free < length + SPARE:
            self.close_connection = True
            return self._send(507, {"error": "not enough space on the device"})
        name = safe_path(urllib.parse.parse_qs(url.query).get("name", [""])[0])
        if name is None:
            self.close_connection = True
            return self._send(400, {"error": "folder nested too deep"})
        fd, tmp = tempfile.mkstemp(suffix=".part", dir=self.server.tmpdir)
        self.server.active += 1
        try:
            left = length
            with os.fdopen(fd, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(left, CHUNK))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
                    self.server.touch()
            if left:
                os.unlink(tmp)
                self.close_connection = True
                return
            dest = self.server.claim(tmp, name)
        except OSError as e:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            self.close_connection = True
            return self._send(500, {"error": str(e)})
        finally:
            self.server.active -= 1
            self.server.touch()
        entry = {"name": os.path.relpath(dest, self.server.inbox), "bytes": length}
        self.server.uploaded.append(entry)
        self.server.emit(dict(entry, event="uploaded"))
        self._send(200, entry)


def serve(port=0, idle_timeout=600, emit=print, pin=None, host="0.0.0.0", root=None):
    """Run until idle (blocking). root: the Emulation folder (internal storage's by default)."""
    emu = root or storage.home()
    inbox = os.path.join(emu, "inbox")
    os.makedirs(inbox, exist_ok=True)
    srv = Server((host, port), inbox, emu, emit, idle_timeout, pin)
    p = srv.server_address[1]
    emit({"event": "listening", "port": p, "pin": srv.pin, "idle_timeout": idle_timeout,
          "urls": [f"http://{a}:{p}/" for a in lan_addresses()]})
    threading.Thread(target=srv.watch_idle, daemon=True).start()
    try:
        srv.serve_forever(poll_interval=0.2)
    finally:
        srv.server_close()
        srv.cleanup()
        if srv.uploaded:
            srv.sort_inbox()  # a batch the page never finished
    return srv


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kettle: add games</title>
<style>
:root { --bg:#f6f6f4; --fg:#1d1d1b; --mute:#6b6b66; --card:#fff; --line:#ddd9d0; --acc:#c4582b; --ok:#2f7d4f; --bad:#b3261e; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecebe6; --mute:#9a9992; --card:#212120; --line:#34332f; --acc:#e57a4a; --ok:#5cbf83; --bad:#f2827a; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.45 system-ui, sans-serif; }
main { max-width:640px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:1.5rem; margin:0 0 4px; }
p { color:var(--mute); margin:0 0 20px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:16px; }
input[type=text] { font-size:1.6rem; letter-spacing:.3em; width:100%; padding:10px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--fg); text-align:center; }
button, label.btn { display:inline-block; font:inherit; font-weight:600; padding:12px 18px; border-radius:8px; border:0; background:var(--acc); color:#fff; cursor:pointer; }
#drop { border:2px dashed var(--line); border-radius:12px; padding:32px 16px; text-align:center; }
#drop.over { border-color:var(--acc); }
.file { padding:8px 0; border-bottom:1px solid var(--line); overflow-wrap:anywhere; }
.file:last-child { border-bottom:0; }
.bar { height:6px; background:var(--line); border-radius:3px; margin-top:6px; overflow:hidden; }
.bar i { display:block; height:100%; width:0; background:var(--acc); }
.ok { color:var(--ok); } .bad { color:var(--bad); } .mute { color:var(--mute); font-size:.9rem; }
[hidden] { display:none !important; }
</style></head><body><main>
<h1>Add games to Kettle</h1>
<p>ROMs, disc images, zips and BIOS files. Kettle works out which system each one is for.</p>
<form id="login" class="card">
  <label for="pin">PIN shown on the device</label>
  <input id="pin" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" required>
  <div style="margin-top:12px"><button>Continue</button> <span id="loginmsg" class="bad"></span></div>
</form>
<section id="up" hidden>
  <div id="drop" class="card">
    <div style="margin-bottom:12px">Drop files or folders anywhere on this page, or</div>
    <label class="btn">Choose files<input id="pick" type="file" multiple hidden></label>
    <div class="mute" style="margin-top:12px">Pick a disc's .cue together with its .bin tracks.</div>
  </div>
  <div id="list" class="card" hidden></div>
  <div id="result" class="card" hidden></div>
</section>
<script>
const $ = (id) => document.getElementById(id);
const queue = []; let busy = false;
$("login").onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch("/api/login", {method: "POST", headers: {"Content-Type": "application/json"},
                                         body: JSON.stringify({pin: $("pin").value.trim()})});
  if (r.ok) { $("login").hidden = true; $("up").hidden = false; }
  else { const j = await r.json().catch(() => ({})); $("loginmsg").textContent = j.error || "Wrong PIN"; }
};
// files: [{f: File, path: "folder/sub/name" or the file's name}]
function add(files) {
  if (!files.length) return;
  $("list").hidden = false;
  for (const {f, path} of files) {
    const row = document.createElement("div"); row.className = "file";
    row.innerHTML = '<div></div><div class="bar"><i></i></div><div class="mute">waiting</div>';
    row.firstChild.textContent = path;
    $("list").appendChild(row); queue.push({f, path, row});
  }
  if (!busy) next();
}
const plain = (list) => Array.from(list, (f) => ({f, path: f.webkitRelativePath || f.name}));
// a dropped folder's files, with their paths in it (Firefox and Chrome: webkitGetAsEntry)
function walk(entry, prefix) {
  return new Promise((res) => {
    if (entry.isFile) return entry.file((f) => res([{f, path: prefix + f.name}]), () => res([]));
    const reader = entry.createReader(), all = [];
    const more = () => reader.readEntries(async (batch) => {
      if (!batch.length) return res((await Promise.all(all)).flat());
      for (const e of batch) all.push(walk(e, prefix + entry.name + "/"));
      more();
    }, () => res([]));
    more();
  });
}
async function dropped(dt) {
  const entries = Array.from(dt.items || [], (i) => i.kind === "file" && i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return plain(dt.files);
  return (await Promise.all(entries.map((e) => walk(e, "")))).flat();
}
function put(item) {
  return new Promise((res) => {
    const x = new XMLHttpRequest();
    x.open("PUT", "/api/upload?name=" + encodeURIComponent(item.path));
    const bar = item.row.querySelector("i"), msg = item.row.querySelector(".mute");
    x.upload.onprogress = (e) => { if (e.lengthComputable) { bar.style.width = (100 * e.loaded / e.total) + "%";
      msg.textContent = Math.round(100 * e.loaded / e.total) + "%"; } };
    x.onload = () => { const ok = x.status === 200; bar.style.width = "100%";
      let err = ""; try { err = JSON.parse(x.responseText).error || ""; } catch (e) {}
      msg.textContent = ok ? "uploaded" : ("failed: " + (err || x.status)); msg.className = ok ? "ok" : "bad"; res(ok); };
    x.onerror = () => { msg.textContent = "failed: connection lost"; msg.className = "bad"; res(false); };
    x.send(item.f);
  });
}
async function next() {
  busy = true;
  while (queue.length) await put(queue.shift());
  busy = false;
  const r = await fetch("/api/done", {method: "POST"}); if (!r.ok) return;
  const {results} = await r.json(); const games = {}; let bios = [], unsorted = 0, failed = [];
  for (const x of results) {
    if (x.action === "error") failed.push(x.src.split("/").pop());
    else if (x.kind === "bios" && x.dest) bios.push(x.dest.split("/").pop());
    else if (x.action === "unsorted") unsorted++;
    else if (x.kind === "game" && x.action !== "identical") games[x.system] = (games[x.system] || 0) + 1;
  }
  const lines = Object.entries(games).map(([s, n]) => n + " " + s.toUpperCase());
  if (bios.length) lines.push("BIOS: " + bios.join(", "));
  if (unsorted) lines.push(unsorted + " not recognised: the device will ask which system they're for");
  if (failed.length) lines.push(failed.length + " failed: " + failed.join(", "));
  $("result").hidden = false;
  $("result").textContent = lines.length ? "Sorted: " + lines.join(" · ") : "Nothing new to sort.";
}
$("pick").onchange = (e) => { add(plain(e.target.files)); e.target.value = ""; };
// the whole page takes a drop: Firefox opens a file dropped anywhere else, and refuses a drop
// whose effect stays the file manager's "move"
const drop = $("drop"); let depth = 0;
const ready = () => !$("up").hidden;
window.addEventListener("dragenter", (e) => { e.preventDefault(); if (ready() && ++depth === 1) drop.classList.add("over"); });
window.addEventListener("dragleave", () => { if (depth && --depth === 0) drop.classList.remove("over"); });
window.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = ready() ? "copy" : "none"; });
window.addEventListener("drop", async (e) => {
  e.preventDefault(); depth = 0; drop.classList.remove("over");
  if (ready()) add(await dropped(e.dataTransfer));
});
</script></main></body></html>
"""
