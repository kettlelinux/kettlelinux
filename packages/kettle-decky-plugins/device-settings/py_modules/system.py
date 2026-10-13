# The System tab: what the device starts up in, Game Mode or the desktop (steamos-manager's
# default login mode, through steamosctl on the user's session bus); the SSH server, turned on and
# off (Game Mode has no password prompt: kettle-ssh through pkexec, org.kettle.ssh,
# 50-kettle-ssh.rules; enabling it at every start-up stays with the desktop's Kettle Welcome); and
# resetting the device (kettle-reset, through pkexec: 50-kettle-reset.rules lets Decky's plugin
# backends do that): every setting back to its default, or everything erased. Erasing is refused
# while /home holds the Kettle Installer's backup of the internal storage; the desktop's Reset
# Kettle says what that means first. These were the Welcome window's up to 1.12.0-38.
#
# And the bootloader, on devices with a ROCKNIX ABL build: kettle-abl-update (package rocknix-abl)
# through pkexec, as org.kettle.abl-update (50-kettle-abl-update.rules lets Decky's plugin
# backends run it), --check first, then --yes: updating a ROCKNIX ABL it recognises to the image's
# release, installing it over the stock bootloader (--install, which saves the stock one first),
# or putting the saved stock one back (--restore-stock).
#
# Turning SSH on, erasing everything and writing the bootloader wait, as root, for the device's
# Volume Up and Volume Down to be held together (/usr/lib/kettle/confirm-keys): no password is
# asked, and a dialog could be clicked by any program running as the user. Plugin.main shows
# what's waiting (/run/kettle/confirm.json) as a notification.
import json
import os
import pwd
import re
import subprocess
import threading

import decky

MODES = ("game", "desktop")
RESET = "/usr/bin/kettle-reset"
UFS_BACKUP = "/home/.kettle/ufs-backup"  # the Kettle Installer's (kettle-backup-ufs)
RESETS = ("settings", "everything")
ABL_UPDATE = "/usr/bin/kettle-abl-update"  # package rocknix-abl
SSH = "/usr/lib/kettle/kettle-ssh"
CONFIRM = "/run/kettle/confirm.json"  # confirm-keys: what the volume keys are being waited for


