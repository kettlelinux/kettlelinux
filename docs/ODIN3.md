# AYN Odin 3

The Odin 3 is Kettle's second Snapdragon 8 Elite device after the
[Pocket FIT Elite](POCKETFITELITE.md). Its SoC is AYN's CQ8725S, an SM8750 variant with its own
SoC id (706). Most of the rest is hardware Kettle already runs:

- From the Pocket FIT Elite: the SM8750 SoC, the A830 GPU, the WCN7860 Wi-Fi and the
  WCD9395 codec.
- From the Thor and Portal: the ICNA3520 panel (the Thor's top screen), the AYN gamepad MCU
  (rsinput), the HTR3212 stick lights and the PMIH0108 haptics.

It uses the same kernel build, userspace and A/B updates as every device. How its files are kept
apart from the other devices': [PORTING.md](PORTING.md).

The port was started on 2026-11-06 with a unit on hand (16 GB, Android 15 V1.0.0.187, bootloader
unlocked). Its first images (20261106.1 from microSD, then 20261107.1 installed to the internal
UFS and updated A/B) ran on it on 2026-11-07: [Tested](#tested) and
[Still to check](#still-to-check).

References:

- **ROCKNIX's SM8750 device** (`projects/ROCKNIX/devices/SM8750`, `next` @ `13d241a`). It has
  `cq8725s-ayn-common.dtsi` and `cq8725s-ayn-odin3.dts` (Teguh Sobirin, BSD-3-Clause).
- **Armada** (armada-os/armada @ `d5f0724e`). It ships the same dts files plus its own fixes,
  credited below.

## Hardware, from ROCKNIX's dts
| | |
|---|---|
| SoC | CQ8725S (msm-id 706; the stock devicetree also lists 705, 639 and 618, board-id `0x1001f`) |
| CPU | six Oryon cores 0.38-3.53 GHz, two prime cores 1.02-4.32 GHz (Android's tables, this unit) |
| GPU | Adreno 830, 160-1100 MHz |
| Display | 1080x1920 AMOLED, ICNA3520 (`chipone,icna3520`), mounted at 90 degrees, 60/120 Hz |
| Touch | FocalTech FT5426 (edt-ft5x06) on i2c4 |
| Controls | AYN MCU gamepad on UART15 (rsinput, `AYN Odin3 Gamepad`, 2020:3001); back paddles M1/M2 on TLMM gpio 3/7 (`gpio-keys-paddles`, BTN_Z/BTN_C); Volume Up on gpio-keys, Volume Down on the PMIC |
| Lights | two HTR3212 (four RGB LEDs round each stick); an RGB light on PMIC LPG channels 1-3 |
| Audio | 2x AW88166 speaker amps on secondary MI2S; WCD9395 headphone codec over SoundWire, with its USB-C/jack switch; a DMIC; DisplayPort over USB-C |
| Wi-Fi/BT | WCN7860 (ath12k, PCI `17cb:110e`) |
| Haptics | PMIH0108 HV haptics (LRA), fed rumble by rsinput |
| Fan | pwm-fan on PM8550 PWM 3, cooling levels 0 30 45 60 70 90 120 150 (the Portal's) |
| Battery | 8000 mAh (7838 mAh design), pmic-glink battery manager |
| Storage | UFS, microSD |

## Building
```sh
scripts/build-kernel.sh      # cq8725s-ayn-odin3.dtb; 22-sm8750 (0026/0027 add the CQ8725S id)
scripts/build-packages.sh kettle-firmware-odin3 kettle-ucm-odin3 kettle-power kettle-motion inputplumber
KETTLE_DEVICE=odin3 scripts/build-image.sh    # -> out/kettle-<build>-odin3.img
```

## Booting

There is no U-Boot for SM8750, and the Odin 3 has no `loader` partition, so AYN's U-Boot route
(the Portal's and Thor's) doesn't exist here. The image boots through OpenABL's SM8750 build in
`abl_a`/`abl_b`, as on the Pocket FIT Elite:

- OpenABL picks the devicetree by its *Device model* setting, which must read "AYN Odin 3" (the
  dtb's `model`). OpenABL also knows the Odin 3's panel lines for its menu.
- `\KERNEL` only gets this board's dtb (`ABL_DTBS="qcom/cq8725s-*.dtb"`), so the Pocket FIT
  Elite's never shows up in that menu.

On the test unit OpenABL v1.2 went into `abl_b` only, with fastboot (`fastboot flash abl_b`,
then `fastboot set_active b`); `abl_a` still holds AYN's stock ABL, so "Boot other slot" returns
to stock Android. Not done yet: back up the stock `abl_a` from Kettle (1 MiB, with its sha256),
then flash OpenABL there too.

If slot b gets marked unbootable (no Android on it ever marks it successful, so tries run out
when it boots Android or stalls), the bootloader falls back to slot a's stock ABL. `fastboot
set_active b` clears that. On the stock ABL, ask for single variables only: `fastboot getvar all`
hung there and left fastboot answering nothing until a forced restart.

## What is different from the other devices

**Kernel** (`kernel/dts/qcom/cq8725s-*`):

- ROCKNIX's dts and dtsi, with Armada's dts changes:
  - the DisplayPort audio link
  - PCIe WAKE# made active-low
  - the four WCN7860 PMU rails kept on (re-enabling them at resume can hang the SoC)
  - the unused WSA macros off (bound, they kept the ADSP waking in s2idle)
  - Volume Up no longer a wakeup source
  - five codec rails in LPM through s2idle
  - the SoCCP image (deep sleep)
  - the internal mic's DMIC route
  - the gamepad's 1024 axis range
- Not taken from Armada: its DPU dither property (`armada,dpu-8bpc-dither`), which our kernel
  has no driver for.
- The Pocket FIT Elite's SoC-level fixes, each commented in the dts:
  - crypto off (7.3's missing QCE driver keeps DDR at its maximum and blocks deep sleep)
  - the CoreSight TNOC off
  - no USB or Wi-Fi wakeup
  - the non-secure ADSP fastrpc device (gyro)
  - the CDSP off
  - the SD card capped at 100 MHz
- Ours: the stick rings grouped as multicolor LEDs `rgb:l1..l4`/`rgb:r1..r4`, as on the Portal.
  The PMIC RGB light is `power-led`, with no kernel trigger: kettle-ledd's "charging" mode does
  what Armada's trigger did. And `cq8725s-ayn-odin3-fan.dtsi`, the fan bound to the CPU and GPU
  zones at 50-80 C, one level per 5 C, as `qcs8550-ayn-fan.dtsi` does.

**Kernel patches:** `22-sm8750/0026`/`0027` (CQ8725S SoC id). Everything else the board needs
is already in the stack:

- `20-sm8550`: rsinput with rumble, the HTR3212, the ICNA35xx panel and the aw88166. Its
  haptics driver (`1000`) is ROCKNIX's SM8750 copy, the newer Qualcomm driver: the Odin 3's
  PMIH0108 haptics block is revision 5 (HAP530), which the SM8550 copy refused ("haptics revision
  is not supported", first boot 2026-11-07). The Portal and Thor use the same copy.
- `22-sm8750`: the SM8750 parts.

Left out of ROCKNIX's SM8750 set:

- `0518`: ICNA3520 frame-length tuning in sysfs. Its defaults are what we send, and it would
  touch the Thor's panel too.
- `1000`/`1001`/`1004`: the haptics driver and its fixes, carried in `20-sm8550` instead.
- `1002`/`1300`: rumble and stick ranges for ROCKNIX's rewritten rsinput. Ours has both.
- `0032`: aw88166 AYN version. Ours is the same apart from no-op DAI ops; the card ignores
  `-ENOTSUPP`.
- `0050`: only silences a GDSC warning.

**Firmware** (`packages/kettle-firmware-odin3`): its own package, since kettle-firmware-ayn is
the SM8550 boards' files at an older pin. It holds:

- ROCKNIX `extra-firmware` (the Pocket FIT Elite's pin): `qcom/sm8750/ayn/odin3/*` (DSPs,
  battery manager, amp tuning), WCN7860 and Bluetooth.
- Armada: `soccp.mbn`, from the Odin 3's modem partition, and `SM8750-AYN-tplg.bin`, the audio
  topology. ROCKNIX's has no MultiMedia4 stream for DisplayPort, which Armada's UCM profile
  routes, so the HiFi verb failed and PipeWire had no outputs (first boot, 2026-11-07).
- linux-firmware-qcom: the A830 and iris firmware.

**Audio** (`packages/kettle-ucm-odin3`): Armada's version of ROCKNIX's profile (card
`SM8750-AYN`). It has:

- speakers
- headphones in PCM mode with the compander off (it clipped)
- the internal mic and the headset mic
- DisplayPort

`61-kettle-odin3-jack.rules` keeps the SoundWire buses awake for jack detection, as on the
Pocket FIT Elite.

**Controls:** `40-kettle-odin3.yaml` is the Portal's InputPlumber profile with the Odin 3's names:

- a Deck controller
- the Thor's map (`kettle-thor`): the face buttons are labelled Nintendo-style (A right, B
  bottom), and Steam follows the labels; the button below the right stick is Quick Access
- the paddles as the back buttons
- kettle-motiond's gyro

**Power** (`packages/kettle-power/odin3.toml`): Android's frequency tables. The rest is the
Pocket FIT Elite's (TDP 4-22 W, profiles) or Armada's (the charge limit through the firmware's
end threshold, floor 55%; AYN's own Android keeps an 80% end threshold, so the firmware takes
it). The charge current is the 8.6 A Android had set.

**Gyro:** kettle-motion with the rotation every other device uses, until measured. The Pocket
FIT Elite's `kettle-sensors-settle` sleep hook is here too: the same ADSP sensors process and
the same early-suspend hang window are assumed.

**Screen:** Game Mode turns the panel `right` and reports the Portal's panel size for Steam's
UI scale, as on the Thor. The desktop layout is the Pocket FIT Elite's (`Rotated270`).

## Tested
On the unit, 2026-11-07:

- **Boot** from microSD (20261106.1) and from the internal UFS, and an A/B update to 20261107.1
  with `rauc install`.
- **Screen and touch:** the panel the right way up, touch where pressed.
- **Lights:** the stick rings light.
- **Wi-Fi, Bluetooth, sound card, gamepad, paddles, gyro device:** all come up; no failed units.
- **Audio:** the speakers play; PipeWire lists the speakers, headphones, DisplayPort and the
  internal mic (after the topology fix, see Firmware).
- **Rumble:** the haptics driver probes HAP530 and a rumble through the gamepad plays. After a
  stop it once warned "poll HPWR_DISABLED failed after stopped play" and reset the module (its
  recovery path); watch idle power for a haptics rail left on.
- **Power:** cpufreq tops out at 3.53 GHz (main) and 4.09 GHz (prime) under Linux; Android listed
  4.32 GHz for the prime cores.

## Still to check
On the unit, in order:

1. **Boot:** Device model "AYN Odin 3" from a cold start, 60/120 Hz, the GPU chip id
   (`0x44050000` vs upstream's `0x44050001`).
2. **SD at SDR104:** if cards read cleanly at full speed, drop the 100 MHz cap.
3. **Controls:**
   - the face buttons in Steam and on the desktop by their Nintendo labels (20261107.1)
   - the button map, the Home/Quick Access buttons, the paddles
   - the stick axes (range 1024)
   - rumble in a game
4. **Lights:** the stick ring order, the `power-led` channel order and colours.
5. **Audio:** the headphone jack and its detection, the internal and headset mics, DP audio.
6. **Wi-Fi/BT:** under a long download (the 7.3 ring-size fix `40-kettle/1466`), after resume.
7. **Suspend:**
   - CX/DDR collapse (SoCCP image, crypto off)
   - wake sources
   - a suspend right after a gyro game closes: Armada hit a hang there, fixed by turning off
     SSC island mode (`enable_island` 0 in the vendor `pakala_power_0.json`)
   - the settle hook's window
8. **Gyro:** the axis matrix in a game.
9. **Power:** the cpufreq tables Linux gets (4.32 GHz boost steps?), the fan curve and tach,
   TDP range in a game, the charge limit and speeds, `constant_charge_current_max`.
