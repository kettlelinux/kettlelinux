# Steam Portal

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
| `scripts/build-image.sh` | rootless SD image: deckard packages via pacman in a user namespace (qemu binfmt), \KERNEL boot.img → `out/steamportal-DATE.img` |
| `scripts/mkbootimg.py` | Android boot.img v0 writer (byte-identical to AOSP mkbootimg for our args) |
| `image/` | `pacman.conf` (deckard `mash-20240428.1` + `release-0.4` hotfixes), `packages.txt` |
| `device/odin2portal/` | rootfs overlay (s2idle, power key, first-boot grow, sshd) + ALSA UCM patches |
| `scripts/build-packages.sh` | rootless makepkg in an aarch64 chroot → local `[steamportal]` repo (installed ahead of Valve's) |
| `scripts/push-kernel.sh` | install out/kernel on a running Portal over SSH (keeps previous kernel as a boot entry) |
| `packages/` | our PKGBUILDs: `kscreen` (Display Settings, absent from all deckard snapshots), `mangohud` (Valve's deckard build + Portal sensors for the Steam performance overlay), `plasma-keyboard` (desktop on-screen keyboard), `decky-loader` + `steamportal-decky-plugins` + `lsfg-vk` + `optiscaler` (Game Mode plugins, below) |
| `tools/` | `bc` shim; `qemu-aarch64-static` (extracted from Arch's package, not installed) |

Build (x86_64 host, no root needed):
```sh
scripts/build-kernel.sh      # ~3 min on 32 cores
scripts/build-firmware.sh
scripts/build-packages.sh    # our own packages (packages/*/PKGBUILD) -> out/repo/aarch64
scripts/build-image.sh       # reads WIFI_SSID/WIFI_PSK/SSH_PUBKEY from local.env (gitignored)
```
Flashing and the hardware checklist: [docs/TESTING.md](docs/TESTING.md).

## Status
- [x] Kernel 7.2.7 + 82 patches builds; Portal DTB with panel (ICNA3512), rsinput gamepad,
      HTR3212 LEDs, haptics, s2idle suspend patch set, SDR104 microSD, WCN7850 SID fix.
- [x] Boots on hardware via U-Boot (systemd-boot/extlinux) and the ROCKNIX ABL path
- [x] Plasma 6.2.5 desktop (SteamOS desktop mode), audio (UCM alias fix), display scale 1.5
- [x] Steam: Valve's arm64 client + own handheld Game Mode session (gamescope DRM), steamos-manager switching
- [x] Desktop mode: plasma-keyboard on-screen keyboard (KWin input method) and gamepad mouse mode (below)
- [ ] Game Mode plugins: Decky Loader with Frame Generation (lsfg-vk) and Upscaling (FSR 1, OptiScaler) — built, not yet validated on hardware
- [ ] InputPlumber (Steam Deck controller emulation for the rsinput pad)
- [ ] Boot chain: ESP with `BOOTAA64.EFI` (steamcl/GRUB, A/B) — or boot.img v0 `KERNEL` for first bring-up
- [ ] Firmware package: linux-firmware-qcom (a740/gmu/zap) + Portal ADSP/CDSP/topology blobs
- [ ] Mirror the pinned deckard repos locally (Valve prunes snapshots)
- [ ] Own packages: kernel, firmware, handheld gamescope session (DRM backend), inputplumber + AYN mapping,
      ALSA UCM for `AYN-Odin2`, fan curve, steamos-manager device TOML, powerbuttond hwdb
- [ ] Suspend: s2idle validation on hardware (wake sources, rsinput/Wi-Fi/panel resume, drain)
- [ ] Image: A/B btrfs rootfs + RAUC with our own keyring/compatible (`steamportal-aarch64`)

## Desktop mode controls
`steamportal-desktop-controller` (user service, Plasma session only) grabs the gamepad and
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

- **Frame Generation** (Lossless Scaling through the `lsfg-vk` Vulkan layer; Proton ARM64
  games use the native Vulkan loader): on/off, multiplier 2–4×, flow scale, performance
  mode, V-Sync (FIFO) pacing, swapchain image count, gamescope WSI bypass; FP16 applies to
  all games. Settings live in the plugin's `games.json`; games that are on get an lsfg-vk
  profile in `~/.config/lsfg-vk/conf.toml` matched by `SteamAppId`, and `env -u
  DISABLE_LSFGVK` in their launch options (the session disables the layer everywhere else).
  Multiplier, flow scale and performance mode apply live. Needs Lossless Scaling from Steam,
  installed with Proton and switched to the **lsfg-vk** beta branch (it provides
  `lsfg-vk.dll`); nothing of it is shipped.
- **Upscaling**: gamescope FSR 1 (per-game render resolution; Steam's Sharp filter and FSR
  sharpness for the running game), and OptiScaler for DX11/DX12 games with DLSS/FSR 2+/XeSS.
  OptiScaler is copied next to the game's exe as a proxy DLL and switched on/off per game with
  `WINEDLLOVERRIDES` in the launch options; its per-game settings (upscaler FSR 3.1/2.2/XeSS,
  forced render scale, RCAS sharpening, FSR frame generation + HUD fix, NVIDIA spoofing,
  overlay key) are the game's own `OptiScaler.ini`. "Remove" restores the game folder exactly.

Licensing: lsfg-vk is CC BY-NC-ND 4.0, so `packages/lsfg-vk` must stay patch-free and the
image non-commercial. OptiScaler (GPL-3.0) is shipped with only its redistributable parts
(no Nukem dlssg-to-fsr3 binary, no Microsoft D3D12Core.dll, no NVIDIA files).

## Suspend
SM8550's TrustZone has no PSCI SYSTEM_SUSPEND, so there is no deep/S3; the target is s2idle
(`mem_sleep_default=s2idle`, systemd `MemorySleepMode=s2idle`) with the wake-source and
cluster-sleep patches in `20-sm8550` (02xx, 10xx). Not yet validated on a Portal by anyone.
