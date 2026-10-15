# KONKR Pocket FIT Elite

The Pocket FIT Elite (KONKR is AYANEO's sub-brand) is the first Kettle device on the Snapdragon 8
Elite (SM8750, Adreno 830). This is the 24 GB / 1 TB model. It uses the same kernel build: SM8750
support is a patch directory and a config fragment next to the SM8550 and SM8250 ones. It also
uses the same userspace and the same A/B updates. The port was written before a unit arrived;
it first booted on one on 2026-10-15 (build 20261015.2), see [Verified on a unit](#verified-on-a-unit). How its files are kept apart from the other devices':
[PORTING.md](PORTING.md).

The references are ROCKNIX's SM8750 device (`projects/ROCKNIX/devices/SM8750`, `next` @
`bac971fe`). It runs this board on 7.2 with its own dts, `sm8750-konkr-pf-elite.dts` (Patrick
Hennig, BSD-3-Clause). The dts was written from the stock Android device tree read on a running
unit, and its comments mark what is still unverified. Armada (armada-os/armada @ `2e0874d8`), which
ships the same board in one kernel with SM8550 devices, is the second reference: its fixes on
top of ROCKNIX's are credited below.

## Hardware, from ROCKNIX's dts
| | |
|---|---|
| SoC | SM8750 (msm-id 618/639), the real 8 Elite, not the Odin 3's CQ8725S |
| Display | 6" 1080x1920 LCD mounted at 90 degrees, 4-lane DSI with DSC, 144/120/90/60 Hz (`ayaneo,ar14-144hz`); AW99706 backlight, SGM3804 bias |
| Touch | Chipone TDDI (ICNL9922C) on i2c4 |
| Controls | AYANEO MCU: the gamepad over SPI (`AYANEO MCU Gamepad`), the KONKR key, extra buttons and stick RGB over UART (`KONKR System Buttons`, LED `konkr:rgb:joysticks`); volume and performance-mode keys on gpio-keys |
| Audio | 2x AW88261 speaker amps on secondary MI2S; WCD9395 headphone codec over SoundWire, with its USB-C/jack switch |
| Wi-Fi/BT | WCN7860 (ath12k, PCI `17cb:110e`) |
| Fan | pwm-fan on PM8550 PWM 3, cooling levels 0/64/128/255 |
| Battery | 8000 mAh, pmic-glink battery manager |

## Building
```sh
scripts/build-kernel.sh                  # SM8750: kernel/patches/22-sm8750, kernel/config/sm8750.config
scripts/build-packages.sh kettle-firmware-konkr kettle-ucm-konkr kettle-power inputplumber
KETTLE_DEVICE=pocketfitelite scripts/build-image.sh    # -> out/kettle-<build>-pocketfitelite.img
```

## Booting
There is no U-Boot for SM8750 (mainline U-Boot has no SM8750 clock driver, [BOOTLOADER.md](BOOTLOADER.md)).
The image boots through ROCKNIX's ABL, as ROCKNIX does:
- ROCKNIX's SM8750 ABL build (`abl_signed-SM8750.elf`, in `packages/rocknix-abl`) replaces the
  stock ABL in `abl_a` and `abl_b`. The unit came with its bootloader unlocked
  (`ro.boot.verifiedbootstate=orange`), and stock Android ships AYANEO's pre-root helper
  `/product/bin/xsu`, which runs a command as root from `adb shell` without Magisk:
  `xsu dd if=… of=/dev/block/by-name/abl_a`. Run it detached (`(nohup /product/bin/xsu … &)`):
  in the foreground `adb` loses the device. Some invocations silently don't run and its output
  loses lines, so back up both slots first and read every write back (after
  `echo 3 > /proc/sys/vm/drop_caches`) before rebooting. The two stock slots held different ABL
  versions.
- With the ABL in place, holding Volume Down at power-on opens its menu (Boot mode Linux). It
  starts Kettle's steamcl (`\EFI\BOOT\BOOTAA64.EFI`), then GRUB with `DTB`.
- Still to find out: how to reach EDL, and whether KONKR's firmware offers a UEFI path like the
  Odin 3's. An install guide (like [INSTALL-RP5.md](INSTALL-RP5.md)) is still to write.

## What is different from the other devices
- **Kernel** (`kernel/patches/22-sm8750`): 33 of ROCKNIX's SM8750 patches (one of them in Armada's version) and two of Armada's. They add GPU clock and
  GPU nodes, the A830 catalog entry, WCN7860 Wi-Fi/BT, the panel, backlight, touch, both MCU
  drivers, UFS, DPU inline rotation, the HPH PCM mode and CPU cooling. Five are rebased (header
  notes say how). The Odin 3's CQ8725S, rsinput and haptics patches are left out, as are those
  already in `20-sm8550`. `40-kettle/1240` is ROCKNIX's KONKR wcd-mbhc fix, already shared.
- **From Armada**:
  - `22-sm8750/0509` defers for a late USB-C mode switch on SM8750 only. ROCKNIX's version
    deferred on every SoC, which on a board with no mode switch never ends and leaves the panel
    dark.
  - `0521` gives PCIe an `opp-suspend` floor for `20-sm8550/1048`. Without the floor the
    memory votes drop to 0 in s2idle, and the device resets instead of waking (seen on the
    SM8550 devices).
  - `0618` keeps a DisplayPort PCM prepare from failing while nothing is plugged in.
  - In the dts: the DisplayPort audio link, PCIe WAKE# made active-low, volume-up no longer a
    wakeup source, and three codec rails idled in LPM through s2idle.
  - The UCM profile adds the DisplayPort device and keeps the amps at unity gain.
