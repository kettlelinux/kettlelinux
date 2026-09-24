# Testing on an Odin 2 Portal

The SD card's first partition (FAT, `STEAMPORTAL`) carries every boot path, so it works
with whichever loader the device runs:

| Loader | Uses |
|---|---|
| ROCKNIX ABL | `\KERNEL` + `\KERNEL.md5` (boot.img v0, all SM8550 DTBs; ABL picks by Device model) |
| U-Boot (standard boot / distro_bootcmd) | `\extlinux\extlinux.conf` → `\Image` + `\dtbs\qcom\qcs8550-ayn-odin2portal.dtb` |
| Any UEFI (U-Boot EFI, ABL EFI chainload) | `\EFI\BOOT\BOOTAA64.EFI` = systemd-boot → `\loader\entries\steamportal.conf` |

Partition 1 also has the GPT *LegacyBIOSBootable* attribute, which older U-Boot
`distro_bootcmd` scripts use to choose the partition. From a U-Boot prompt you can boot by hand:
`load mmc 1:1 ${kernel_addr_r} Image; load mmc 1:1 ${fdt_addr_r} dtbs/qcom/qcs8550-ayn-odin2portal.dtb; setenv bootargs "<append line from extlinux.conf>"; booti ${kernel_addr_r} - ${fdt_addr_r}`
(check the SD device number with `mmc list`).

## If you use the ROCKNIX ABL

The test image boots from the microSD card. Android on internal storage is not touched,
but booting Linux requires replacing the stock bootloader (ABL) with ROCKNIX's once.

### One-time: install the ROCKNIX ABL (from Android)

Needs root in Android (Magisk) or an ADB root shell. Releases: https://github.com/ROCKNIX/abl
(tested reference: v1.1.8).

1. Copy the release's scripts + `abl_signed-*.elf` to the device.
2. **Back up the stock ABL first** — `backup_abl.sh` writes `abl_a.img`/`abl_b.img`.
   Copy both backups *off the device* (PC/cloud). They are the only way back to stock.
3. Run `flash_abl.sh`. It writes `/dev/block/by-name/abl_a` and `abl_b`.
4. Undo at any time with `restore_backup_abl.sh`.

Boot controls with the ROCKNIX ABL:
- Hold **Vol−** at power-on: ABL menu. Set **Device model = Odin 2 Portal** (all AYN boards
  report the same msm-id/board-id; the kernel carries every SM8550 DTB and the ABL picks by
  this setting), **Boot source = SD**, **Boot mode = Linux**.
- **Vol+** at power-on (or Boot mode = Android) boots Android as before.

## 2. Write the image

```sh
scripts/build-kernel.sh && scripts/build-firmware.sh
WIFI_SSID='MyNetwork' WIFI_PSK='secret' scripts/build-image.sh   # Wi-Fi optional but needed for SSH
sudo dd if=out/steamportal-YYYYMMDD.img of=/dev/sdX bs=4M conv=fsync status=progress
```

Check `/dev/sdX` with `lsblk` first — dd overwrites the whole target.
The root partition grows to fill the card on first boot.

Login: `steamos` / `steamos` (sudo via wheel), on the panel console or `ssh steamos@steamportal.local`
(or the IP from your router). Root login is disabled.

## 3. Checklist (report back with `dmesg` + `journalctl -b` for anything that fails)

| Area | Command | Expect |
|---|---|---|
| Boot / panel | — | console on the OLED, rotated upright |
| Kernel | `uname -r` | `7.2.7-steamportal` |
| Wi-Fi | `nmcli dev wifi list` | WCN7850 (`ath12k_pci`) sees networks |
| Bluetooth | `bluetoothctl show` | controller present |
| Gamepad | `sudo evtest` | "RSInput Gamepad"-like device; sticks/triggers/buttons move |
| Rumble | `fftest /dev/input/eventN` (gamepad node) | motors buzz |
| Touch | `sudo evtest` | ft5x06 touchscreen |
| Battery | `cat /sys/class/power_supply/*/capacity` | battery % via qcom_battmgr |
| Fan | `cat /sys/class/hwmon/hwmon*/fan1_input`; `stress-ng --cpu 8 -t 45s` | 0 rpm when idle below 50 C; ramps to ~4500 rpm under load, stops again after |
| GPU (GL) | `sudo eglinfo -B` | freedreno, Adreno 740 |
| GPU (Vulkan) | `vulkaninfo --summary` | Turnip, Adreno 740 |
| Compositor | `sudo gamescope -W 1920 -H 1080 -- vkcube` (from a VT) | spinning cube |
| Audio | `aplay -l`; `speaker-test -c2 -twav` | card `AYN-Odin2`, speakers play |
| Sleep | `cat /sys/power/mem_sleep`; `sudo systemctl suspend`, wake with power key | `[s2idle]`; resumes with panel, pad, Wi-Fi |
| Wake source | `cat /sys/power/pm_wakeup_irq` after a spurious wake | which IRQ woke it |
| Power key | short press | suspends (long press powers off) |
| Swap | `swapon --show` | `/dev/zram0`, half of RAM (max 8 GB) |
| Power draw | `steamportal-powertest state`; on battery: `steamportal-powertest 120 idle` | per-run mW + settings in `~/.local/state/steamportal-powertest.csv` |

Suspend is the least proven area: nobody has validated s2idle on a Portal yet. After a
resume check `dmesg | tail -50`, that the gamepad still reports input, and Wi-Fi reconnects.

## 4. Power/performance A/B runs

`steamportal-powertest [SECONDS] [LABEL]` averages battery draw (plus CPU/GPU clocks and peak
temperatures) over a run and logs it with the scheduler, Wi-Fi power-save and display mode in
effect. Same workload, charger unplugged, change one thing at a time:

```sh
steamportal-powertest 120 idle-lavd                     # panel on, desktop idle
sudo systemctl stop scx; steamportal-powertest 120 idle-eas
FPS=60 steamportal-powertest 300 game-lavd              # FPS: read off the overlay
sudo iw dev wlan0 set power_save on; steamportal-powertest 120 idle-wifips
steamportal-powertest results
```
