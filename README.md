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
| `scripts/build-firmware.sh` | Portal firmware: ROCKNIX extra-firmware (DSPs, amp, topology, WCN7850) + linux-firmware GPU/BT → `out/firmware/` |
| `scripts/build-image.sh` | rootless SD image: deckard packages via pacman in a user namespace (qemu binfmt), \KERNEL boot.img → `out/kettle-DATE.img` |
| `scripts/mkbootimg.py` | Android boot.img v0 writer (byte-identical to AOSP mkbootimg for our args) |
| `image/` | `pacman.conf` (deckard `mash-20240428.1` + `release-0.4` hotfixes), `packages.txt` |
| `device/odin2portal/` | rootfs overlay (s2idle, power key, first-boot grow, sshd) + ALSA UCM patches |
| `scripts/build-packages.sh` | rootless makepkg in an aarch64 chroot → local `[kettle]` repo (installed ahead of Valve's) |
| `scripts/push-kernel.sh` | install out/kernel on a running Portal over SSH (keeps previous kernel as a boot entry) |
| `packages/` | our PKGBUILDs: `kscreen` (Display Settings, absent from all deckard snapshots), `mangohud` (Valve's deckard build + Portal sensors for the Steam performance overlay), `plasma-keyboard` (desktop on-screen keyboard), `decky-loader` + `kettle-decky-plugins` + `kettle-framegen` + `lsfg-vk` + `optiscaler-arm64ec` (Game Mode plugins, below) |
| `tools/` | `bc` shim; `qemu-aarch64-static` (extracted from Arch's package, not installed) |

Build (x86_64 host, no root needed):
```sh
scripts/build-kernel.sh      # ~3 min on 32 cores
scripts/build-firmware.sh
scripts/build-packages.sh    # our own packages (packages/*/PKGBUILD) -> out/repo/aarch64
scripts/build-image.sh       # reads WIFI_SSID/WIFI_PSK/SSH_PUBKEY from local.env (gitignored)
```
Flashing and the hardware checklist: [docs/TESTING.md](docs/TESTING.md).
Installing to the internal storage next to Android (Kettle Installer), with backup and
restore: [docs/INTERNAL-INSTALL.md](docs/INTERNAL-INSTALL.md).

## Status
- [x] Kernel 7.2.7 + 82 patches builds; Portal DTB with panel (ICNA3512), rsinput gamepad,
      HTR3212 LEDs, haptics, s2idle suspend patch set, SDR104 microSD, WCN7850 SID fix.
- [x] Boots on hardware via U-Boot (systemd-boot/extlinux) and the ROCKNIX ABL path
- [x] Plasma 6.2.5 desktop (SteamOS desktop mode), audio (UCM alias fix), display scale 1.5
- [x] Steam: Valve's arm64 client + own handheld Game Mode session (gamescope DRM), steamos-manager switching
- [x] Desktop mode: plasma-keyboard on-screen keyboard (KWin input method) and gamepad mouse mode (below)
- [ ] Game Mode plugins: Decky Loader with Frame Generation (kettle-framegen, lsfg-vk) and Upscaling (FSR 1, SGSR 2) — built, not yet validated on hardware
- [ ] InputPlumber (Steam Deck controller emulation for the rsinput pad)
- [ ] Boot chain: ESP with `BOOTAA64.EFI` (steamcl/GRUB, A/B) — or boot.img v0 `KERNEL` for first bring-up
- [ ] Firmware package: linux-firmware-qcom (a740/gmu/zap) + Portal ADSP/CDSP/topology blobs
- [ ] Mirror the pinned deckard repos locally (Valve prunes snapshots)
- [ ] Own packages: kernel, firmware, handheld gamescope session (DRM backend), inputplumber + AYN mapping,
      ALSA UCM for `AYN-Odin2`, fan curve, steamos-manager device TOML, powerbuttond hwdb
- [ ] Suspend: s2idle validation on hardware (wake sources, rsinput/Wi-Fi/panel resume, drain)
- [ ] Image: A/B btrfs rootfs + RAUC with our own keyring/compatible (`kettle-aarch64`)

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

## Game Mode plugins
Decky Loader runs natively (system Python, `plugin_loader.service`) with its self-updater
patched out; our plugins sit in `/usr/share/decky/plugins` and are linked into
`~/homebrew/plugins`. Both are per game: a game picker at the top of each Quick Access panel
starts on the running game and lists every installed game, so a game can be set up before
it is launched. Settings are kept when a game is turned off.

- **Frame Generation**, per game with one of two engines (Proton ARM64 games use the native
  Vulkan loader, so both are aarch64 Vulkan layers):
  - **Kettle** (`packages/kettle-framegen`, ours): runs on the game's own VkDevice. Each
    presented frame is copied to a history, a luma pyramid gives block motion between it and
    the previous frame (coarse to fine, vectors centred between the two frames), and 1–3
    in-between frames are warped from both, each pixel choosing between neighbouring block
    vectors and zero (keeps motion edges and HUDs clean), then presented ahead of the real
    one with FIFO. Loaded only with `KETTLE_FG=1` in the game's launch options; settings in
    `~/.config/kettle-framegen/<appid>.conf`, reread live. `KETTLE_FG_STATS=1` logs its GPU
    time, `KETTLE_FG_DUMP=<dir>` saves one set of previous/generated/current frames.
    Also tested on a desktop RADV GPU (Vulkan validation and sync validation clean, 8- and
    10-bit swapchains).
  - **Lossless Scaling** through the `lsfg-vk` layer, when the user has it.

  Kettle is the default (tested with Skyrim SE: 30 fps base, a solid 60 shown at 2×, 2.7 ms
  of GPU per rendered frame at 1280×720); Lossless Scaling is a per-game choice.
  On/off, multiplier 2–4×, flow scale, V-Sync (FIFO) pacing, swapchain image count, gamescope
  WSI bypass; Lossless Scaling also has performance mode and FP16 (all games). Settings live
  in the plugin's `games.json`; lsfg-vk games get an lsfg-vk profile in
  `~/.config/lsfg-vk/conf.toml` matched by `SteamAppId`, and `env -u DISABLE_LSFGVK` in their
  launch options (the session disables that layer everywhere else).
  Multiplier and flow scale apply live (and performance mode with lsfg-vk). Turnip's UBWC tile
  compression on the images lsfg-vk shares with the game gives blocky generated frames on the
  Adreno 740, so lsfg-vk games also get `TU_DEBUG=noubwc` (per-game "Artifact fix" toggle, on by default;
  tested with Skyrim SE: artifacts gone, 40–50 fps shown at 2×). The base frame rate is capped
  per game inside the renderer (`DXVK_CONFIG` `dxgi/d3d9.maxFrameRate`, `VKD3D_FRAME_RATE`):
  Steam's own limiter is enforced by gamescope on every presented frame, generated ones
  included, so it halves the real frame rate. The default, **Auto**, measures each game: our
  mangoapp (`packages/mangohud` 0005) writes the focused app's frame rate to
  `$XDG_RUNTIME_DIR/kettle-fps`, the plugin divides it by the multiplier while lsfg-vk is
  loaded, and after each session picks the highest evenly paced cap the game held (refresh a
  multiple of cap × multiplier: 60/30/20/15 at 2× on 120 Hz), probing one step up when it sat
  at its cap and not retrying steps it couldn't hold. 3×/4× from a ~30 fps base warp visibly,
  so the multiplier stays the user's choice. The Lossless Scaling engine needs Lossless
  Scaling from Steam, installed with Proton and switched to the **lsfg-vk** beta branch (it
  provides `lsfg-vk.dll`); nothing of it is shipped.
- **Upscaling**: gamescope FSR 1 per game: render resolution (Steam's per-game resolution
  override), and Steam's Sharp (FSR) filter and sharpness for the running game.
  **SGSR 2** per game through OptiScaler, for DX11/DX12 games with DLSS, FSR 2+ or XeSS: the
  game's upscaler inputs go to Qualcomm's Snapdragon Game Super Resolution 2, a temporal
  upscaler tuned for Adreno. Upstream OptiScaler is x86-64 and its Detours hooks fault on Proton
  ARM64's ARM64EC dxgi/DXVK/winevulkan (Skyrim SE), so `packages/optiscaler-arm64ec` builds
  the [Sloptiscaler](https://github.com/justradical/Sloptiscaler) fork as an ARM64EC DLL
  (llvm-mingw), which runs natively inside the FEX-emulated game and adds the SGSR 2 backend.
  SGSR 2 is the only backend there: FSR 2/3 links against stubs, and XeSS/DLSS and the frame
  generation runtimes are x86-64 vendor binaries. Tested with Deep Rock Galactic (DX12, DLSS
  through Streamline, NVIDIA spoofing on): SGSR 2 1279×720 → 1920×1080 at DLSS Quality, image
  good. Vulkan games are untested. Turning it on
  copies OptiScaler into the game's folder (game folder and proxy DLL name are chosen in the
  panel, `dxgi.dll` by default) and adds `WINEDLLOVERRIDES=<proxy>=n,b` to its launch options;
  turning it off removes both and restores any file it moved aside. It can't stay in the folder
  while off, since Proton sets dxgi/d3d12 to native and would load it. The game's
  `OptiScaler.ini` (render scale, RCAS sharpening, NVIDIA spoofing so games offer DLSS,
  overlay key) is parked in the plugin's settings while the game is off.

Licensing: kettle-framegen is ours (BSD-3-Clause). lsfg-vk is CC BY-NC-ND 4.0, so
`packages/lsfg-vk` must stay patch-free and the image non-commercial while it ships.

## Suspend
SM8550's TrustZone has no PSCI SYSTEM_SUSPEND, so there is no deep/S3; the target is s2idle
(`mem_sleep_default=s2idle`, systemd `MemorySleepMode=s2idle`) with the wake-source and
cluster-sleep patches in `20-sm8550` (02xx, 10xx). Not yet validated on a Portal by anyone.
