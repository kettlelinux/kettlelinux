#!/usr/bin/env python3
"""Writes the Steam Input layouts of every emulation shortcut: emulation-xbox.vdf and
emulation-nintendo.vdf (the device's FACE_BUTTONS picks one), run by the PKGBUILD. An emulator
whose hotkeys can't be rebound to the standard keys (systems.json "keys": Play!, xemu, melonDS)
gets layouts of its own, emulation-<face>-<emulator id>.vdf, with the same buttons sending its
own key chords (systems.layout() names the one a game needs); a hotkey it has no key for does
nothing there.

The gamepad passes through as Steam's virtual Xbox pad, by position. Holding Select holds the
"Hotkeys" action layer, whose buttons send the keys every emulator's seeded config binds
(defaults/, emu-run's keys bridge for the rest):

  Select + A  save state  F2      Select + L1/R1  state slot -/+   F6/F7
  Select + B  load state  F4      Select + L2     rewind (held)    R
  Select + X  menu        F1      Select + R2     screenshot       F8
  Select + Y  fast-forward Space  Select + D-pad left/right  swap screens  F9
  Select + Start  quit (Esc; the Steam menu's Exit game when an emulator hangs)
  (rewind works in the systems.json "rewind" systems, the 8/16-bit ones RetroArch runs)

A/B/X/Y are the buttons *labelled* so: on a Nintendo-labelled pad A is the east button.
Select alone, released before the layer was used, still reaches the game as Select.

Usage: mkvdf.py <outdir> [systems.json]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kettle_emulation import keys as K  # noqa: E402

# the action of each labelled face button; positions are Steam's (button_a = south)
LABEL_ACTIONS = {"A": "save_state", "B": "load_state", "X": "menu", "Y": "fast_forward"}
POSITION_OF = {
    "xbox": {"A": "button_a", "B": "button_b", "X": "button_x", "Y": "button_y"},
    "nintendo": {"A": "button_b", "B": "button_a", "X": "button_y", "Y": "button_x"},
}


def q(s):
    return '"%s"' % s


class W:
    def __init__(self):
        self.lines, self.depth = [], 0

    def kv(self, k, v):
        self.lines.append("\t" * self.depth + q(k) + "\t\t" + q(v))

    def open(self, k):
        self.lines.append("\t" * self.depth + q(k))
        self.lines.append("\t" * self.depth + "{")
        self.depth += 1

    def close(self):
        self.depth -= 1
        self.lines.append("\t" * self.depth + "}")

    def text(self):
        return "\n".join(self.lines) + "\n"


def activators(w, acts):
    """acts: [(activator, [bindings], {settings})]"""
    w.open("activators")
    for name, bindings, settings in acts:
        w.open(name)
        w.open("bindings")
        for b in bindings:
            w.kv("binding", b + ", , ")
        w.close()
        if settings:
            w.open("settings")
            for k, v in settings.items():
                w.kv(k, v)
            w.close()
        w.close()
    w.close()
    w.open("disabled_activators")
    w.close()


def group(w, gid, mode, inputs, settings=None):
    """inputs: {input: [(activator, [bindings], {settings})]}"""
    w.open("group")
    w.kv("id", str(gid))
    w.kv("mode", mode)
    w.kv("name", "")
    w.kv("description", "")
    w.open("inputs")
    for name, acts in inputs.items():
        w.open(name)
        activators(w, acts)
        w.close()
    w.close()
    if settings:
        w.open("settings")
        for k, v in settings.items():
            w.kv(k, v)
        w.close()
    w.close()


def press(*bindings):
    return [("Full_Press", list(bindings), {})]


def tap(*bindings):
    """Once, as the button goes down: a key held as long as the button would auto-repeat
    (40 save states for a one-second press on the Portal)."""
    return [("Start_Press", list(bindings), {})]


def xi(button):
    return "xinput_button " + button


def key(k):
    return "key_press " + k


def keypress(chord):
    return [key(k) for k in chord]


def layout(face, keymap=None, name=None):
    """keymap: action -> chord (keys.keymap()); the standard keys without one."""
    km = keymap if keymap is not None else K.keymap()

    def on(action, how=None):
        """The activators of a hotkey, or None when this emulator has no key for it."""
        chord = km.get(action)
        return (how or tap)(*keypress(chord)) if chord else None

    def present(d):
        return {k: v for k, v in d.items() if v}

    w = W()
    w.open("controller_mappings")
    w.kv("version", "3")
    w.kv("revision", "1")
    w.kv("title", "Kettle Emulation" + (f" ({name})" if name else ""))
    w.kv("description", "Gamepad by button position. Hold Select for hotkeys: A save state, "
         "B load state, X menu, Y fast-forward, L1/R1 state slot, L2 rewind, R2 screenshot, "
         "D-pad left/right swap screens, Start quit.")
    w.kv("controller_type", "controller_steamos_handheld")
    w.kv("major_revision", "0")
    w.kv("minor_revision", "0")
    w.kv("Timestamp", "0")
    w.open("actions")
    w.open("Default")
    w.kv("title", "Gamepad")
    w.kv("legacy_set", "1")
    w.close()
    w.close()
    w.open("action_layers")
    w.open("Preset_1000001")
    w.kv("title", "Hotkeys")
    w.kv("legacy_set", "1")
    w.kv("set_layer", "1")
    w.kv("parent_set_name", "Default")
    w.close()
    w.close()

    # the gamepad (set 1, preset 0)
    group(w, 0, "four_buttons", {b: press(xi(b[-1].upper())) for b in
                                ("button_a", "button_b", "button_x", "button_y")})
    group(w, 1, "dpad", {"dpad_" + d: press(xi("DPAD_" + x)) for d, x in
                         (("north", "UP"), ("south", "DOWN"), ("east", "RIGHT"), ("west", "LEFT"))},
          {"requires_click": "0"})
    group(w, 2, "joystick_move", {"click": press(xi("JOYSTICK_LEFT"))})
    group(w, 3, "joystick_move", {"click": press(xi("JOYSTICK_RIGHT"))}, {"output_joystick": "1"})
    group(w, 4, "trigger", {}, {"output_trigger": "1"})
    group(w, 5, "trigger", {}, {"output_trigger": "2"})
    # Select: held, the hotkey layer; tapped (released within 250 ms, a tap as people tap it:
    # 120 ms was too short on the Portal), Select
    group(w, 6, "switches", {
        "button_menu": [("Full_Press", [xi("SELECT")], {"interruptable": "1"}),
                        ("Long_Press", ["controller_action hold_layer 2 0 0"],
                         {"long_press_time": "250"})],
        "button_escape": press(xi("START")),
        "left_bumper": press(xi("SHOULDER_LEFT")),
        "right_bumper": press(xi("SHOULDER_RIGHT")),
    })

    # the hotkey layer (set 2, preset 1): only what it changes; the sticks stay the gamepad's
    pos = POSITION_OF[face]
    group(w, 10, "four_buttons", present({pos[label]: on(a) for label, a in LABEL_ACTIONS.items()}))
    group(w, 11, "dpad", present({"dpad_east": on("swap_screens"), "dpad_west": on("swap_screens")}),
          {"requires_click": "0"})
    # rewind runs while L2 is held
    group(w, 12, "trigger", present({"click": on("rewind", press)}), {"output_trigger": "0"})
    group(w, 13, "trigger", present({"click": on("screenshot")}), {"output_trigger": "0"})
    group(w, 14, "switches", present({
        "button_menu": [("Full_Press", ["controller_action hold_layer 2 0 0"], {})],
        # quit: every seeded emulator quits on its key, saving (Steam's quit_application on a
        # long press never fired on the Portal; the Steam menu's Exit game is the forced way)
        "button_escape": on("quit"),
        "left_bumper": on("slot_down"),
        "right_bumper": on("slot_up"),
    }))

    for pid, pname, groups in (
            (0, "Default", {0: "button_diamond", 1: "dpad", 2: "joystick", 3: "right_joystick",
                            4: "left_trigger", 5: "right_trigger", 6: "switch"}),
            (1, "Preset_1000001", {10: "button_diamond", 11: "dpad", 12: "left_trigger",
                                   13: "right_trigger", 14: "switch"})):
        w.open("preset")
        w.kv("id", str(pid))
        w.kv("name", pname)
        w.open("group_source_bindings")
        for gid, source in groups.items():
            w.kv(str(gid), source + " active")
        w.close()
        w.close()
    w.open("settings")
    w.close()
    w.close()
    return w.text()


def layouts(db):
    """{file name: text} of every layout: the standard pair and each keyed emulator's."""
    out = {}
    for face in POSITION_OF:
        out[f"emulation-{face}.vdf"] = layout(face)
        for eid, emu in db["emulators"].items():
            if "keys" in emu:
                out[f"emulation-{face}-{eid}.vdf"] = layout(face, K.keymap(emu), emu["name"])
    return out


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "systems.json")
    with open(path) as f:
        db = json.load(f)
    for name, text in layouts(db).items():
        with open(os.path.join(out, name), "w") as f:
            f.write(text)
