# Installing to the internal storage

Kettle Linux starts from the microSD card. Once it works there, the **Kettle Installer**
(application menu → System, desktop mode) copies it to the internal UFS storage next to
Android. Run it from the SD card system with the charger connected.

| Choice | What happens |
|---|---|
| **Dual boot** | Android keeps the size you pick (16 GiB up); Kettle Linux gets the rest |
| **Kettle Linux first** | Android keeps 16 GiB (enough to start and set up); Kettle Linux gets the rest |
| **Update the internal install** | copies the SD card's system over the internal one again; Android untouched |
| **Remove from internal storage** | deletes Kettle's partitions and grows Android's back, keeping Android's data or resetting it |
| **Back up / Restore** | image the internal storage to the SD card, or write a backup back |

Afterwards the device starts the internal Kettle Linux when no SD card is inserted, and the
card's system when one is (U-Boot tries the SD card first). Android starts as before.

## What is erased

Android's `userdata` (its apps and data) is metadata-encrypted with keys held in the TEE, so
it cannot be shrunk while keeping its contents. **Installing erases Android's apps and data on
the internal storage**; Android itself stays and runs its setup again on its next start
(Android's recovery is asked to reset it through the `misc` partition; if Android instead shows
"Cannot load Android system", choose *Factory data reset*). Save what you need from inside
Android first (Google backup, or copy files to the SD card or a computer).

No other Android partition is changed. After partitioning, the installer compares the whole
partition table with the saved one, and if anything other than `userdata` moved it writes the
old table back and stops.

## Backups

The installer does not continue without a backup that matches the internal storage as it is
now (same partition tables, same device). It makes one first, or reuses one already on the card:

| Kind | Holds | Size |
|---|---|---|
| **full** | every UFS LUN, including Android's apps and data (still encrypted; only restorable on this device) | about the data on the device |
| **essentials** | everything except Android's `userdata`: partition tables, bootloaders, firmware, device-unique calibration (`persist`, modem), Android itself | a few GiB |

The wizard samples the storage to estimate each size and only offers what fits on the card.
Backups go to `/var/lib/kettle/ufs-backup/<date>` on the SD card and are **lost if the card
is reflashed**, so copy the folder to a computer too. Each one records the SoC serial, and
restoring it on any other device is refused, because calibration data belongs to one unit.

## Safety measures

- Runs only from the SD card system, with nothing on the internal storage mounted.
- Needs the charger, or at least 50% battery. Sleep, the power key and shutdown are blocked
  while it runs, and it runs as a system unit (`kettle-ufs.service`), so closing the window or
  logging out does not stop it.
- Ignores Ctrl-C/SIGTERM while a partition table or a LUN is being written.
- Saves the partition table to `/var/lib/kettle/` and the SD boot partition before any change.
- The new root partition is labelled `kettle-ufs-root.partial`, and the ESP stays empty,
  until the copy passes `e2fsck` and the boot files compare equal. An interrupted install
  therefore never boots; the wizard then offers **Finish the installation**.
- Everything is logged to `/var/log/kettle/`.

## Command line (SSH or Konsole)

The wizard runs these tools; they also work on their own (`--help` for all options):

```sh
sudo kettle-backup-ufs [--essentials]
sudo kettle-install-internal [--android-size GB | --android-minimal] [--backup full|essentials|DIR] [--no-games]
sudo kettle-install-internal --reinstall
sudo kettle-uninstall-internal [--wipe-android]
sudo kettle-restore-ufs [--all-luns] /var/lib/kettle/ufs-backup/<date>
```

`kettle-restore-ufs` rewrites only LUN 0 (Android and the partition table, all the installer
changes) unless `--all-luns` is given. Only use that if the firmware LUNs themselves were damaged.

## Not yet verified on hardware

- Stock AYN ABL and the ROCKNIX ABL acting on the recovery `--wipe_data` request in `misc`
  (the fallback is Android's own "Cannot load Android system" prompt).
- Android using the extra space after an uninstall that keeps its data, once it has been
  factory-reset.
- Restoring a full backup after Android has changed its keys (for example after an OTA update).
