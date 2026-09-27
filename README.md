# Kettle Linux

A SteamOS-like Linux distro for the **AYN Odin 2 Portal** (Snapdragon 8 Gen 2, SM8550/QCS8550).

Kettle combines a patched mainline kernel with the aarch64 userspace from Valve's SteamOS
"deckard" (Steam Frame). You get Valve's arm64 Steam client, a handheld Game Mode and a
Plasma desktop. Updates work like SteamOS: signed, atomic A/B images installed from Steam's
own *Check for updates*.

> **Status:** early and in active development. Kettle boots on hardware with working display,
> audio, Wi-Fi, controls, Game Mode and Desktop Mode. Several features are built but not yet
> tested on a Portal. See [Project Status](https://github.com/kettlelinux/kettlelinux/wiki/Project-Status).

**Documentation lives in the [wiki](https://github.com/kettlelinux/kettlelinux/wiki).**

## Features

- **Mainline kernel for the Portal**: Linux 7.2 with a pinned patch stack for the panel,
  gamepad, LEDs, haptics, microSD, Wi-Fi and s2idle suspend.
- **SteamOS experience**: Valve's arm64 Steam client with its own handheld Game Mode
  (gamescope), steamos-manager, and switching between Game Mode and Desktop.
- **Atomic A/B updates**: Valve's SteamOS update stack (steamcl, RAUC, atomupd) built for arm64,
  with a read-only root and automatic fallback if an update fails to boot.
  ([docs/UPDATES.md](docs/UPDATES.md))
- **Install to internal storage** next to Android with the Kettle Installer, including backup
  and restore. ([docs/INTERNAL-INSTALL.md](docs/INTERNAL-INSTALL.md))
- **Controller support**: InputPlumber presents the built-in pad to Steam as a Steam Deck
  controller. In Desktop Mode the gamepad works as mouse and keyboard, with an on-screen keyboard.
- **Game Mode plugins** (Decky Loader), all off by default and enabled per game:
  - **Frame Generation**: Kettle's own Vulkan layer, 2–4× with automatic frame rate capping.
  - **Upscaling**: gamescope SGSR 1, and SGSR 2, Arm ASR or FSR 2.2 through an ARM64EC build of OptiScaler.
- **Power control**: TDP budget, performance profiles, GPU clock and per-game fan curves from
  Steam's Performance panel, the Power plugin, or a Desktop Mode tray applet.
- **Games outside Steam**: ARM64EC Wine with FEX, DXVK and vkd3d-proton, plus Lutris and Heroic
  built for arm64.
- **Desktop welcome hub**: setup shortcuts, controls help, and one-click *Gaming Extras*
  (emulators, streaming and tools) from Flathub.
- **Kettle branding**: boot splash, Steam startup movie and Plasma splash, all rendered from source art.

## Getting started

- **Download:** [kettlelinux.org](https://kettlelinux.org)
- **Installing:** [docs/INSTALL.md](docs/INSTALL.md)
- **Testing your own builds:** [docs/TESTING.md](docs/TESTING.md)
- **Building from source:** [Building](https://github.com/kettlelinux/kettlelinux/wiki/Building)
  (x86_64 Linux host, no root needed)
- **Repository layout:** [Repository Layout](https://github.com/kettlelinux/kettlelinux/wiki/Repository-Layout)

## Thanks

Kettle Linux is built on the work of many projects and people. Thank you all.

**Device support and kernel**
- [ROCKNIX](https://github.com/ROCKNIX): SM8550 kernel patches, the Odin 2 device trees,
  [extra firmware](https://github.com/ROCKNIX/extra-firmware) and the [ABL](https://github.com/ROCKNIX/abl)
- Teguh Sobirin: the Odin 2 family device trees
- [pocknix-os](https://github.com/shuuri-labs/pocknix-os): suspend, UFS and SD patches
- Aaron Kling: the upstream "Support AYN QCS8550 Devices" series
- Manivannan Sadhasivam (via NovaDeck), Armada and Thorch: kernel fixes carried in our patch stack
- [The Linux kernel](https://kernel.org) and [linux-firmware](https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git)

**SteamOS and the base system**
- [Valve](https://store.steampowered.com/steamos): SteamOS, the deckard userspace,
  [steamos-efi](https://gitlab.steamos.cloud/holo/steamos-efi),
  [steamos-customizations](https://gitlab.steamos.cloud/holo/steamos-customizations),
  [gamescope](https://github.com/ValveSoftware/gamescope) and Proton ARM64
- [RAUC](https://rauc.io) and [desync](https://github.com/folbricht/desync): update bundles and chunk stores
- [KDE Plasma](https://kde.org/plasma-desktop/), [plasma-keyboard](https://invent.kde.org/plasma/plasma-keyboard)
  and [KScreen](https://invent.kde.org/plasma/kscreen)
- [Plymouth](https://www.freedesktop.org/wiki/Software/Plymouth/)
- [Mesa](https://mesa3d.org) (turnip, the Adreno Vulkan driver)

**Controls, overlays and plugins**
- [InputPlumber](https://github.com/ShadowBlip/InputPlumber) by ShadowBlip
- [MangoHud](https://github.com/flightlessmango/MangoHud)
- [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) by SteamDeckHomebrew
- [Sloptiscaler](https://github.com/justradical/Sloptiscaler), a fork of [OptiScaler](https://github.com/optiscaler/OptiScaler)
- [Snapdragon GSR](https://github.com/SnapdragonStudios/snapdragon-gsr) (Qualcomm),
  [Arm ASR](https://github.com/arm/accuracy-super-resolution-generic-library) and
  [AMD FidelityFX FSR 2](https://github.com/GPUOpen-Effects/FidelityFX-FSR2)
- [DirectXShaderCompiler](https://github.com/microsoft/DirectXShaderCompiler) and
  [llvm-mingw](https://github.com/mstorsjo/llvm-mingw)

**Running Windows games**
- [Hangover](https://github.com/AndreRH/hangover) and [Wine](https://www.winehq.org)
- [FEX-Emu](https://github.com/FEX-Emu/FEX)
- [DXVK](https://github.com/doitsujin/dxvk) and [vkd3d-proton](https://github.com/HansKristian-Work/vkd3d-proton)
- [Lutris](https://lutris.net), [Winetricks](https://github.com/Winetricks/winetricks) and
  [cabextract](https://www.cabextract.org.uk/)
- [Heroic Games Launcher](https://heroicgameslauncher.com) with
  [legendary](https://github.com/legendary-gl/legendary),
  [gogdl](https://github.com/Heroic-Games-Launcher/heroic-gogdl) and
  [nile](https://github.com/imLinguin/nile)

The provenance of every kernel patch is in [kernel/patches/README.md](kernel/patches/README.md),
and each PKGBUILD in [packages/](packages/) links its upstream.

## License
Kettle Linux's own work (the build scripts, device overlay, `kettle-*` packages and docs) is
under the BSD 3-Clause License, in [LICENSE](LICENSE). Everything built from other projects keeps
its upstream license: the patches in `kernel/patches/` and `packages/*/` are under the license
of the project they patch (the kernel's GPL-2.0-only, Valve's SteamOS packages' GPL-2.0+ and
LGPL-2.1+, and so on), and each PKGBUILD's `license=` says what the package it builds is under.
