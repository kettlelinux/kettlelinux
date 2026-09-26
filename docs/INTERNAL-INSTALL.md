# Installing to the internal storage

Kettle Linux starts from the microSD card. Once it works there, the **Kettle Installer**
(application menu → System, desktop mode) copies it to the internal UFS storage next to
Android. Run it from the SD card system with the charger connected.

| Choice | What happens |
|---|---|
| **Dual boot** | Android keeps the size you pick (16 GiB up); Kettle Linux gets the rest |
| **Kettle Linux first** | Android keeps 16 GiB (enough to start and set up); Kettle Linux gets the rest |
| **Reinstall the internal system** | replaces it with a fresh copy of the SD card's system; Android untouched |
| **Remove from internal storage** | deletes Kettle's partitions and grows Android's back, keeping Android's data or resetting it |
| **Back up / Restore** | image the internal storage to the SD card, or write a backup back |

Afterwards the device starts the internal Kettle Linux when no SD card is inserted, and the
card's system when one is (U-Boot tries the SD card first). Android starts as before.

The internal install uses the same partition layout as the SD card image and updates itself the
same way (see [UPDATES.md](UPDATES.md)); there is no need to reinstall it for a new version.
It holds a copy of the card's system image (slot A), `/var` (settings, Wi-Fi, passwords) and
`/home` (Steam and your files; installed games too, unless you skip them). The system takes a
fixed 25 GiB (two 12 GiB slots and small boot and `/var` partitions); `/home` gets the rest.

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
Backups go to `/home/.kettle/ufs-backup/<date>` on the SD card and are **lost if the card
is reflashed**, so copy the folder to a computer too. (Kettle builds from before system updates
kept them in `/var/lib/kettle/ufs-backup`: copy those off the old card before flashing a new
image.) Each one records the SoC serial, and
restoring it on any other device is refused, because calibration data belongs to one unit.

## Safety measures

- Runs only from the SD card system, with nothing on the internal storage mounted.
- Needs the charger, or at least 50% battery. Sleep, the power key and shutdown are blocked
  while it runs, and it runs as a system unit (`kettle-ufs.service`), so closing the window or
  logging out does not stop it.
- Ignores Ctrl-C/SIGTERM while a partition table or a LUN is being written.
- Saves the partition table to `/var/lib/kettle/` and the SD boot partition before any change.
- Slot A's root partition is named `rootfs-A.partial`, and the ESP stays empty, until every
  copy has passed its file system check. An interrupted install therefore never boots; the
  wizard then offers **Finish the installation**.
- The card's system image is copied as is, so its root file system must be read-only
  (`holo-readonly status`), as it is unless you unlocked it.
- The SD image's first-boot partitioning (`systemd-repart`) is switched off on the internal
  install, and the system image itself only runs it from the SD card (so a factory reset,
  which clears `/etc`, can't bring it back): nothing may ever repartition the Android disk.
- Refuses to work on `/dev/sda` unless it is LUN 0 of the internal UFS.
- New partitions go right after the shrunk userdata, one after the other, at explicit positions;
  the rest of the partition table is compared before and after, and put back if anything else
  changed.
- Both ESPs (the SD card's and the internal one) carry `steamcl-restricted`, so each steamcl
  boots only the slots on its own disk. Each slot's GRUB takes its kernel from its own disk too.
- A factory reset (Steam's Settings) formats the internal install's `/var` and `/home` by
  partition UUID, never by kernel device name.
- A Kettle install from before system updates (one `kettle-ufs-root` partition) can't be
  upgraded in place: the wizard offers to remove it, then install again.
- Everything is logged to `/var/log/kettle/`.

## Command line (SSH or Konsole)

The wizard runs these tools; they also work on their own (`--help` for all options):

```sh
sudo kettle-backup-ufs [--essentials]
sudo kettle-install-internal [--android-size GB | --android-minimal] [--backup full|essentials|DIR] [--no-games]
sudo kettle-install-internal --reinstall
sudo kettle-uninstall-internal [--wipe-android]
sudo kettle-restore-ufs [--all-luns] /home/.kettle/ufs-backup/<date>
```

`kettle-restore-ufs` rewrites only LUN 0 (Android and the partition table, all the installer
changes) unless `--all-luns` is given. Only use that if the firmware LUNs themselves were damaged.

## Not yet verified on hardware

- steamcl and GRUB started by U-Boot from the UFS (no SD card inserted), and an update of the
  internal install.

- Stock AYN ABL and the ROCKNIX ABL acting on the recovery `--wipe_data` request in `misc`
  (the fallback is Android's own "Cannot load Android system" prompt).
- Android using the extra space after an uninstall that keeps its data, once it has been
  factory-reset.
- Restoring a full backup after Android has changed its keys (for example after an OTA update).