def _session_env() -> dict:
    # Decky starts this backend as the user but without the session's environment
    run = f"/run/user/{os.getuid()}"
    return {**os.environ, "HOME": decky.DECKY_USER_HOME, "XDG_RUNTIME_DIR": run,
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={run}/bus"}


def _steamosctl(*args: str) -> str:
    r = subprocess.run(["steamosctl", *args], env=_session_env(), capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"steamosctl {args[0]} failed")
    return r.stdout.strip()


def boot_mode() -> str | None:
    """What the device starts up in: "game", "desktop", or None if steamos-manager can't say."""
    try:
        out = _steamosctl("get-default-login-mode")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
        decky.logger.warning("reading the start-up mode: %s", e)
        return None
    return next((m for m in MODES if m in out.lower()), None)


def set_boot_mode(mode: str):
    if mode not in MODES:
        raise ValueError(f"unknown start-up mode {mode!r}")
    _steamosctl("set-default-login-mode", mode)
    decky.logger.info("start-up mode set to %s", mode)


def _addresses() -> list[str]:
    """This device's IPv4 addresses, for "ssh user@address"."""
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    # "2: wlan0    inet 192.168.1.5/24 ...", leaving out container networks (Lepton's podman)
    return [a for i, a in re.findall(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)/", out, re.M)
            if not i.startswith(("podman", "docker", "br-", "veth", "virbr", "cni"))]


def _sshd(*args: str) -> int:
    return subprocess.run(["systemctl", *args, "sshd.service"], capture_output=True, timeout=30).returncode


def ssh_status() -> dict:
    """The SSH server: running now, and enabled at start-up (set from the desktop)."""
    return {"active": _sshd("is-active", "-q") == 0, "enabled": _sshd("is-enabled", "-q") == 0,
            "user": pwd.getpwuid(os.getuid()).pw_name, "addresses": _addresses()}


def set_ssh(on: bool):
    # on: up to 30 s for the volume keys
    r = subprocess.run(["pkexec", SSH, "on" if on else "off"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        msg = (r.stderr.strip().splitlines() or ["kettle-ssh failed"])[-1]
        raise RuntimeError(msg.removeprefix("kettle-ssh: "))
    decky.logger.info("SSH server %s", "started" if on else "stopped")


def reset_status() -> dict:
    """What's set to be reset on the next start ("none", "settings", "everything"), and
    whether erasing everything would erase a backup of the internal storage."""
    out = subprocess.run([RESET, "status"], capture_output=True, text=True, timeout=15)
    try:
        backup = bool(os.listdir(UFS_BACKUP))
    except OSError:
        backup = os.path.isdir(UFS_BACKUP)  # there, but not readable here: assume it holds one
    return {"pending": out.stdout.split(":", 1)[0].strip() or "none", "ufs_backup": backup}


def reset(what: str):
    """Resets on the next start, and restarts the device now."""
    if what not in RESETS:
        raise ValueError(f"unknown reset {what!r}")
    # kettle-reset restarts the device itself: as root, which logind lets reboot (Decky's backend,
    # outside any session, would need a password)
    decky.logger.info("reset %s on the next start; restarting", what)
    r = subprocess.run(["pkexec", RESET, what], capture_output=True, text=True, timeout=90)  # 30 s of it the keys
    if r.returncode != 0:
        msg = ((r.stderr or r.stdout).strip().splitlines() or [f"kettle-reset failed ({r.returncode})"])[-1]
        raise RuntimeError(msg.removeprefix("kettle-reset: "))


def _abl(*args: str, timeout: int) -> dict:
    """kettle-abl-update --porcelain: {"slots": {"a": version | "test-signed" | "other", ...},
    "image": version, "backup": a saved stock bootloader to put back, "result": code}; raises with
    its message on an error."""
    r = subprocess.run(["pkexec", ABL_UPDATE, "--porcelain", *args], capture_output=True, text=True,
                       timeout=timeout)
    out = {"slots": {}, "image": None, "backup": False, "result": None}
    for line in r.stdout.splitlines():
        w = line.split()
        if len(w) == 3 and w[0] == "slot":
            out["slots"][w[1]] = w[2]
        elif len(w) == 2 and w[0] in ("image", "result"):
            out[w[0]] = w[1]
        elif len(w) == 2 and w[0] == "backup":
            out["backup"] = w[1] == "yes"
    if r.returncode != 0 or out["result"] is None:
        msg = (r.stderr.strip().splitlines() or ["kettle-abl-update failed"])[-1]
        raise RuntimeError(msg.removeprefix("kettle-abl-update: "))
    return out


# the bootloader being written, and the last status: a check can't run beside it
# (kettle-abl-update's lock), and the System tab, reopened meanwhile, shows it still going
_abl_write = {"busy": None, "last": None}
_abl_lock = threading.Lock()  # each call runs in its own thread (asyncio.to_thread)
# what kettle-abl-update --check can't act on: no ROCKNIX build for this SoC, or no abl partitions
# Linux can see (the RP5's)
ABL_NONE = ("no-build", "no-partitions")
ABL_MODES = {"update": (), "install": ("--install",), "restore": ("--restore-stock",)}


def abl_status() -> dict:
    """What the bootloader is, and what kettle-abl-update would do. available: it can install or
    update one here (the System tab shows its section only then); installed: some abl slot holds
    a ROCKNIX ABL; busy: what's being done ("update", "install", "restore"), if anything."""
    if _abl_write["busy"]:
        return {**(_abl_write["last"] or {"slots": {}, "image": None, "backup": False, "result": None,
                                          "check": None, "installed": True}),
                "available": True, "busy": _abl_write["busy"]}
    if not os.access(ABL_UPDATE, os.X_OK):
        return {"available": False, "installed": False}
    try:
        s = _abl("--check", timeout=60)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
        decky.logger.warning("kettle-abl-update --check: %s", e)
        return {"available": False, "installed": False}
    # check: what can be done now; result: the same, or (abl_update) what was just done
    s = {**s, "check": s["result"], "available": s["result"] not in ABL_NONE,
         "installed": any(v != "other" for v in s["slots"].values())}
    _abl_write["last"] = s
    return s


def abl_update(mode: str = "update") -> dict:
    """Writes the bootloader: "update" a recognised, older ROCKNIX ABL, "install" the ROCKNIX ABL
    over a stock one (saving it first), or "restore" the saved stock one. The result as
    abl_status's, after a fresh check."""
    if mode not in ABL_MODES:
        raise ValueError(f"unknown mode {mode!r}")
    with _abl_lock:
        if _abl_write["busy"]:
            raise RuntimeError("the bootloader is already being written")
        _abl_write["busy"] = mode
    decky.logger.info("kettle-abl-update: %s", mode)
    try:
        r = _abl(*ABL_MODES[mode], "--yes", timeout=300)
    finally:
        _abl_write["busy"] = None
    decky.logger.info("kettle-abl-update %s: %s", mode, r["result"])
    # what's there now (and whether a stock backup is), with what was done as the result
    s = abl_status()
    if not s["available"]:  # the check failed: what the write saw
        s = {**r, "check": None, "available": True,
             "installed": any(v != "other" for v in r["slots"].values())}
    return {**s, "result": r["result"]}


def confirm_pending() -> dict | None:
    """What the volume keys are being waited for ({"what", "until"}), if anything."""
    try:
        with open(CONFIRM) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