- **Shared with SM8550, re-test the Portal/Thor**:
  - `22-sm8750/0048` reparents the DSI byte/pixel clocks to XO at power-off, on every
    6G v2.9 DSI.
  - `0060` turns `20-sm8550/0036`'s primary-only I2S clock into a refcounted clock for every
    MI2S port.
  - `0618` changes DP audio on every SoC.
- **GPU**: the A830 entry matches chip id `0x44050000`, from the dts compatible. Upstream's
  series for 7.4 uses `0x44050001`: check `dmesg` on the unit and revisit when it lands. The
  firmware (`gen80000_*`, the SM8750 zap) comes from linux-firmware-qcom.
- **Fan**: ROCKNIX drives the fan from userspace, so its dts binds it to no thermal zone. Ours adds
  `sm8750-konkr-pf-elite-fan.dtsi`: active trips at 50/60/70 C on the CPU clusters and the GPU,
  as `qcs8550-ayn-fan.dtsi` does for the AYN boards.
- **Controls**: InputPlumber joins the two MCU devices into one Deck controller
  (`40-kettle-pocketfitelite.yaml`). The KONKR key is Steam and the front-top-left button is
  Quick Access. The extra shoulder buttons are L4/R4, and the two other front buttons L5/R5.
  The rear buttons send nothing (ROCKNIX: the MCU reports neither). The face buttons are
  Xbox-labelled. The d-pad is a hat, which the desktop controller now takes too.
- **Steam UI scale**: Game Mode reports the Portal's panel size (`GAMESCOPE_INTERNAL_PHYSICAL_SIZE`),
  as the RP5 and Thor do. The real 6" makes the UI far too large.
- **Headphone jack**: `61-kettle-pocketfitelite-jack.rules` keeps the WCD9395's SoundWire buses
  runtime-active, as ROCKNIX does, because a clock-stopped bus misses the jack plug.
- **Charging**: no charge speeds or `current` charge limit yet. It is not known whether the SM8750
  battery manager takes `constant_charge_current` (`40-kettle/1190`) as the Portal's does.

## Verified on a unit
2026-10-15, build 20261015.2 with the dts fixes below (24 GB / 1 TB unit):
- Boots from the SD card through the ROCKNIX ABL; panel (`DSI-1`, 1080x1920, 144/120 Hz),
  rotation and Steam UI scale, touch, Adreno 830 (Turnip Vulkan, all 14 OPPs 160-1100 MHz),
  gamepad and system buttons as one Deck controller in Steam, speakers, Wi-Fi (WCN7860) and
  Bluetooth, fan, battery reading, Steam login.
- s2idle: RTC wake, `systemctl suspend` and the power key (sleep and wake), Wi-Fi back after.
- Internal install (build 20261015.3): `kettle-install-internal` with a full backup (941 GiB
  LUN 0 at ~400 MB/s, 6.5 GB compressed), Android kept 64 GiB; the ROCKNIX ABL v1.2 starts
  `\KERNEL` from `kettle-esp` (*Boot source: Internal*) and the system runs from UFS. The UFS
  tools needed `ufs-lib.sh` to find the LUNs by SCSI host (the SM8750 node is `ufs@`, not
  `ufshc@`). The install's `efi-A`/`efi-B` (64 MiB on 4K-sector UFS) come out as FAT32 with
  16316 clusters, under FAT32's minimum: not read on this boot path, but a strict FAT driver
  (UEFI) would take them for FAT16.
- CPU tables: six cores 384 MHz-3.53 GHz, two prime cores 1.02-4.09 GHz (this unit's bin).
- Fixed in the dts after the first boots: the SD bus at SDR104 read the card with I/O errors
  every few seconds (`max-frequency` 100 MHz); the CDSP firmware crashed at every start and the
  recovery loop restarted it ~5 times a second (CDSP disabled); PCIe waited forever on the
  CoreSight TNOC under `fw_devlink.strict=1` (TNOC disabled), so there was no Wi-Fi.
- Open: the WCN7860 twice stopped answering (ath12k `-108`, no firmware crash logged), once
  22 s into a boot and once after a resume, and iwd crashed with it; other boots and resumes
  were fine. Haptics (no node in the dts). One early power-key suspend didn't wake (during a
  boot with that failure; not seen since).

## Still to check, by hand
- Desktop Mode rotation (KWin `Rotated270`), the refresh rates in use, a game under load.
- Measured TDP limits (the 4-22 W range in `packages/kettle-power/pocket-fit-elite.toml` is a
  placeholder) and the profiles' power draw.
- Fan trips and noise; the fan's tach (`fan1_input`).
- The button map against the physical buttons; the stick RGB in `kettle-leds` (one multicolor
  LED for both rings, where the AYN devices have `rgb:{l,r}N`).
- Gyro: there is no IMU node in the dts, so it is probably the ADSP's Sensor Core as on the
  Portal and Thor (`kettle-motion` would need a `[konkr,pocket-fit-elite]` matrix).
- The intermittent WCN7860 loss above; suspend over many cycles; DisplayPort out and its audio, the USB-C orientation GPIO (marked TODO in the
  dts), the charger and the charge limit, the headphone jack.
- `60-kettle-usb-power.rules` and `60-kettle-ath12k-iommu-fq.rules` match SM8550's USB controller
  and WCN7850 only. Extend them to SM8750/WCN7860 once tested.
