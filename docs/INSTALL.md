# Installing Kettle Linux

Kettle Linux runs from a microSD card in the AYN Odin 2 Portal and the AYN Thor. Android on the
internal storage stays as it is, and you can start either one. The only change to the device
itself is a one-time bootloader swap, below, so it can start Linux. If your device already runs
the ROCKNIX ABL or U-Boot (from ROCKNIX or another Linux distro, for example), skip that step.

The steps are the same on both devices, with the differences noted. The Thor is newer to Kettle
than the Portal: see its release notes for what has been tested on it.

Kettle is early and in active development. Check the known issues in the release notes on
[kettlelinux.org](https://kettlelinux.org) before you start.

## What you need

- An AYN Odin 2 Portal or AYN Thor
- A microSD card of **32 GB or more**. Games are installed to it too, so bigger and faster
  (A2 / U3) is better. Everything on it is erased.
- A computer to write the card from (Windows, macOS or Linux)
- Root in Android (Magisk) or an ADB root shell, for the one-time bootloader step (not needed
  if you already have the ROCKNIX ABL or U-Boot)

## 1. Install the ROCKNIX bootloader (once)

**Skip this step** if your device already has the ROCKNIX ABL or U-Boot: Kettle's card works
with both as they are. Go on to step 2.

The stock bootloader (ABL) only starts Android. The ROCKNIX ABL adds a menu that can
start Linux from the SD card, and still starts Android. You only do this once; Kettle updates
never touch it.

Get the latest release from [github.com/ROCKNIX/abl](https://github.com/ROCKNIX/abl)
(tested: v1.1.8). Then, in Android:

1. Copy the release's scripts and its `abl_signed-*.elf` to the device.
2. **Back up the stock ABL first:** run `backup_abl.sh`. It writes `abl_a.img` and `abl_b.img`.
   Copy both **off the device** (to a computer or cloud storage): they are the only way back to
   the stock bootloader.
3. Run `flash_abl.sh`. It writes the ROCKNIX ABL to both `abl_a` and `abl_b`.

`restore_backup_abl.sh` puts the stock bootloader back at any time.

## 2. Download and check the image

Download the latest image for your device from [kettlelinux.org](https://kettlelinux.org)
(about 4 GB): `kettle-<build>-odin2portal.img.xz` for the Portal, `kettle-<build>-thor.img.xz`
for the Thor. Each device's image only works on that device. The page shows its SHA-256 checksum. To check the
download, compare it with:

- **Linux / macOS:** `sha256sum kettle-*.img.xz` (macOS: `shasum -a 256 kettle-*.img.xz`)
- **Windows (PowerShell):** `Get-FileHash kettle-*.img.xz`

If they differ, download it again.

## 3. Write it to the microSD card

You don't need to unpack the `.img.xz` first: these tools read it as it is.

- **Any system:** [balenaEtcher](https://etcher.balena.io) or
  [Raspberry Pi Imager](https://www.raspberrypi.com/software/) (*Choose OS*, *Use custom*).
  Pick the image, pick the card, write.
- **Linux, from a terminal:** find the card with `lsblk` (check the size: the command
  overwrites whatever you point it at), then

  ```sh
  xzcat kettle-*.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
  ```

## 4. First start

1. Put the card in the device and start it from the card:
   - **ROCKNIX ABL:** hold **Vol−** while powering on to open its menu, and set
     **Device model:** Odin 2 Portal (or your Thor), **Boot source:** SD, **Boot mode:** Linux.
     On the Thor, Kettle has so far been started through U-Boot; whether the ROCKNIX ABL's
     menu offers a Thor hasn't been checked yet.
   - **U-Boot:** start from the SD card as you would any other card. Kettle's card has the
     `extlinux.conf` and EFI loader U-Boot looks for.
2. The first start takes a little longer than later ones: Kettle sets itself up on the
   rest of the card (the space for games and your files, and a second system slot for updates).
3. Kettle starts in **Game Mode**, Steam's handheld interface. Connect to Wi-Fi and sign in to
   Steam as on a Steam Deck. On the Thor, Steam is on the top screen and the bottom screen has a
   touch shell of its own; *Quick Access*, *Screens* turns it off or on.
4. For the desktop, choose *Switch to Desktop* in Steam's power menu. **Kettle Welcome** opens
   there (it's also in the app menu): use it to set a new password (every copy starts with
   user `kettle`, password `kettle`), to turn on SSH if you want it (it's off), and for controls help and extra apps.
   *Return to Gaming Mode* on the desktop goes back.

## Updates

Kettle updates like SteamOS: in Game Mode, *Settings*, *System*, *Check for updates*. An update
installs into the second system slot while you keep playing and takes effect on the next start.
Your games, settings and files are kept. With U-Boot, if an update fails to start, the device
goes back to the version that worked. The ROCKNIX ABL always starts the newest version, so
there it doesn't go back by itself.

You only need to write a new image to the card to start over from scratch.

## Starting Android

With the ROCKNIX ABL, hold **Vol+** while powering on, or set **Boot mode: Android** in its menu
(**Vol−**). With U-Boot, start Android the way your setup does. Android is exactly as you left
it.

## Writing a new image over an existing Kettle card

Writing an image erases the whole card: your games, files and settings, and any **backups of
the internal storage** the Kettle Installer made (they're kept on the card, in
`/home/.kettle/ufs-backup`). Copy those off first: *Copy a backup to a USB drive* in the Kettle
Installer (builds after 20260927.4), or put the card in a Linux computer and copy the folder from its `home` partition.

## Installing to the internal storage

Once Kettle runs from the card, the Kettle Installer (in Desktop Mode) can also install it to
the internal storage next to Android, so it runs without the card. It backs up the internal
storage first. See [INTERNAL-INSTALL.md](INTERNAL-INSTALL.md) before you do: it erases
Android's apps and data.

## Problems

Check the [issues](https://github.com/kettlelinux/kettlelinux/issues) first, and open a new
one if yours isn't there. Say which build you run (`BUILD_ID` in `cat /etc/os-release`) and attach the output of `sudo dmesg` and
`journalctl -b` from Konsole in Desktop Mode.
