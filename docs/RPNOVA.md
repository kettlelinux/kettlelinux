# Retroid Pocket Nova

The Retroid Pocket Nova has the same SoC as the Odin 2 Portal and the Thor: the QCS8550
(Snapdragon 8 Gen 2 without the modem, Adreno 740). Its board is close to AYN's: ROCKNIX's device
tree for it is a thin overlay on its Retroid Pocket 6 dts, which itself builds on the AYN common
dtsi. So the Nova uses the SM8550 kernel, patches and packages the AYN devices use, plus its own
panel. It also uses the same userspace and the same A/B updates. **The port was written before a
unit arrived: nothing below has run on hardware yet.** How its files are kept apart from the
other devices': [PORTING.md](PORTING.md).

The references are ROCKNIX (its SM8550 image lists the Nova; the dts, `qcs8550-retroidpocket-rpnova.dts`,
and the panel driver, `20-sm8550/0105`, came with our SM8550 import) and pocknix-os, which runs the
same dts as a beta device (shuuri-labs/pocknix-os issue #78).

## Hardware
| | |
|---|---|
| SoC | QCS8550 (msm-id `0x25b`, board-id `0x1001f`, as the RP6 dts sets them), 8 or 12 GB RAM, 128 GB UFS 3.1, microSD |
| Display | 4.5" 4:3 AMOLED, 1280x960, landscape-native (no dts rotation), 4-lane DSI video mode, 120 and 60 Hz (`il97680a,rpnova`, brightness over DCS 0..3445) |
| Touch | FocalTech FT5426 on i2c_hub_3, 1280x960, no axis inversion |
| Controls | rsinput MCU (`AYN Odin2 Gamepad`, both sticks inverted in the dts, trigger deadzones 100), hall sticks and analog triggers; back paddles on TLMM GPIO 57/58; Volume Up on gpio-keys |
| Lights | Two HTR3212s, four RGB LEDs round each stick (`rgb:l1..l4`, `rgb:r1..r4`), as on the Portal |
| Audio | The AYN-Odin2 card: AW88166 speaker amps (the Odin 2's tuning, `aw883xx_acf.bin`), WCD938x headphone codec |
| Wi-Fi/BT | WCN7850 (ath12k), Wi-Fi 7, Bluetooth 5.3 |
| Fan | pwm-fan on PM8550 PWM 3, from the AYN common dtsi |
| Battery | 5000 mAh, pmic-glink battery manager (the Odin 2's ADSP firmware) |
| Motion | 6-axis IMU, expected behind the ADSP's Sensor Core as on the Portal and Thor |

## Building
```sh
scripts/build-kernel.sh                  # the Nova's dtb is already in the SM8550 build
scripts/build-packages.sh kettle-firmware-ayn kettle-ucm-ayn kettle-power kettle-motion \
  kettle-leds inputplumber kettle-decky-plugins
KETTLE_DEVICE=rpnova scripts/build-image.sh    # -> out/kettle-<build>-rpnova.img
```

## Booting (planned)
There is no U-Boot for Retroid's SM8550 devices (AYN's `u-boot-ayn` is built for the Odin 2
boards, and Retroid's own U-Boot tree has only SM8250). The image boots through ROCKNIX's ABL, as
ROCKNIX does on the Nova:
- ROCKNIX's SM8550 ABL build (`abl_signed-SM8550.elf`, in `packages/rocknix-abl`) replaces the
  stock ABL. ROCKNIX flashes it from rooted Android (`backup_abl.sh`, then `flash_abl.sh`).
  Once Kettle runs, `kettle-abl-update` keeps it up to date (`ABL_SOC=SM8550`).
- With the ABL in place, holding Volume Down at power-on opens its menu: set **Device model**
  (the Nova, if v1.2 lists it; check), **Boot source:** SD, **Boot mode:** Linux. v1.2 starts
  `\EFI\BOOT\BOOTAA64.EFI` (steamcl, then GRUB with the Nova's dtb from `boot.conf`), and falls
  back to `\KERNEL` with the `qcs8550-*` dtbs appended.
- An install guide (like [INSTALL-RP5.md](INSTALL-RP5.md)) follows once a unit has booted.

## What is different from the AYN devices
- **Screen**: the first Kettle panel that is not mounted rotated. Game Mode runs it as it is
  (`GAMESCOPE_ORIENTATION=normal`), the desktop with no transform (KWin `Normal`, scale 1.5).
  Steam's UI scale comes from the panel's physical size: Game Mode reports 151x113 mm, the Steam
  Deck's pixel density at 1280x960, so the UI is laid out as on a Deck, 160 pixels taller. The boot
  and desktop splashes scale uniformly from 1920x1080 and are centred, so 4:3 needs nothing else.
- **Refresh rates**: 60 and 120 Hz in Quick Access > Power (`refresh-rates`), 120 Hz by
  default. The panel driver picks the panel's rate setup (register 0x60) by guessing the
  current mode, as the RP6's driver did before `20-sm8550/1021` left that panel one mode (the
  Portal's driver guesses the same way and switches five rates cleanly).
- **Back paddles**: ROCKNIX's RP6 dts puts them on `/gpio-keys` next to Volume Up, so
  InputPlumber taking them would take Volume Up too (upstream's config adds a keyboard target to
  get it back). Our Nova dts moves them to a `gpio-keys-paddles` device, as on the Portal.
- **Fan**: the RP6 dts has the AYN pwm-fan and trip points but no cooling maps (ROCKNIX drives the
  fan from userspace). Our Nova dts includes `qcs8550-ayn-fan.dtsi`, the Portal's curve.
- **Controls**: InputPlumber presents the pad as a Deck controller (`40-kettle-rpnova.yaml`), with
  the motion sensors from `kettle-motiond`. Its map (`kettle-rpnova-capability-map.yaml`) is the
  Thor's without the AYN key: the face buttons are labelled Nintendo-style, and Steam follows the
  labels (upstream's `rsinput1` follows the Xbox layout by position, which swapped A/B and X/Y on
  a Nova). Upstream's `50-retroid_pocket_nova.yaml` isn't installed: it takes `gpio-keys` (Volume
  Up), which ours leaves to the kernel, so it made a second controller that raced ours for the
  pad (seen on 20261016.4).
- **Firmware**: `kettle-firmware-rpnova` (in `packages/kettle-firmware-ayn`) installs the Odin 2's
  ADSP and amplifier files, the paths the dts asks for, as ROCKNIX ships them.
- **Charging**: no charge speeds or `current` charge limit yet. The ADSP image is the Odin 2's,
  whose battery manager takes `constant_charge_current` on the Portal and Thor, but its battery
  profile is the Odin 2's 8000 mAh pack and the Nova's real charge current isn't known. Until a
  unit is measured, Steam's charge limit is the charger's end threshold.

## Still to check, by hand
- Boot: the ABL flash from Android (root), whether ABL v1.2's Device model list has the Nova,
  the dtb GRUB boots, and what SMBIOS the ABL's EFI reports (the UCM profile and steamos-manager
  match the devicetree, with the Odin 2's EFI aliases as a fallback).
- Screen: picture, touch and orientation, 60 Hz and switching between 60 and 120 Hz
  (if it sticks at a low frame rate or a wrong rate after a switch, limit it to 120 Hz as
  `20-sm8550/1021` does for the RP6). Steam's UI scale and the desktop's.
- Brightness: the dts keeps the RP6's `pwm-backlight` node as well as the panel's own DCS
  backlight, so two backlight devices may show up (`hwcheck-device` lists them). Check which one
  Steam's slider and Plasma drive, and whether the PWM one controls anything on this board.
  pocknix found the lowest Plasma brightness turns the panel fully dark: measure a floor, as
  `40-kettle/1120` does for the Portal.
- Controls: the face button labels, both sticks' directions (the dts inverts both axes) and
  centring, the trigger deadzones, the paddles, Quick Access, and the desktop controller.
- Stick lights: the colour order. The RP6 dts' LED labels don't match their nodes (the node
  `ledl_b1` is labelled `l:r1`); kettle-ledd reads each group's `multi_index`, so check the
  colours themselves.
- Audio: the speakers with the Odin 2's amplifier tuning (`aw883xx_acf.bin`), the headphone jack
  and its detection, the microphone.
- Battery and charging: what `charge_now`/`charge_full` read (the Odin 2's profile), charge
  current from a PD charger, whether `constant_charge_current` is taken, the end threshold.
  pocknix testers reported charging stopping after a kernel update. If the readings are wrong,
  try the unit's own ADSP files from its Android partitions (`/vendor/firmware_mnt/image`).
- Fan: does it spin up with the trips, its noise, and whether `fan1_input` (tach) reads.
- Motion: whether the Sensor Core on the Odin 2's ADSP image finds the Nova's IMU from its
  own `persist` registry, and the axis matrix (`packages/kettle-motion/devices.conf`, identity
  for now).
- Power: the TDP range (4-18 W, a placeholder), the profiles, idle and sleep drain, s2idle and
  wake: the SM8550 deep sleep (PCIe GDSCs off, `40-kettle/1463`, no PCIe suspend floor) reaches
  CX/AOSS/DDR collapse on the Portal and Thor; check that the Nova does and wakes, Wi-Fi/BT after resume.
- AYN-specific tuning in the common dtsi (regulators, PCIe, audio rails): the Nova runs it as
  ROCKNIX does, but none of our fixes on top of it have been tried on Retroid's board.
