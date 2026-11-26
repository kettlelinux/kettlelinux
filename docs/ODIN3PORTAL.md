# AYN Odin 3 Portal

The Odin 3 Portal is the [Odin 3](ODIN3.md)'s board in a Portal-style body. It has the same
CQ8725S SoC (sold as "Dragonwing Q8"), A830 GPU, WCN7860 Wi-Fi, AYN MCU pad, HTR3212 stick
lights, AW88166 amps and WCD9395 codec. What is different:

- a 7" 1080x1920 AMOLED, a Visionox VTDR6130, not the Odin 3's 6" ICNA3520
- its own ADSP firmware
- no USB-C redriver
- Xbox-labelled face buttons (A at the bottom), as on the Odin 2 Portal

The port is built from Armada's Odin 3 Portal support (armada-os/armada `main` @ `384ac7c0`),
on top of our Odin 3 port. It was started on 2026-11-25 without a unit: nothing here has run on
hardware yet.

## Building
```sh
scripts/build-kernel.sh      # cq8725s-ayn-odin3portal.dtb; 40-kettle/1470 (the panel)
scripts/build-packages.sh kettle-firmware-odin3portal kettle-power kettle-motion inputplumber
KETTLE_DEVICE=odin3portal scripts/build-image.sh    # -> out/kettle-<build>-odin3portal.img
```

## Booting

