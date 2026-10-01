# Retroid Pocket 5

The RP5 is the first Kettle device on another SoC: a Snapdragon 865 (SM8250, Adreno 650), where
the Portal and the Thor have a QCS8550. It uses the same kernel build (SM8250 support is a patch
directory and a config fragment next to the SM8550 ones), the same userspace, and the same A/B
updates. What it needs of its own is below, with what has been checked on an RP5. How
its files are kept apart from the other devices': [PORTING.md](PORTING.md).

The references are ROCKNIX's SM8250 device (`projects/ROCKNIX/devices/SM8250`, at the ROCKNIX
commit pinned in `kernel/patches/README.md`), which has run the RP5 on 7.2 for a while, and
pocknix-os (Arch Linux ARM with Steam on the RP5), whose findings on the device are credited
where they are used.

## Building
```sh
scripts/build-kernel.sh                  # SM8250: kernel/patches/21-sm8250, kernel/config/sm8250.config
scripts/build-packages.sh u-boot-retroidpocket kettle-firmware-retroid kettle-ucm-retroid \
  kettle-power inputplumber steamos-customizations-kettle mangohud kettle-decky-plugins
KETTLE_DEVICE=rp5 scripts/build-image.sh    # -> out/kettle-<build>-rp5.img (+ .raucb)
```

## Booting
Two ways, both from the SD card. Neither needs a bootloader unlock.
- **Retroid's U-Boot, in the loader partition** (with A/B fallback, like the AYN devices). The
  RP5's own bootloader (ABL) boots whatever is in its `loader` partition. Flash it once, from a
  PC, with the RP5 in fastboot mode (hold Power + Volume Down):
  ```sh
  fastboot flash loader u-boot-rp5.img     # from the SD card's KETTLE partition
  ```
  Then boot the loader: hold Power + Volume Up, or set it as the default in Android's Retroid
  settings. `fastboot boot u-boot-rp5.img` tries it without flashing. U-Boot boots
  `\EFI\BOOT\BOOTAA64.EFI` (steamcl) from the SD card, then GRUB and the slot's kernel.
  `u-boot-rp5.img` is `packages/u-boot-retroidpocket`: Retroid's source and recipe.
- **ROCKNIX's ABL**, for those who have installed it for ROCKNIX (or Batocera, Knulli, ...). It
  boots `\KERNEL`, which carries both RP5 devicetrees (`ABL_DTBS`); its Device model setting
  picks the panel. No A/B fallback: `\KERNEL` follows the newest slot.

### The two panels
Newer RP5s have a Visionox VTDR6130 panel instead of the CH13726A, and nothing tells the two
apart before the panel's driver runs: the wrong devicetree leaves the screen black (Steam still
starts). Kettle boots the CH13726A devicetree unless told otherwise: put an empty file named
`visionox` (or `visionox.txt`) in the top folder of the SD card's KETTLE partition, from a PC,
and GRUB boots `sm8250-retroidpocket-rp5-visionox.dtb` instead (`DTB_ALT` in `device.conf`,
checked at every boot). pocknix-os uses the same file name.

