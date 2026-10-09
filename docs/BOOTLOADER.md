# Kettle's own bootloader (u-boot-kettle)

Status: **in testing, not yet the documented install path.** Until it has been proven on each
device, docs/INSTALL.md and docs/INSTALL-RP5.md keep pointing at the vendors' U-Boot
(`u-boot-ayn.img`, `u-boot-rp5.img`). Both images are on the KETTLE partition.

## Why

Every device boots the same way:

```
stock Qualcomm ABL ─► loader_a/b: U-Boot (an Android boot image) ─► U-Boot EFI
  ─► \EFI\BOOT\BOOTAA64.EFI (steamcl, A/B slots) ─► GRUB ─► kernel   (docs/UPDATES.md)
```

The steps before U-Boot (the ABL, the partition layout, slot bits, fastboot) are in
[BOOT.md](BOOT.md).

Until now, the U-Boot step was the vendors' forks of mainline: AYN's `ayn-sm8550` (unpatched) and
Retroid's `retroidpocket/sm8250` (one Kettle patch). That caused these problems:

- **Boot order on AYN is AYN's.** Its `bootefi bootmgr` follows the BootOrder saved in
  `ubootefi.var`. The RP5 needed a patch for the same thing.
- **One devicetree for every AYN model.** The Thor reports SMBIOS "AYN Odin 2", so
  steamos-manager and the ALSA card name can't tell it from the Portal (docs/THOR.md).
- **Every new port brings another unmaintained vendor fork.**

## What it is

`packages/u-boot-kettle` is mainline U-Boot (a pinned release), built as `qcom_defconfig` +
`qcom-phone.config` + `kettle.config`. Its environment (`kettle.env`) works like this:

- It boots `\EFI\BOOT\BOOTAA64.EFI` from the SD card, else from the internal storage, in that
  fixed order. It uses standard boot with EFI only, so extlinux is never used.
- If standard boot finds nothing, it falls back to `bootefi bootmgr`. This catches internal
  installs whose `kettle-esp` isn't flagged bootable. Standard boot only scans partitions
  flagged LegacyBIOSBootable, or partition 1 when none is flagged.
  `kettle-install-internal` sets that flag on new installs.
- Holding Volume Down, or a failed boot, opens a menu with these entries: boot, SD only,
  internal only, internal storage as a USB drive, fastboot, serial gadget, shell, reset.

On Qualcomm, U-Boot runs on the devicetree appended to it, so the binary is the same for every
device. `scripts/build-image.sh` appends the device's own **kernel** devicetree (`DTB` in
`device.conf`) and wraps the result as an Android boot image, `u-boot-kettle.img`. That file goes
on the KETTLE partition next to the vendor images. U-Boot then fills SMBIOS from that devicetree:
the vendor comes from the first `compatible`, the product from `model`:

| Device | SMBIOS | ALSA card (EFI) |
|---|---|---|
| Odin 2 Portal | `ayn` / `AYN Odin 2 Portal` (was `AYN Odin 2`) | `ayn-AYNOdin2Portal` |
| Thor | `ayn` / `AYN Thor` (was `AYN Odin 2`) | `ayn-AYNThor` |
| RP5 | `retroidpocket` / `Retroid Pocket 5` (unchanged) | unchanged |

The steamos-manager device files and `kettle-ucm-*` already know both the old and the new names.

## Trying it (no write)

From fastboot mode (docs/INSTALL.md):

```
fastboot boot u-boot-kettle.img
```

That starts it once from RAM, and the next boot is the installed loader again. `fastboot flash
loader` writes only the active slot's loader (`loader_a` on a factory device). After a slot
switch (an Android update, `fastboot set_active`), ABL starts `loader_b`, which still holds the
vendor's U-Boot (docs/BOOT.md). To install it:
`fastboot flash loader u-boot-kettle.img`. To go back: flash `u-boot-ayn.img` /
`u-boot-rp5.img` the same way.

What to check:

- [ ] Boots the SD card. With no card, boots the internal install.
- [ ] `cat /sys/class/dmi/id/product_name` shows the device's own name, and Steam shows the
      right device.
- [ ] Audio works (UCM profile found under the new card name).
- [ ] Slot fallback: `holo-bootconf config --image B --set image-invalid 1` boots the other slot.
- [ ] The menu opens with Volume Down. Fastboot and the USB drive mode work from it.

## Research notes (2026-10)

