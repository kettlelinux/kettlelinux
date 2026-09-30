# AYN Thor

The Thor has the same SoC as the Odin 2 Portal (QCS8550), so it shares the kernel, the
userspace and almost all of the Portal's configuration. What it adds is a second screen, a lid
and the AYN key. What has been checked on a Thor and what hasn't is below. How the Thor's files
are kept apart from the Portal's, and what both share: [PORTING.md](PORTING.md).

## Building
```sh
scripts/build-kernel.sh                  # the same kernel; its Thor DTB was always built
scripts/build-packages.sh kettle-firmware-ayn kettle-ucm-ayn kettle-power inputplumber gamescope
scripts/build-packages.sh bluez-qt networkmanager-qt modemmanager-qt pulseaudio-qt plasma-pa \
  plasma-nm kinfocenter plasma-systemmonitor plasma-nano kwin plasma-mobile
KETTLE_DEVICE=thor scripts/build-image.sh   # -> out/kettle-<build>-thor.img (+ .raucb)
```
`KETTLE_DEVICE` can also go in `local.env`. Without it the build is for the Portal, as before.

## What is different from the Portal
| Area | Thor | Where |
|---|---|---|
| Device tree | `qcs8550-ayn-thor.dts` (ROCKNIX), with the kernel fan curve now shared with the Portal (`qcs8550-ayn-fan.dtsi`) | `kernel/dts/qcom/` |
| Firmware | `ayn/thor/*` ADSP, amplifier tuning, `AYN-Thor-tplg.bin` | `kettle-firmware-thor` (`packages/kettle-firmware-ayn`) |
| Audio | card `AYN-Thor` (`ayn-AYNOdin2` under EFI), internal mic on DMIC3 (ROCKNIX `0005_Add-AYN-Thor.patch`) | `kettle-ucm-thor` (`packages/kettle-ucm-ayn`) |
| Power | `thor.toml`, picked by the device tree's compatible; power figures copied from the Portal | `packages/kettle-power` |
| Steam's device | steamos-manager `ayn-thor.toml` (DMI "AYN Odin 2" as the Thor's U-Boot reports it, "AYN Thor", DT `ayn,thor`), in the Thor's image only | `device/thor/overlay/usr/share/steamos-manager` |
| Brightness | Steam's slider sets the top screen (the bottom panel's backlight is named `bottom-panel`, so Steam finds the top one first); the bottom screen has its own, in Quick Access > Screens, and dims with the top one | `40-kettle/1130`, `device/thor/overlay` (`kettle-bottom-brightness`), `kettle-decky-screens` |
| Controller | Steam Deck target as on the Portal, plus the AYN key as Quick Access | `packages/inputplumber/40-kettle-thor.yaml` |
| Game Mode | Steam on the top screen (orientation `right`, output found by its 1080x1920 mode); Plasma Mobile's touch shell on the bottom one, see below | `device/thor/overlay`, `packages/gamescope` 0012-0016 |
| Desktop Mode | both screens, bottom one centred under the top one, each touchscreen mapped to its own screen | `device/thor/overlay` |
| Updates | RAUC compatible `kettle-aarch64-thor`, update variant `thor`: Portal and Thor bundles are refused on each other | `device/thor/device.conf` |

## Verified on a Thor
Booted from SD through U-Boot's EFI (GRUB loads `qcs8550-ayn-thor.dtb`):
- Every device found (`kettle-hwcheck`): both panels, both touchscreens, gamepad, AYN key, lid
  switch, LEDs, haptics, fan, battery, Wi-Fi, Bluetooth, ADSP/CDSP, turnip Vulkan.
- Connectors: top panel (DSI1) `DSI-2`, bottom (DSI0) `DSI-1`. Game Mode runs on `DSI-2`;
  without the bottom-screen shell (below) gamescope switches the bottom panel off (no CRTC,
  backlight powered down).
- Touch: the Thor's dts swaps and inverts the touch axes, which the Portal's doesn't (the kernel
  reports 1920x1080 for the 1080x1920 top panel), so taps landed rotated;
  `LIBINPUT_CALIBRATION_MATRIX` in `61-kettle-thor-touch.rules` turns them back to the panels'
  own orientation.
- Audio: the Thor's U-Boot reports the Odin 2's SMBIOS product ("AYN Odin 2"), so its card is
  `ayn-AYNOdin2` under EFI; `kettle-ucm-thor` aliases that to the Thor's profile. Speaker path
  and internal mic checked.
- Steam's device: for the same reason steamos-manager can't tell the two apart by DMI; each
  image carries only its own device file (`device/*/overlay/usr/share/steamos-manager`).
