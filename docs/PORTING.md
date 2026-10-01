# Adding a device

Kettle Linux builds one image per device from the same sources. Most of an image is shared: the
kernel, the packages, and `device/common/overlay`. What a device adds is kept in
`device/<name>/`, so a new device is a new directory, not changes to shared scripts. The Odin 2
Portal (`odin2portal`) and the AYN Thor (`thor`) are the examples to copy; the Retroid Pocket 5
(`rp5`, [RP5.md](RP5.md)) is the example of a device on another SoC (SM8250).

## Shared or per-device?
- **Shared** is anything that works the same, or better, on every device: a bug fix, a newer
  package, a feature built on hardware every device has (iris video decoding in Firefox, for
  example). It goes in `image/packages.txt`, `device/common/overlay` or a shared package, and it
  applies to every image. A fix found on one device ships to all of them.
- **Per-device** is only what describes that device's hardware: its device tree, firmware,
  audio profile, screens, buttons and power limits.
- **Shared, and off unless a device turns it on**: a feature only some devices need, but that
  is not tied to one device (the Thor's second screen in Game Mode is gamescope's
  `GAMESCOPE_LEASE_OUTPUT`, which any two-screen device can set). The code is shared; the setting
  that turns it on is in the device's directory.

Shared code never checks which device it runs on (no `if ayn,thor` in a script). It reads a
setting instead, from the device's `device.conf` or one of its overlay's files.

## What a device directory holds
| File | What it is | Read by |
|---|---|---|
| `device.conf` | `MODEL`, `DTB`, `ABL_DTBS`, `RAUC_COMPATIBLE`, `PAD_NAME`, `FACE_BUTTONS` (all required); `DTB_ALT` (optional) | `scripts/build-image.sh`; installed in the image as `/usr/lib/kettle/device.conf` |
| `packages.txt` | packages only this device's image gets, added to `image/packages.txt` | `scripts/build-image.sh` |
| `overlay/` | files copied over `device/common/overlay` | `scripts/build-image.sh` |
| `overlay/usr/lib/kettle/gamescope.conf` | Game Mode's screen: `GAMESCOPE_ORIENTATION`, `GAMESCOPE_OUTPUT`, a second screen's `GAMESCOPE_LEASE_*` (required) | `gamescope-session` |
| `overlay/etc/skel/.config/kwinoutputconfig.json` | the desktop's screen layout and rotation | KWin, for new users |
| `overlay/usr/share/steamos-manager/devices/<name>.toml` | the device as Steam sees it (steamos-manager) | steamos-manager |
| `overlay/usr/lib/kettle/hwcheck-device` | the device's own `kettle-hwcheck` checks (optional) | `kettle-hwcheck` |

`device.conf` on the device: shell scripts source `/usr/lib/kettle/device.conf`, and Python
scripts in `/usr/lib/kettle` read it with `import kettle_device` (`kettle_device.conf["PAD_NAME"]`).
A new setting goes in every device's `device.conf`, in `build-image.sh`'s list of required
settings if it has no sensible default, and in the table above.

Devicetree settings (the image build copies them into `/usr/lib/kettle/boot.conf`):
- `DTB`: the devicetree GRUB and extlinux boot with, relative to `/boot/dtbs`.
- `ABL_DTBS`: globs of the devicetrees appended to `\KERNEL` for the ROCKNIX ABL, which picks one
  with its Device model setting. One ABL build serves one SoC, so only that SoC's
  (`qcom/qcs8550-*.dtb` for the AYN devices).
- `DTB_ALT`: revisions of the device that nothing can tell apart before the kernel runs, as
  `NAME:DTB` pairs (the RP5's `visionox:...-rp5-visionox.dtb`). An empty file `NAME` or `NAME.txt`
  in the top folder of the KETTLE partition makes GRUB and extlinux boot that DTB instead.
- `PAD_NAME` also goes into the udev rule that keeps the pad a joystick
  (`60-input-kettle-gamepad.rules`).

## Per-device parts of shared packages
Some packages carry a file for each device. Two patterns, and which to use:
- **A package per device** (`kettle-firmware-<name>`, `kettle-ucm-<name>` from
  `packages/kettle-firmware-{ayn,retroid}` and `packages/kettle-ucm-{ayn,retroid}`): for large files, or files that
  would clash between devices. They conflict with each other, and the device's `packages.txt`
  names its own.
- **One package, the device's file picked at run time from the device tree's `compatible`**
  (`packages/inputplumber`'s `40-kettle-<name>.yaml`, `packages/kettle-power`'s `<name>.toml`):
  for small settings files, when the program already picks a file by the hardware it finds.

## Updates
Each device has its own update stream: `RAUC_COMPATIBLE` (RAUC refuses another device's bundle)
and the update variant, the device directory's name (`steamos-atomupd`'s `Variants`, set by
`build-image.sh`). `scripts/publish-update.sh` keeps each variant's releases apart
(`images/<variant>/`), and each device's builds need build IDs of their own. A device's
`RAUC_COMPATIBLE` and directory name never change once it has users: installed systems would
stop taking updates.

## Adding one
1. **Kernel**: its device tree in `kernel/dts/qcom/` (ROCKNIX's, where there is one), built by
   `scripts/build-kernel.sh`. There is one kernel for every device: a new SoC adds its patches
   as `kernel/patches/2N-<soc>/` and its drivers as a `kernel/config/<soc>.config` fragment in
   `build-kernel.sh`'s `FRAGMENTS` (`21-sm8250`, `sm8250.config`), checked like
   `steamos.config`. Patches its hardware needs go in `kernel/patches/`, shared if they
   are drivers.
2. **`device/<name>/`**: `device.conf` (a new `RAUC_COMPATIBLE`), `packages.txt`, and the overlay
   files above.
3. **Firmware and audio**: a `kettle-firmware-<name>` and `kettle-ucm-<name>`, added to the
   existing packages or new ones.
4. **Controls and power**: the InputPlumber profile, and a `kettle-power` description (TDP
   range, fan, charge limit), matched by the device tree's `compatible`.
5. **Build**: `KETTLE_DEVICE=<name> scripts/build-image.sh`. It stops if `device.conf` or
   `gamescope.conf` is missing something.
6. **Check it**: `sudo kettle-hwcheck` on the device, then a `docs/<NAME>.md` like
   [THOR.md](THOR.md): what's different, what has been checked on hardware, what hasn't.
7. **Every device's image** after a change to shared code: build and boot each one, not only
   the device the change was made for.