- **Mainline U-Boot on these SoCs.**
  - SM8250 and SM8550 are well supported: clocks, pinctrl, RPMh regulators, UFS, SDHCI,
    USB gadget, PMIC buttons, SMBIOS from DT.
  - SM8650 is mostly there.
  - SM8750 (Odin 3) has no clock driver yet.
  - Display only reuses the framebuffer ABL set up (simplefb). There is no charger or battery
    driver.
  - Capsule updates only know `uefi`/`xbl`/`boot`, not `loader`.
- **What the ABL reports (checked on the Portal).** `hardware_platform` 31, subtype 0: a generic
  board ID. The Portal and Thor are probably indistinguishable to the ABL, so the images are built
  per device rather than picked by board ID.
- **Loader slots** (details in [BOOT.md](BOOT.md)).
  - On the Portal, `loader_a` and `loader_b` hold the same image.
  - The ABL boots `loader_<slot>`, where the slot is the one it picks from `boot_a`/`boot_b`.
  - AYN's ABL never counts boot retries in Loader mode, so no "mark successful" step is needed.
    For the same reason the ABL won't fall back on its own if a new U-Boot fails.
  - Updating U-Boot later means writing the inactive loader slot and switching slots, with a
    switch back by hand in fastboot if it doesn't start. This is not done yet.
- **AYN firmware without a "Loader" choice ("Android" / "UEFI").** On the Odin 3, "UEFI" starts
  `\EFI\BOOT\BOOTAA64.EFI` from the SD card straight from Qualcomm's UEFI. That is steamcl in
  Kettle's image, so it may boot with no U-Boot at all (the kernel may need to reset the display
  controller). This is unconfirmed on the Portal and Thor.
- **ROCKNIX ABL for firmware without Loader (decided 2026-10-09).** Devices whose fastboot menu
  has no Loader choice use the ROCKNIX ABL, installed from Android with ROCKNIX's scripts.
  ROCKNIX's developers confirmed that it starts steamcl: v1.2 tries `\EFI\BOOT\BOOTAA64.EFI`
  first, then `\KERNEL`. Kettle doesn't install it, but `packages/rocknix-abl` ships the
  current release and `kettle-abl-update`, which updates an installed one. The updater works
  like Armada's `armada-abl-update`:
  - It recognises releases by the hash of the partition's first bytes (`releases.tsv`;
    1.1–1.1.8 from Armada's catalogue).
  - It refuses a stock ABL and never installs an older release than the one there.
  - Before writing, it needs the charger or 30% battery.
  - It writes one slot at a time, reads it back, and puts the old contents back if the read-back
    doesn't match.
  - 1.1.9's files were deleted upstream, so a test-signed (`qtestsign`) ABL that isn't listed
    needs `--force`.
  - It isn't run automatically yet.
  - **The RP5 doesn't show its abl partitions to Linux (checked 2026-10-09 on the user's RP5).**
    Its boot chain is on UFS LUN 4 (`sde`), where the primary GPT header has a bad CRC. The
    partition entries are intact and the same as the backup GPT's, and the backup header is
    valid. The protective MBR's size is also off by one, so the kernel gives up on the whole
    LUN: there is no `abl_a`/`abl_b`/`loader_*` in `/dev/disk/by-partlabel`, and
    `kettle-abl-update` says so and does nothing. Booting with the kernel's `gpt` option would
    make it use the backup GPT. That is untested, and it is not yet known whether every RP5
    has this.
  - The licence is open: the ROCKNIX ABL is binary-only, from a private fork of Qualcomm's
    BSD-licensed LinuxLoader, and its repo states no licence. Get ROCKNIX's OK to redistribute
    it before shipping.
- **A Kettle ABL.** These devices run test-signed ABLs (the ROCKNIX ABL is signed with qtestsign
  test keys), so secure boot isn't enforced. Qualcomm's `abl2esp` (BSD, boots
  `\EFI\BOOT\BOOTAA64.EFI`) would be the base. It means flashing both `abl` slots, and recovery
  needs EDL, whose programmers are public only for the Odin 2 and Retroid's SM8250 devices. It is
  only worth it if the "UEFI" choice doesn't work.
- **Ruled out.**
  - edk2 ports (Mu-Silicium, edk2-msm): they need Qualcomm binary drivers taken from device
    firmware, which can't be redistributed.
  - lk2nd: older SoCs only.
  - Replacing `uefi`/`xbl`: brick risk, and it loses fastboot.
