"""The keys bridge: a uinput keyboard that emu-run owns while a game runs, so the plugin's QAM
buttons send the very keys Select's hotkey layer sends (mkvdf.py), and emu-run can quit an
emulator the graceful way (Esc) before signalling it.

The plugin talks to it over $XDG_RUNTIME_DIR/kettle-emulation/keys.sock: one action name per
connection, answered "ok" or "error <why>".
"""
import os
import socket
import threading
import time

# action -> the key every seeded emulator binds to it
ACTIONS = {
    "save_state": "KEY_F2",
    "load_state": "KEY_F4",
    "menu": "KEY_F1",
    "fast_forward": "KEY_SPACE",
    "slot_down": "KEY_F6",
    "slot_up": "KEY_F7",
    "rewind": "KEY_R",
    "screenshot": "KEY_F8",
    "swap_screens": "KEY_F9",
    "quit": "KEY_ESC",
}
# held this long; rewind runs while the key is down
HOLD = {"rewind": 2.0}


def runtime_dir():
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
                     "kettle-emulation")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


class Bridge:
    def __init__(self):
        import evdev
        from evdev import ecodes as e

        self.e = e
        self.codes = {a: getattr(e, k) for a, k in ACTIONS.items()}
        self.kbd = evdev.UInput({e.EV_KEY: sorted(set(self.codes.values()))},
                                name="Kettle Emulation Keys")
        self.lock = threading.Lock()
        self.sock = None

    def tap(self, action):
        code = self.codes[action]
        with self.lock:
            self.kbd.write(self.e.EV_KEY, code, 1)
            self.kbd.syn()
            time.sleep(HOLD.get(action, 0.06))
            self.kbd.write(self.e.EV_KEY, code, 0)
            self.kbd.syn()

    def serve(self):
        path = os.path.join(runtime_dir(), "keys.sock")
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        os.chmod(path, 0o600)
        self.sock.listen(4)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(2)
                try:
                    action = conn.recv(64).decode().strip()
                except (OSError, UnicodeDecodeError):
                    continue
                if action in self.codes:
                    self.tap(action)
                    reply = "ok"
                else:
                    reply = "error unknown action"
                try:
                    conn.sendall(reply.encode() + b"\n")
                except OSError:
                    pass

    def close(self):
        if self.sock:
            self.sock.close()
            try:
                os.unlink(os.path.join(runtime_dir(), "keys.sock"))
            except OSError:
                pass
        self.kbd.close()


def send(action):
    """The plugin's side: True when the running game's bridge pressed the key."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect(os.path.join(runtime_dir(), "keys.sock"))
        s.sendall(action.encode())
        return s.recv(64).decode().strip() == "ok"
    except OSError:
        return False
    finally:
        s.close()
