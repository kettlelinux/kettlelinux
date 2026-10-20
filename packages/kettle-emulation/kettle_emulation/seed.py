"""First-run configs and the settings Kettle keeps the same in every emulator.

The emulators are Flathub's, so their configs live in ~/.var/app/<app id>/{config,data}/. Two
kinds of settings:
- **kept**: hotkeys (the keys mkvdf.py's layer sends, or the emulator's own where systems.json
  gives it "keys"), folders under ~/Emulation, fullscreen, no confirm-on-quit, no updaters.
  Rewritten before every launch, so the standard controls can't drift. RetroArch reads them from
  an append-config; the others get them set in their own files.
- **seeded**: everything else (video, per-device resolution, pad layouts). Written once, when the
  file is missing; after that it's the user's.

seeded.json records each emulator's seed version. The Flatpak permissions are applied before every
launch (an app installed outside the plugin gets them too, and so does one whose overrides were
reset).
"""
import configparser
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HOME = os.path.expanduser("~")
EMU = os.path.join(HOME, "Emulation")
CONF = os.path.join(HOME, ".config/kettle/emulation")
SEEDED = os.path.join(CONF, "seeded.json")
APPS = os.path.join(HOME, ".var/app")
RA_DIR = os.path.join(APPS, "org.libretro.RetroArch/config/retroarch")
FOLDERS = ("roms", "bios", "saves", "states", "screenshots", "backups", "inbox")


def app_dir(app, kind="config"):
    """A Flatpak app's own XDG folder: ~/.var/app/<app>/<config|data|cache>."""
    return os.path.join(APPS, app, kind)


def device():
    try:
        import kettle_device
        return kettle_device.conf
    except ImportError:
        return {}


def tier():
    """high on the 8 Gen 2/8 Elite devices, mid otherwise (device.conf EMU_TIER)."""
    return device().get("EMU_TIER", "mid")


def confirm_south():
    """Menus confirm with the button labelled A: south on Xbox-labelled pads, east on Nintendo's."""
    return device().get("FACE_BUTTONS", "xbox") != "nintendo"


def ensure_dirs(root=EMU):
    from . import systems
    for d in FOLDERS:
        os.makedirs(os.path.join(root, d), exist_ok=True)
    db = systems.load()
    for sysdef in db["systems"].values():
        os.makedirs(os.path.join(root, "roms", sysdef["folders"][0]), exist_ok=True)
    # the save, state and screenshot folders the emulators are pointed at: RetroArch quietly
    # falls back to its own when a configured one doesn't exist (the Portal's first saves did)
    if root == EMU:
        wanted = [os.path.join(HOME, s["dir"]) for e in db["emulators"].values()
                  for s in e.get("saves", ())]
        wanted += [v for k, v in retroarch_kept().items() if k.endswith("_directory")]
        for d in wanted:
            if os.path.realpath(d).startswith(os.path.realpath(EMU) + os.sep):
                os.makedirs(d, exist_ok=True)


