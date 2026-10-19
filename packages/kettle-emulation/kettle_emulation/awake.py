"""Keeping the device awake while games are copied onto it (the upload server, the importer):
a systemd-inhibit sleep/idle block held for as long as there's a copy, released after it.
50-kettle-emulation-share.rules lets the plugin's backends take it without a password."""
import os
import subprocess
import threading


class Awake:
    """hold() for each copy that starts, release() when it ends; the inhibitor is held while
    any copy runs. Without systemd-inhibit (or polkit saying no) copies just go on unheld."""

    def __init__(self, why, linger=0):
        self.why = why
        self.linger = linger  # seconds held after the last copy (an upload's next file follows)
        self.count = 0
        self.proc = None
        self.timer = None
        self.lock = threading.Lock()

    def hold(self):
        with self.lock:
            self.count += 1
            if self.timer:
                self.timer.cancel()
                self.timer = None
            if self.proc is None or self.proc.poll() is not None:
                try:
                    self.proc = subprocess.Popen(
                        ["systemd-inhibit", "--what=sleep:idle", "--who=Kettle Emulation",
                         f"--why={self.why}", "--mode=block",
                         # ends with this process, however it ends: never a block left behind
                         "tail", f"--pid={os.getpid()}", "-f", "/dev/null"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
                except OSError:
                    self.proc = None

    def release(self):
        with self.lock:
            self.count = max(0, self.count - 1)
            if self.count or self.proc is None:
                return
            if self.linger:
                if self.timer is None:
                    self.timer = threading.Timer(self.linger, self._end)
                    self.timer.daemon = True
                    self.timer.start()
                return
        self._end()

    def _end(self):
        with self.lock:
            self.timer = None
            if self.count == 0 and self.proc is not None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                self.proc = None

    def __enter__(self):
        self.hold()
        return self

    def __exit__(self, *exc):
        self.release()
