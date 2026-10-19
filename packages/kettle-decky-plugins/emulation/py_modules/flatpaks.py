# The emulators: Flathub's own Flatpaks of them (systems.json's "flatpaks": RetroArch, whose cores
# come from libretro's buildbot, cores.py, and the standalone emulators), installed for the user
# (flatpak --user, as Game Stores' Flathub tab does). Kettle builds none of them: what keeps
# their controls the same is the configs emu-run writes before each start.
#
# Installs, updates and removals run one at a time as a user systemd unit (kettle-emulation-job),
# so they carry on when the plugin restarts; their output goes to the job's log, where progress()
# reads flatpak's progress lines. After an install the app gets systems.json's "permissions"
# (flatpak override --user: the Emulation folder and the cards, which a sandboxed emulator
# otherwise can't open).
import os
import re
import shlex
import subprocess
import time

FLATPAK = "/usr/bin/flatpak"
FLATHUB = "flathub"
FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"
UNIT = "kettle-emulation-job"
EXIT_MARK = "KETTLE-EMULATION-EXIT"
UPDATES_FOR = 600  # s an update check is kept (it reads the network)
_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def env(home: str) -> dict:
    """The session's environment (the plugin's backend runs without it), without Decky's PYTHONPATH."""
    e = dict(os.environ)
    e.pop("PYTHONPATH", None)
    uid = os.getuid()
    e.update(HOME=home, XDG_RUNTIME_DIR=f"/run/user/{uid}", DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus",
             LC_ALL="C.UTF-8")
    return e


def _run(home: str, *cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env(home), capture_output=True, text=True, timeout=timeout)


def installed(home: str) -> dict | None:
    """id -> {version, origin, installation} of the installed apps (the user's wins when an app is
    in both installations: one installed for all users can't be removed from here). None when
    flatpak couldn't list them: that isn't "nothing installed"."""
    try:
        r = _run(home, FLATPAK, "list", "--app", "--columns=application,version,origin,installation")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = {}
    for line in r.stdout.splitlines():
        f = line.split("\t")
        if len(f) == 4 and (f[0] not in out or f[3] == "user"):
            out[f[0]] = {"version": f[1], "origin": f[2], "installation": f[3]}
    return out


_updates = {"at": 0.0, "apps": set()}


def updates(home: str) -> set:
    """The user's apps with an update out (kept UPDATES_FOR seconds)."""
    if time.time() - _updates["at"] > UPDATES_FOR:
        try:
            r = _run(home, FLATPAK, "remote-ls", "--user", "--updates", "--app", "--columns=application")
        except (OSError, subprocess.TimeoutExpired):
            return _updates["apps"]
        if r.returncode == 0:
            _updates.update(at=time.time(), apps=set(r.stdout.split()))
    return _updates["apps"]


def forget_updates():
    """After an install, update or removal: the next updates() asks again, and until then no app
    counts as having one (an update just done isn't out any more)."""
    _updates.update(at=0.0, apps=set())