The same route as the Odin 3: OpenABL's SM8750 build in `abl_a`/`abl_b` (see
[ODIN3.md](ODIN3.md#booting)). OpenABL lists the *Device model* choices from the dtbs it finds
on the boot drive, so it offers "AYN Odin 3 Portal" (the dtb's `model`; `\KERNEL` carries only
the Portal's dtb, `ABL_DTBS="qcom/cq8725s-ayn-odin3portal.dtb"`) and takes the panel rotation for
its menu from that dtb. OpenABL v1.2 has no panel power lines for the Portal (its table has the
Odin 3's GPIO 56/97, which the Portal's panel doesn't use), so it switches none at hand-over.

The test unit came with its bootloader already unlocked (stock Android 15, build
20261104).

## What is different from the Odin 3

**Kernel:**

- `kernel/dts/qcom/cq8725s-ayn-odin3portal.dts` includes the Odin 3 dts, so every Odin 3 and
  Kettle fix carries over (fan curve, LEDs, paddles, deep sleep, crypto off, gyro fastrpc). It
  changes only what Armada's Portal dts changes:
  - the panel: `vtdr6130,o3p` with its vddio and tvdd supplies, rotation 270, and the Odin 3's
    panel rails (gpio 56, 97) removed
  - no redriver: the QMP PHY goes straight to pmic_glink, and the USB-C audio switch has no
    reset line
  - reserved memory (two more carve-outs, the splash buffer, a larger Gunyah region, no cpusys VM)
  - ADSP firmware from `qcom/sm8750/ayn/odin3portal/`, and the modem remoteproc off
  - the fan PWM period (50 us), SD pin drive strength 16
  - the pad named "AYN Odin3 Portal Gamepad"
- The sound card keeps the Odin 3's name, `SM8750-AYN`. Armada's Portal topology and UCM profile
  are only links to the Odin 3's, so `kettle-ucm-odin3` and the Odin 3's topology work as they are.
- `40-kettle/1470`: the VTDR6130 driver gets the Portal's panel (Armada 1111, 1304 and 1305,
  squashed). Not taken: Armada's DPU 8 bpc dither property.

**Firmware** (`packages/kettle-firmware-odin3portal`): the Portal's `adsp.mbn` and
`adsp_dtb.mbn` from Armada. Its SoCCP image is byte-identical to the Odin 3's, and is linked
together with the amp tuning and the `.jsn` service files. Everything else comes from
`kettle-firmware-odin3`.

**Controls** (`40-kettle-odin3portal.yaml`): the Odin 2 Portal's profile with the Portal's
names. It uses upstream's `rsinput1` map, because the face buttons are Xbox-labelled.
`40-kettle-odin3.yaml` now matches `ayn,odin3` exactly: its old `ayn,odin3*` also matched the
Portal.

**Power, gyro and screen:**

- `kettle-power/odin3portal.toml` is a copy of the Odin 3's.
- kettle-motion: the same axis rotation as the other devices (gravity on the Sensor Core's +X
  held upright in landscape, measured under Android on a unit).
- Game Mode turns the panel `left` (as on the Odin 2 Portal) at 60 or 120 Hz, 120 by default.

## The install-time reset (fixed by kernel 1471)

The first internal install died during the /home copy: the unit reset or powered off with no
kernel message, and the PMK8550 PON fault register showed UVLO or OVLO. A loop that copied /home
from the SD card to UFS reproduced it every time, about 2:45 into the copy, when free memory ran
out. It happened on battery or charger, with the CPU and GPU capped, and with the screen left on.
Once the system survived and logged `synchronous external abort` in `clear_page`, `copy_page` and
`__arch_copy_from_user`. Every faulting address was in 0xf2c00000-0xf37fffff, the ADSP fastrpc
remote heap.

Upstream's sm8750.dtsi makes that heap a `reusable` CMA pool. But mainline fastrpc assigns the
whole region to the LPASS and ADSP heap VMs at probe, without allocating it first. So the page
allocator still hands those pages out, and Linux faults on them. Kernel patch 1471 makes the region
`no-map`, which costs 12 MiB.

Tested on 2026-11-26 with only the dtb changed (loaded next to GRUB). The same copy loop ran 12
cycles, about 45 minutes with free memory down to 118 MB, with no abort and no reset. The KONKR
Pocket FIT Elite and the Odin 3 share sm8750.dtsi and get the fix too; they still need a retest.

With 1471 in the kernel, 20261126.1 installed to internal storage in 6.5 minutes on the same day
(free memory down to 128 MB during the /home copy) and boots from UFS. That needs OpenABL in both
`abl_a` and `abl_b`: with stock ABL left in `abl_a`, the unit dropped into stock fastboot whenever
slot B was marked unbootable (`fastboot set_active b` got it back).

## Still to check (first image)

20261125.1 booted from microSD through OpenABL v1.2 in `abl_b` (`abl_a` still stock) on
2026-11-25. Checked over SSH: the panel at 120 Hz (both modes listed), the backlight
(3071/4095), the A830 (GMU v5.1.25), the ADSP and SoCCP with the Portal's firmware, the sound
card, the pad and paddles claimed by `40-kettle-odin3portal.yaml` as a Deck controller, Kettle
Motion Sensors, the touchscreen, Wi-Fi (5 GHz, 160 MHz), Bluetooth, USB-C (sink, PD 5 V),
battery and charging, SD at SDR104 100 MHz, kettle-powerd, and a 60 s s2idle with CX/DDR collapse
for 59.5 s and a clean resume. Seen in the log: the AW88166 `pa stop check fail` (as on the
Odin 3) and three Bluetooth `Frame reassembly failed (-84)` at boot. Tested by hand the same day:
touch, buttons and paddles, speakers, stick LEDs and the power LED.

- [x] OpenABL boots the image with *Device model* "AYN Odin 3 Portal"; its menu shows upright
- [x] the panel lights up at 120 Hz and comes back after suspend (60 Hz and brightness steps not tried)
- [x] touch (an FT5452, driven as FT5426): orientation
- [x] pad, paddles; face buttons map by label (A bottom) (rumble not tried)
- [ ] gyro in Steam's gyro test (axes measured under Android: same rotation as the others)
- [ ] speakers work; headphone jack, internal mic, DisplayPort audio not tried
- [x] Wi-Fi, Bluetooth (up; Bluetooth pairing not tried)
- [ ] USB-C: data in both orientations, DisplayPort out (no redriver)
- [ ] battery and charging (the Portal's ADSP), the charge limit
- [ ] fan, TDP; s2idle deep sleep and wake work
- [x] stick LEDs and the power LED
- [x] A/B update (20261125.1 -> 20261126.1 from a local bundle over HTTP, `rauc install`, 2026-11-26)
