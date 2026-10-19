"""emu-run <system> <rom>: what every emulation shortcut runs.

Steam only ever knows this command, so changing a system's or a game's emulator in the plugin
never touches the shortcut. The emulators are Flathub's, installed per user from the plugin's
Emulators tab (systems.json "flatpaks"); a libretro core runs in Flathub's RetroArch, from its
cores folder (the plugin downloads them from libretro's buildbot). emu-run:
- picks the emulator: the game's choice, then the system's, then the first installed one in
  systems.json's list (~/.config/kettle/emulation/choices.json holds the choices);
- refuses a missing ROM (a card that isn't in), a missing required BIOS, a setup step the
  emulator still needs ("needs") or a missing emulator by writing
  $XDG_RUNTIME_DIR/kettle-emulation/last-error.json, which the plugin shows as a toast;
- gives the Flatpak its folders (systems.json "permissions", through `flatpak override --user`,
  also for an app installed outside the plugin), seeds first-run configs (seed.py) and runs the
  emulator under the keys bridge (keys.py), with the emulator's own key map where it has one;
- on SIGTERM (Steam's "Exit game"), presses the emulator's quit key first so it saves on the
  way out, and signals it (the app inside the sandbox, not just `flatpak run`) only if it's
  still running a few seconds later.
Any other error before the emulator starts is refused the same way ("internal"), so a game
never just closes without a word.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback

from . import keys, seed, systems

CHOICES = os.path.expanduser("~/.config/kettle/emulation/choices.json")
FLATPAK = "flatpak"
QUIT_GRACE = 5  # seconds the emulator gets to quit on Esc before it's signalled
POLL = 0.1  # how often the wait loop looks at the stop flag


class Refused(Exception):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def core_path(core):
    p = os.path.join(seed.RA_DIR, "cores", f"{core}_libretro.so")
    return p if os.path.exists(p) else None


_installed = {}


def flatpak_installed(app):
    if app not in _installed:
        _installed[app] = shutil.which(FLATPAK) is not None and subprocess.run(
            [FLATPAK, "info", app], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL).returncode == 0
    return _installed[app]


def installed(emu):
    if emu["kind"] == "libretro":
        return flatpak_installed(systems.RETROARCH) and core_path(emu["core"]) is not None
    return flatpak_installed(emu["flatpak"])


def choose(db, system, rom):
    """(emulator id, emulator) for this game; raises Refused when none can run it."""
    sysdef = db["systems"].get(system)
    if sysdef is None:
        raise Refused("system", f"Unknown system '{system}'")
    choices = read_json(CHOICES, {})
    wanted = [choices.get("games", {}).get(rom), choices.get("systems", {}).get(system)]
    for eid in [w for w in wanted if w in sysdef["emulators"]] + sysdef["emulators"]:
        emu = db["emulators"][eid]
        if installed(emu):
            return eid, emu
    first = db["emulators"][sysdef["emulators"][0]]
    if first["kind"] == "libretro":
        what = (f"the {first['name']} core" if flatpak_installed(systems.RETROARCH)
                else f"RetroArch and its {first['name']} core")
    else:
        what = first["name"]
    raise Refused("emulator", f"{sysdef['name']} needs {what}: install it in Emulation > Emulators")


def command(system, emu, rom):
    # --die-with-parent: the sandbox goes with flatpak run, whatever ends it
    run = [FLATPAK, "run", "--die-with-parent", systems.flatpak_of(emu)]
    if emu["kind"] == "libretro":
        return run + ["-f", "--appendconfig", seed.append_configs(system),
                      "-L", core_path(emu["core"]), rom]
    return run + [rom if a == "{rom}" else a for a in emu["exec"]]


def met(check):
    """A "needs" check: a path under $HOME that exists, or a glob there matching anything (an
    emulator's installed firmware: registered/*.nca)."""
    path = os.path.join(seed.HOME, check)
    if any(c in check for c in "*?["):
        import glob
        return bool(glob.glob(path))
    return os.path.exists(path)


def check_needs(emu):
    """The setup an emulator needs that emu-run can see (systems.json "needs" with a "check":
    paths under $HOME, any one of which will do)."""
    for need in emu.get("needs", ()):
        if not isinstance(need, dict) or not need.get("check"):
            continue
        checks = need["check"] if isinstance(need["check"], list) else [need["check"]]
        if not any(met(c) for c in checks):
            raise Refused("needs", f"{emu['name']}: {need['text']}")


def check_switch_keys(system, emu, rom):
    """A Switch game made for a newer system version than the user's prod.keys: said here,
    where the emulator would start and show nothing (switch.py)."""
    if system != "switch" or emu["kind"] != "flatpak":
        return
    paths = [c for need in emu.get("needs", ()) if isinstance(need, dict)
             for c in (need["check"] if isinstance(need.get("check"), list) else [need.get("check")])
             if c and c.endswith("prod.keys")]
    # the emulator's own copy first (the one it reads), then Emulation/bios/switch's
    paths.sort(key=lambda c: c.startswith("Emulation/"))
    found = next((os.path.join(seed.HOME, c) for c in paths
                  if os.path.isfile(os.path.join(seed.HOME, c))), None)
    if found and os.path.isfile(rom):
        from . import switch
        message = switch.too_new(rom, found)
        if message:
            raise Refused("needs", message)


def check_rom(rom):
    if os.path.exists(rom):
        return
    if rom.startswith("/run/media/"):
        mount = "/".join(rom.split("/")[:5])
        if not os.path.ismount(mount):
            raise Refused("storage", "This game is on a card that isn't in")
    raise Refused("rom", f"The game file is gone: {os.path.basename(rom)}")


def check_bios(system):
    try:
        from . import bios
    except ImportError:
        return
    # a recognised file under another name, in a subfolder or on a card: the emulators only read
    # ~/Emulation/bios/<the expected name>, so it's copied there first
    if hasattr(bios, "install_found"):
        try:
            for name in bios.install_found(system):
                print(f"emu-run: installed BIOS {name}", file=sys.stderr)
        except OSError as err:
            print(f"emu-run: couldn't install BIOS: {err}", file=sys.stderr)
    missing = bios.missing_required(system)
    if missing:
        raise Refused("bios", "Missing BIOS: " + ", ".join(missing) +
                      " (put it in Emulation/bios; Emulation > BIOS shows what's needed)")


def check_system_dirs(sysdef, emu):
    """The folders a libretro core needs in RetroArch's system folder (blueMSX's Machines and
    Databases, fetched with its core in Emulation > Emulators)."""
    if emu["kind"] != "libretro":
        return
    missing = [d for d in sysdef.get("system_dirs", ())
               if not os.path.isdir(os.path.join(seed.EMU, "bios", d))]
    if missing:
        raise Refused("bios", f"{emu['name']} needs its system files ({', '.join(missing)} in "
                      "Emulation/bios): install its core again in Emulation > Emulators")


def report(system, rom, err):
    print(f"emu-run: {err}", file=sys.stderr)
    try:
        write_json(os.path.join(keys.runtime_dir(), "last-error.json"),
                   {"system": system, "rom": rom, "reason": err.reason, "message": str(err),
                    "time": time.time()})
    except OSError as e:
        print(f"emu-run: couldn't write the error: {e}", file=sys.stderr)


def prepare(system, rom):
    """(argv, env, emulator id) for this game; raises Refused when it can't run."""
    db = systems.load()
    check_rom(rom)
    eid, emu = choose(db, system, rom)
    check_system_dirs(db["systems"][system], emu)
    check_bios(system)
    seed.seed(eid)
    seed.permissions(systems.flatpak_of(emu))
    check_needs(emu)
    check_switch_keys(system, emu, rom)
    return command(system, emu, rom), seed.environment(eid, emu), eid, emu


def start_bridge(emu=None):
    try:
        bridge = keys.Bridge(emu)
        bridge.serve()
        return bridge
    except Exception as err:  # no uinput: the hotkey layer still works, the QAM buttons don't
        print(f"emu-run: no keys bridge: {err}", file=sys.stderr)
        return None


def descendants(pid):
    """pid's processes below it, deepest first: the app flatpak run's sandbox runs."""
    kids = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                ppid = int(f.read().rpartition(")")[2].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(d))
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        for c in kids.get(p, ()):
            out.append(c)
            todo.append(c)
    return out[::-1]


# flatpak's own processes around the app: signalling the outer bwrap ends the sandbox at once
# (its children die by PDEATHSIG), so they're signalled last
SANDBOX = {"bwrap", "xdg-dbus-proxy", "flatpak", "flatpak-session"}


def _comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def inside(child):
    """The app's processes in flatpak run's sandbox (not bwrap or the D-Bus proxy), deepest
    first."""
    return [p for p in descendants(child.pid) if _comm(p) not in SANDBOX]


def _kill(pids, sig):
    for p in pids:
        try:
            os.kill(p, sig)
        except OSError:
            pass


def signal_tree(child, sig):
    """The signal to the app inside the sandbox, so its own handler saves; to flatpak run
    itself only when nothing is in there. True when the app got it."""
    pids = inside(child)
    _kill(pids or [child.pid], sig)
    return bool(pids)


def wait(child, bridge, stopping):
    """The emulator's exit code. Once `stopping` holds a signal: the emulator's quit key (the
    bridge's) and QUIT_GRACE seconds to save and quit; then that signal to the app inside the
    sandbox and another QUIT_GRACE; then to flatpak run (which ends the sandbox); then SIGKILL.
    The signal handlers only fill `stopping`: waiting or pressing keys inside a handler would run
    inside child.wait(), whose lock makes poll() report the child as running."""
    while not stopping:
        try:
            return child.wait(timeout=POLL)
        except subprocess.TimeoutExpired:
            pass
    if bridge:
        try:
            if bridge.tap("quit"):
                return child.wait(timeout=QUIT_GRACE)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for step in (lambda: signal_tree(child, stopping[0]),
                 lambda: _kill([child.pid], stopping[0])):
        step()
        try:
            return child.wait(timeout=QUIT_GRACE)
        except subprocess.TimeoutExpired:
            pass
    _kill(descendants(child.pid) + [child.pid], signal.SIGKILL)
    return child.wait()


def run(system, rom):
    stopping = []  # the first SIGTERM/SIGINT; repeats are ignored while the quit runs

    def on_signal(signum, _frame):
        if not stopping:
            stopping.append(signum)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    # running.json and keys.sock are removed on the way out only once this run owns them
    state = bridge = None
    try:
        try:
            argv, env, eid, emu = prepare(system, rom)
            if stopping:  # Steam gave up before the emulator started
                return 128 + stopping[0]
            bridge = start_bridge(emu)
            print("emu-run: " + " ".join(argv), file=sys.stderr, flush=True)
            child = subprocess.Popen(argv, env=env)
        except Refused as err:
            report(system, rom, err)
            return 1
        except Exception as err:
            traceback.print_exc()
            report(system, rom, Refused("internal", f"The game couldn't start: {err}"))
            return 1
        path = os.path.join(keys.runtime_dir(), "running.json")
        try:
            write_json(path, {"system": system, "rom": rom, "emulator": eid, "pid": child.pid,
                              "bridge": bridge is not None,
                              "appid": os.environ.get("SteamGameId")})
            state = path
        except OSError as err:  # the plugin won't see the game, but it still runs
            print(f"emu-run: couldn't write {path}: {err}", file=sys.stderr)
        return wait(child, bridge, stopping)
    finally:
        if state:
            try:
                os.unlink(state)
            except OSError:
                pass
        if bridge:
            bridge.close()


def main(argv=sys.argv[1:]):
    if len(argv) != 2:
        print("usage: emu-run <system> <rom | x:rom hex>", file=sys.stderr)
        return 2
    rom = argv[1]
    # the plugin's shortcuts pass the path hex: Steam runs launch options through a shell, so a
    # file name never goes into them as text
    if rom.startswith("x:"):
        try:
            rom = os.fsdecode(bytes.fromhex(rom[2:]))
        except ValueError:
            print("emu-run: bad ROM path", file=sys.stderr)
            return 2
    return run(argv[0], os.path.abspath(rom))
