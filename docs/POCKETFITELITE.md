# KONKR Pocket FIT Elite

The Pocket FIT Elite (KONKR is AYANEO's sub-brand) is the first Kettle device on the Snapdragon 8
Elite (SM8750, Adreno 830). This is the 24 GB / 1 TB model. It uses the same kernel build: SM8750
support is a patch directory and a config fragment next to the SM8550 and SM8250 ones. It also
uses the same userspace and the same A/B updates. **The port was written before a unit arrived:
nothing below has run on hardware yet.** How its files are kept apart from the other devices':
[PORTING.md](PORTING.md).

The reference is ROCKNIX's SM8750 device (`projects/ROCKNIX/devices/SM8750`, `next` @
`bac971fe`). It runs this board on 7.2 with its own dts, `sm8750-konkr-pf-elite.dts` (Patrick
Hennig, BSD-3-Clause). The dts was written from the stock Android device tree read on a running
unit, and its comments mark what is still unverified.

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

## Booting (planned)
There is no U-Boot for SM8750 (mainline U-Boot has no SM8750 clock driver, [BOOTLOADER.md](BOOTLOADER.md)).
The image boots through ROCKNIX's ABL, as ROCKNIX does:
- ROCKNIX's SM8750 ABL build (`abl_signed-SM8750.elf`, already in `packages/rocknix-abl`) replaces
  the stock ABL. ROCKNIX flashes it from rooted Android (`backup_abl.sh`, `flash_abl.sh`).
- With the ABL in place, holding Volume Down at power-on opens its menu. From there it boots
  `\KERNEL` from the SD card: our kernel with the `sm8750-*` dtbs appended (`ABL_DTBS`). It
  picks the dtb by `qcom,msm-id` and `qcom,board-id`.
- Still to find out on the unit: whether the bootloader must be unlocked (rooting Android needs
  it), how to reach EDL, and whether KONKR's firmware offers a UEFI path like the Odin 3's.
- An install guide (like [INSTALL-RP5.md](INSTALL-RP5.md)) follows once a unit has booted.

## What is different from the other devices
- **Kernel** (`kernel/patches/22-sm8750`): 33 of ROCKNIX's SM8750 patches. They add GPU clock and
  GPU nodes, the A830 catalog entry, WCN7860 Wi-Fi/BT, the panel, backlight, touch, both MCU
  drivers, UFS, DPU inline rotation, the HPH PCM mode and CPU cooling. Five are rebased (header
  notes say how). The Odin 3's CQ8725S, rsinput and haptics patches are left out, as are those
  already in `20-sm8550`. `40-kettle/1240` is ROCKNIX's KONKR wcd-mbhc fix, already shared.
- **Shared with SM8550, re-test the Portal/Thor**:
  - `22-sm8750/0048` reparents the DSI byte/pixel clocks to XO at power-off, on every
    6G v2.9 DSI.
  - `0060` turns `20-sm8550/0036`'s primary-only I2S clock into a refcounted clock for every
    MI2S port.
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
- **Headphone jack**: `61-kettle-pocketfitelite-jack.rules` keeps the WCD9395's SoundWire buses
  runtime-active, as ROCKNIX does, because a clock-stopped bus misses the jack plug.
- **Charging**: no charge speeds or `current` charge limit yet. It is not known whether the SM8750
  battery manager takes `constant_charge_current` (`40-kettle/1190`) as the Portal's does.

## Still to check, by hand
- Boot: the ABL flash, the dtb pick, panel rotation (`GAMESCOPE_ORIENTATION=right`,
  KWin `Rotated270`; if upside down, swap to `left`/`Rotated90`), the refresh rates.
- GPU chip id and Vulkan (Turnip on A830), the zap shader, GPU frequency table and speed bin.
- CPU frequency tables (SCMI) for the profiles in `packages/kettle-power/pocket-fit-elite.toml`,
  and measured TDP limits (the 4-22 W range there is a placeholder).
- Fan trips and noise; the fan's tach (`fan1_input`).
- The button map against the physical buttons; the stick RGB in `kettle-leds` (one multicolor
  LED for both rings, where the AYN devices have `rgb:{l,r}N`).
- Gyro: there is no IMU node in the dts, so it is probably the ADSP's Sensor Core as on the
  Portal and Thor (`kettle-motion` would need a `[konkr,pocket-fit-elite]` matrix).
- Suspend (s2idle), Wi-Fi/BT, DisplayPort out, the USB-C orientation GPIO (marked TODO in the
  dts), the charger and the charge limit, speakers and the jack.
- `60-kettle-usb-power.rules` and `60-kettle-ath12k-iommu-fq.rules` match SM8550's USB controller
  and WCN7850 only. Extend them to SM8750/WCN7860 once tested.
