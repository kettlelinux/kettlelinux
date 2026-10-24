"""The keys bridge: a uinput keyboard that emu-run owns while a game runs, so the plugin's QAM
buttons send the very keys Select's hotkey layer sends (mkvdf.py), and emu-run can quit an
emulator the graceful way before signalling it.

Most emulators get the standard keys bound in their config (seed.py). An emulator whose hotkeys
can't be rebound (xemu, melonDS's state keys) has its own key map in systems.json
("keys": action -> "LEFT_CONTROL+1"): mkvdf.py writes it a layout of its own, and the bridge
presses its chords. An action that emulator has no key for is "unsupported".

Key names are Steam Input's (the layouts' key_press bindings); evdev() turns them into codes.

The plugin talks to the bridge over $XDG_RUNTIME_DIR/kettle-emulation/keys.sock: one action
name per connection, answered "ok" or "error <why>".
"""
import os
import socket
import threading
import time

# action -> the key every seeded emulator binds to it (Steam Input names)
STANDARD = {
    "save_state": "F2",
    "load_state": "F4",
    "menu": "F1",
    "fast_forward": "SPACE",
    "slot_down": "F6",
    "slot_up": "F7",
    "rewind": "R",
    "screenshot": "F8",
    "swap_screens": "F9",
    "quit": "ESCAPE",
}
# the same as evdev names, for callers of the first version
ACTIONS = {a: "KEY_" + {"SPACE": "SPACE", "ESCAPE": "ESC"}.get(k, k) for a, k in STANDARD.items()}
# held this long; rewind runs while the key is down
HOLD = {"rewind": 2.0}

# Steam Input key names that aren't evdev's KEY_<name>
_EVDEV = {"ESCAPE": "ESC", "LEFT_CONTROL": "LEFTCTRL", "RIGHT_CONTROL": "RIGHTCTRL",
          "LEFT_SHIFT": "LEFTSHIFT", "RIGHT_SHIFT": "RIGHTSHIFT", "LEFT_ALT": "LEFTALT",
          "RIGHT_ALT": "RIGHTALT", "RETURN": "ENTER"}


def chord(spec):
    """'LEFT_CONTROL+1' -> ['LEFT_CONTROL', '1'] (Steam names, modifiers first)."""
    return [k for k in spec.split("+") if k]


def evdev(name):
    """The evdev KEY_* name of a Steam Input key name."""
    return "KEY_" + _EVDEV.get(name, name)


def keymap(emu=None):
    """action -> chord (Steam names) for this emulator (systems.json entry); an action missing
    from an emulator's own "keys" has no key there."""
    own = (emu or {}).get("keys")
    if own is None:
        return {a: chord(k) for a, k in STANDARD.items()}
    return {a: chord(k) for a, k in own.items() if k}


def runtime_dir():
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
                     "kettle-emulation")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


class Bridge:
    def __init__(self, emu=None):
        import evdev as ev
        from evdev import ecodes as e

        self.e = e
        self.codes = {a: [getattr(e, evdev(k)) for k in keys] for a, keys in keymap(emu).items()}
        everything = {c for cs in self.codes.values() for c in cs} | {
            getattr(e, evdev(k)) for k in STANDARD.values()}
        self.kbd = ev.UInput({e.EV_KEY: sorted(everything)}, name="Kettle Emulation Keys")
        self.lock = threading.Lock()
        self.sock = None

    def can(self, action):
        return action in self.codes

    def tap(self, action):
        """Presses the action's chord; False when this emulator has no key for it."""
        codes = self.codes.get(action)
        if not codes:
            return False
        with self.lock:
            for c in codes:
                self.kbd.write(self.e.EV_KEY, c, 1)
                self.kbd.syn()
            time.sleep(HOLD.get(action, 0.06))
            for c in reversed(codes):
                self.kbd.write(self.e.EV_KEY, c, 0)
                self.kbd.syn()
        return True

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
                if action not in STANDARD:
                    reply = "error unknown action"
                elif self.tap(action):
                    reply = "ok"
                else:
                    reply = "error unsupported"
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