_SIZE = re.compile(r"^\s*(Download|Installed):\s*([\d.]+)\s*([kMGT]?B|bytes)", re.M)
_UNITS = {"bytes": 1, "B": 1, "kB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}
_info: dict = {}


def info(home: str, app: str) -> dict:
    """{download, installed} sizes in bytes of the app on Flathub (0 when unknown; network, kept a day)."""
    hit = _info.get(app)
    if hit and time.time() - hit["at"] < 86400:
        return hit["sizes"]
    sizes = {"download": 0, "installed": 0}
    try:
        r = _run(home, FLATPAK, "remote-info", "--user", FLATHUB, app)
    except (OSError, subprocess.TimeoutExpired):
        return sizes
    if r.returncode == 0:
        for what, n, unit in _SIZE.findall(r.stdout):
            sizes[what.lower()] = int(float(n) * _UNITS[unit])
        _info[app] = {"at": time.time(), "sizes": sizes}
    return sizes


def override_args(permissions: list[str]) -> list[str]:
    """systems.json's permissions as `flatpak override` options: each is an option itself
    ("--filesystem=~/Emulation") or a bare filesystem ("~/Emulation", "/run/media")."""
    out = []
    for p in permissions:
        if not isinstance(p, str) or not p or "\n" in p or "\0" in p:
            raise ValueError(f"not a permission: {p!r}")
        out.append(p if p.startswith("--") else f"--filesystem={p}")
    return out


def commands(kind: str, apps: list[str], perms: dict) -> list[list[str]]:
    """The job's commands, run one after the other. In English and not --noninteractive (that
    prints no progress): progress() reads flatpak's lines; -y answers its questions."""
    for a in apps:
        if not _ID.match(a):
            raise ValueError(f"not a Flatpak app: {a!r}")
    if not apps:
        raise ValueError("nothing to do")
    if kind == "install":
        cmds = [[FLATPAK, "remote-add", "--user", "--if-not-exists", FLATHUB, FLATHUB_REPO],
                [FLATPAK, "install", "--user", "-y", FLATHUB, *apps]]
        cmds += [[FLATPAK, "override", "--user", *override_args(perms[a]), a] for a in apps if perms.get(a)]
        return cmds
    if kind == "update":
        return [[FLATPAK, "update", "--user", "-y", *apps]]
    if kind == "remove":
        return [[FLATPAK, "uninstall", "--user", "-y", *apps]]
    raise ValueError(f"not a job: {kind}")


def start(home: str, log: str, cmds: list[list[str]]):
    """Runs the commands as the job unit; their output and then EXIT_MARK <code> go to `log`."""
    with open(log, "w"):
        pass
    e = env(home)
    subprocess.run(["systemctl", "--user", "reset-failed", UNIT], env=e, capture_output=True)
    script = f'{{ {" && ".join(shlex.join(c) for c in cmds)}; }} >>"$0" 2>&1; echo "{EXIT_MARK} $?" >>"$0"'
    # a transient unit gets the user manager's environment, not this one: flatpak in English
    # there too, or progress() and error_text() can't read it
    r = subprocess.run(["systemd-run", "--user", "--unit", UNIT, "--collect", "--quiet", "-p", "Nice=10",
                        "--setenv=LC_ALL=C.UTF-8",
                        "-p", "IOSchedulingClass=best-effort", "-p", "IOSchedulingPriority=7",
                        "--", "bash", "-c", script, log], env=e, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"couldn't start it: {r.stderr.strip()}")


def running(home: str) -> bool:
    r = subprocess.run(["systemctl", "--user", "is-active", UNIT], env=env(home), capture_output=True, text=True)
    return r.stdout.strip() in ("active", "activating", "deactivating")


def stop(home: str):
    subprocess.run(["systemctl", "--user", "stop", UNIT], env=env(home), capture_output=True)


def tail(log: str, n: int = 16384) -> str:
    try:
        with open(log, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def progress(log: str) -> dict:
    """flatpak's progress, which it prints a line at a time when not on a terminal: "Installing
    2/3… ▌ 45%  1.2 MB/s  00:12" (no "2/3" for a single step; GLib puts a no-break space before
    the unit); the steps count as equal parts."""
    m = re.findall(r"^(?:Installing|Updating|Uninstalling)(?: (\d+)/(\d+))?….*?(\d+)%(?:\s+([\d.]+)\s(bytes|[kMG]B)/s)?(?:\s+([\d:]+))?",
                   log, re.M)
    if not m:
        return {"percent": 0.0, "eta": "", "speed": 0.0}
    i, n, pct, speed, unit, eta = m[-1]
    i, n = int(i or 1), int(n or 1)
    mib = float(speed) * {"bytes": 1, "kB": 1e3, "MB": 1e6, "GB": 1e9}[unit] / 2**20 if speed else 0.0
    return {"percent": round((i - 1 + int(pct) / 100) / n * 100, 1), "eta": eta, "speed": mib}


def exit_code(log: str) -> int | None:
    m = re.findall(rf"{EXIT_MARK} (\d+)", log)
    return int(m[-1]) if m else None


def error_text(log: str) -> str:
    lines = [l for l in log.splitlines() if l.strip() and EXIT_MARK not in l]
    errors = [l for l in lines if "error:" in l.lower()]
    return (errors or lines or ["no output"])[-1][-300:]
