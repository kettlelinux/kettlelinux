# Waiting for a directory's entries to change (inotify), for the plugin backends that would
# otherwise look again every few seconds: nothing wakes them while nothing changes. Installed
# into each plugin's py_modules/ by the PKGBUILD.
#
#   with Watch(path) as w:   # first: a change made while the state is read still wakes wait()
#       ... read the state ...
#       await w.wait(timeout)
import asyncio
import ctypes
import os

CREATE, DELETE, MOVED_TO, MOVED_FROM, CLOSE_WRITE = 0x100, 0x200, 0x80, 0x40, 0x8
ENTRIES = CREATE | DELETE | MOVED_TO | MOVED_FROM | CLOSE_WRITE
_ONLYDIR, _NONBLOCK, _CLOEXEC = 0x01000000, os.O_NONBLOCK, os.O_CLOEXEC
_libc = ctypes.CDLL(None, use_errno=True)


class Watch:
    """Changes to the entries of directory `path` (OSError if it isn't one). Also wakes when
    the directory itself goes, which a fresh Watch then sees."""

    def __init__(self, path: str, mask: int = ENTRIES):
        self.fd = _libc.inotify_init1(_NONBLOCK | _CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        if _libc.inotify_add_watch(self.fd, os.fsencode(path), mask | _ONLYDIR) < 0:
            e = ctypes.get_errno()
            os.close(self.fd)
            raise OSError(e, os.strerror(e), path)

    async def wait(self, timeout: float | None = None) -> bool:
        """Until something changed (True) or `timeout` s went by (False)."""
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        loop.add_reader(self.fd, lambda: ready.done() or ready.set_result(None))
        try:
            await asyncio.wait_for(ready, timeout)
        except asyncio.TimeoutError:
            return False
        finally:
            loop.remove_reader(self.fd)
        try:
            while os.read(self.fd, 65536):
                pass
        except BlockingIOError:
            pass
        return True

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
