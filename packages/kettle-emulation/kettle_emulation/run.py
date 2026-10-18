"""emu-run <system> <rom>: what every emulation shortcut runs.

Steam only ever knows this command, so changing a system's or a game's emulator in the plugin
never touches the shortcut. emu-run:
- picks the emulator: the game's choice, then the system's, then the first installed one in
  systems.json's list (~/.config/kettle/emulation/choices.json holds the choices);
- refuses a missing ROM (a card that isn't in), a missing required BIOS or a missing emulator by
  writing $XDG_RUNTIME_DIR/kettle-emulation/last-error.json, which the plugin shows as a toast;
- seeds first-run configs (seed.py) and runs the emulator under the keys bridge (keys.py);
- on SIGTERM (Steam's "Exit game"), presses the emulator's quit key first so it saves on the
  way out, and signals it only if it's still running a few seconds later.
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
CORE_DIRS = ("/usr/lib/libretro", os.path.expanduser("~/.config/retroarch/cores"))
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
    for d in CORE_DIRS:
        p = os.path.join(d, f"{core}_libretro.so")
        if os.path.exists(p):
            return p
    return None


def flatpak_installed(app):
    return shutil.which("flatpak") is not None and subprocess.run(
        ["flatpak", "info", app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def installed(emu):
    kind = emu["kind"]
    if kind == "libretro":
        return shutil.which("retroarch") is not None and core_path(emu["core"]) is not None
    if kind == "flatpak":
        return flatpak_installed(emu["flatpak"])
    return shutil.which(emu["exec"][0]) is not None


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
    if first.get("download"):
        raise Refused("emulator", f"{sysdef['name']} needs an extra core: download "
                      f"{first['name']} in Emulation > Extra cores")
    if first["kind"] == "flatpak":
        raise Refused("emulator", f"{sysdef['name']} needs {first['name']}: install "
                      f"{first['name']} from Game Stores > Flathub")
    raise Refused("emulator", f"No emulator for {sysdef['name']} is installed")


def command(system, emu, rom):
    if emu["kind"] == "libretro":
        return ["retroarch", "-f", "--appendconfig", seed.append_configs(system),
                "-L", core_path(emu["core"]), rom]
    return [rom if a == "{rom}" else a for a in emu["exec"]]


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
    Databases, fetched with its core in Extra cores)."""
    if emu["kind"] != "libretro":
        return
    missing = [d for d in sysdef.get("system_dirs", ())
               if not os.path.isdir(os.path.join(seed.EMU, "bios", d))]
    if missing:
        raise Refused("bios", f"{emu['name']} needs its system files ({', '.join(missing)} in "
                      "Emulation/bios): download it again in Emulation > Extra cores")


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
    return command(system, emu, rom), seed.environment(eid, emu), eid


def start_bridge():
    try:
        bridge = keys.Bridge()
        bridge.serve()
        return bridge
    except Exception as err:  # no uinput: the hotkey layer still works, the QAM buttons don't
        print(f"emu-run: no keys bridge: {err}", file=sys.stderr)
        return None


def wait(child, bridge, stopping):
    """The emulator's exit code. Once `stopping` holds a signal: Esc (the bridge's quit key)
    and QUIT_GRACE seconds to save and quit, then that signal, then SIGKILL after another
    QUIT_GRACE. The signal handlers only fill `stopping`: waiting or pressing keys inside a
    handler would run inside child.wait(), whose lock makes poll() report the child as running."""
    while not stopping:
        try:
            return child.wait(timeout=POLL)
        except subprocess.TimeoutExpired:
            pass
    if bridge:
        try:
            bridge.tap("quit")
            return child.wait(timeout=QUIT_GRACE)
        except (OSError, subprocess.TimeoutExpired):
            pass
    child.send_signal(stopping[0])
    try:
        return child.wait(timeout=QUIT_GRACE)
    except subprocess.TimeoutExpired:
        child.kill()
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
            argv, env, eid = prepare(system, rom)
            if stopping:  # Steam gave up before the emulator started
                return 128 + stopping[0]
            bridge = start_bridge()
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
