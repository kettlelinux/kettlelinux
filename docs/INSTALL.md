# Installing Kettle Linux

Kettle Linux runs from a microSD card in the AYN Odin 2 Portal and the AYN Thor. Android on the
internal storage stays as it is, and you can start either one. Nothing on the device is
replaced: AYN ships both with U-Boot, a second bootloader next to Android's, and Kettle starts
through it. You only tell the device once to start U-Boot instead of Android.

The steps are the same on both devices, with the differences noted. The Thor is newer to Kettle
than the Portal: see its release notes for what has been tested on it.

Kettle is early and in active development. Check the known issues in the release notes on
[kettlelinux.org](https://kettlelinux.org) before you start.

**Retroid Pocket 5:** it starts Kettle with a U-Boot flashed from a computer. Follow
[INSTALL-RP5.md](INSTALL-RP5.md).

## What you need

- An AYN Odin 2 Portal or AYN Thor
- A microSD card of **32 GB or more**. Games are installed to it too, so bigger and faster
  (A2 / U3) is better. Everything on it is erased.
- A computer to write the card from (Windows, macOS or Linux)

## 1. Download and check the image

Download the latest image for your device from [kettlelinux.org](https://kettlelinux.org)
(about 4 GB): `kettle-<build>-odin2portal.img.xz` for the Portal, `kettle-<build>-thor.img.xz`
for the Thor. Each device's image only works on that device. The page shows its SHA-256 checksum. To check the
download, compare it with:

- **Linux / macOS:** `sha256sum kettle-*.img.xz` (macOS: `shasum -a 256 kettle-*.img.xz`)
- **Windows (PowerShell):** `Get-FileHash kettle-*.img.xz`

If they differ, download it again.

## 2. Write it to the microSD card

You don't need to unpack the `.img.xz` first: these tools read it as it is.

- **Any system:** [balenaEtcher](https://etcher.balena.io) or
  [Raspberry Pi Imager](https://www.raspberrypi.com/software/) (*Choose OS*, *Use custom*).
  Pick the image, pick the card, write.
- **Linux, from a terminal:** find the card with `lsblk` (check the size: the command
  overwrites whatever you point it at), then

  ```sh
  xzcat kettle-*.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
  ```

## 3. Start U-Boot instead of Android (once)

1. Turn the device off. Hold **Power + Volume Down** until the fastboot screen appears.
2. With the volume keys, select the option that sets the default boot to **Loader** (instead
   of Android), and press **Power** to choose it.

From then on the device starts U-Boot, which starts Kettle from the SD card. This only changes
which bootloader starts by default: Android, its apps and its data are not touched, and Kettle
updates never change it. To go back, choose Android as the default the same way.

**If you have the ROCKNIX ABL** (installed for ROCKNIX, Batocera, Knulli, ...), skip this step:
Kettle's card works with it as it is. With U-Boot, though, a failed update falls back to the
version that worked (below); ROCKNIX's `restore_backup_abl.sh` puts the stock bootloader back,
and with it the Loader option.

### If U-Boot doesn't start

U-Boot lives in the device's `loader` partition. If that was erased or overwritten, Kettle's
card carries AYN's U-Boot to put back, from a computer:

1. Install Google's **fastboot** on the computer:
   [SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)
   (Windows, macOS, Linux; on Linux also your package manager, e.g. `sudo apt install fastboot`).
2. Put the card you wrote in the computer. Copy **`u-boot-ayn.img`** from the drive called
   **KETTLE** to the computer, next to `fastboot`.
3. Put the card back in the device, start fastboot mode (step 3 above) and connect it to the
   computer by USB. `fastboot devices` should list it.
4. Try it without writing anything: `fastboot boot u-boot-ayn.img`. The device starts U-Boot,
   which starts Kettle.
5. If that worked, go back into fastboot mode and write it for good:

   ```sh
   fastboot flash loader u-boot-ayn.img
   ```

   This writes only the `loader` partition. Then set the default boot to Loader (step 3).

`u-boot-ayn.img` is built from AYN's own source ([AYNTechnologies/u-boot](https://github.com/AYNTechnologies/u-boot)), the same version the devices ship with.

## 4. First start

1. Put the card in the device and turn it on:
   - **U-Boot:** it starts Kettle from the card by itself.
   - **ROCKNIX ABL:** hold **Vol−** while powering on to open its menu, and set
     **Device model:** Odin 2 Portal (or your Thor), **Boot source:** SD, **Boot mode:** Linux.
     On the Thor, Kettle has so far been started through U-Boot; whether the ROCKNIX ABL's
     menu offers a Thor hasn't been checked yet.
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

With U-Boot, set the default boot back to **Android** in fastboot mode (step 3). With the
ROCKNIX ABL, hold **Vol+** while powering on, or set **Boot mode: Android** in its menu
(**Vol−**). Android is exactly as you left it.

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
