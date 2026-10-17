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
| Lights | Two HTR3212s, four RGB LEDs round each stick (`rgb:l1..l4`, `rgb:r1..r4`), as on the Portal; no power LED (the AYN dtsi's `power-led` node is dropped, as on the Thor) |
| Audio | The AYN-Odin2 card: AW88166 speaker amps (the Odin 2's tuning, `aw883xx_acf.bin`), WCD938x headphone codec |
| Wi-Fi/BT | WCN7850 (ath12k), Wi-Fi 7, Bluetooth 5.3 |
| Fan | pwm-fan on PM8550 PWM 3, from the AYN common dtsi |
| Battery | 5000 mAh (`8553644_QUECTEL_SA885G_5000MAH`, the Nova's own ADSP firmware), pmic-glink battery manager |
| Motion | QST QMI8658 (accelerometer and gyro) behind the ADSP's Sensor Core; its driver is only in the Nova's own ADSP firmware |

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
- **ADSP firmware: the Nova's own, from its Android vendor partition.** Android loads
  `vendor/firmware/adsp.*` (split `.mdt`/`.bNN` files), which has the QMI8658 driver and the
  Nova's battery profile; the copy on `modem_a` is only a fallback, and like the Odin 2's
  (`kettle-firmware-rpnova`) it has neither (it names the Odin 2's 8000 mAh `SG8550` profile).
  Firmware from a unit can't ship in the image, and a running ADSP can't be restarted (stopping
  it resets the SoC, seen on a Nova). So the dts names firmware the image doesn't have
  (`qcom/sm8550/retroid/rpnova/`): the ADSP stays offline at boot until
  `kettle-adsp-firmware.service` (`packages/kettle-motion`, enabled by `device/rpnova`) has
  joined the Nova's own into `/var/lib/kettle-firmware` (on the first start) and starts it, with
  the Odin 2's from the image (`ADSP_FIRMWARE_FALLBACK`) if there is no vendor copy or it
  doesn't start. On the Nova's own firmware (tested 2026-10-16, swapped into the image by hand):
  the battery reads a 5191 mAh design, and the charge current's maximum is 7 A.
- **Gyro**: the Nova's sensors process rebuilds its registry from the vendor configuration at
  every start, which Android allows. `kettle-motion-setup` keeps a writable copy of persist's
  sensors directory (`sensors/persist`, owned by fastrpc) and hexagonrpcd serves it, with
  hexagonrpc 0002-0004 (file writes there only, messages over 256 bytes, methods from 31 on).
  Tested on a Nova: kettle-motiond finds the accelerometer and gyro and streams them.
- **Amplifier tuning**: still the Odin 2's `aw883xx_acf.bin`; the Nova's vendor partition has its
  own, which loads too early for a runtime copy. The speakers work as they are.
- **Charging**: as on the Portal and Thor, kettle-powerd holds Steam's charge limit and Device
  Settings' charge speeds (Fast 7 A, Balanced 3 A, Slow 1.5 A) through `constant_charge_current`.
  Tested on a Nova on a 9 V PD charger at 99%: a 0.3 A cap took the battery from 566 to 277 mA
  within 2 s, and 7 A brought it straight back.

## Checked on a unit (20261016.4, 2026-10-16)
- Boots from the SD card through ROCKNIX ABL 1.2 in both slots (`kettle-abl-update --check`;
  fastboot's `version-bootloader` reads 1.1.8 all the same), which starts steamcl (EFI, no
  SMBIOS). `kettle-hwcheck`: every check passes.
- Internal storage (YMTC UFS, 115 GiB LUN 0): `userdata` is LUN 0's last partition, as the
  installer expects (`kettle-install-internal --plan`).
- Screen, touch, brightness (the panel's DCS backlight `ae94000.dsi.0`; the RP6 dts' PWM
  `backlight` stays powered off), speakers, the stick lights, Wi-Fi, Bluetooth.
- Every button, the paddles and Volume Up, with the face buttons by their labels.
- The charge current cap (Charging, above), and the gyro and battery profile on the Nova's own
  ADSP firmware (above).
- `kettle-adsp-firmware` on an A/B update (20261016.6): it copied the firmware from `vendor_a`
  and the ADSP was up 7.2 s into boot, with audio, the battery's own profile and the gyro.
- The gyro in a game; its axes were swapped with the identity matrix guessed before the unit
  came. Held upright in landscape, the Sensor Core puts gravity on +X (`ssccli --sensor
  accelerometer`), so the Nova takes the Portal's and Thor's rotation.

## Still to check, by hand
- Boot: a ROCKNIX ABL install from Android needs root, which Retroid's user build lacks (this
  unit already had 1.2); the internal install with *Boot source: Internal*.
- Screen: 60 Hz and switching between 60 and 120 Hz
  (if it sticks at a low frame rate or a wrong rate after a switch, limit it to 120 Hz as
  `20-sm8550/1021` does for the RP6). Steam's UI scale and the desktop's.
- Brightness: the lowest levels (pocknix found the lowest Plasma brightness turns the panel
  fully dark), for a floor like `40-kettle/1120`'s on the Portal.
- Controls: the sticks' centring and the trigger deadzones in games, and the desktop
  controller.
- Audio: the headphone jack and its detection, the microphone (the speakers work).
- Battery and charging: a charge limit held and released below ~95% (at 98–99% the Portal's
  firmware latches "Not charging" after a 0 cap until a replug), and the percentage on the
  Nova's own profile over a full discharge. pocknix testers reported charging stopping after a
  kernel update.
- `kettle-adsp-firmware`: the vendor copy on a fresh install from an SD card, and the fallback
  without one.
- Fan: does it spin up with the trips, its noise, and whether `fan1_input` (tach) reads.
- Motion: the new axis matrix in a game (`packages/kettle-motion/devices.conf`), and the gyro
  after sleep.
- Power: the TDP range (4-18 W, a placeholder), the profiles, idle and sleep drain, s2idle and
  wake: the SM8550 deep sleep (PCIe GDSCs off, `40-kettle/1463`, no PCIe suspend floor) reaches
  CX/AOSS/DDR collapse on the Portal and Thor; check that the Nova does and wakes, Wi-Fi/BT after resume.
- AYN-specific tuning in the common dtsi (regulators, PCIe, audio rails): the Nova runs it as
  ROCKNIX does, but none of our fixes on top of it have been tried on Retroid's board.
