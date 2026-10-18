# Radxa Orion O6N

The Orion O6N is Radxa's mini-ITX board on the CIX P1 (CD8160, "Sky1"). It is the first Kettle
machine that is neither a handheld nor Qualcomm. Its firmware is UEFI and describes the hardware
with ACPI, so there is no devicetree. The GPU is a Mali-G720 Immortalis (Panthor, Mesa's
Panfrost and PanVK), Game Mode runs on whatever monitor or TV is plugged in, and controllers
connect over USB or Bluetooth. The port is written from the user's Arch Linux work on the board
(`06n-arch`: its kernel, Mesa and power packages, tested on a unit there) but has not run Kettle on
one yet. How its files are kept apart from the handhelds': [PORTING.md](PORTING.md).

## Hardware
| | |
|---|---|
| SoC | CIX P1 CD8160: 8x Cortex-A720 (CPUs 0-1 and 6-11; cpufreq policies 0, 6, 8, 10), 4x Cortex-A520 (CPUs 2-5, policy 2) |
| GPU | Mali-G720 Immortalis (`CIXH5000`), Panthor, CSF firmware arch12.8 |
| Display | Linlon D60 (`linlondp`), HDMI, DisplayPort and USB-C DP (trilin) |
| Video | Linlon VPU (`CIXH3010`, amvx): V4L2 mem2mem decode/encode |
| Network | 2x RTL8125B 2.5 GbE (r8169); M.2 slot for Wi-Fi |
| Storage | NVMe (M.2), USB |
| Firmware | EDK2 UEFI, ACPI with SCMI; SMBIOS "Radxa Computer (Shenzhen) Co., Ltd." / "Radxa Orion O6N" |

## Firmware settings
In the board's UEFI setup (BIOS 1.3.1 or later, as 06n-arch ran):
- Device Manager > O/S Hardware Description Selection: **ACPI**
- Platform Configuration > Compliance > **Enable ACPI SCMI**: on

## Building
```sh
KETTLE_DEVICE=radxa-o6n scripts/build-kernel.sh   # the cix kernel flavour: out/kernel-cix
scripts/build-x86-packages.sh                     # mesa-panfrost and fex-mesa-panfrost
scripts/build-packages.sh kettle-firmware-radxa
KETTLE_DEVICE=radxa-o6n scripts/build-image.sh
```
The image is written to a USB stick or straight to the NVMe drive. The first boot makes rootfs-B
and grows /home on whichever disk it booted from (`REPART=disk`).

## Booting
EDK2 starts steamcl from `\EFI\BOOT\BOOTAA64.EFI` on the esp, which picks the slot and starts its
GRUB, which loads `/boot/Image` and the initramfs with no devicetree (`BOOT=uefi`). There is no
\KERNEL or extlinux, and no ABL to install. The kernel command line has `clk_ignore_unused` in
place of the Qualcomm options (`CMDLINE_SOC`).

## What is different from the other devices
- **Kernel**: a flavour of its own, `kernel/cix` ([its README](../kernel/cix/patches/README.md)):
  CIX's BSP series (cix-linux-main), as ported to 7.2 in 06n-arch, rebased onto the same 7.3-rc7
  as the qcom kernel. Ours on top: Panthor cached GPU memory, the scheduler stall fix, the GPU
  Energy Model and the fan's platform profile (3001-3004, from 06n-arch), `cix_dst`'s overflow
  (3005), `soc_button_array` on ARM64 for the power button (3006) and the VPU driver (3007).
- **Graphics**: `mesa-panfrost` in place of Valve's Turnip-only Mesa: upstream Mesa main with
  06n-arch's PanVK patches (geometry shaders, clip/cull distance, transform feedback, ...), and an
  x86 build of the same for FEX's games (`fex-mesa-panfrost`). Built on the x86_64 side
  (`scripts/build-x86-packages.sh`). Adreno-only packages are left out (`packages.txt`).
- **DXVK**: games get `DXVK_CONFIG=d3d11.maxFeatureLevel=11_0;dxgi.maxDeviceMemory=4096`
  (`/usr/lib/kettle/game-env`): PanVK has no tessellation, and reports ~3/4 of RAM as VRAM. A
  game's own `DXVK_CONFIG` replaces it.
- **Starts in the desktop** (Plasma, as 06n-arch ran it): on 20261018.1 Game Mode (gamescope on
  linlondp + Panthor) gave a black screen while the system kept running. Game Mode is a switch
  away until that is fixed.
- **No built-in gamepad, battery or panel**: no `PAD_NAME`, so no InputPlumber, desktop controller
  or Quick Access button services; Steam takes USB and Bluetooth controllers as they are. Game
  Mode's `gamescope.conf` sets nothing: the monitor's EDID decides.
- **No volume keys**: `CONFIRM_KEYS=none`. Turning SSH on and resetting Kettle ask for the
  user's password, so they are the desktop's (Kettle Welcome, Reset Kettle); Game Mode's Device
  Settings doesn't offer them, and Steam's own Factory Reset is refused there.
- **Games** start on the eight Cortex-A720s (`GAME_CPU_AFFINITY=0xfc3`).
- **Network**: the RTL8125Bs never runtime-suspend (an unplugged one in D3hot panicked the board
  at every login in 06n-arch).
- **Desktop**: KWin draws its own cursor (`KWIN_FORCE_SW_CURSOR=1`), for a cursor plane crash CIX
  reported under wlroots.
- **Sleep**: s2idle, as on the handhelds (deep sleep hangs the board); the power button wakes it.

## Verified on a unit
Nothing yet: no Kettle image has run on an O6N.

## Still to check, by hand
- [ ] boot from USB: steamcl, GRUB without a devicetree, the slot's root, verity
- [ ] Panthor (`Sky1: non-coherent GPU, cached memory` in dmesg), KWin and gamescope on HDMI/DP,
  GBM on the linlondp card through Mesa's kmsro
- [ ] a USB and a Bluetooth controller in Game Mode (no InputPlumber)
- [ ] Steam, a FEX DX11 game (Skyrim SE ran at ~50 fps in 06n-arch), a DX12 game
- [ ] RAUC A/B update on USB, then on NVMe
- [ ] s2idle and the power button; the fan's platform profile; HDMI/DP audio
- [ ] the VPU in Remote Play and Firefox (amvx loads from its ACPI ID, CIXH3010)
- [ ] the gamescope cursor plane (KWin uses a software cursor for CIX's report)
- [ ] kettle-powerd: no description yet (no battery or charger, fan through the platform profile)
- [ ] Reset Kettle and SSH from the desktop ask for the password; Device Settings shows neither
