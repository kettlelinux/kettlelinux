# Steam's browser (CEF) through its DevTools port, 127.0.0.1:8080, which Decky Loader turns on:
# the list of open pages, and running JavaScript in one of them. Standard library only (a
# minimal WebSocket client), called from a thread.
import base64, json, os, socket, struct, urllib.parse, urllib.request

BASE = "http://127.0.0.1:8080"


def targets() -> list[dict]:
    with urllib.request.urlopen(BASE + "/json", timeout=5) as r:
        return json.load(r)


class _WS:
    def __init__(self, url: str):
        u = urllib.parse.urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("CEF closed the connection")
            buf += chunk
        self.rest = buf.split(b"\r\n\r\n", 1)[1]
        self.n = 0

    def close(self):
        self.s.close()

    def _read(self, n: int) -> bytes:
        while len(self.rest) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("CEF closed the connection")
            self.rest += chunk
        d, self.rest = self.rest[:n], self.rest[n:]
        return d

    def _send(self, obj):
        p = json.dumps(obj).encode()
        hdr = bytes([0x81])
        if len(p) < 126:
            hdr += bytes([0x80 | len(p)])
        elif len(p) < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", len(p))
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", len(p))
        mask = os.urandom(4)
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(p)))

    def _recv(self) -> dict:
        _, b2 = self._read(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read(8))[0]
        return json.loads(self._read(n))

    def call(self, method: str, **params) -> dict:
        self.n += 1
        self._send({"id": self.n, "method": method, "params": params})
        while True:
            m = self._recv()
            if m.get("id") == self.n:
                return m


def evaluate(target: dict, js: str):
    """Runs js in the page target (from targets()) and returns its value."""
    ws = _WS(target["webSocketDebuggerUrl"])
    try:
        r = ws.call("Runtime.evaluate", expression=js, awaitPromise=True, returnByValue=True)
    finally:
        ws.close()
    return r.get("result", {}).get("result", {}).get("value")
