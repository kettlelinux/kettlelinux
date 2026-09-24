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
| `packages/` | our PKGBUILDs: `kscreen` (Display Settings, absent from all deckard snapshots), `mangohud` (Valve's deckard build + Portal sensors for the Steam performance overlay) |
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
- [ ] InputPlumber (Steam Deck controller emulation for the rsinput pad), on-screen keyboard
- [ ] Boot chain: ESP with `BOOTAA64.EFI` (steamcl/GRUB, A/B) — or boot.img v0 `KERNEL` for first bring-up
- [ ] Firmware package: linux-firmware-qcom (a740/gmu/zap) + Portal ADSP/CDSP/topology blobs
- [ ] Mirror the pinned deckard repos locally (Valve prunes snapshots)
- [ ] Own packages: kernel, firmware, handheld gamescope session (DRM backend), inputplumber + AYN mapping,
      ALSA UCM for `AYN-Odin2`, fan curve, steamos-manager device TOML, powerbuttond hwdb
- [ ] Suspend: s2idle validation on hardware (wake sources, rsinput/Wi-Fi/panel resume, drain)
- [ ] Image: A/B btrfs rootfs + RAUC with our own keyring/compatible (`steamportal-aarch64`)

## Suspend
SM8550's TrustZone has no PSCI SYSTEM_SUSPEND, so there is no deep/S3; the target is s2idle
(`mem_sleep_default=s2idle`, systemd `MemorySleepMode=s2idle`) with the wake-source and
cluster-sleep patches in `20-sm8550` (02xx, 10xx). Not yet validated on a Portal by anyone.