- Brightness: Steam's slider drives the first backlight in `/sys/class/backlight`. That was the
  bottom panel's (`ae94000.dsi.0`, first both alphabetically and in sysfs order); the bottom
  panel's backlight is now named `bottom-panel` (its dts `label`, `40-kettle/1130`), which sorts
  after the top one's (`ae96000.dsi.0`) both ways, so the slider drives the top screen.
- Controller: InputPlumber builds "AYN Thor (Kettle)" from the pad and the AYN key, Deck target.
- Power: `kettle-powerd` uses `thor.toml`; the TDP limit works on the charger (stress-ng at 5 W
  caps the clusters at 1344/1785/1977 MHz). The kernel fan curve works (`qcs8550-ayn-fan.dtsi`).
- Suspend: `kettle-suspendtest` freezer, devices and RTC-woken s2idle stages, and a 5-cycle
  `systemctl suspend` soak; pad, touchscreens, panel and Wi-Fi fine after.
- Internal storage matches what the Kettle Installer expects (UFS LUN 0 `/dev/sda`, userdata
  last, `loader_a/b`, `misc`).

## The bottom screen in Game Mode
gamescope drives one screen. Game Mode's gamescope keeps the top panel and **leases** the
bottom one's connector (`--lease-connector DSI-1`), handing the lease over
`$XDG_RUNTIME_DIR/gamescope-lease.sock`. `kettle-bottom-screen.service` runs a second
gamescope on it (`--drm-lease-client`), and in that a KWin of its own with Plasma Mobile's
shell (`usr/lib/kettle/bottom-screen`, `bottom-shell`). The same mechanism as Bazzite's
(OpenGamingCollective gamescope) and Armada's on the Thor; see `packages/gamescope/PKGBUILD`.
- Touch: Game Mode's gamescope never passes the bottom touchscreen to Steam
  (`--ignore-touch-device bottom_touchscreen`); it forwards its touches to the bottom gamescope
  over the lease socket. KWin nested in an X server needed a fix to take touches at all
  (`packages/kwin`).
- Its settings stay apart from the desktop's (`~/.config/kettle/bottom-shell`), and it runs
  on its own session bus, so nothing in it handles brightness or suspend next to Steam. Its
  caches are its own too (`~/.cache/kettle/bottom-shell`): KDE's app database would otherwise
  be one file for both. The shell is scaled 2x (`BOTTOM_SHELL_SCALE`), set in its KWin's output
  settings: nested in X, KWin's `--scale` enlarges its window instead.
- Its KWin runs without explicit sync (`KWIN_NO_EXPLICIT_SYNC=1`, `packages/kwin` 0002):
  nested in X, its clients hung with it (Firefox froze, the panels stopped drawing, plasmashell
  aborted in libwayland). It runs its own Xwayland, so X11 apps (Heroic) are its windows, not
  the bottom gamescope's.
- Apps started there use the desktop's settings (`~/.config`, linked in), so Firefox has one
  profile; only KWin's and Plasma's own settings are kept apart.
- The shell's own screen comes back if it ends or crashes (`Restart=always`, 5 times a minute).
- Quick Access > Screens (`kettle-decky-screens`) turns the bottom screen on or off (kept across
  reboots) and sets its brightness (`~/.config/kettle/bottom-screen.json`).
  `kettle-bottom-brightness.service` applies it, and dims the bottom screen with the top one when
  Steam dims it for idleness (the top backlight falling with no input for a few seconds);
  touches on the bottom screen count as input for Steam's dimming (gamescope 0018).
- `GAMESCOPE_BOTTOM_SCREEN=0` in `~/.config/kettle/gamescope.conf` leaves the bottom screen off
  too. So does any failure to lease it: the bottom gamescope then exits.
- Plasma Mobile is built at deckard's Plasma version (6.2.5), which needed networkmanager-qt
  and modemmanager-qt at deckard's KF6 version (6.14; deckard ships 6.1), bluez-qt (which
  deckard lacks: the shell's QML module imports it, and without it none of the shell loads),
  and plasma-pa 6.2.5 with pulseaudio-qt (deckard's plasma-pa is 6.0.4, whose QML API the
  shell's volume controls outgrew). plasma-pa 6.2.5 is the desktop's volume applet too.
  deckard's other Plasma apps left at 6.0.4 are built at 6.2.5 as well: plasma-nm (the shell's
  Wi-Fi settings), kinfocenter and plasma-systemmonitor (neither started with deckard's 6.2.5
  libraries, on the desktop too).

## Firefox's hardware video decoding
Both devices have the SM8550's iris decoder (`&iris` in `qcs8550-ayn-common.dtsi`), which
FFmpeg reaches through its `*_v4l2m2m` decoders. Three pieces make Firefox use it:
- **`ffmpeg-v4l2`**: Firefox's V4L2 path takes only DRM-PRIME frames, which stock FFmpeg
  (Valve's 7.0 too) never outputs (Firefox logs "Got non-DRM-PRIME frame from FFmpeg V4L2",
  Mozilla bug 1852765). This is Raspberry Pi's FFmpeg fork (8.1), in `/usr/lib/ffmpeg-v4l2`
  beside Valve's: Firefox 152 loads the newest libavcodec it finds (`.so.62`, this one);
  everything else links Valve's `.so.61`.
