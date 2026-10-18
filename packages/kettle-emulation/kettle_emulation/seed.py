"""First-run configs and the settings Kettle keeps the same in every emulator.

Two kinds:
- **kept**: hotkeys (the keys mkvdf.py's layer sends), folders under ~/Emulation, fullscreen,
  no confirm-on-quit, no updaters. Rewritten on every launch, so the standard controls can't
  drift. RetroArch reads them from an append-config; the standalones get the keys set in their
  own files before each start.
- **seeded**: everything else (video, per-device resolution). Written once, when the file is
  missing; after that it's the user's (and the plugin's settings page's).

seeded.json records each emulator's seed version, so a later version adds what's new without
redoing what the user changed.
"""
import configparser
import json
import os

HOME = os.path.expanduser("~")
EMU = os.path.join(HOME, "Emulation")
CONF = os.path.join(HOME, ".config/kettle/emulation")
SEEDED = os.path.join(CONF, "seeded.json")
RA_DIR = os.path.join(HOME, ".config/retroarch")
FOLDERS = ("roms", "bios", "saves", "states", "screenshots", "backups", "inbox")


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
    for sysdef in systems.load()["systems"].values():
        os.makedirs(os.path.join(root, "roms", sysdef["folders"][0]), exist_ok=True)


def write_cfg(path, values):
    """RetroArch's key = "value" format."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for k, v in values.items():
            f.write(f'{k} = "{v}"\n')
    os.replace(tmp, path)


# --- RetroArch -------------------------------------------------------------------------------
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
        "input_joypad_driver": "sdl2",
        "input_autodetect_enable": "true",
        "libretro_directory": "/usr/lib/libretro",
        "libretro_info_path": "/usr/share/libretro/info",
        "core_updater_buildbot_cores_url": "https://buildbot.libretro.com/nightly/linux/aarch64/latest/",
        "system_directory": os.path.join(EMU, "bios"),
        "savefile_directory": os.path.join(EMU, "saves/retroarch"),
        "savestate_directory": os.path.join(EMU, "states/retroarch"),
        "screenshot_directory": os.path.join(EMU, "screenshots"),
        "sort_savefiles_by_content_enable": "true",
        "sort_savestates_by_content_enable": "true",
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
    """The `--appendconfig` list for a game: what Kettle keeps, then the system's own."""
    from . import systems
    kept = os.path.join(CONF, "retroarch-kettle.cfg")
    write_cfg(kept, retroarch_kept())
    paths = [kept]
    extra = systems.load()["systems"].get(system, {}).get("retroarch")
    if extra:
        p = os.path.join(CONF, f"retroarch-{system}.cfg")
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


# --- standalones: the kept keys are filled in from each emulator's own format ----------------
def set_ini(path, sections, create_only=None):
    """Sets these keys in an ini file, leaving every other line as it is."""
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
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
        cp.write(f, space_around_delimiters=True)
    os.replace(tmp, path)


def bios_file(name):
    p = os.path.join(EMU, "bios", name)
    return p if os.path.isfile(p) else ""


# --- PPSSPP (~/.config/ppsspp/PSP/SYSTEM) ----------------------------------------------------
PPSSPP_DIR = os.path.join(HOME, ".config/ppsspp/PSP/SYSTEM")
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


# --- Dolphin (~/.config/dolphin-emu) ---------------------------------------------------------
DOLPHIN_DIR = os.path.join(HOME, ".config/dolphin-emu")
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


# --- melonDS (~/.config/melonDS/melonDS.toml) ------------------------------------------------
MELONDS_TOML = os.path.join(HOME, ".config/melonDS/melonDS.toml")
QT_KEY = {"F1": 0x01000030, "F2": 0x01000031, "F4": 0x01000033, "F6": 0x01000035,
          "F7": 0x01000036, "F8": 0x01000037, "F9": 0x01000038, "Escape": 0x01000000,
          "Space": 0x20}


def toml_dump(d, prefix=""):
    """The subset of TOML melonDS writes: tables, strings, ints, floats, bools."""
    def val(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, list):
            return "[" + ", ".join(val(x) for x in v) + "]"
        return json.dumps(str(v))
    lines = [f"{k} = {val(v)}" for k, v in d.items() if not isinstance(v, dict)]
    for k, v in d.items():
        if isinstance(v, dict):
            name = f"{prefix}.{k}" if prefix else k
            lines += ["", f"[{name}]", toml_dump(v, name)]
    return "\n".join(lines)


def keep_melonds():
    import tomllib
    try:
        with open(MELONDS_TOML, "rb") as f:
            conf = tomllib.load(f)
    except (OSError, ValueError):
        conf = {}
    new = not conf
    inst = conf.setdefault("Instance0", {})
    inst.setdefault("Keyboard", {}).update({
        "HK_SaveState": QT_KEY["F2"], "HK_LoadState": QT_KEY["F4"], "HK_Pause": QT_KEY["F1"],
        "HK_FastForwardToggle": QT_KEY["Space"], "HK_FastForward": -1,
        "HK_PrevStateSlot": QT_KEY["F6"], "HK_NextStateSlot": QT_KEY["F7"],
        "HK_Quit": QT_KEY["Escape"], "HK_SwapScreens": QT_KEY["F9"], "HK_FullscreenToggle": -1,
    })
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
    os.makedirs(os.path.dirname(MELONDS_TOML), exist_ok=True)
    tmp = MELONDS_TOML + ".tmp"
    with open(tmp, "w") as f:
        f.write(toml_dump(conf) + "\n")
    os.replace(tmp, MELONDS_TOML)


SEEDERS = {"retroarch": seed_retroarch}
# the standalones' kept settings, for the emulator about to start (seed(eid))
KEEPERS = {"ppsspp": keep_ppsspp, "dolphin": keep_dolphin, "melonds": keep_melonds}


def seed(eid=None):
    """Every emulator's first-run config (once), and the kept settings of the one about to start."""
    ensure_dirs()
    os.makedirs(CONF, exist_ok=True)
    try:
        with open(SEEDED) as f:
            have = json.load(f)
    except (OSError, ValueError):
        have = {}
    changed = False
    for name, fn in SEEDERS.items():
        version = fn(have.get(name, 0))
        if have.get(name) != version:
            have[name] = version
            changed = True
    if eid in KEEPERS:
        KEEPERS[eid]()
    if changed:
        tmp = SEEDED + ".tmp"
        with open(tmp, "w") as f:
            json.dump(have, f)
        os.replace(tmp, SEEDED)


def environment(eid, emu):
    env = dict(os.environ)
    if emu["kind"] == "standalone":
        # gamescope's games are X11 clients
        env["QT_QPA_PLATFORM"] = "xcb"
        env["SDL_VIDEODRIVER"] = "x11"
    return env
