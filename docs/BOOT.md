# How the devices boot: ABL, partitions, slots, fastboot

This is how the Qualcomm devices boot, from power-on up to Kettle's U-Boot. It also covers the
UFS partition layout, the A/B slot bits, and what fastboot does. For everything after U-Boot
(steamcl, GRUB, Kettle's own A/B slots) see [UPDATES.md](UPDATES.md). Which bootloader starts Kettle
(the vendors' U-Boot, or the ROCKNIX ABL) is in [BOOTLOADER.md](BOOTLOADER.md).

Each fact below is tagged with its source:
- **[Portal]**: read off the user's Odin 2 Portal, an internal install, on 2026-10-04.
- **[ABL]**: from disassembling the Portal's ABL.
- **[upstream]**: from Qualcomm's or Android's public sources.

The Thor (QCS8550) and the RP5 (SM8250) have not been read yet.

## Boot chain

```
PBL (boot ROM)  ─► xbl + xbl_config        UFS boot LUN 1 (xbl_a) or 2 (xbl_b)
                ─► uefi_x (XBL core: Qualcomm's UEFI, DXE drivers, display, USB)
                ─► abl_x (LinuxLoader.efi: Android bootloader + fastboot)
                     default "Android": boot_x (+ vendor_boot_x, init_boot_x, dtbo_x)
                     default "Loader":  loader_x = U-Boot ─► EFI ─► steamcl ─► GRUB ─► Linux
```

- **PBL is in ROM.** It reads the UFS `bBootLunEn` attribute to pick the xbl LUN. On the
  Portal that attribute is `boot_lun_enabled=0x1`, so the `xbl_a` LUN is used
  (`/sys/devices/platform/soc@0/1d84000.ufshc/attributes`) **[Portal]**. If the active slot
  changes, ABL moves the boot LUN to match ("Boot lun mismatch switch from 1 to 2") **[ABL]**.
- **ABL is Qualcomm's LinuxLoader with AYN changes.** It is built from tree `VENDOR.13.2.6`
  (`msm-kernel-kalama-gki`, `abl-user`) **[ABL]**.
  - `abl_a` and `abl_b` are byte-identical **[Portal]**.
  - The file is an ELF wrapping a UEFI firmware volume. That volume holds an LZMA section, which
    contains the LinuxLoader PE.
- **Fastboot mode is inside ABL.** It is a different thing from Android's userspace fastbootd.

## UFS layout (Portal)

The disk is UFS with 4096-byte sectors. It has eight LUNs, each with its own GPT. Partition names
are global, so `/dev/disk/by-partlabel/<name>` works whatever the LUN **[Portal]**.

| LUN | Dev | Size | Holds |
|---|---|---|---|
| 0 | sda | 941 GiB | Android data partitions, then Kettle's partitions (below) |
| 1 | sdb | 20 MiB | `xbl_a`, `xbl_config_a`, `multiimgqti_a`, `multiimgoem_a`, `apdp` |
| 2 | sdc | 20 MiB | the same for slot b (`apdpb`) |
| 3 | sdd | 32 MiB | `cdt`, `ddr` (DDR training) |
| 4 | sde | 4 GiB | everything else for boot and firmware: 80 partitions (table below) |
| 5 | sdf | 32 MiB | `modemst1`, `modemst2`, `fsg`, `fsc` |
| 6, 7 | sdg, sdh | 4 GiB each | no partition table, all zeros (unused) |

### LUN 0

Partitions, in order:
- **Android:** `nvdata1`, `nvdata2`, `reserve1`, `reserve2`, `persist`, `qpdata1`, `qpdata2`,
  `frp`, `keystore`, `ssd`, `rawdump`, `misc`, `metadata`, `super` (5.3 GiB: system, vendor and
  product are logical partitions inside it), `vbmeta_system_a`, `vbmeta_system_b`, `userdata`.
- **Kettle:** after `userdata`, the internal install adds `kettle-esp`, `efi-A`, `efi-B`,
  `rootfs-A`, `rootfs-B`, `var-A`, `var-B` and `home` (see
  [INTERNAL-INSTALL.md](INTERNAL-INSTALL.md)). On the Portal, `userdata` was shrunk to 16 GiB.

### LUN 4

| Partitions (`_a` and `_b` of each) | Size | Notes |
|---|---|---|
| `abl` | 1 MiB | the Android bootloader. A bad write means the device is recoverable only through EDL |
| `loader` | 10 MiB | **the Loader**: AYN's U-Boot, an Android boot image v0. Kettle replaces it |
| `boot`, `vendor_boot` | 96 MiB each | Android 13 kernel (boot image v4, 2024-01 patch level) |
| `init_boot` | 8 MiB | Android generic ramdisk |
| `recovery` | 100 MiB | Android recovery (v4, ramdisk only) |
| `dtbo` | 24 MiB | Android devicetree overlays (56 entries) |
| `vbmeta` | 64 KiB | AVB root. Its flags are 0: verity and verification are **not** disabled |
| `uefi` | 5 MiB | Qualcomm's XBL core UEFI. **Never flash**: it is not a bootloader for users |
| `tz`, `hyp`, `devcfg`, `aop`, `aop_config`, `cpucp`, `shrm`, `qupfw`, `uefisecapp`, `keymaster`, `featenabler`, `imagefv`, `xbl_ramdump`, `vm-bootsys`, `modem`, `dsp`, `bluetooth`, `mdtp`, `mdtpsecapp`, `qweslicstore`, `rticmpdata` | | firmware |

LUN 4 also has single partitions with no `_a`/`_b` copy:
- `devinfo` (one 4 KiB block: lock state and AYN's Loader flag, see below)
- `splash`, `logdump`, `logfs`, `uefivarstore`, `toolsfv`, `dip`, `limits`, `limits-cdsp`
- `secdata`, `spunvm`, `tzsc`, `storsec`, `connsec`, `qmcs`, `vm-data`, `vm-persist`,
  `mdcompress`, `xbl_sc_logs`, `xbl_sc_test_mode`

**Every `_a` partition is byte-identical to its `_b` partner on the Portal**, including `loader`,
`abl`, `boot`, `xbl` and `uefi` **[Portal]**. The factory wrote both slots, and no Android OTA has
run since.

Partitions on an inactive slot carry Qualcomm's "unused" type GUID
`77036CD4-03D5-42BB-8ED1-37E5A88BAA34`. Switching the active slot swaps the type GUIDs. A few
`_b` partitions have their own type instead: `loader_b`, `uefi_b`, `init_boot_b` and
`xbl_ramdump_b` **[Portal]**.

### What is safe to touch

| Risk | Partitions |
|---|---|
| Kettle writes these | `userdata` (shrinks it), `misc` (an Android wipe request, see below), the partitions after `userdata`, `loader_a` (by hand, with fastboot) |
| Recoverable from fastboot | `loader_*`, `boot_*`, `dtbo_*`, `vbmeta_*`, `vendor_boot_*`, `init_boot_*`, `recovery_*` |
| Needs EDL if broken | `abl_*`: fastboot lives in it |
| Bricks the device, or loses data unique to the unit | `xbl*`, `xbl_config*`, `cdt`, `ddr`, `uefi_*`, `tz`, `hyp`, `devcfg`, `aop*`, `imagefv`; `persist` (sensor calibration), `modemst*`/`fsg`/`fsc`, `devinfo`, `keystore`, `frp`, `nvdata*` |

## A/B slot bits

ABL keeps the slot state in the GPT attribute bits of `boot_a` and `boot_b` **[upstream]**:

| Bits | Field |
|---|---|
| 48–49 | priority (0–3) |
| 50 | active |
| 51–53 | retry count (0–7) |
| 54 | successful |
| 55 | unbootable |

On the Portal **[Portal]**:

| Partition | Attribute bits | Meaning |
|---|---|---|
| `boot_a` | 48, 49, 50, 52, 53, 54 | priority 3, active, retry count 6, **successful** |
| `boot_b` | none | priority 0, retry count 0, not successful: **not bootable** |
| `loader_a` | 50 | active (ABL sets bit 50 on every `_a` partition of the active slot) |
| `loader_b` | none | |

Other `_a` firmware partitions carry bits 50 and 54. Bit 60 (read-only) appears on many
partitions. The GPT sets it and ABL ignores it.

### What ABL does with them

Every boot, ABL's `FindBootableSlot()` runs on `boot_a`/`boot_b` before it loads any image
**[ABL]**:

1. Take the active slot. If it is marked successful and not unbootable, boot it.
2. If it is not successful but has retries left, take one retry off and boot it.
   - Qualcomm's `IsABRetryCountUpdateRequired()` skips the decrement in fastboot, recovery and
     the off-mode charger, and `fastboot boot` doesn't count either **[upstream]**.
   - **AYN added Loader mode to that list.** Their version reads the Loader flag (`0x84c35`) and
     returns false **[ABL]**, so the retry count never drops in Loader mode.
3. Otherwise, mark the slot unbootable and switch to the other slot. That happens only if the
   other slot is marked **successful**; retries left are not enough. Failing that, the device
   stops in fastboot **[upstream]** **[ABL]**.

Then, in Loader mode, `LoadImageAndAuth()` builds the partition name with
`StrnCpyS(Pname, L"loader")` + `StrnCatS(Pname, CurrentSlot.Suffix)`. **It boots `loader_<the
slot FindBootableSlot chose>`** **[ABL]**.

What this means for Kettle:

- **Kettle doesn't need qbootctl or a "mark successful" service.** In Loader mode the retry count
  never moves. `boot_a` also still carries Android's successful bit.
- **The slot changes only if something changes these bits:** `fastboot set_active`, an Android
  OTA, or `boot_a` marked unbootable. After such a change, ABL loads **`loader_b`**. Today
  `loader_b` is a copy of AYN's factory U-Boot. So after a slot switch, a device with Kettle's
  U-Boot in `loader_a` alone silently goes back to AYN's U-Boot.
- **Updating the loader safely later:** write the inactive `loader_x`, then switch slots. Because
  Loader mode never counts retries, ABL won't fall back on its own if the new U-Boot doesn't
  start. Recovery would mean switching slots again by hand in fastboot.

## The "Android" / "Loader" default

AYN added a Loader boot mode to ABL. It is chosen in the fastboot menu, which also shows the
current setting ("Loader"/"Android") **[ABL]**.

- **Where it is stored:** one byte, offset `0xca0` of the `devinfo` partition, inside Qualcomm's
  `DeviceInfo` struct. The struct starts with `ANDROID-BOOT!`, and `is_unlocked` is at `0xd`.
  On the Portal, both are 1 **[Portal]**.
- **When ABL uses it:** `IsLoaderMode()` is `devinfo.is_unlocked && devinfo[0xca0]`. On a
  relocked device the flag is ignored and Android boots.
- **The setter:** refuses with "Unlocked bootloader required" on a locked device. Otherwise it
  writes the byte and saves `devinfo` (3240 bytes) **[ABL]**.
- **Reset:** if `devinfo`'s magic doesn't match, ABL rebuilds the partition with Loader = 0. So
  a wiped or damaged `devinfo` means Android boots again **[ABL]**.
- **No fastboot command sets it.** The only OEM commands are listed under
  [Fastboot](#fastboot); the menu is the only way.
- **Linux could flip the byte** with `dd` to `/dev/disk/by-partlabel/devinfo` to offer "boot
  Android next time". This hasn't been tried. Read-modify-write only that one byte, and keep a
  backup: `devinfo` also holds the lock state and rollback indexes.
- **Order of checks:** ABL checks Loader mode before recovery. Kettle's installer leaves
  `boot-recovery --wipe_data --reason=kettle` in `misc`, and that stays pending, untouched, for as
  long as the default is Loader. Switching the default to Android lets Android recovery wipe and
  re-create `userdata` on its first start. That is the intended behaviour (`ufs-lib.sh`).

## Loading the Loader image

The `loader` partition holds an Android boot image **v0**:
- the kernel field is gzip(U-Boot) with its devicetree appended
- base `0x10000000`, kernel offset `0x8000`, page size 4096
- cmdline `nodtbo`, no ramdisk

`packages/steamos-customizations-kettle/mkbootimg.py` builds exactly this, with the vendors'
arguments **[Portal]**.

- **`nodtbo` is a flag that ABL reads.** If the boot image's cmdline contains `nodtbo`, ABL skips
  the `dtbo` overlay ("ApplyOverlay: Ignore") **[ABL]**. Without it, ABL would lay Android's
  `dtbo_x` overlays over U-Boot's devicetree.
- **How ABL finds the devicetree.** It takes the single DTB appended to the kernel ("Single
  appended DTB found"). It does not need a `qcom,msm-id` match **[ABL]** **[upstream]**.
- **Verification.** Loader mode only exists on unlocked devices. There, ABL boots images that fail
  AVB verification (orange state), so the unsigned `loader` image starts.

## Fastboot

**Commands ABL accepts** (from the command table) **[ABL]**:
- `getvar`, `download`, `flash`, `erase`, `boot`, `continue`, `set_active`
- `reboot`, `reboot-bootloader`, `reboot-recovery`, `reboot-fastboot`
- `flashing lock`, `flashing unlock`, `flashing lock_critical`, `flashing unlock_critical`,
  `flashing get_unlock_ability`
- `snapshot-update`
- `oem device-info`, `oem select-display-panel`, `oem audio-framework`,
  `oem set-gpu-preemption`, `oem disable-charger-screen`

There is no extra block on `flash`, `erase` or `boot` beyond the usual locked-state check
("Flashing of %s is not allowed in %a state"). The Portal is unlocked, including critical
partitions (`devinfo` bytes `0xd`/`0xe` = 1) **[Portal]**.

- **`fastboot flash loader <img>` writes the current slot's `loader` only**, which is `loader_a`
  today, and `loader_b` keeps whatever it had. The ABL adds the suffix, not the host tool, in
  three steps **[upstream]**:
  1. The ABL publishes `has-slot` for `boot`, `system` and `modem` only.
  2. So the host sends the bare name `loader`.
  3. `CmdFlash` doesn't find a partition called `loader` and appends the current slot's suffix.

  To write the other slot, name it: `fastboot flash loader_b <img>`.
- **`fastboot boot <img>`** boots the image from RAM once and writes nothing. It also clears
  the slot's unbootable bit ("CmdBoot: ClearUnbootable") **[ABL]**. That it works on this ABL
  hasn't been confirmed yet (below).
- **`fastboot set_active` resets the slot bits**: the successful bit is cleared and the retry
  count set back **[upstream]**. Don't run it on a Kettle device without a reason (see [A/B slot bits](#ab-slot-bits)).
- **`fastboot erase dtbo`**, which older guides use to get an appended DTB accepted, isn't
  needed. `nodtbo` does the same job.

**Still to check in fastboot mode** (on the Portal, read-only):
- `fastboot getvar all`: `current-slot`, `has-slot:loader`, `slot-successful:a`,
  `slot-retry-count:a`, `unlocked`, `max-download-size`.
- Confirm that `fastboot boot u-boot-ayn.img` works on this ABL.

## Recovery: EDL

When ABL can't run any more (a bad `abl`, `xbl` or `uefi`), the only way back is Qualcomm's
emergency download mode: USB ID 05c6:9008, Sahara plus a Firehose programmer, flashing a full
firmware package. The programmer must be signed for the device. This mode is different from the
crash-dump mode (05c6:900e) the RP5 lands in when buttons are held too long.

What exists publicly (checked 2026-10):

| Device | EDL package |
|---|---|
| Odin 2 | A full QFIL flat build from DROIX (`odin2_20231201`, programmer `xbl_s_devprg_ns.melf`, UFS): [guide](https://droix.net/knowledge-base/article/how-to-reflash-ayn-odin-2/). It is labelled Odin 2 only; nothing says it fits the Portal. |
| Odin 2 Portal, Thor | None found |
| RP5 | None official. A community RP Mini package with `prog_ufs_firehose_sm8250_lite_lp5.elf` exists, but it is not known to work on the RP5. |

So on the Portal, Thor and RP5, treat `abl`, `xbl`, `uefi` and the other firmware partitions as
partitions with no way back.

## Open questions

- Read the Thor and the RP5 the same way: layout, slot bits, the ABL's Loader code, `devinfo`.
  The RP5's `loader` is on LUN 4 ([RP5.md](RP5.md)); its ABL is from Retroid, not AYN.
- AYN firmware whose menu offers "Android" / "UEFI" instead of "Loader" (one user reported this):
  is that a different ABL build? Public guides only talk about a "Switch boot mode" entry. The
  "Loader" choice is mentioned once, for firmware 355. AYN hasn't published its ABL source.
- Whether Linux should offer "boot Android next" by writing `devinfo[0xca0]`.

## How this was read

The commands were all read-only, run on the Portal. The GPT was dumped again at the end, and it
had not changed.

- **Partition tables:** `sfdisk --dump /dev/sd[a-h]`.
- **a/b comparison:** `sha256sum` of each `_a`/`_b` pair.
- **Images:** copied off the device with `cat /dev/disk/by-partlabel/<p>`.
- **ABL:**
  1. LZMA-decompressed the firmware volume in `abl_a`. The LinuxLoader PE starts at offset `0xb8`.
  2. Disassembled it with `llvm-objdump`. It was built with the machine outliner, so the code is
     split into fragments.
  3. Resolved `adrp`/`add` pairs to find the code that uses each string.
- **Functions read:** `LoadImageAndAuth` (`0xdfc4`–`0xe5e8`), `FindBootableSlot` (`0x169f8`–
  `0x17038`), `IsABRetryCountUpdateRequired` (`0x51c08`), `IsLoaderMode` (`0x197d0`), the Loader
  setter (`0x1985c`), the `devinfo` reset (`0x1a1ac`), and the `nodtbo` check (`0x7724`, used at
  `0x95b8`).
