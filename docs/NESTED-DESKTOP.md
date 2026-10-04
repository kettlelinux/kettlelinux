# The desktop in Game Mode

**Desktop** in Steam's library runs Desktop Mode's Plasma inside Game Mode, as a Steam app, like
SteamOS's Nested Desktop. It has the same settings, apps and files as Desktop Mode. Opening it
needs no session switch, and the Steam button goes back to Steam with the desktop still running.
Logging out, the desktop's **Return to Gaming Mode** icon, or Steam's **Exit Game** closes it.

| Part | Where |
|---|---|
| The launcher | `device/common/overlay/usr/lib/kettle/nested-desktop` |
| Autostarts left out of it | `device/common/overlay/usr/share/kettle/nested-desktop/xdg/autostart` |
| Controller layout | `device/common/overlay/usr/share/kettle/nested-desktop/controller.vdf` |
| On-screen keyboard shortcut | `usr/lib/kettle/osk-toggle`, `usr/share/applications/org.kettle.osk-toggle.desktop` |
| Library entry, artwork and layout | Welcome plugin, `packages/kettle-decky-plugins/welcome/src/desktop.ts` |
| Artwork | `kettle-desktop-art`, `packages/kettle-branding/render-desktop-art.py` |

## How it runs
- `startplasma-wayland` runs on a session bus of its own, with its own `XDG_RUNTIME_DIR`
  (`$XDG_RUNTIME_DIR/nested-desktop`), so it finds no systemd user manager. Desktop Mode's
  services stay off (`kettle-desktop-controller`, ...), and nothing in it answers to Steam's.
  The system bus (NetworkManager, BlueZ, logind) is shared, and audio goes to the session's
  PipeWire through links in the runtime dir.
- KWin uses its windowed X11 backend, as a window of gamescope's Xwayland. The size comes from
  gamescope's screen (`xdpyinfo`). The scale is the desktop's own for the built-in panel (from
  `kwinoutputconfig.json`; `NESTED_DESKTOP_SCALE` overrides it). It is written to the nested
  output's entry (`X11-0`) before every start, next to the real outputs' entries, which it
  leaves alone. As for the Thor's bottom screen: KWin runs without explicit sync
  (`KWIN_NO_EXPLICIT_SYNC=1`, `packages/kwin` 0002), and gamescope's Vulkan layer is off for apps
  started there (`DISABLE_GAMESCOPE_WSI=1`).
- Only the login's own environment reaches it: Steam's runtime libraries, overlay preload, cursor
  and `xim` input method don't.
- Autostarts it leaves out, through `XDG_CONFIG_DIRS` (hidden entries):
  - Steam: it's already running.
  - powerdevil: it would dim and suspend next to Steam.
  - Kettle Welcome.
  - Baloo's file indexer: it would run during Game Mode, costing power.
- Everything the desktop started carries a mark in its environment
  (`KETTLE_NESTED_DESKTOP=<launcher pid>`), and ends with it. Without that, daemons that outlive
  its session bus (geoclue's agent, ...) kept Steam showing the app as running.
- Return to Gaming Mode runs `steamosctl switch-to-game-mode`, which fails on the private bus,
  so it falls back to logging out: the desktop closes and Steam comes back.
- Valve's own version (`steamos-nested-desktop` in `steamdeck-kde-presets`, sized for the
  Deck's 1280x800 screen) is left out of the image (`NoExtract`, `image/pacman.conf`).

## The library entry
The Welcome plugin adds it once per device, after the first sign-in, as "Desktop":
- its artwork (Steam's asset types 0-3) and icon;
- the desktop's controls as its controller layout, for the device's own pad.

Steam keeps a layout per controller. Steam's API selects it as
`local:///usr/share/kettle/nested-desktop/controller.vdf`; Steam reads the file from there,
and records the choice in the pad's `configset_<serial>.vdf` under the entry's lowercased name.
Each step is recorded (`welcome.json`), so an entry the user removes, or a layout they change,
stays that way.

## Controls
The desktop's own mapping (`desktop-controller`), in Steam Input:

| Input | Does |
|---|---|
| Left stick | pointer; R1 held: precise (slower) |
| Right stick | scroll (repeats while held); click: middle click |
| A, R2 | left click |
| B, L2 | right click |
| X | on-screen keyboard: sends Ctrl+Alt+Meta+F12, the shortcut of `org.kettle.osk-toggle.desktop` |
| Y | Enter |
| L1 | Escape |
| D-pad | arrow keys |
| Start | application menu (Meta) |
| Select | Overview (Meta+W) |
| Start held | gamepad controls, for games run from the desktop (held again: back) |

The Steam button and Quick Access stay Steam's. Steam Input can only send keys, so X reaches
the keyboard through a global shortcut: `osk-toggle` makes the same KWin calls as
`desktop-controller`. The shortcut works in Desktop Mode too.
