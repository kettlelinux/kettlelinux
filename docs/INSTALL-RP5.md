# Installing Kettle Linux on the Retroid Pocket 5

Kettle Linux runs from a microSD card in the Retroid Pocket 5. Android on the internal storage
stays as it is, and you can start either one. The RP5 needs no bootloader unlock and no root:
its own bootloader can start a second system from a partition Retroid set aside for it, the
`loader` partition. You put Kettle's U-Boot there once, from a computer, and U-Boot then starts
Kettle from the card.

Getting the RP5 into fastboot mode for that one step is the part that trips people up. The
instructions below use the way that works.

Kettle on the RP5 is new. Check the known issues in the release notes on
[kettlelinux.org](https://kettlelinux.org) before you start.

> **At your own risk.** Kettle Linux is provided as is, without warranty. Installing it changes how
> your device starts up and can erase data, affect your warranty, or leave a device that doesn't
> start until it's restored. Back up anything you want to keep first. See the
> [disclaimer](https://kettlelinux.org/legal.html#disclaimer).

## What you need

- A Retroid Pocket 5
- A microSD card of **32 GB or more**. Games are installed to it too, so bigger and faster
  (A2 / U3) is better. Everything on it is erased.
- A computer (Windows, macOS or Linux) and a USB-C cable that carries data, not only power
- Google's **fastboot** tool on the computer:
  - **Windows / macOS:** [SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)
    (unzip it, then run `fastboot` from that folder)
  - **Linux:** your distribution's `android-tools` package (Arch: `sudo pacman -S android-tools`,
    Debian/Ubuntu: `sudo apt install fastboot`)

## 1. Download and check the image

Download the latest image for the RP5 from [kettlelinux.org](https://kettlelinux.org):
`kettle-<build>-rp5.img.xz`. Images for other devices don't work on the RP5. The page shows
its SHA-256 checksum. To check the download, compare it with:

- **Linux / macOS:** `sha256sum kettle-*-rp5.img.xz` (macOS: `shasum -a 256 kettle-*-rp5.img.xz`)
- **Windows (PowerShell):** `Get-FileHash kettle-*-rp5.img.xz`

If they differ, download it again.

## 2. Write it to the microSD card

You don't need to unpack the `.img.xz` first: these tools read it as it is.

- **Any system:** [balenaEtcher](https://etcher.balena.io) or
  [Raspberry Pi Imager](https://www.raspberrypi.com/software/) (*Choose OS*, *Use custom*).
  Pick the image, pick the card, write.
- **Linux, from a terminal:** find the card with `lsblk` (check the size: the command
  overwrites whatever you point it at), then

  ```sh
  xzcat kettle-*-rp5.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
  ```

When it's done, take the card out and put it back in the computer. A small drive named
**KETTLE** appears. Copy the file **`u-boot-rp5.img`** from it to your computer, next to
`fastboot`. That is the U-Boot you put on the RP5 in step 4. Then eject the card and put it in
the RP5.

## 3. Get the RP5 into fastboot mode

1. **Turn the RP5 off completely.** Hold Power and choose *Power off*. A short press only puts
   it to sleep.
2. **Unplug the USB cable** from the RP5.
3. **Hold Volume Down, and while holding it, plug the USB cable into the RP5** (the other end
   in the computer). Keep holding Volume Down until a text screen saying *Fastboot* appears,
   then let go.

Holding **Power + Volume Down** is the usual way into fastboot on Android devices, but on the
RP5 it often doesn't work. Holding the buttons too long can also leave the RP5 with a black
screen, showing up on the computer as a Qualcomm *QUSB_BULK* device. That is a crash-dump mode,
not fastboot, and nothing is broken: hold **Power** for about 20 seconds until it turns off,
then start again from 1.

Another way, from Android: turn on *USB debugging* (*Settings*, *About*, tap *Build number*
seven times, then *Developer options*), connect the cable, accept the prompt on the RP5, and run
`adb reboot bootloader` (`adb` comes with fastboot).

Check that the computer sees it:

```sh
fastboot devices
```

It should list one device followed by `fastboot`. If it lists nothing: try another USB port
or cable.

**On Windows**, if it still lists nothing, Windows needs Google's USB driver (Windows Update
sometimes installs one by itself):

1. Download the [Google USB Driver](https://developer.android.com/studio/run/win-usb) and
   extract the zip.
2. With the RP5 in fastboot mode and plugged in, open **Device Manager**. Right-click the device
   (usually **Android** under *Other devices*, with a yellow mark) and choose **Update driver**.
3. Choose **Browse my computer for drivers**, then **Let me pick from a list of available
   drivers on my computer** (don't enter a folder on that screen: Windows may not match the
   driver to the RP5 by itself).
4. In the list of device types, select **Show All Devices** and click **Next**. Click
   **Have Disk**, then **Browse**, and select `android_winusb.inf` from the extracted folder.
5. Pick **Android Bootloader Interface** and accept the warning. `fastboot devices` should now
   list the RP5.

You don't need a Qualcomm driver (QDLoader / 9008): that is for EDL mode, which these steps
don't use. A *QUSB_BULK* device means the RP5 is in crash-dump mode, not fastboot (above).

## 4. Put Kettle's U-Boot in the loader partition (once)

Optional, but a good idea: try it once without changing anything on the RP5.

```sh
fastboot boot u-boot-rp5.img
```

The RP5 starts U-Boot, which starts Kettle from the card. If that works, go back into fastboot
mode (step 3) and make it permanent:

```sh
fastboot flash loader u-boot-rp5.img
```

This writes only the `loader` partition. Android, its apps and its data are not touched, and
Kettle updates never change the loader partition again.

## 5. Choose what starts by default

The RP5's bootloader still starts Android by default. You have two ways to start Kettle:

- **Each time:** from off, hold **Power + Volume Up**. That starts the loader, so Kettle.
- **By default:** in fastboot mode (step 3), use the volume keys to select the option that
  makes **Loader** the default and press Power to choose it. From then on the RP5 starts Kettle
  when you turn it on. To go back to Android by default, do the same and choose Android.

## 6. First start

1. The first start takes a little longer than later ones: Kettle sets itself up on the rest of
   the card (the space for games and your files, and a second system slot for updates).
2. Kettle starts in **Game Mode**, Steam's handheld interface. Connect to Wi-Fi and sign in to
   Steam as on a Steam Deck.
3. For the desktop, choose *Switch to Desktop* in Steam's power menu. **Kettle Welcome** opens
   there: use it to set a new password (every copy starts with user `kettle`, password
   `kettle`), to turn on SSH if you want it (it's off), and for controls help and extra apps.
   *Return to Gaming Mode* on the desktop goes back.

### Black screen? Your RP5 may have the newer panel

RP5s from 2026 batches (often the 12 GB model) have a different screen, a Visionox panel, and
nothing can tell the two apart before Linux starts. Kettle starts with the original panel's
settings, so on a newer RP5 the screen stays black, although Kettle runs (you may hear Steam
start).

To fix it: turn the RP5 off, put the card in the computer, and create an empty file named
**`visionox`** (or `visionox.txt`) on the **KETTLE** drive, next to `u-boot-rp5.img`. Put the
card back and start Kettle again. Kettle keeps using the Visionox settings as long as that file
is there, updates included.

## Updates

Kettle updates like SteamOS: in Game Mode, *Settings*, *System*, *Check for updates*. An update
installs into the second system slot while you keep playing and takes effect on the next start.
Your games, settings and files are kept. If an update fails to start, the RP5 goes back to the
version that worked.

You only need to write a new image to the card to start over from scratch. You don't need to
flash U-Boot again.

## Installing to the internal storage

Once Kettle runs from the card, the **Kettle Installer** (in Desktop Mode, application menu,
*System*) can also install it to the internal storage next to Android, so it runs without the
card. Read [INTERNAL-INSTALL.md](INTERNAL-INSTALL.md) first: it erases Android's apps and data
(Android itself stays and sets itself up again), and it offers a backup first: *full* (Android's
data too, so it can be brought back) or *essentials* (smaller; Android's data can't be brought
back).

Run it with the charger connected and let it finish: the backup and the copy take a while, and
the installer says when it's done.

Afterwards, with Kettle's U-Boot from step 4:

- **No card in the RP5:** the internal Kettle starts.
- **Card in the RP5:** the card's Kettle starts, as before. That is how you reinstall, remove
  or restore the internal install: start from the card and use the Kettle Installer.

## If you use the ROCKNIX bootloader instead

If you already replaced the RP5's bootloader with ROCKNIX's (for ROCKNIX, Batocera, Knulli and
others), the card starts as it is: in its menu (hold **Volume Down** while powering on), set
**Device model** to your RP5 (the Visionox model on a newer RP5), **Boot source** to SD and
**Boot mode** to Linux. You can skip steps 3 to 5. It starts Kettle the same way U-Boot does
(through steamcl), so a failed update falls back to the version that worked here too.

## Starting Android

Android is exactly as you left it. With Loader as the default, set Android as the default again
in fastboot mode (step 5) whenever you want it. Otherwise, turning the RP5 on without holding
anything starts Android.

## Problems

Check the [issues](https://github.com/kettlelinux/kettlelinux/issues) first, and open a new
one if yours isn't there. Say which build you run (`BUILD_ID` in `cat /etc/os-release`), which
panel your RP5 has if you know, and attach the output of `sudo dmesg` and `journalctl -b` from
Konsole in Desktop Mode.
