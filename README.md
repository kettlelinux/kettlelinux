# Kettle Linux

A SteamOS-like distro for the AYN Odin 2 Portal (Snapdragon 8 Gen 2, SM8550/QCS8550):
a patched mainline kernel plus Valve's SteamOS "deckard" (Steam Frame) aarch64 userspace.

## Layout
| Path | What |
|---|---|
| `kernel/kernel.conf` | pinned kernel.org source (7.2.7 + sha256) |
| `kernel/patches/` | ordered patch stack — provenance in `kernel/patches/README.md` |
| `kernel/dts/` | Odin 2 family device trees (ROCKNIX / Teguh Sobirin) |
| `kernel/config/` | `base.config` (ROCKNIX SM8550) + `steamos.config` fragment; `generated.config` is the result |
| `scripts/build-kernel.sh` | fetch, patch (`--fuzz=0`), config (asserts every fragment option survived), LLVM cross-build → `out/kernel/` |
| `scripts/refresh-patches.sh` | rebase the stack's context onto a new pinned kernel |
| `scripts/mirror-repos.sh` | freeze Valve's deckard repos into `cache/mirror/` (what our builds use, or `--full`); builds install from it once it exists, or from `KETTLE_MIRROR=<url>` |
| `scripts/build-image.sh` | rootless release build: deckard packages via pacman in a user namespace (qemu binfmt) → system image, SD card image (SteamOS A/B layout) and signed update bundle, `out/kettle-BUILDID-odin2portal.{img,raucb,castr}` |
| `scripts/publish-update.sh` | add a build to the update server tree (`out/update-server`, static files) with Valve's own server tool |
| `scripts/mkbootimg.py` | Android boot.img v0 writer (byte-identical to AOSP mkbootimg for our args) |
| `image/` | `pacman.conf` (deckard `mash-20240428.1` + `release-0.4` hotfixes), `packages.txt` |
| `device/odin2portal/` | rootfs overlay (s2idle, power key, first-boot grow, sshd) |
| `scripts/build-packages.sh` | rootless makepkg in an aarch64 chroot → local `[kettle]` repo (installed ahead of Valve's); downloaded sources are kept in `cache/src/<name>/` and reused |
| `scripts/push-kernel.sh` | install out/kernel into the running slot of a Portal over SSH (development) |
| `packages/` | our PKGBUILDs: `steamos-efi` + `steamos-customizations-kettle` (Valve's SteamOS A/B update system, built for arm64: [docs/UPDATES.md](docs/UPDATES.md)), `inputplumber` (Steam Deck controller emulation), `kettle-firmware-odin2portal` (ROCKNIX extra-firmware DSPs, amp, topology, WCN7850 + linux-firmware GPU/BT, pinned), `kettle-ucm-odin2portal` (ALSA UCM for `AYN-Odin2`), `kscreen` (Display Settings, absent from all deckard snapshots), `mangohud` (Valve's deckard build + Portal sensors for the Steam performance overlay), `plasma-keyboard` (desktop on-screen keyboard), `plymouth` + `kettle-branding` (boot splash, Steam startup movie, Plasma splash), `decky-loader` + `kettle-decky-plugins` + `kettle-framegen` + `optiscaler-arm64ec` (+ build-only `directx-shader-compiler`) + `gamescope` (SGSR 1) (Game Mode plugins, below), `kettle-power` + `kettle-power-applet` (power, clocks and fan behind Steam's Performance panel, the Power plugin and the desktop's Power applet, below), `kettle-welcome` (Desktop Mode welcome and hub), `kettle-firefox-desktop` (menu entry, icons and default-browser setting for Valve's bare `firefox`; the taskbar's "Install Chromium" placeholder is left out via `NoExtract`), `wine` + `fex-emu-wine` + `dxvk` + `vkd3d-proton` + `winetricks` + `cabextract` + `lutris` + `heroic-games-launcher` (games outside Steam, below) |
| `tools/` | `bc` shim; `qemu-aarch64-static` (extracted from Arch's package, not installed) |

Build (x86_64 host, no root needed):
```sh
scripts/build-kernel.sh      # ~3 min on 32 cores
scripts/build-packages.sh    # our own packages (packages/*/PKGBUILD) -> out/repo/aarch64
scripts/mirror-repos.sh      # once: freeze Valve's repos locally (~2 GB); later builds use it
scripts/build-image.sh       # reads WIFI_SSID/WIFI_PSK/SSH_PUBKEY/KETTLE_UPDATE_URL from local.env (gitignored)
scripts/publish-update.sh out/kettle-BUILDID-odin2portal.raucb   # to release it as an update
```
Updates work like SteamOS's: whole-image A/B updates, signed, installed by Steam's own
*Check for updates* — see [docs/UPDATES.md](docs/UPDATES.md).
Flashing and the hardware checklist: [docs/TESTING.md](docs/TESTING.md).
Installing to the internal storage next to Android (Kettle Installer), with backup and
restore: [docs/INTERNAL-INSTALL.md](docs/INTERNAL-INSTALL.md).

## Status
- [x] Kernel 7.2.7 + 82 patches builds; Portal DTB with panel (ICNA3512), rsinput gamepad,
      HTR3212 LEDs, haptics, s2idle suspend patch set, SDR104 microSD, WCN7850 SID fix.
- [x] Boots on hardware via U-Boot (systemd-boot/extlinux) and the ROCKNIX ABL path
- [x] Plasma 6.2.5 desktop (SteamOS desktop mode), audio (UCM alias fix), display scale 1.5
- [x] Steam: Valve's arm64 client + own handheld Game Mode session (gamescope DRM), steamos-manager switching
- [ ] Boots straight into Game Mode (`/etc/sddm.conf.d/zz-holo-autologin.conf`); "Start up in" (Game
      Mode or Desktop) on both Welcome pages sets steamos-manager's default login mode — untested on hardware
- [x] Desktop mode: plasma-keyboard on-screen keyboard (KWin input method) and gamepad mouse mode (below)
- [ ] Desktop welcome (Kettle Welcome hub, Gaming Extras from Flathub) and games outside Steam (ARM64EC Wine + FEX + DXVK/vkd3d-proton, Lutris, Heroic) — built, untested on hardware
- [ ] Game Mode plugins: Decky Loader with Frame Generation (kettle-framegen) and Upscaling (gamescope FSR 1/SGSR 1; SGSR 2, Arm ASR, FSR 2.2 via OptiScaler) — SGSR 2 validated in Deep Rock Galactic, the rest built
- [ ] InputPlumber (Steam Deck controller emulation for the rsinput pad): `packages/inputplumber` (0.81.0 from
      source) with `40-kettle-odin2portal.yaml` (Deck target; the button below the right stick is Quick Access),
      run by Game Mode only (`kettle-inputplumber.service`) so the desktop controller keeps the raw pad;
      `kettle-qam-button` remains as a fallback — built, untested on hardware
- [ ] Boot chain: ESP with `BOOTAA64.EFI` = steamcl (Valve's A/B chainloader, built for arm64) → each slot's GRUB;
      the ROCKNIX ABL's `\KERNEL` and U-Boot extlinux follow the newest slot — built, untested on hardware
- [x] Firmware package: linux-firmware-qcom (a740/gmu/zap) + Portal ADSP/CDSP/topology blobs (`kettle-firmware-odin2portal`)
- [x] Mirror the pinned deckard repos locally (Valve prunes snapshots; the hotfix repo isn't a snapshot at all): `scripts/mirror-repos.sh`
- [ ] Own packages: kernel. Done: inputplumber + AYN mapping, firmware, gamescope, ALSA UCM for `AYN-Odin2`
      (`kettle-ucm-odin2portal`), Game Mode power button (Valve's `steamos-powerbuttond`: its hwdb already
      matches `pmic_pwrkey`; runs with Game Mode, untested on hardware)
- [ ] Power: kettle-powerd (TDP budget, profiles, GPU clock, charge limit, fan control via
      steamos-manager remotes.d) + Power plugin (per-game fan curve, core parking). On hardware:
      profiles, GPU clock, fan modes, core parking and the TDP budget (stress-ng 9.2 W held at
      5 W on the charger) work through steamos-manager; not yet checked in Steam's own UI or on
      battery. No charge limit: the charger firmware doesn't support it
- [ ] Desktop Mode Power applet (system tray: profile, TDP, GPU clock, fan, CPU cores) — built,
      tested against kettle-powerd on a fake sysfs, untested on hardware
- [ ] Suspend: s2idle validation on hardware (wake sources, rsinput/Wi-Fi/panel resume, drain)
- [ ] Image: A/B btrfs rootfs + RAUC with our own keyring/compatible (`kettle-aarch64`), SteamOS partition layout,
      read-only root, update bundles and server tree (`publish-update.sh`); internal installs use the same layout —
      built, untested on hardware; no update server yet ([docs/UPDATES.md](docs/UPDATES.md))

## Boot splash, startup movie and Plasma splash
`plymouth` (built by us; no deckard snapshot has it) shows `kettle-plymouth-theme` from early
boot until SDDM starts the session, and again at shutdown: a copper kettle on black with steam
rising from the spout and a progress line under the name. There is no initramfs, so it starts
from the root file system (`plymouth-start.service`). The art is SVG in
`packages/kettle-branding/art`, rendered at build time. The default boot entry uses
`quiet splash`; the **verbose boot** entry (extlinux and systemd-boot menus) shows kernel and
systemd messages instead. The ABL's `\KERNEL` always boots with the splash.

Steam then plays `kettle-steam-startup` in place of its own startup movie: the same picture
building up again, with a boil and a chime, then a fade into Game Mode. It is rendered from
the same art at build time (`render-startup.py`: SVG frames, VP9 + Opus like Valve's movies),
and `run-steam` copies it to `config/uioverrides/movies/steam_os_startup.webm`, the override
Steam checks first. A movie chosen in Settings > Customization > Startup Movie still wins.

Desktop Mode starts with `kettle-plasma-splash`, the same picture as a Plasma (KSplash) QML
scene whose progress line follows Plasma's startup. Plasma puts the global theme's splash
(Valve's Vapor has none) in `~/.config/kdedefaults`, ahead of `/etc/xdg`, so a session env
script (`/etc/xdg/plasma-workspace/env/kettle-splash.sh`) writes it into the user's own
`ksplashrc` when there is none; a splash picked in System Settings > Splash Screen is kept.

Our `plymouth` does not load a gamma table (`packages/plymouth/0001-drm-leave-gamma-alone.patch`):
on the Portal's display controller the table outlives plymouth, and KWin's page flips then
never complete (black screen, "Pageflip timed out").

## Desktop mode controls
`kettle-desktop-controller` (user service, Plasma session only) grabs the gamepad and
drives the pointer and keyboard through uinput. Hold **Select+Start** to toggle it off, e.g.
for a game started from the desktop, and again to turn it back on.

| Input | Action | Input | Action |
|---|---|---|---|
| left stick | pointer | right stick | scroll (both axes) |
| A / R2 | left click (hold to drag) | B / L2 | right click |
| R1 (held) | precise pointer | R3 | middle click |
| X / Home | on-screen keyboard | Y | Enter |
| D-pad | arrow keys | L1 | Escape |
| Start | application menu | Select | Overview |

The on-screen keyboard also pops up by itself whenever a text field gets focus
(`KWIN_IM_SHOW_ALWAYS=1`), and from the keyboard icon in the system tray.

## Desktop welcome and Gaming Extras
`kettle-welcome` is our own Kirigami app (`packages/kettle-welcome/src`), the desktop's welcome
window and a hub to come back to: it opens on a user's first desktop login
(`/etc/xdg/autostart`, `--autostart`; the "Show this window every time the desktop starts"
switch makes that every login, `~/.config/kettle-welcomerc`), and from the application menu as
**Kettle Welcome**. A second start raises the open window (`--page <name>` picks the page).
Pages, in a sidebar:
- **Welcome**: get started (Wi-Fi, change the password, gaming apps, install to internal
  storage), then the other pages and Return to Game Mode, and **Start up in**: Game Mode or
  Desktop (`steamosctl set-default-login-mode`)
- **Setup**: System Settings modules in their own windows (`kcmshell6`): password and account
  (`kcm_users`; the password starts as `kettle`, which also guards SSH and sudo), Wi-Fi,
  display, sound, power, game controllers, on-screen keyboard, language, date and time,
  appearance, all settings; and an **SSH server** switch (`systemctl enable/disable --now
  sshd`, authorized through the desktop's polkit password dialog) that shows the `ssh` command
  with this device's addresses. Release images start with SSH off.
- **Controls**: the gamepad controls above, the on-screen keyboard, Return to Game Mode
- **Games**: Heroic, Lutris and Steam; adding their games to Game Mode; how Windows games run
- **Gaming Extras**: optional apps, ticked and installed from Flathub for the user only
  (`flatpak --user`, no password). `welcome-flatpak` runs the installs as a transient systemd
  user unit, so they finish even if the window is closed. Also in the menu as **Gaming Extras**
  (`kettle-welcome --page extras`).
- **System**: Kettle Installer (internal storage), Discover, System Monitor, battery, about

`kettle-welcome --screenshot DIR` saves every page as `DIR/<page>.png` and quits (for checking
layouts, e.g. offscreen in the build chroot).

Gaming Extras lists only apps with an aarch64 build on Flathub. RetroArch, Moonlight, BoilR
and Ludusavi start ticked:

| Group | Apps |
|---|---|
| Steam helpers and tools | BoilR, Ludusavi, ProtonUp-Qt, SGDBoop, AntiMicroX, GOverlay, Flatseal, Warehouse |
| Emulators | RetroArch, Dolphin, PPSSPP, Azahar, melonDS, Ryujinx, RPCS3, xemu, Flycast, Rosalie's Mupen GUI, mGBA, MAME, ScummVM, DOSBox Staging |
| Streaming and more | Moonlight, Chiaki4deck, Prism Launcher, Vesktop |

x86-only on Flathub, so left out: PCSX2, DuckStation, Cemu, shadPS4, RetroDECK, Bottles,
Protontricks, Discord, OBS, Parsec.

## Games outside Steam
Windows games outside Steam run the way Proton ARM64 runs them inside Steam: an ARM64EC Wine
with FEX's emulator DLLs translating the x86 code in-process, with no x86 root file system.
- `wine`: Hangover's Wine 11.16 (wine-11.16 + the WoW64 thread-suspend and address-space
  patches Proton ARM64 carries). FEX is the default emulator for both x86-64
  (`libarm64ecfex.dll`, env `HODLL64`) and 32-bit x86 (`libwow64fex.dll`, env `HODLL`;
  Hangover's default is box64's wowbox64, which we don't ship). Prefixes are always 64-bit;
  `/usr/bin/wine64` links to `wine` for Lutris.
- Direct3D: `dxvk` 3.1.1 (D3D 8/9/10/11 and dxgi) and `vkd3d-proton` 3.0.1 (D3D 12), built as
  ARM64EC (x86-64 games; runs natively inside the FEX-emulated process) and i686 (32-bit
  games), as in Proton ARM64. They are build inputs, not image packages: the `wine` package
  installs them in place of Wine's own d3d8/d3d9/d3d10core/d3d11/dxgi/d3d12/d3d12core, stamped
  as Wine builtins, so every prefix (Lutris, Heroic, winetricks, plain `wine`) renders through
  Vulkan on turnip with no per-prefix setup. DirectDraw and D3D 1-7 stay on wined3d. DXVK's
  usual knobs apply (`DXVK_HUD`, `DXVK_CONFIG_FILE`, `VKD3D_CONFIG`, ...).
- `fex-emu-wine`: FEX-2609.1's `libarm64ecfex.dll`/`libwow64fex.dll` (+ Unix side) as Wine
  builtins, and Proton ARM64's FEX defaults in `/usr/share/fex-emu/Config.json` (override in
  `~/.config/fex-emu/Config.json`, per game in `AppConfig/<Game.exe>.json`, or `FEX_*`).
- `lutris` 0.5.22: patched (`0001`) so that on aarch64, which Lutris has no Wine builds for,
  it defaults to the system Wine instead of GE-Proton through umu, and ignores x86 Wine
  versions pinned by install scripts. New users get no Lutris runtime and the system Wine and
  winetricks, with Lutris's own (downloaded, x86) DXVK/VKD3D/nvapi off so they don't replace
  ours in the prefix (`/etc/skel/.local/share/lutris`). python-moddb is not packaged (optional; only
  ModDB-hosted downloads need it).
- `heroic-games-launcher` 2.22.3: built from source for arm64 (Heroic publishes no Linux arm64
  build), with legendary, gogdl and nile built from source and `vulkan-helper` rebuilt in place
  of the committed binary; Electron is upstream's arm64 release (Chromium isn't practical to
  build). New users default to the system Wine, with Heroic's downloaded x86 DXVK/VKD3D and
  anti-cheat runtimes off (`/etc/skel/.config/heroic/config.json`). comet (GOG Galaxy online
  features) is not included.
- `winetricks`, `cabextract`: for both launchers.

## Game Mode plugins
Decky Loader runs natively (system Python, `plugin_loader.service`) with its self-updater
patched out; our plugins sit in `/usr/share/decky/plugins` and are linked into
`~/homebrew/plugins`. Both are per game: a game picker at the top of each Quick Access panel
starts on the running game and lists every installed game, so a game can be set up before
it is launched. Settings are kept when a game is turned off.

- **Frame Generation** (`packages/kettle-framegen`, ours; Proton ARM64 games use the native
  Vulkan loader, so an aarch64 Vulkan layer covers them). It runs on the game's own VkDevice.
  Each presented frame is copied to a history, a luma pyramid gives block motion between it
  and the previous frame (coarse to fine, vectors centred between the two frames), and 1–3
  in-between frames are warped from both, each pixel choosing between neighbouring block
  vectors and zero by how well a three-pixel strip matches (keeps motion edges and HUDs
  clean), then presented ahead of the real one with FIFO. On a scene cut (most blocks
  unmatched) the generated frames are the nearer real frame instead of a blend. Loaded only
  with `KETTLE_FG=1` in the game's launch options; settings in
  `~/.config/kettle-framegen/<appid>.conf`, reread live, including `stats = 1` (GPU time per
  stage in the game's log) and `dump = <dir>` (saves the next previous/generated/current
  frames; `KETTLE_FG_STATS=1` and `KETTLE_FG_DUMP=<dir>` do the same at launch). Tested with
  Skyrim SE (60 fps base, 120 shown at 2×, 1.95 ms of GPU per rendered frame at 1280×720 with
  flow scale 0.5) and Deep Rock Galactic, and on a desktop RADV GPU (Vulkan validation and
  sync validation clean, 8- and 10-bit swapchains).

  On/off, multiplier 2–4×, flow scale (0.5 by default: 0.8 doubles the motion cost on the
  Adreno 740 for no visible gain), V-Sync (FIFO) pacing, swapchain image count, gamescope WSI
  bypass. Settings live in the plugin's `games.json`. Multiplier and flow scale apply live.
  The base frame rate is capped
  per game inside the renderer (`DXVK_CONFIG` `dxgi/d3d9.maxFrameRate`, `VKD3D_FRAME_RATE`):
  Steam's own limiter is enforced by gamescope on every presented frame, generated ones
  included, so it halves the real frame rate. The default, **Auto**, measures each game: our
  mangoapp (`packages/mangohud` 0005) writes the focused app's frame rate to
  `$XDG_RUNTIME_DIR/kettle-fps`, the plugin divides it by the multiplier while the layer is
  loaded, and after each session picks the highest evenly paced cap the game held (refresh a
  multiple of cap × multiplier: 60/30/20/15 at 2× on 120 Hz), probing one step up when it sat
  at its cap and not retrying steps it couldn't hold. 3×/4× from a ~30 fps base warp visibly,
  so the multiplier stays the user's choice. (An lsfg-vk engine, needing the user's own
  Lossless Scaling, was dropped once this one outdid it; the plugin clears the launch options
  it wrote.)
- **Upscaling**: two layers, both per game.
  - **gamescope (any game)**: render resolution (Steam's per-game resolution override) plus
    Steam's scaling filter and sharpness for the running game. Our `packages/gamescope`
    rebuilds deckard's gamescope (same commit, e383171f) with Valve's SGSR 1 backport from
    3.16.29, so Steam's "Sharp" runs Qualcomm's Snapdragon GSR 1 followed by RCAS; our 0009
    adds `gamescopectl steam_sharp_filter fsr|sgsr|…` to choose what Sharp runs (default sgsr).
    Built, not yet run on the device.
  - **OptiScaler (DX11/DX12 games with DLSS, FSR 2+ or XeSS)**: the game's upscaler inputs go
    to a temporal upscaler chosen in the panel: **SGSR 2** (Qualcomm, tuned for Adreno; the
    default), **Arm ASR** (Arm's FSR 2.2-derived mobile upscaler, balanced or quality preset)
    or **FSR 2.2**. Upstream OptiScaler is x86-64 and its Detours hooks fault on Proton ARM64's
    ARM64EC dxgi/DXVK/winevulkan (Skyrim SE), so `packages/optiscaler-arm64ec` builds the
    [Sloptiscaler](https://github.com/justradical/Sloptiscaler) fork as an ARM64EC DLL
    (llvm-mingw), which runs natively inside the FEX-emulated game. Our patches: 0001 guards
    SGSR 2's kernel weight sum, which cancelled to ~0 at some sub-pixel phases and showed as
    vertical strips of black/white pixels moving with each frame while turning; 0002 handles
    display-resolution motion vectors (UE's DLSS plugin default); 0003/0004 add Arm ASR with a
    D3D12 backend for its API and DXIL built from its HLSL (ASR 25.06's performance preset is
    broken upstream, so the panel offers balanced and quality); 0005 builds FSR 2.2.1's DX12
    shaders with Linux dxc instead of AMD's compiler under Wine. dxc comes from
    `packages/directx-shader-compiler` (build-time only; built with CMake's own flags, since
    with makepkg's it segfaults). Tested with Deep Rock Galactic (DX12, DLSS through
    Streamline, NVIDIA spoofing on): SGSR 2 1279×720 → 1920×1080 at DLSS Quality, ~2.2 ms/frame
    GPU (~13% of a 60 fps frame). ASR and FSR 2.2 are built, not yet run on the device. DX11
    games use the 11-on-12 bridge; Vulkan games always get SGSR 2 (the Vulkan SGSR 2 shaders are
    precompiled SPIR-V without 0001/0002, and untested). FSR 3.1+ and XeSS are loaded from
    AMD's/Intel's own DLLs at runtime, which aren't shipped. Turning it on copies OptiScaler
    into the game's folder (game folder and proxy DLL name are chosen in the panel, `dxgi.dll`
    by default) and adds `WINEDLLOVERRIDES=<proxy>=n,b` to its launch options; turning it off
    removes both and restores any file it moved aside. It can't stay in the folder while off,
    since Proton sets dxgi/d3d12 to native and would load it. The game's `OptiScaler.ini`
    (upscaler, render scale, RCAS sharpening, NVIDIA spoofing so games offer DLSS, overlay key)
    is parked in the plugin's settings while the game is off.
  - **AMD FSR 3.1** (optional component, downloaded on request by the Welcome plugin from
    AMD's FidelityFX SDK v2.3.0, pinned sha256): AMD's signed x86-64 DLLs load fine next to the
    ARM64EC OptiScaler under FEX, adding **FSR 3.1** to the upscaler list and **FSR frame
    generation** (from the upscaler's inputs, with optional HUDFix, or the game's own FSR 3 FG).
    The DLLs are copied into a game's folder only while its settings use them. In Deep Rock
    Galactic, FSR 3.1 cost ~3.9 ms/frame more than SGSR 2 and looked the same; its frame
    generation ran (FfxApi FG 3.1.6) but felt choppy, so the Frame Generation plugin remains
    the recommended way to generate frames.
- **Welcome**: a full-screen page that opens once, on the first Game Mode boot (a tour of
  Kettle, Game Mode and the desktop mode controls), then stays reachable from its Quick
  Access panel. Its Welcome tab has **Start up in**: Game Mode (the default) or Desktop,
  steamos-manager's default login mode (`steamosctl`, on the user's session bus). Its setup checklist offers optional components: software that can't be
  shipped in the image, listed
  in `welcome/components.json` with its upstream URL and a pinned sha256, downloaded only when
  the user asks, verified, and unpacked to `~/.local/share/kettle/components/<id>`. The list is
  empty for now; an entry belongs there only when the component can't be built and shipped
  cleanly and a legitimate upstream download exists.
  It also applies game fixes (`welcome/src/fixes.ts`): launch options a game needs to run here
  at all, added once to a game in the library (recorded in the plugin's `fixes.json`, so
  removing one keeps it off). **DOOM Eternal**: its idTechLauncher refuses non-NVIDIA/AMD/Intel
  GPUs ("GPU Validation Failed"), so a `bash -c` wrapper swaps it for `DOOMEternalx64vk.exe`
  in `%command%`; the game itself runs on the Adreno.

Licensing: kettle-framegen and the plugins are ours (BSD-3-Clause).

## Power, clocks and fan
`kettle-powerd` (`packages/kettle-power`, root, system bus `org.kettlelinux.Power1`) is the
only thing that writes CPU caps (`scaling_max_freq`, CPU hotplug), GPU caps (devfreq
`min_freq`/`max_freq`), the fan and the charge limit. Every source of a cap goes through it and
the lowest wins, so nothing fights over the same sysfs file. Device description:
`odin2portal.toml` (frequency tables as read on the Portal; the prime core's 3187.2 MHz only
with CPU boost on). State is kept in `/var/lib/kettle-power/state.json`.

**Steam's own controls** (Quick Access > Performance, per-game profiles included). steamos-manager
relays these to kettle-powerd via `remotes.d/kettle-power.toml`. It has no backend of its own
for them on this hardware, and the device config
`devices/ayn-odin2portal.toml` deliberately leaves them out: a local backend would win over
the remote one and write the same files. It matches on DMI when U-Boot's EFI provides SMBIOS
(`ayn` / `AYN Odin 2`: steamos-manager then ignores `dt.compatible`), else on the device tree.
- **TDP limit** (TdpLimit1, 4–18 W): there is no SoC power limit on Snapdragon, so this is a
  budget for the *whole device's* draw, screen included: battery V×I, or on the charger its
  input × 0.9 minus what goes into the battery (`current_now` updates about every 0.5 s;
  `power_now` is stale). Each second it lowers or raises caps one step, choosing the busier
  unit: the GPU through its OPPs (GPU busy from debugfs `perf_now`, patch 1110) or the CPU
  down a 16-step ladder (every cluster at the same share of its top clock, down to 30%). 18 W
  means no limit. Steam drops it to 5 W for downloads during sleep (`download_mode_limit`).
- **Performance profile** (PerformanceProfile1): Performance (no caps), Balanced, Powersave,
  as per-cluster CPU caps plus a GPU cap.
- **GPU clock** (GpuPerformanceLevel1): auto, or fixed (min = max) at 220–680 MHz.
- **Battery charge limit** (BatteryChargeLimit1): not offered. The Portal's charger
  firmware never answers qcom_battmgr's charge-limit request (`charge_control_end_threshold`
  writes time out after 1 s and read back 0), so `charge_limit = false` in `odin2portal.toml`.
  The code is there for firmware that does (55–100%, charging resumes 5% below).
- **Fan control** (FanControl1): 0 keeps the device tree curve whatever the Power plugin says.

**Power plugin** (`kettle-decky-power`): what Steam has no UI for, per game or for all games,
applied while the game runs (the plugin reports the running game to kettle-powerd):
- fan: automatic (the kernel's step_wise curve from the DTS), a custom curve (6 points, linear
  in between, slows down only 3 °C below a point), or a fixed speed; full speed from 90 °C
  either way. Custom settings switch the fan's thermal zones to the `user_space` governor
  (`CONFIG_THERMAL_GOV_USER_SPACE`) and write `pwm1`; handing back restores step_wise and its
  last level. `ExecStopPost=kettle-powerd --restore` does the same if the daemon dies;
- the prime core on/off, 1–4 performance cores online, and a max clock per cluster;
- a live readout (draw, battery, hottest fan zone, fan RPM, clocks, GPU busy, what Steam has
  set), and the charge limit where the firmware has one.

**Power applet** (`kettle-power-applet`, Desktop Mode): Power (a speedometer) in Plasma's
system tray, in by default, with a readout, the profile, TDP limit and GPU clock Steam has
in Quick Access > Performance, and the Power plugin's fan and CPU core settings. Desktop Mode
has settings of its own, as a game has in Game Mode:
- fan and CPU: the applet makes `desktop` kettle-powerd's active game, so what is set here is
  kept under that key; until something is, Game Mode's all-games settings apply, and **Use
  Game Mode's Settings** goes back to them. When the desktop ends, the Power plugin sets the
  active game again as Game Mode starts;
- profile, TDP limit, GPU clock: device-wide in kettle-powerd, and Steam sets its own again in
  Game Mode, so the applet keeps the desktop's in `~/.config/kettle-powerrc` and sets them
  again when the desktop starts.

It's our own Plasma applet (`package/`, QML) with a small C++ backend (`src/`, QML module
`org.kettle.private.power`) that talks to kettle-powerd over D-Bus; `KETTLE_POWER_BUS=session`
points it at a kettle-powerd on the session bus, as the daemon itself has for testing.

Debugging: `busctl introspect org.kettlelinux.Power1 /org/kettlelinux/Power1`,
`busctl call org.kettlelinux.Power1 /org/kettlelinux/Power1 org.kettlelinux.Power1 GetStatus`,
`steamosctl get-all-properties` (what Steam sees), `journalctl -u kettle-powerd`.

## Suspend
SM8550's TrustZone has no PSCI SYSTEM_SUSPEND, so there is no deep/S3; the target is s2idle
(`mem_sleep_default=s2idle`, systemd `MemorySleepMode=s2idle`) with the wake-source and
cluster-sleep patches in `20-sm8550` (02xx, 10xx). Not yet validated on a Portal by anyone.
