# The Buttons tab: what the rear buttons do, on the devices whose controller lets them copy another
# button. The KONKR Pocket FIT Elite's MCU reports no rear button of its own; it can make each one
# press a regular button instead, stored in the MCU (it survives power cycles). The
# driver (kernel 22-sm8750/0069) has key_lc_back and key_rc_back on its serial device: "<func>
# <target>", func 1 = a gamepad button, target its code (1-16 below, checked on a unit), "0 0"
# nothing, "255 255" as it left the factory (nothing too). They're root's, and Decky runs this as
# the user without its groups, so it reads them and sets them through kettle-rear-buttons (pkexec,
# org.kettle.rear-buttons: no password, device/pocketfitelite).
import glob
import os
import subprocess

import decky

DRIVER = "/sys/bus/serial/drivers/konkr_sysbtn"
HELPER = "/usr/lib/kettle/kettle-rear-buttons"
SIDES = {"left": "key_lc_back", "right": "key_rc_back"}
# the MCU's gamepad button codes (JoystickFunctionType); 17-24, the stick directions, move nothing
TARGETS = {
    "a": 1, "b": 2, "x": 3, "y": 4, "view": 5, "menu": 6,
    "up": 7, "down": 8, "left": 9, "right": 10,
    "lb": 11, "rb": 12, "l3": 13, "r3": 14, "lt": 15, "rt": 16,
}


def _device() -> str | None:
    for d in glob.glob(os.path.join(DRIVER, "*")):
        if os.path.exists(os.path.join(d, SIDES["left"])):
            return d
    return None


def available() -> bool:
    return _device() is not None


def _read(d: str, attr: str) -> str:
    """The button's setting: a TARGETS key, or "none"."""
    for tries in range(3):
        try:
            # each read asks the MCU over its UART; while buttons are being pressed it sometimes
            # doesn't answer in time (ETIMEDOUT)
            with open(os.path.join(d, attr)) as f:
                func, target = (int(v) for v in f.read().split())
            break
        except TimeoutError:
            if tries == 2:
                raise
    if func == 1:
        for name, code in TARGETS.items():
            if code == target:
                return name
    return "none"


def get() -> dict:
    d = _device()
    if d is None:
        return {"available": False}
    try:
        return {"available": True, "error": None, **{side: _read(d, attr) for side, attr in SIDES.items()}}
    except (OSError, ValueError) as e:
        decky.logger.error("buttons: reading the rear buttons: %s", e)
        return {"available": True, "error": f"Can't read the rear buttons: {e}", "left": "none", "right": "none"}


def set_button(side: str, target: str) -> dict:
    if _device() is None or side not in SIDES or (target != "none" and target not in TARGETS):
        return get()
    code = str(TARGETS[target]) if target != "none" else "none"
    try:
        r = subprocess.run(["pkexec", HELPER, side, code], capture_output=True, text=True, timeout=30)
        failed = r.returncode != 0 and ((r.stderr.strip().splitlines() or ["kettle-rear-buttons failed"])[-1])
    except (OSError, subprocess.TimeoutExpired) as e:
        failed = str(e)
    if failed:
        decky.logger.error("buttons: setting the %s rear button: %s", side, failed)
        return {**get(), "error": f"Can't set the {side} rear button: {failed.removeprefix('kettle-rear-buttons: ')}"}
    decky.logger.info("buttons: %s rear button -> %s", side, target)
    return get()