def _replace(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def write_cfg(path, values):
    """RetroArch's key = "value" format."""
    _replace(path, "".join(f'{k} = "{v}"\n' for k, v in values.items()))


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# --- Flatpak permissions ----------------------------------------------------------------------
def permissions(app):
    """Gives a Flatpak app what systems.json "permissions" lists (~/Emulation, the cards), before
    every launch: cheap and idempotent, and it covers an app installed some other way or whose
    overrides were reset. Best effort: a failure is logged, and the emulator then shows its own
    error."""
    from . import systems
    want = systems.flatpaks().get(app, {}).get("permissions", [])
    if not want:
        return
    args = [p if p.startswith("--") else f"--filesystem={p}" for p in want]
    try:
        subprocess.run(["flatpak", "override", "--user", *args, app], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    except (OSError, subprocess.SubprocessError) as err:
        print(f"emu-run: flatpak override {app} failed: {err}", file=sys.stderr)


# --- RetroArch (org.libretro.RetroArch) -------------------------------------------------------
RA_KEYS = {
    "input_exit_emulator": "escape",
    "input_save_state": "f2",
    "input_load_state": "f4",
    "input_menu_toggle": "f1",
    "input_toggle_fast_forward": "space",
    "input_hold_fast_forward": "nul",
    "input_state_slot_decrease": "f6",
    "input_state_slot_increase": "f7",
    "input_rewind": "r",
    "input_screenshot": "f8",
    # the keys come straight from Steam's layer: no hotkey-enable button, no pad hotkeys
    "input_enable_hotkey": "nul",
    "input_enable_hotkey_btn": "nul",
    "input_menu_toggle_gamepad_combo": "0",
    "input_hold_fast_forward_btn": "nul",
    # RetroArch's own default on a key the layer sends: F9 (swap screens) would mute the audio.
    # Its other default hotkeys sit on keys the layer never sends (checked against
    # config.def.keybinds.h: F3 F5 F11 h k l e p f m n , u y t i ` keypad +/-, scroll lock)
    "input_audio_mute": "nul",
    # keys the layer never sends that a USB keyboard (or a keyboard core's game) would
    "input_toggle_fullscreen": "nul",
    "input_pause_toggle": "nul",
}


def retroarch_kept():
    v = dict(RA_KEYS)
    v.update({
        "config_save_on_exit": "false",
        "quit_press_twice": "false",
        "video_fullscreen": "true",
        "pause_nonactive": "false",
        "menu_swap_ok_cancel_buttons": "true" if confirm_south() else "false",
        # PipeWire's PulseAudio server: an older retroarch.cfg can hold "null" (no sound; seen
        # on the Portal), which RetroArch saves after a failed audio start
        "audio_driver": "pulse",
        # its own screensaver inhibit fails over D-Bus in the Flatpak under gamescope, and
        # libdbus aborts RetroArch on the way out (seen on the Portal); Game Mode keeps the
        # screen on while a game runs anyway
        "suspend_screensaver_enable": "false",
        "input_joypad_driver": "sdl2",
        "input_autodetect_enable": "true",
        # the cores the plugin downloads from libretro's buildbot
        "libretro_directory": os.path.join(RA_DIR, "cores"),
        "core_updater_buildbot_cores_url": "https://buildbot.libretro.com/nightly/linux/aarch64/latest/",
        "system_directory": os.path.join(EMU, "bios"),
        "savefile_directory": os.path.join(EMU, "saves/retroarch"),
        "savestate_directory": os.path.join(EMU, "states/retroarch"),
        "screenshot_directory": os.path.join(EMU, "screenshots"),
        # <dir>/<ROM folder>/<game>.srm, where the Saves page looks: no core-name folder (an
        # older retroarch.cfg had sorting by core on), so a game's saves stay its own when the
        # system's core changes
        "sort_savefiles_by_content_enable": "true",
        "sort_savestates_by_content_enable": "true",
        "sort_savefiles_enable": "false",
        "sort_savestates_enable": "false",
        "savestate_thumbnail_enable": "true",
        "savestate_auto_index": "false",
        "notification_show_autoconfig": "false",
        "menu_show_core_updater": "false",
        "menu_show_online_updater": "true",
    })
    return v


def retroarch_seeded():
    return {
        "video_driver": "vulkan",
        "driver_switch_enable": "true",
        "video_vsync": "true",
        "video_threaded": "false",
        "menu_driver": "ozone",
        "savefile_compression": "false",
        "autosave_interval": "10",
        "video_smooth": "false",
        "aspect_ratio_index": "22",  # core provided
        # on only for the light systems (systems.json "rewind": their append-config turns it on)
        "rewind_enable": "false",
    }


def retroarch_core_options():
    hi = tier() == "high"
    return {
        "mupen64plus-rdp-plugin": "gliden64",
        "mupen64plus-43screensize": "1280x960" if hi else "960x720",
        "reicast_internal_resolution": "1920x1440" if hi else "1280x960",
        "flycast_internal_resolution": "1920x1440" if hi else "1280x960",
        "beetle_psx_hw_internal_resolution": "4x" if hi else "2x",
        "swanstation_GPU_ResolutionScale": "4" if hi else "2",
        "pcsx_rearmed_neon_enhancement_enable": "enabled" if hi else "disabled",
        "melonds_render_mode": "opengl",
        "melonds_opengl_resolution": "3" if hi else "2",
        # blueMSX picks MSX2+ for a cartridge and, without the real MSX2+ ROMs (Kettle downloads
        # only the free C-BIOS), falls back to "MSX2+ - C-BIOS"; only Auto does (the option's
        # values are machine names, none of them C-BIOS, and a named machine never falls back)
        "bluemsx_msxtype": "Auto",
    }


def append_configs(system):
    """The `--appendconfig` list for a game: what Kettle keeps, then the system's own. In
    RetroArch's own config folder, which its sandbox can always read."""
    from . import systems
    kdir = os.path.join(RA_DIR, "kettle")
    kept = os.path.join(kdir, "retroarch-kettle.cfg")
    write_cfg(kept, retroarch_kept())
    paths = [kept]
    extra = systems.load()["systems"].get(system, {}).get("retroarch")
    if extra:
        p = os.path.join(kdir, f"retroarch-{system}.cfg")
        write_cfg(p, extra)
        paths.append(p)
    return "|".join(paths)


def seed_retroarch(have):
    cfg = os.path.join(RA_DIR, "retroarch.cfg")
    if not os.path.exists(cfg):
        write_cfg(cfg, retroarch_seeded())
    opts = os.path.join(RA_DIR, "retroarch-core-options.cfg")
    if not os.path.exists(opts):
        write_cfg(opts, retroarch_core_options())
    return 1


# --- ini files --------------------------------------------------------------------------------
def set_ini(path, sections, create_only=None, qt=False):
    """Sets these keys in an ini file, leaving every other line as it is. qt: a QSettings file
    (key=value, no spaces; keys such as Shortcuts\\Main%20Window\\Exit\\KeySeq kept as they are)."""
    cp = configparser.RawConfigParser(strict=False, interpolation=None, delimiters=("=",))
    cp.optionxform = str
    if os.path.exists(path):
        cp.read(path, encoding="utf-8")
    elif create_only:
        for sec, kv in create_only.items():
            cp.setdefault(sec, {})
            for k, v in kv.items():
                cp[sec][k] = v
    for sec, kv in sections.items():
        if not cp.has_section(sec):
            cp.add_section(sec)
        for k, v in kv.items():
            cp[sec][k] = v
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        cp.write(f, space_around_delimiters=not qt)
    os.replace(tmp, path)


def _qt_key(name):
    """A shortcut's name as a QSettings key: its "/" become "\\" (the frontends' AdjustKey: the
    "Continue/Pause Emulation" group), then spaces %20."""
    return name.replace("/", "\\").replace(" ", "%20")


def qt_shortcuts(group, keys):
    """QSettings keys for Qt emulators' hotkeys (Azahar, Eden): name -> key sequence ("" none)."""
    out = {}
    for name, seq in keys.items():
        base = "Shortcuts\\" + _qt_key(group) + "\\" + _qt_key(name)
        out[base + "\\KeySeq"] = seq
        out[base + "\\KeySeq\\default"] = "false"
    return out


def qt_settings(values):
    """QSettings values with their \\default=false marker (Citra-family configs)."""
    out = {}
    for k, v in values.items():
        out[k] = v
        out[k + "\\default"] = "false"
    return out


def bios_file(name):
    p = os.path.join(EMU, "bios", name)
    return p if os.path.isfile(p) else ""


# --- PPSSPP (org.ppsspp.PPSSPP) ---------------------------------------------------------------
PPSSPP_DIR = os.path.join(app_dir("org.ppsspp.PPSSPP"), "ppsspp/PSP/SYSTEM")
# controls.ini: "<device>-<keycode>"; 1 keyboard (Android NKCODEs), 10 the first SDL pad
PPSSPP_KEYS = {
    "Save State": "1-132", "Load State": "1-134", "Pause": "1-131", "SpeedToggle": "1-62",
    "Previous Slot": "1-136", "Next Slot": "1-137", "Rewind": "1-46", "Screenshot": "1-138",
    "Exit App": "1-111",
    # keys PPSSPP binds by default that the layer's keys would also hit
    "Fast-forward": "", "Toggle Fullscreen": "",
}
PPSSPP_PAD = {  # by position: Cross south, Circle east, Square west, Triangle north
    "Cross": "10-189", "Circle": "10-190", "Square": "10-191", "Triangle": "10-188",
    "L": "10-193", "R": "10-192", "Start": "10-197", "Select": "10-196",
    "Up": "10-19", "Down": "10-20", "Left": "10-21", "Right": "10-22",
}


def keep_ppsspp():
    set_ini(os.path.join(PPSSPP_DIR, "controls.ini"), {"ControlMapping": PPSSPP_KEYS},
            create_only={"ControlMapping": PPSSPP_PAD})
    set_ini(os.path.join(PPSSPP_DIR, "ppsspp.ini"), {
        "General": {"CheckForNewVersion": "False", "FirstRun": "False",
                    "DiscordRichPresence": "False", "PauseOnLostFocus": "False"},
        "Graphics": {"FullScreen": "True"},
        "SystemParam": {"ButtonPreference": "1"},  # Cross (south) confirms
    }, create_only={
        "Graphics": {"GraphicsBackend": "3 (VULKAN)",
                     "InternalResolution": "3" if tier() == "high" else "2"},
    })


# --- Dolphin (org.DolphinEmu.dolphin-emu) -----------------------------------------------------
DOLPHIN_DIR = os.path.join(app_dir("org.DolphinEmu.dolphin-emu"), "dolphin-emu")
DOLPHIN_PAD = "SDL/0/Steam Virtual Gamepad"


def dolphin_hotkeys():
    k = {"Device": "XInput2/0/Virtual core pointer"}
    # the slot keys Dolphin binds by default (F1-F8, Shift+F1-F8) would clash with the layer's
    for n in range(1, 11):
        k[f"Load State/Load State Slot {n}"] = ""
        k[f"Save State/Save State Slot {n}"] = ""
    k.update({
        "Save State/Save to Selected Slot": "`F2`",
        "Load State/Load from Selected Slot": "`F4`",
        "General/Toggle Pause": "`F1`",
        "Emulation Speed/Disable Emulation Speed Limit": "`space`",
        "Other State Hotkeys/Decrease Selected State Slot": "`F6`",
        "Other State Hotkeys/Increase Selected State Slot": "`F7`",
        "General/Take Screenshot": "`F8`",
        "General/Stop": "",
        "General/Exit": "`Escape`",
    })
    return k


def dolphin_gcpad():
    b = lambda name: f"`{name}`"  # noqa: E731
    return {"Device": DOLPHIN_PAD,
            # by position: A south, B west, X east, Y north
            "Buttons/A": b("Button S"), "Buttons/B": b("Button W"), "Buttons/X": b("Button E"),
            "Buttons/Y": b("Button N"), "Buttons/Z": b("Shoulder R"), "Buttons/Start": "Start",
            "Main Stick/Up": b("Left Y-"), "Main Stick/Down": b("Left Y+"),
            "Main Stick/Left": b("Left X-"), "Main Stick/Right": b("Left X+"),
            "C-Stick/Up": b("Right Y-"), "C-Stick/Down": b("Right Y+"),
            "C-Stick/Left": b("Right X-"), "C-Stick/Right": b("Right X+"),
            "Triggers/L": b("Trigger L"), "Triggers/R": b("Trigger R"),
            "Triggers/L-Analog": b("Trigger L"), "Triggers/R-Analog": b("Trigger R"),
            "D-Pad/Up": b("Pad N"), "D-Pad/Down": b("Pad S"), "D-Pad/Left": b("Pad W"),
            "D-Pad/Right": b("Pad E"), "Rumble/Motor": "Strong"}


def dolphin_wiimote():
    b = lambda name: f"`{name}`"  # noqa: E731
    return {"Device": DOLPHIN_PAD, "Source": "1", "Extension": "Nunchuk",
            "Buttons/A": b("Button S"), "Buttons/B": b("Trigger R"), "Buttons/1": b("Button W"),
            "Buttons/2": b("Button N"), "Buttons/-": b("Button E"), "Buttons/+": "Start",
            "Buttons/Home": b("Shoulder R"),
            "IR/Up": b("Right Y-"), "IR/Down": b("Right Y+"),
            "IR/Left": b("Right X-"), "IR/Right": b("Right X+"),
            "D-Pad/Up": b("Pad N"), "D-Pad/Down": b("Pad S"), "D-Pad/Left": b("Pad W"),
            "D-Pad/Right": b("Pad E"), "Shake/X": b("Shoulder L"),
            "Nunchuk/Buttons/C": b("Shoulder L"), "Nunchuk/Buttons/Z": b("Trigger L"),
            "Nunchuk/Stick/Up": b("Left Y-"), "Nunchuk/Stick/Down": b("Left Y+"),
            "Nunchuk/Stick/Left": b("Left X-"), "Nunchuk/Stick/Right": b("Left X+"),
            "Rumble/Motor": "Strong"}


def keep_dolphin():
    set_ini(os.path.join(DOLPHIN_DIR, "Hotkeys.ini"), {"Hotkeys": dolphin_hotkeys()})
    set_ini(os.path.join(DOLPHIN_DIR, "Dolphin.ini"), {
        "Interface": {"ConfirmStop": "False", "PauseOnFocusLost": "False", "CursorVisibility": "0"},
        "Display": {"Fullscreen": "True", "RenderToMain": "False"},
        "Analytics": {"Enabled": "False", "PermissionAsked": "True"},
        "Input": {"BackgroundInput": "False"},
    }, create_only={
        "Core": {"GFXBackend": "Vulkan"},
        "General": {"ISOPaths": "1", "ISOPath0": os.path.join(EMU, "roms/gc")},
    })
    gfx = os.path.join(DOLPHIN_DIR, "GFX.ini")
    if not os.path.exists(gfx):
        set_ini(gfx, {"Settings": {"InternalResolution": "3" if tier() == "high" else "2"}})
    for name, section, values in (("GCPadNew.ini", "GCPad1", dolphin_gcpad()),
                                  ("WiimoteNew.ini", "Wiimote1", dolphin_wiimote())):
        p = os.path.join(DOLPHIN_DIR, name)
        if not os.path.exists(p):
            set_ini(p, {section: values})


# --- melonDS (net.kuribo64.melonDS) -----------------------------------------------------------
MELONDS_TOML = os.path.join(app_dir("net.kuribo64.melonDS"), "melonDS/melonDS.toml")
# Qt key codes
QT_KEY = {"F1": 0x01000030, "F2": 0x01000031, "F4": 0x01000033, "F6": 0x01000035,
          "F7": 0x01000036, "F8": 0x01000037, "F9": 0x01000038, "F10": 0x01000039,
          "Escape": 0x01000000, "Space": 0x20, "P": 0x50}


def _tkey(k):
    return k if k and all(c.isalnum() or c in "-_" for c in k) else json.dumps(k)


def _tval(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_tval(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_tkey(k)} = {_tval(x)}" for k, x in v.items()) + "}"
    return json.dumps(str(v))


def _tables(v):
    return isinstance(v, list) and v and all(isinstance(x, dict) for x in v)


def toml_dump(d, prefix=""):
    """TOML as melonDS and xemu write it: tables, arrays of tables ([[a.b]]: xemu's
    input.gamepad_mappings), strings, ints, floats, bools, so keys Kettle doesn't own survive."""
    lines = [f"{_tkey(k)} = {_tval(v)}" for k, v in d.items()
             if not isinstance(v, dict) and not _tables(v)]
    for k, v in d.items():
        name = f"{prefix}.{_tkey(k)}" if prefix else _tkey(k)
        if isinstance(v, dict):
            lines += ["", f"[{name}]", toml_dump(v, name)]
        elif _tables(v):
            for item in v:
                lines += ["", f"[[{name}]]", toml_dump(item, name)]
    return "\n".join(lines)


def _toml(path):
    import tomllib
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return {}


def keep_melonds():
    """Upstream melonDS: its state keys are fixed menu shortcuts (Shift+F1 save slot 1, F1 load
    it: systems.json "keys"); pause, fast-forward and swap screens are hotkeys of its own."""
    conf = _toml(MELONDS_TOML)
    new = not conf
    inst = conf.setdefault("Instance0", {})
    inst.setdefault("Keyboard", {}).update({
        "HK_Pause": QT_KEY["P"], "HK_FrameLimitToggle": QT_KEY["Space"], "HK_FastForward": -1,
        # F9 is its load-state-from-file shortcut
        "HK_SwapScreens": QT_KEY["F10"], "HK_FullscreenToggle": -1,
    })
    inst["SaveFilePath"] = os.path.join(EMU, "saves/melonds")
    inst["SavestatePath"] = os.path.join(EMU, "states/melonds")
    for d in (inst["SaveFilePath"], inst["SavestatePath"]):
        os.makedirs(d, exist_ok=True)
    if new:
        # by position: DS A east, B south, X north, Y west (SDL joystick indices of an xpad)
        inst["JoystickID"] = 0
        inst["Joystick"] = {"A": 1, "B": 0, "X": 3, "Y": 2, "L": 4, "R": 5, "Select": 6,
                            "Start": 7, "Up": 0x101, "Right": 0x102, "Down": 0x104, "Left": 0x108}
        conf.setdefault("3D", {}).update({"Renderer": 1, "GL": {"ScaleFactor": 4 if tier() == "high" else 2}})
        conf.setdefault("Screen", {})["UseGL"] = True
    emu = conf.setdefault("Emu", {})
    emu["DirectBoot"] = True
    # the real BIOS and firmware when all three are in ~/Emulation/bios, else melonDS's own
    files = [bios_file(n) for n in ("bios9.bin", "bios7.bin", "firmware.bin")]
    emu["ExternalBIOSEnable"] = all(files)
    ds = conf.setdefault("DS", {})
    ds["BIOS9Path"], ds["BIOS7Path"], ds["FirmwarePath"] = files
    _replace(MELONDS_TOML, toml_dump(conf) + "\n")


# --- Play! (org.purei.Play): PlayStation 2 ----------------------------------------------------
PLAY_CONFIG = os.path.join(app_dir("org.purei.Play"), "Play Data Files/config.xml")


def keep_play():
    """Its keys are fixed (Ctrl+Shift+1 save, Ctrl+1 load, Ctrl+R pause: systems.json "keys"; its
    Ctrl+Q lives in the menu bar fullscreen hides, so Steam's Exit game quits it); this turns off
    the exit question and pausing in the background."""
    try:
        root = ET.parse(PLAY_CONFIG).getroot()
    except (OSError, ET.ParseError):
        root = ET.Element("Config")
    prefs = {p.get("Name"): p for p in root.findall("Preference")}
    for name, typ, value in (("ui.showexitconfirmation", "boolean", "false"),
                             ("ui.pausewhenfocuslost", "boolean", "false")):
        p = prefs.get(name)
        if p is None:
            p = ET.SubElement(root, "Preference", {"Name": name})
        p.set("Type", typ)
        p.set("Value", value)
    # Play!'s parser takes only double-quoted attributes: ElementTree's declaration is single-quoted
    _replace(PLAY_CONFIG, '<?xml version="1.0" encoding="UTF-8"?>\n'
             + ET.tostring(root, encoding="unicode") + "\n")


# --- RPCS3 (net.rpcs3.RPCS3): PlayStation 3 ---------------------------------------------------
RPCS3_DIR = os.path.join(app_dir("net.rpcs3.RPCS3"), "rpcs3")
RPCS3_SHORTCUTS = {  # GuiConfigs/CurrentSettings.ini [Shortcuts]; "" unbinds
    # its savestate key saves, then kills and reboots the game from the state: not a hotkey
    "game_window_savestate": "",
    "gw_home_menu": "F1",
    "game_window_frame_limit": "Space",
    "game_window_screenshot": "F8",
    "game_window_stop": "Esc",
    # Esc leaves fullscreen by default
    "game_window_exit_fullscreen": "",
    "main_window_exit_fullscreen": "",
}


def set_yaml(path, section, values):
    """Sets `key: value` lines of one top-level section of a block YAML file (RPCS3's
    config.yml), keeping every other line."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    start = next((i for i, l in enumerate(lines) if l.rstrip() == f"{section}:"), None)
    if start is None:
        lines += [f"{section}:"]
        start = len(lines) - 1
    end = start + 1
    while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip()):
        end += 1
    body = lines[start + 1:end]
    for k, v in values.items():
        for i, l in enumerate(body):
            if l.startswith(f"  {k}:"):
                body[i] = f"  {k}: {v}"
                break
        else:
            body.append(f"  {k}: {v}")
    lines[start + 1:end] = body
    _replace(path, "\n".join(lines) + "\n")


PS3_FIRMWARE = os.path.join(EMU, "bios/ps3/PS3UPDAT.PUP")


def _install_ps3_firmware():
    """The PS3 system software from Emulation/bios/ps3 into RPCS3 when it's new or changed:
    `rpcs3 --headless --installfw` installs and exits with no window (rpcs3.cpp, checked on the
    Portal: 4.93, 1075 files in dev_flash, about 4 s). It aborts on its way out (exit 134, a
    teardown check) after a good install, so success is the installed vsh.self, not the exit
    code. A marker keeps it from reinstalling the same file every launch."""
    try:
        st = os.stat(PS3_FIRMWARE)
    except OSError:
        return
    marker = os.path.join(RPCS3_DIR, ".kettle-firmware")
    vsh = os.path.join(RPCS3_DIR, "dev_flash/vsh/module/vsh.self")
    stamp = f"{st.st_size} {int(st.st_mtime)}"
    try:
        with open(marker) as f:
            if f.read().strip() == stamp and os.path.exists(vsh):
                return
    except OSError:
        pass
    permissions("net.rpcs3.RPCS3")  # it reads the file from ~/Emulation
    try:
        subprocess.run(["flatpak", "run", "--command=rpcs3", "net.rpcs3.RPCS3", "--headless",
                        "--installfw", PS3_FIRMWARE], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
    except (OSError, subprocess.SubprocessError) as err:
        print(f"emu-run: installing the PS3 firmware failed: {err}", file=sys.stderr)
        return
    if os.path.exists(vsh):
        _replace(marker, stamp + "\n")
    else:
        print("emu-run: RPCS3 didn't install the PS3 firmware", file=sys.stderr)


# Player 1's pad: RPCS3's own default is the keyboard (cfg_input::load, pad_config.cpp, when
# input_configs/global/Default.yml is missing or empty). Its evdev handler names a pad by its
# evdev name, which for Steam's virtual pad is known exactly (/proc/bus/input/devices on the
# Portal; evdev_joystick_handler.cpp get_device_name/add_device), where the SDL handler's name
# can be the real controller's (SDL3 reads Steam's virtual gamepad info). Only Handler and
# Device are written: the handler's own defaults fill in the rest when RPCS3 loads it
# (pad_thread.cpp InitPadConfig, then "Reload with proper defaults"), and the evdev defaults
# are by position (Cross BTN_A south, Circle BTN_B east, Square BTN_X west, Triangle BTN_Y north).
RPCS3_INPUT = os.path.join(RPCS3_DIR, "input_configs/global/Default.yml")
# Steam's virtual pad through RPCS3's SDL handler, which names a pad "<SDL3's name> <n>" and
# wants it exactly (sdl_pad_handler.cpp). The Flathub build has no evdev handler ("Evdev" is an
# invalid enum there: the Portal's game said "please connect controller"). SDL3 hides Steam's
# virtual pad without SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD, and can name it after the
# controller behind it, so the name is asked of RPCS3's own SDL3 before each launch, with the
# launch's own environment (the Portal: "SteamOS Handheld Controller" under Steam, "Steam Virtual
# Gamepad" over SSH).
STEAM_PAD_SDL_NAME = "Steam Virtual Gamepad"
STEAM_PAD_HINT = {"SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD": "1"}
# run inside RPCS3's sandbox (python3 is in its runtime, SDL3 in /app/lib): the name SDL3 gives
# Steam's virtual pad. Under Steam that's the controller behind it, with its product ID too (the
# Portal: "SteamOS Handheld Controller", 28de:12f0, not the pad's 11ff), and Steam's ignore
# list leaves only the virtual pad, so it's the first Valve gamepad SDL lists
_SDL_PROBE = """
import ctypes
sdl = ctypes.CDLL("libSDL3.so.0")
sdl.SDL_Init.argtypes = [ctypes.c_uint32]; sdl.SDL_Init.restype = ctypes.c_bool
sdl.SDL_GetGamepads.argtypes = [ctypes.POINTER(ctypes.c_int)]
sdl.SDL_GetGamepads.restype = ctypes.POINTER(ctypes.c_uint32)
sdl.SDL_GetGamepadVendorForID.argtypes = [ctypes.c_uint32]; sdl.SDL_GetGamepadVendorForID.restype = ctypes.c_uint16
sdl.SDL_OpenGamepad.argtypes = [ctypes.c_uint32]; sdl.SDL_OpenGamepad.restype = ctypes.c_void_p
sdl.SDL_GetGamepadName.argtypes = [ctypes.c_void_p]; sdl.SDL_GetGamepadName.restype = ctypes.c_char_p
if sdl.SDL_Init(0x2000):
    n = ctypes.c_int(0); ids = sdl.SDL_GetGamepads(ctypes.byref(n))
    for i in range(n.value):
        if sdl.SDL_GetGamepadVendorForID(ids[i]) == 0x28de:
            # the opened pad's name, as RPCS3 reads it: before it's opened SDL3 still says
            # "Steam Virtual Gamepad" (the Portal, under Steam)
            pad = sdl.SDL_OpenGamepad(ids[i])
            print((sdl.SDL_GetGamepadName(pad) or b"").decode(errors="replace") if pad else "")
            break
"""


def rpcs3_pad_name():
    """What RPCS3 will call Steam's virtual pad ("<name> 1"), from its own SDL3."""
    env = {**os.environ, **STEAM_PAD_HINT}
    try:
        r = subprocess.run(["flatpak", "run", "--command=python3", "--env=LD_LIBRARY_PATH=/app/lib",
                            *(f"--env={k}={v}" for k, v in STEAM_PAD_HINT.items()),
                            "net.rpcs3.RPCS3", "-"], input=_SDL_PROBE, env=env, text=True,
                           capture_output=True, timeout=30)
        name = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        name = ""
    return f"{name or STEAM_PAD_SDL_NAME} 1"


def _keep_rpcs3_pad():
    """Player 1 becomes Steam's virtual pad while it's RPCS3's default (no file, the keyboard,
    no handler) or Kettle's own (an earlier Steam pad entry, or 0.3.1's Evdev one); a pad the
    user set up stays."""
    try:
        with open(RPCS3_INPUT, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    start = next((i for i, l in enumerate(lines) if l.rstrip() == "Player 1 Input:"), None)
    if start is None:
        start, end = len(lines), len(lines)
    else:
        end = start + 1
        while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip()):
            end += 1
        block = {l.split(":", 1)[0].strip(): l.split(":", 1)[1].strip()
                 for l in lines[start + 1:end] if ":" in l and l.startswith("  ") and not l.startswith("   ")}
        handler, device = block.get("Handler", ""), block.get("Device", "")
        ours = handler == "Evdev" or (handler == "SDL" and device.startswith(
            (STEAM_PAD_SDL_NAME, "SteamOS Handheld Controller", "Steam Deck", "Steam Controller")))
        if handler not in ("", "Keyboard", "Null") and not ours:
            return
    device = rpcs3_pad_name()
    lines[start:end] = ["Player 1 Input:", "  Handler: SDL", f"  Device: {device}"]
    _replace(RPCS3_INPUT, "\n".join(lines) + "\n")


def keep_rpcs3():
    _install_ps3_firmware()
    _keep_rpcs3_pad()
    set_ini(os.path.join(RPCS3_DIR, "GuiConfigs/CurrentSettings.ini"), {
        "Shortcuts": RPCS3_SHORTCUTS,
        "main_window": {"confirmationBoxExitGame": "false", "infoBoxEnabledWelcome": "false",
                        "confirmationBoxBootGame": "false"},
        "Meta": {"checkUpdateStart": "false"},
    }, qt=True)
    set_yaml(os.path.join(RPCS3_DIR, "config.yml"), "Miscellaneous", {
        "Start games in fullscreen mode": "true",
        # with --no-gui: back to Steam when the game stops
        "Exit RPCS3 when process finishes": "true",
    })


# --- xemu (app.xemu.xemu): Xbox ---------------------------------------------------------------
XEMU_TOML = os.path.join(app_dir("app.xemu.xemu", "data"), "xemu/xemu/xemu.toml")
XBOX = os.path.join(EMU, "bios/xbox")


def keep_xemu():
    """Its keys are fixed (F1 menu, F5 load / Shift+F5 save the snapshot bound to F5, F12
    screenshot, Ctrl+Q quit: systems.json "keys"); this binds F5 to a "kettle" snapshot and
    points it at the console files in Emulation/bios/xbox."""
    conf = _toml(XEMU_TOML)
    g = conf.setdefault("general", {})
    g["show_welcome"] = False
    g["skip_boot_anim"] = True
    g.setdefault("updates", {})["check"] = False
    g.setdefault("snapshots", {}).setdefault("shortcuts", {})["f5"] = "kettle"
    conf.setdefault("display", {}).setdefault("window", {})["fullscreen_on_startup"] = True
    files = conf.setdefault("sys", {}).setdefault("files", {})
    files.update({"bootrom_path": os.path.join(XBOX, "mcpx_1.0.bin"),
                  "flashrom_path": os.path.join(XBOX, "xbox_bios.bin"),
                  "hdd_path": os.path.join(XBOX, "xbox_hdd.qcow2"),
                  "eeprom_path": os.path.join(XBOX, "eeprom.bin")})
    os.makedirs(XBOX, exist_ok=True)
    _replace(XEMU_TOML, toml_dump(conf) + "\n")


# --- Eden (dev.eden_emu.eden), Ryujinx (io.github.ryubing.Ryujinx): Switch --------------------
EDEN_INI = os.path.join(app_dir("dev.eden_emu.eden"), "eden/qt-config.ini")
EDEN_KEYS = os.path.join(app_dir("dev.eden_emu.eden", "data"), "eden/keys")
RYUJINX_DIR = os.path.join(app_dir("io.github.ryubing.Ryujinx"), "Ryujinx")
SWITCH_KEYS = os.path.join(EMU, "bios/switch")
# where each emulator's own Install Firmware puts the system's NCAs (switch.py)
RYUJINX_FIRMWARE = os.path.join(RYUJINX_DIR, "bis/system/Contents/registered")
EDEN_FIRMWARE = os.path.join(app_dir("dev.eden_emu.eden", "data"), "eden/nand/system/Contents/registered")


def _install_firmware(layout, registered):
    """The firmware from Emulation/bios/switch/firmware, when there's one (a broken one is left
    to the launch check: the game is refused for want of firmware)."""
    from . import switch
    try:
        switch.install_firmware(layout, registered)
    except Exception as e:  # a broken zip too: never what stops a launch here
        print(f"emu-run: couldn't install the Switch firmware: {e}", file=sys.stderr)


def _copy_keys(dest):
    """prod.keys and title.keys from Emulation/bios/switch, where the emulator reads its own:
    copied when the emulator has none, and again when the user puts newer ones there (the
    Portal's keys were replaced and the emulator kept the old ones). Keys installed in the
    emulator itself after them are left alone."""
    for name in ("prod.keys", "title.keys"):
        src = os.path.join(SWITCH_KEYS, name)
        dst = os.path.join(dest, name)
        if not os.path.isfile(src):
            continue
        if os.path.exists(dst):
            try:
                if os.path.getmtime(src) <= os.path.getmtime(dst):
                    continue
                with open(src, "rb") as a, open(dst, "rb") as b:
                    if a.read() == b.read():
                        continue
            except OSError:
                continue
        os.makedirs(dest, exist_ok=True)
        tmp = dst + ".tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)


# Steam's virtual pad as Eden's SDL2 driver names it: its SDL GUID with the name CRC (bytes 2-3)
# zeroed, as raw hex (sdl_driver.cpp GetGUID, uuid.cpp RawString), which is also SDL's own
# controller-database GUID for "Steam Virtual Gamepad" on Linux (bus 0003, 28de:11ff, version 1)
EDEN_PAD_GUID = "03000000de280000ff11000001000000"
# SDL's mapping of that pad (SDL_gamecontrollerdb.h): joystick button, hat and axis numbers
_PAD = {"a": ("button", 0), "b": ("button", 1), "x": ("button", 2), "y": ("button", 3),
        "lb": ("button", 4), "rb": ("button", 5), "back": ("button", 6), "start": ("button", 7),
        "guide": ("button", 8), "ls": ("button", 9), "rs": ("button", 10),
        "up": ("hat", "up"), "down": ("hat", "down"), "left": ("hat", "left"),
        "right": ("hat", "right"), "lt": ("axis", 2), "rt": ("axis", 5)}
# Eden's own default for a gamepad (sdl_driver.cpp GetDefaultButtonBinding), by position:
# Switch A east, B south, X north, Y west
_EDEN_BUTTONS = {"button_a": "b", "button_b": "a", "button_x": "y", "button_y": "x",
                 "button_lstick": "ls", "button_rstick": "rs", "button_l": "lb", "button_r": "rb",
                 "button_zl": "lt", "button_zr": "rt", "button_plus": "start", "button_minus": "back",
                 "button_dleft": "left", "button_dup": "up", "button_dright": "right",
                 "button_ddown": "down", "button_slleft": "lb", "button_srleft": "rb",
                 "button_slright": "lb", "button_srright": "rb", "button_home": "guide"}


def _eden_param(**kv):
    """A ParamPackage as Eden writes one: key:value pairs, comma-joined, in quotes (a value with a
    comma is quoted, config.cpp AdjustOutputString)."""
    return '"' + ",".join(f"{k}:{v}" for k, v in kv.items()) + '"'


def eden_pad(player=0):
    """[Controls] keys making player `player` Steam's virtual pad as a Pro Controller, the values
    Eden's own auto-mapping writes (sdl_driver.cpp Build*ParamPackage*)."""
    pad = {"engine": "sdl", "port": 0, "guid": EDEN_PAD_GUID}
    values = {"type": "0", "connected": "true"}  # ControllerType::ProController
    for key, src in _EDEN_BUTTONS.items():
        kind, n = _PAD[src]
        if kind == "button":
            values[key] = _eden_param(**pad, button=n)
        elif kind == "hat":
            values[key] = _eden_param(**pad, hat=0, direction=n)
        else:
            values[key] = _eden_param(**pad, axis=n, threshold=0.5, invert="+")
    for key, (x, y) in (("lstick", (0, 1)), ("rstick", (3, 4))):
        values[key] = _eden_param(**pad, axis_x=x, axis_y=y, offset_x="0.000000",
                                  offset_y="0.000000", invert_x="+", invert_y="+")
    return qt_settings({f"player_{player}_{k}": v for k, v in values.items()})


def _eden_player_is_default(cp, player=0):
    """Still Eden's own player: its button A never set (\\default true or missing) or a
    keyboard key. A pad the user mapped is theirs."""
    if not cp.has_section("Controls"):
        return True
    key = f"player_{player}_button_a"
    if cp["Controls"].get(key + "\\default", "true").strip().lower() == "true":
        return True
    return "engine:keyboard" in cp["Controls"].get(key, "")


def keep_eden():
    """Its hotkeys and UI settings, keys, firmware, and player 1 as Steam's virtual pad while
    Eden still has its own keyboard default there. A new config also starts in handheld mode
    (720p; Eden's desktop default is docked, settings.h use_docked_mode)."""
    fresh = not os.path.exists(EDEN_INI)
    cp = configparser.RawConfigParser(strict=False, interpolation=None, delimiters=("=",))
    cp.optionxform = str
    if not fresh:
        cp.read(EDEN_INI, encoding="utf-8")
    sections = {"UI": dict(**qt_shortcuts("Main Window", {
        "Continue/Pause Emulation": "F1",
        "Toggle Turbo Speed": "Space",
        "Capture Screenshot": "F8",
        "Exit Eden": "Esc",
        # its defaults on keys the layer sends
        "Exit Fullscreen": "", "Load/Remove Amiibo": "", "Restart Emulation": "",
        "Change Adapting Filter": "", "Change GPU Mode": "",
    }), **qt_settings({"fullscreen": "true", "confirmStop": "2", "check_for_updates": "false",
                       "firstStart": "false"}))}
    if _eden_player_is_default(cp):
        sections["Controls"] = eden_pad()
    if fresh:
        sections["System"] = qt_settings({"use_docked_mode": "0"})  # ConsoleMode::Handheld
    set_ini(EDEN_INI, sections, qt=True)
    _copy_keys(EDEN_KEYS)
    _install_firmware("eden", EDEN_FIRMWARE)


# Ryujinx's own Config.json from a first run (version 70, Ryubing 1.3.3), written when it has
# none: its loader takes every field from the file, so a partial one won't do, and without one
# its first session has the keyboard as player 1 (the Portal's game sat at "press L + R").
# Older templates are fine: Ryujinx migrates a config forward from its "version".
RYUJINX_TEMPLATE = os.path.join(os.environ.get("KETTLE_EMU_DEFAULTS", "/usr/share/kettle/emulation"),
                                "ryujinx-Config.json")
# Steam's virtual pad as Ryujinx's SDL2 driver names it: "<n>-" + its SDL GUID with the name
# CRC zeroed (SDL2GamepadDriver.GenerateGamepadId), bus 0003, vendor 28de, product 11ff, version 1
STEAM_PAD_ID = "0-00000003-28de-0000-ff11-000001000000"


def ryujinx_pad():
    """Player 1: Steam's virtual pad as a Pro Controller, by position (Switch A east, B south,
    X north, Y west), as Ryujinx's own default for a gamepad (InputViewModel)."""
    stick = lambda side, button: {"joystick": side, "invert_stick_x": False,  # noqa: E731
                                  "invert_stick_y": False, "rotate90_cw": False,
                                  "stick_button": button}
    return {
        "left_joycon_stick": stick("Left", "LeftStick"),
        "right_joycon_stick": stick("Right", "RightStick"),
        "deadzone_left": 0.1, "deadzone_right": 0.1, "range_left": 1.0, "range_right": 1.0,
        "trigger_threshold": 0.5,
        "motion": {"motion_backend": "GamepadDriver", "enable_motion": True, "sensitivity": 100,
                   "gyro_deadzone": 1.0},
        "rumble": {"strong_rumble": 1.0, "weak_rumble": 1.0, "enable_rumble": True},
        "led": {"enable_led": False, "turn_off_led": False, "use_rainbow": False, "led_color": 0},
        "left_joycon": dict(button_minus="Minus", button_l="LeftShoulder", button_zl="LeftTrigger",
                            button_sl="Unbound", button_sr="Unbound", dpad_up="DpadUp",
                            dpad_down="DpadDown", dpad_left="DpadLeft", dpad_right="DpadRight"),
        "right_joycon": dict(button_plus="Plus", button_r="RightShoulder", button_zr="RightTrigger",
                             button_sl="Unbound", button_sr="Unbound", button_x="Y", button_b="A",
                             button_y="X", button_a="B"),
        "version": 1, "backend": "GamepadSDL2", "id": STEAM_PAD_ID, "name": "Steam Virtual Gamepad",
        "controller_type": "ProController", "player_index": "Player1",
    }


def keep_ryujinx():
    """Its keys, firmware and Config.json (from RYUJINX_TEMPLATE when it has none). Player 1
    becomes Steam's virtual pad while it's still Ryujinx's default keyboard (a gamepad the user
    set up is theirs). Its hotkeys (KeyboardHotkeys, snake_case): pause F1, turbo mode
    (fast-forward) Space, screenshot F8; it has no save states and no quit key."""
    _copy_keys(os.path.join(RYUJINX_DIR, "system"))
    _install_firmware("ryujinx", RYUJINX_FIRMWARE)
    path = os.path.join(RYUJINX_DIR, "Config.json")
    conf = _read_json(path, None)
    if not isinstance(conf, dict):
        conf = _read_json(RYUJINX_TEMPLATE, None)
        if not isinstance(conf, dict):
            return
    conf.update({"check_updates_on_start": False, "show_confirm_exit": False,
                 "start_fullscreen": True})
    hk = conf.setdefault("hotkeys", {})
    for k in list(hk):
        if hk[k] in ("F1", "F2", "F4", "F6", "F7", "F8", "F9", "Space", "R", "Escape"):
            hk[k] = "Unbound"
    hk.update({"pause": "F1", "turbo_mode": "Space", "screenshot": "F8"})
    players = [p for p in conf.get("input_config") or [] if isinstance(p, dict)]
    first = next((p for p in players if p.get("player_index") == "Player1"), None)
    if first is None or first.get("backend") == "WindowKeyboard":
        players = [p for p in players if p is not first] + [ryujinx_pad()]
    conf["input_config"] = players
    _replace(path, json.dumps(conf, indent=2) + "\n")


# --- Azahar (org.azahar_emu.Azahar): 3DS ------------------------------------------------------
AZAHAR_INI = os.path.join(app_dir("org.azahar_emu.Azahar"), "azahar-emu/qt-config.ini")


def keep_azahar():
    set_ini(AZAHAR_INI, {"UI": dict(**qt_shortcuts("Main Window", {
        "Quick Save": "F2",
        "Quick Load": "F4",
        "Continue/Pause Emulation": "F1",
        "Toggle Turbo Mode": "Space",
        "Capture Screenshot": "F8",
        "Swap Screens": "F9",
        "Exit Azahar": "Esc",
        # its defaults on keys the layer sends
        "Load Amiibo": "", "Rotate Screens Upright": "", "Restart Emulation": "",
        "Toggle Custom Textures": "", "Exit Fullscreen": "",
    }), **qt_settings({"confirmClose": "false"})),
        "Miscellaneous": qt_settings({"check_for_update_on_start": "false"})}, qt=True)


SEEDERS = {"retroarch": seed_retroarch}
# the kept settings of the emulator about to start (seed(eid))
KEEPERS = {"ppsspp": keep_ppsspp, "dolphin": keep_dolphin, "melonds": keep_melonds,
           "play": keep_play, "rpcs3": keep_rpcs3, "xemu": keep_xemu, "eden": keep_eden,
           "ryujinx": keep_ryujinx, "azahar": keep_azahar}


def seed(eid=None):
    """Every emulator's first-run config (once), and the kept settings of the one about to start."""
    ensure_dirs()
    os.makedirs(CONF, exist_ok=True)
    have = _read_json(SEEDED, {})
    changed = False
    for name, fn in SEEDERS.items():
        version = fn(have.get(name, 0))
        if have.get(name) != version:
            have[name] = version
            changed = True
    if eid in KEEPERS:
        KEEPERS[eid]()
    if changed:
        _replace(SEEDED, json.dumps(have))


def environment(eid, emu):
    env = dict(os.environ)
    # Mesa's CPU Vulkan driver (llvmpipe) out of the Flatpaks' sight: Eden takes Vulkan device 0,
    # which in its runtime was llvmpipe (the Portal: a game drawn on the CPU, stuck at its
    # launch screen), and no emulator should ever draw on the CPU when there's a GPU
    env["VK_LOADER_DRIVERS_DISABLE"] = "lvp_icd*"
    if eid == "rpcs3":
        env.update(STEAM_PAD_HINT)  # SDL3 shows it Steam's virtual pad only with this
    return env
