# Bootloaders: the vendors' U-Boot and the ROCKNIX ABL

Every device starts Kettle the same way once its bootloader is running:

```
stock Qualcomm ABL ─► loader_a/b: the vendor's U-Boot (an Android boot image) ─► U-Boot EFI
  ─► \EFI\BOOT\BOOTAA64.EFI (steamcl, A/B slots) ─► GRUB ─► kernel   (docs/UPDATES.md)
```

The steps before U-Boot (the ABL, the partition layout, slot bits, fastboot) are in
[BOOT.md](BOOT.md).

## Which bootloader

- **The fastboot menu offers Loader:** set the default boot to Loader. ABL then starts the
  vendor's U-Boot from `loader`: AYN's on the Portal and Thor, Retroid's on the RP5. If the
  partition was overwritten, Kettle carries the vendors' images to put back:
  `packages/u-boot-ayn` (AYN's source, unchanged) and `packages/u-boot-retroidpocket`
  (Retroid's source, plus one patch for a fixed SD-then-internal boot order). Loader mode needs
  an unlocked bootloader (BOOT.md).
- **No Loader choice:** install the ROCKNIX ABL from Android, with ROCKNIX's scripts
  (docs/INSTALL.md).

Both start steamcl, so both get A/B fallback after a failed update.

Kettle doesn't build its own U-Boot. A mainline U-Boot package (`u-boot-kettle`) was tried and
dropped on 2026-10-09. If a device needs U-Boot put back, Kettle uses AYN's or Retroid's images.

## ROCKNIX ABL

ROCKNIX's developers confirmed that it starts steamcl. v1.2 tries `\EFI\BOOT\BOOTAA64.EFI`
first, and only falls back to `\KERNEL` when that file is missing. Its menu's *Device model*
must be set, or it starts nothing.

Kettle doesn't install it. `packages/rocknix-abl` ships the current release and
`kettle-abl-update`, which updates one that is already installed. It works like Armada's
`armada-abl-update`:

- It recognises releases by the hash of the partition's first bytes (`releases.tsv`;
  1.1–1.1.8 from Armada's catalogue).
- It refuses a stock ABL and never installs an older release than the one there.
- Before writing, it needs the charger or 30% battery.
- It writes one slot at a time, reads it back from the device, and puts the old contents back
  (verified too) if the read-back doesn't match.
- 1.1.9's files were deleted upstream, so a test-signed (`qtestsign`) ABL that isn't listed
  needs `--force`.
- It isn't run automatically; users run `sudo kettle-abl-update`.

Checked on hardware (2026-10-09, `--check` only):

- **Thor:** both slots stock, refused correctly.
- **RP5:** no abl partitions visible to Linux (below).

Open:

- **Licence.** The ROCKNIX ABL is binary-only, from a private fork of Qualcomm's BSD-licensed
  LinuxLoader, and its repo states no licence. Get ROCKNIX's OK to redistribute it before
  shipping.
- **The RP5 doesn't show its abl partitions to Linux** (checked on the user's RP5). Its boot
  chain is on UFS LUN 4 (`sde`), where the primary GPT header has a bad CRC.
  - The partition entries are intact and the same as the backup GPT's, and the backup header
    is valid.
  - The protective MBR's size is also off by one, so the kernel gives up on the whole LUN.
  - As a result there is no `abl_a`/`abl_b`/`loader_*` in `/dev/disk/by-partlabel`, and
    `kettle-abl-update` says so and does nothing.
  - Booting with the kernel's `gpt` option would make it use the backup GPT. That is
    untested, and it is not yet known whether every RP5 has this.

## Research notes (2026-10)

- **Loader slots** (details in [BOOT.md](BOOT.md)).
  - `fastboot flash loader` writes only the active slot's `loader`.
  - The ABL boots `loader_<slot>`, where the slot is the one it picks from `boot_a`/`boot_b`.
  - After a slot switch (an Android update, `fastboot set_active`), it starts the other one.
- **What the ABL reports (Portal).** `hardware_platform` 31, subtype 0: a generic board ID.
  The Portal and Thor are probably indistinguishable to the ABL.
- **AYN firmware without a "Loader" choice ("Android" / "UEFI").** On the Odin 3, "UEFI" starts
  `\EFI\BOOT\BOOTAA64.EFI` from the SD card straight from Qualcomm's UEFI. That is steamcl in
  Kettle's image, so it may boot with no U-Boot at all (the kernel may need to reset the display
  controller). This is unconfirmed on the Portal and Thor.
- **Mainline U-Boot (dropped).**
  - Status on these SoCs:
    - SM8250 and SM8550 are well supported.
    - SM8650 is mostly there.
    - SM8750 (Odin 3) has no clock driver yet.
  - Display only reuses ABL's framebuffer.
  - There is no charger or battery driver.
  - Its standard boot (`bootflow scan`) only looks at partitions flagged LegacyBIOSBootable, or
    at partition 1 when none is. The same holds for the RP5's Retroid U-Boot, which boots that
    way. That is why `kettle-install-internal` flags `kettle-esp`.
- **A Kettle ABL.** These devices run test-signed ABLs (the ROCKNIX ABL is signed with qtestsign
  test keys), so secure boot isn't enforced.
  - Qualcomm's `abl2esp` (BSD, boots `\EFI\BOOT\BOOTAA64.EFI`) would be the base.
  - It means flashing both `abl` slots. Recovery needs EDL, whose programmers are public only
    for the Odin 2 and Retroid's SM8250 devices.
  - Not planned.
- **Ruled out.**
  - edk2 ports (Mu-Silicium, edk2-msm): they need Qualcomm binary drivers taken from device
    firmware, which can't be redistributed.
  - lk2nd: older SoCs only.
  - Replacing `uefi`/`xbl`: brick risk, and it loses fastboot.