## What is different from the Portal
| Area | RP5 | Where |
|---|---|---|
| Kernel | ROCKNIX's SM8250 patches not already carried for SM8550 (gamepad MCU, PM8150B charger and fuel gauge, SPMI haptics, SM8250 audio), plus a 120 ms sleep-out wait for the CH13726A and the Visionox panel's 60 Hz mode only (0106) | `kernel/patches/21-sm8250`, `kernel/config/sm8250.config` |
| Device tree | `sm8250-retroidpocket-rp5.dts` and `-rp5-visionox.dts` (ROCKNIX) | `kernel/dts/qcom/` |
| Boot | U-Boot in the loader partition, or ROCKNIX's ABL; a marker file picks the panel | `packages/u-boot-retroidpocket`, `DTB_ALT`/`ABL_DTBS` |
| Firmware | linux-firmware only: SM8250 ADSP/CDSP/SLPI, A650, iris (`vpu20_p4`), QCA6390 Wi-Fi (ath11k) and Bluetooth | `kettle-firmware-rp5` (`packages/kettle-firmware-retroid`) |
| Audio | card `RetroidPocket` (`retroidpocket-RetroidPocket5` under U-Boot's EFI): WSA881x speakers, WCD9385 jack, DisplayPort audio; jack detection needs the codec kept awake (udev) | `kettle-ucm-rp5` (`packages/kettle-ucm-retroid`), `device/rp5/overlay` |
| Audio at boot | a service reloads the LPASS drivers that probed before the ADSP was up (else no sound card; found by pocknix-os) | `kettle-rp5-audio-heal.service` |
| Power | `rp5.toml`: clusters 4+3+1, A650 305-670 MHz, PM8150B charger (`pm8150b-charger`), no charge limit (the driver has none) | `packages/kettle-power` |
| Steam's device | steamos-manager `retroid-rp5.toml` (DMI `retroidpocket` / "Retroid Pocket 5" as Retroid's U-Boot fills it from its devicetree, DT `retroidpocket,rp5`) | `device/rp5/overlay/usr/share/steamos-manager` |
| Controller | Steam Deck target over upstream's `ret1` map (the button below the right stick is Quick Access), face buttons by their Nintendo-style labels as on the Thor (`FACE_BUTTONS=nintendo`); no paddles | `packages/inputplumber/40-kettle-rp5.yaml`, `kettle-rp5-capability-map.yaml` |
| Game Mode | orientation `left`, as on the Portal (1080x1920 panel, dts rotation 270); the Portal's panel size is reported so Steam's UI isn't oversized (as pocknix-os found) | `device/rp5/overlay/usr/lib/kettle/gamescope.conf` |
| Desktop Mode | DSI-1 at 60 Hz, rotated, scale 2 | `device/rp5/overlay/etc/skel` |
| Desktop controller | the triggers are ABS_HAT2X/ABS_HAT2Y on this pad (rsinput's are ABS_Z/ABS_RZ) | `device/common/overlay/usr/lib/kettle/desktop-controller` |

Shared changes the port brought, which the Portal and Thor need re-testing for: the DSI fixes in
`21-sm8250` (0001, 0016), the CH13726A sleep-out wait (the Thor's bottom panel), the wcd938x jack
IRQ guard (0300), the A740-only GPU runtime-PM rule, and `PAD_NAME` in the gamepad udev rule.

## Verified on an RP5
First boot of 20260930.1 from SD, on an RP5 with the CH13726A panel (Android reports it as a
1080x1920 60 Hz video-mode panel; the Visionox is command mode):
- Boot: stock ABL -> `fastboot boot u-boot-rp5.img` -> U-Boot -> steamcl -> GRUB -> Kettle.
- `kettle-hwcheck`: display, GPU and Vulkan (Turnip, Adreno 650), gamepad, touchscreen, power
  key, haptics, stick LEDs, battery, fan, Wi-Fi, Bluetooth, sound card (speakers playing Steam's
  sound), microSD at SDR104, s2idle offered. SMBIOS from U-Boot is `retroidpocket` /
  `Retroid Pocket 5`, as expected.
- The audio heal service had nothing to reload on that boot.
- The charger's power supply is `pm8150b-charger` (fixed in `rp5.toml`); it reports
  `online=16` and implausibly low input currents.

## Still to check, by hand
- The Visionox devicetree and the `visionox` marker file, on a Visionox unit.
- Both boot paths: `fastboot boot` / `flash loader` with `u-boot-rp5.img` (the boot image is
  written by Kettle's `mkbootimg.py` with Retroid's parameters), and ROCKNIX's ABL with `\KERNEL`.
  steamcl's slot choice and fallback under this U-Boot.
- steamos-manager's match on the DMI strings (Steam's device and power controls).
- Face buttons: the button labelled A is Steam's A in Game Mode, and Desktop Mode's controller follows the labels too.
- Game Mode orientation, touch (the devicetree's inverted axes against the rotation), the UI
  size, and Desktop Mode's scale.
- Gamepad, rumble (SPMI haptics), stick LEDs, sound (speakers, headphones, DisplayPort), whether
  the audio heal service is needed and works, Wi-Fi/Bluetooth, fan, battery and charger readings,
  TDP range and the profiles' CPU caps against the device's cpufreq tables.
- Sleep: s2idle, as on the AYN devices.
- Vulkan: Turnip is Vulkan 1.3 on the A650 without 8-bit storage; whether Proton's DXVK runs
  (pocknix-os swaps in DXVK 2.7).
- Internal (UFS) install: `kettle-install-internal` assumes the AYN layout; pocknix-os found the
  RP5's main LUN `/dev/sda` with Android's userdata last, as on the AYN devices, but with its
  boot chain on another LUN. Not supported yet.
- Not taken yet: ROCKNIX's A650 overclock/ACD/bandwidth votes (`9998-gpu-tuning`).