- **`physmem-shim.so`** (`kettle-firefox-desktop`): on the first hardware frame, Firefox's
  decoder process (RDD) makes a GL texture from it to check dmabufs work. Valve's Mesa is zink
  only (GL on turnip); zink won't start without the RAM size, which glibc reads with
  `sysinfo()`, and the RDD sandbox answers that with EPERM. The check failed and Firefox
  decoded in software. The shim, preloaded by the `kettle-firefox` launcher (menu entry and
  `/usr/local/bin/firefox`), answers with the size read before the sandbox starts.
  `/usr/lib/firefox/firefox` started directly skips it and decodes in software.
- **Two rpi-ffmpeg patches** (`packages/ffmpeg-v4l2`): 0001 stops sending the extradata
  Firefox passes for VP8/VP9/AV1 (the container's vpcC/av1C record) in front of the first
  frame; iris skipped the first keyframe for it, and everything up to the next one. 0002 drops
  the empty, error-flagged capture buffers iris returns for frames that are decoded but not
  shown (VP9/AV1 hidden frames); they reached Firefox as frames with no timestamp, and video
  stopped there. YouTube, which restarts the decoder at every resolution change, played sound
  over a still picture until both were fixed.

Tested on a Thor, sandbox on: 1080p H.264 (600/600 frames), VP9 (300/300) and AV1 (300/300)
files, and YouTube in VP9 and AV1 at 30 fps, all on iris, the decoder process at ~4% CPU.
Iris decodes H.264, HEVC, VP9 and AV1, not VP8. Known limits in Firefox 152: a second codec in
the same session can fall back to software (bug 2071471, fixed in 159), and some videos cropped
at the right edge show green bars (bug 2014641).

## Still to check, by hand
1. **The ROCKNIX ABL path**: whether its *Device model* setting offers a Thor (all AYN boards
   report the same msm-id and board-id).
2. **microSD speed.** The Thor stays on the stock `sdhc_2` node (SD High-Speed, ~13 MB/s); the
   Odin 2 family's SDR104 node (`qcs8550-ayn-odin2-sd.dtsi`, ~85 MB/s) was never tested on a
   Thor. Try it with a known-good card to fall back to: an SD boot needs the slot to work.
3. **Touch by hand**, both screens, Game Mode and desktop, and the desktop's screen layout.
   Desktop mode after Game Mode: the bottom touchscreen still works there.
4. **The bottom screen in Game Mode** (none of it has run on hardware):
   - `journalctl --user -u gamescope-session -u kettle-bottom-screen`: "lease-connector: leased
     'DSI-1'", "sent lease fd", "companion requested touch input"; Steam's frame rate and
     upscaling on the top screen unchanged.
   - Taps land where touched on the bottom screen, corners too; the shell's swipe gestures
     (task switcher, quick settings) and the on-screen keyboard work; apps open there
     fullscreen. Bottom touches never reach Steam.
   - `systemctl --user stop kettle-bottom-screen`: the panel goes dark (not a frozen frame);
     `start` brings it back; a killed bottom gamescope restarts. Restarting Steam leaves it be.
   - Suspend and resume, and Desktop Mode and back a few times: both screens come back.
   - Wi-Fi and the desktop's network settings still work with the newer networkmanager-qt.
   - Battery drain with the shell idle against `GAMESCOPE_BOTTOM_SCREEN=0` (`kettle-powertest`).
5. **Brightness by eye**: Steam's slider on the top screen only, Screens' slider on the bottom
   one, both screens dimming together when idle and coming back on a touch on either; the low
   end (the Portal's panel needed a floor, `40-kettle/1120`).
6. **Buttons**: the AYN key as Quick Access, the lid (logind's default: suspend on close), power
   key suspend and wake.
7. **Power on battery**: `kettle-powertest`; the right TDP range for the Thor (`thor.toml` has
   the Portal's 4-18 W), charge limit support.
8. **Headphones** and the speakers by ear.
9. **Internal install** with the Kettle Installer.
10. **Firefox's hardware video decoding** (above): files and YouTube checked on a Thor.
    - Longer playback, seeking, quality changes and fullscreen: no stall, no corrupt frames.
    - `MOZ_LOG="FFmpegVideo:5" firefox`: "V4L2 Got one frame" keeps counting, no "failed to
      create texture" (the shim missing) and no fallback to a software codec.
    - HEVC (iris decodes it; not tried yet) and the Portal.
