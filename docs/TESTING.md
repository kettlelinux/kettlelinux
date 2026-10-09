# Testing on an Odin 2 Portal

The SD card's first partition (FAT, `KETTLE`, the SteamOS `esp`) carries every boot path, so
it works with whichever loader the device runs:

| Loader | Uses | Slot fallback |
|---|---|---|
| ROCKNIX ABL (v1.2) | `\EFI\BOOT\BOOTAA64.EFI` (steamcl) when it is there; else `\KERNEL` + `\KERNEL.md5` (boot.img v0, all SM8550 DTBs; ABL picks by Device model) | yes through steamcl; `\KERNEL`: no, always the newest slot |
| U-Boot (standard boot / distro_bootcmd) | `\extlinux\extlinux.conf` → `\Image` + `\dtbs\qcom\qcs8550-ayn-odin2portal.dtb` | no: always the newest slot |
| Any UEFI (U-Boot EFI, ABL EFI chainload) | `\EFI\BOOT\BOOTAA64.EFI` = steamcl → the slot's GRUB (`efi-A`/`efi-B`) | yes ([UPDATES.md](UPDATES.md)) |

U-Boot usually tries extlinux before EFI, and would then never reach steamcl: which one it
used shows in the checklist below (Boot path). That decides whether the SD card image should
keep extlinux.

Partition 1 also has the GPT *LegacyBIOSBootable* attribute, which older U-Boot
`distro_bootcmd` scripts use to choose the partition. From a U-Boot prompt you can boot by hand:
`load mmc 1:1 ${kernel_addr_r} Image; load mmc 1:1 ${fdt_addr_r} dtbs/qcom/qcs8550-ayn-odin2portal.dtb; setenv bootargs "<append line from extlinux.conf>"; booti ${kernel_addr_r} - ${fdt_addr_r}`
(check the SD device number with `mmc list`).

## 1. Bootloader

Booting from the SD card with the ROCKNIX ABL (installing it, and its Vol− menu settings) is
in [INSTALL.md](INSTALL.md), the user guide. This page is for testing your own builds.

## 2. Write the image

```sh
scripts/build-kernel.sh && scripts/build-packages.sh
WIFI_SSID='MyNetwork' WIFI_PSK='secret' scripts/build-image.sh   # Wi-Fi optional but needed for SSH
sudo dd if=out/kettle-YYYYMMDD.N-odin2portal.img of=/dev/sdX bs=4M conv=fsync status=progress
```

Check `/dev/sdX` with `lsblk` first — dd overwrites the whole target. (A downloaded
`.img.xz`: `xzcat` it into the same dd, or see [INSTALL.md](INSTALL.md).) The card needs 32 GB or
more. On first boot the system creates slot B and `/home` in the rest of the card (the SteamOS
layout, [UPDATES.md](UPDATES.md)); that first start takes a little longer.

Login: `kettle` / `kettle` (sudo via wheel), on the panel console or `ssh kettle@kettle.local`
(or the IP from your router). Root login is disabled.

## 3. Checklist (report back with `dmesg` + `journalctl -b` for anything that fails)

| Area | Command | Expect |
|---|---|---|
| Boot / panel | — | console on the OLED, rotated upright |
| Kernel | `uname -r` | `7.2.7-kettle` |
| Boot path | `ls /sys/firmware/efi`; `holo-bootconf this-image`; `lsblk -o NAME,PARTLABEL,SIZE,MOUNTPOINTS` | present if steamcl booted it (absent: extlinux or `\KERNEL`); `A`; `rootfs-B` and `home` exist, `/home` fills the card |
| Read-only system | `holo-readonly status`; `findmnt /etc /var /home` | `enabled`; `/etc` an overlay, `/var` and `/home` their own partitions |
| Updates | `sudo rauc status`; `steamos-update check` | slot A booted, good; "No update available" or a build (needs `KETTLE_UPDATE_URL`) |
| Update from a file | copy a newer build's `.raucb` and its `.castr/` folder into one directory on the device; `sudo rauc install kettle-….raucb`; reboot | installs into slot B; boots it (`holo-bootconf this-image`: `B`) |
| Slot fallback (EFI boot only) | in slot B: `sudo holo-bootconf config --image B --set image-invalid 1`; reboot | slot A boots |
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
| Power draw | `kettle-powertest state`; on battery: `kettle-powertest 120 idle` | per-run mW + settings in `~/.local/state/kettle-powertest.csv` |
| Crash reports | `systemctl status kettle-crashd`; `sh -c 'kill -SEGV $$'`; `ls /var/log/kettle-crash` | a `*-coredump-sh` report: `report.json` (versions, game, Kettle features), `backtrace.txt`, journal and kernel log; a GPU hang or firmware crash adds a `*-devcoredump-<driver>` one. With a Steam app id (`SteamAppId=<id> sh -c 'kill -SEGV $$'`): a "<game> crashed" toast in Game Mode, and the report in Quick Access > Crash Reports. A Windows game's crash in Wine (`wine: Unhandled ...` in `~/.local/share/Steam/logs/steam_output.log`) makes a `*-game-<name>` report with the game's output |
| Game Settings | Game Mode: Quick Access > Game Settings, pick a game; FEX > TSO emulation Off, a preset, a Proton version; then check the game's launch options (Properties) | `FEX_TSOENABLED=0 %command%` and the preset's variables in the launch options, your own options untouched; the Proton version in Properties > Compatibility; Reset takes out only what the plugin added and puts the version back. In a launched game `tr '\0' '\n' </proc/$(pgrep -f '\.exe' | head -1)/environ \| grep FEX_` shows the variables. After 5 min of play, "Do these settings work?" > Yes enables Share (with `games.conf`) |
| Desktop power | Desktop Mode: Power (speedometer) in the system tray; Powersave, 6 W, fixed GPU clock, a fixed fan speed; then Return to Game Mode and back | readout moves; `GetStatus` (below) shows the caps and `active_game` `desktop`; Game Mode has Steam's own values and its fan/CPU settings; the desktop's come back with it |

Suspend is the least proven area: nobody has validated s2idle on a Portal yet. After a
resume check `dmesg | tail -50`, that the gamepad still reports input, and Wi-Fi reconnects.

## 4. Power/performance A/B runs

`kettle-powertest [SECONDS] [LABEL]` averages battery draw (plus CPU/GPU clocks and peak
temperatures) over a run and logs it with the scheduler, Wi-Fi power-save and display mode in
effect. Same workload, charger unplugged, change one thing at a time:

```sh
kettle-powertest 120 idle-lavd                     # panel on, desktop idle
sudo systemctl stop scx; kettle-powertest 120 idle-eas
FPS=60 kettle-powertest 300 game-lavd              # FPS: read off the overlay
sudo iw dev wlan0 set power_save on; kettle-powertest 120 idle-wifips
kettle-powertest results
```
