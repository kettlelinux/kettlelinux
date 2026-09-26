# System updates

Kettle Linux updates the way SteamOS does: the whole system image is replaced at once, into
the half of the disk that isn't running, and the device switches over on the next boot. If the
new image fails to boot, it goes back to the previous one. Nothing is upgraded package by package
on the device, and the root filesystem is read-only.

Almost all of this is Valve's own SteamOS code, built for arm64:

| Part | What it does | Source |
|---|---|---|
| `steamcl.efi`, `holo-bootconf` | stage-1 bootloader: picks slot A or B, counts boot attempts, falls back | `packages/steamos-efi` (Valve's `steamos-efi`, GPL-2.0+) |
| initramfs hook, per-slot GRUB, RAUC hooks, `/etc` overlay, `holo-readonly` | the SteamOS partition scheme | `packages/steamos-customizations-kettle` (Valve's `steamos-customizations`, LGPL-2.1+) |
| `rauc` | installs a signed update bundle into the other slot | Valve's repos |
| `steamos-atomupd-client`, `atomupd-daemon` | checks the update server; Steam's *Check for updates* button talks to this | Valve's repos (the client is built for Python 3.12; Kettle's customizations package makes it visible to the image's Python 3.11, on which it runs unchanged) |

Valve's Steam Frame build of these (the `deckard` packages) uses the Qualcomm bootloader's own
A/B slots and a proprietary initramfs. The Portal boots through U-Boot's EFI, like a Steam Deck
boots through its firmware, so Kettle builds the **Steam Deck** variant for arm64.

## Disk layout

The same partitions, names and roles as SteamOS (the SD card image and an internal-storage
install next to Android alike):

| # | Label | Type | Size | Holds |
|---|---|---|---|---|
| 1 | `esp` | FAT | 256 MiB (internal: 512) | `\EFI\BOOT\BOOTAA64.EFI` = steamcl, `\SteamOS\conf\{A,B}.conf` (boot state); also the older boot paths (below) |
| 2 | `efi-A` | FAT | 64 MiB | slot A's GRUB (`\EFI\steamos\grubaa64.efi` + `grub.cfg`) and `\SteamOS\partsets` |
| 3 | `efi-B` | FAT | 64 MiB | the same for slot B |
| 4 | `rootfs-A` | btrfs, read-only | 12 GiB | the system, including the kernel (`/boot/Image`, dtbs, initramfs) |
| 5 | `rootfs-B` | btrfs, read-only | 12 GiB | the other system image |
| 6 | `var-A` | ext4 | 256 MiB | slot A's `/var`, with the `/etc` overlay (`/var/lib/overlays/etc/upper`) |
| 7 | `var-B` | ext4 | 256 MiB | slot B's |
| 8 | `home` | ext4 | the rest | `/home`, grown to fill the disk on first boot; large `/var` directories are bind-mounted from `/home/.steamos/offload` |

SteamOS also has `verity-A`/`verity-B` for dm-verity; Kettle leaves them out for now.

The SD card image carries partitions 1-4, 6 and 7 only, so it is one slot's size (about 13 GiB);
on first boot `systemd-repart` creates `rootfs-B` and `home` in the rest of the card, from
definitions in the image's `/etc` overlay (with the partition UUIDs the slot configuration
already names). An internal install is partitioned in full by the Kettle Installer, and
`systemd-repart` is switched off there (it must never touch the Android disk; the image also
runs it only when the root filesystem is on the SD card).

System images are built as small as they compress (btrfs, zstd); on a slot's first boot
`kettle-readonly-root` grows the filesystem to its partition and sets the read-only flag.

## Boot

```
U-Boot EFI ─► esp:\EFI\BOOT\BOOTAA64.EFI (steamcl)
                 picks the newest good slot from esp:\SteamOS\conf, adds a boot attempt
             ─► efi-X:\EFI\steamos\grubaa64.efi ─► rootfs-X:/boot/Image + dtb + initramfs
                 steamos.efi=PARTUUID=<efi-X> tells the initramfs which slot it is
initramfs (holo hook): /dev/disk/by-partsets/{self,other,A,B,shared}/…, mounts var-X,
                       overlays /etc
graphical.target reached: holo-boot.service marks the slot as booted (attempts back to 0)
```

steamcl only looks at slots on its own disk (`\EFI\BOOT\steamcl-restricted`, and the same
next to `\EFI\steamos\steamcl.efi`): an SD card and an internal install both have slots A and
B. Each slot's GRUB takes its root filesystem from the disk it was loaded from too (partition
number and UUID, checked with `probe`), because both installations get the same system image,
filesystem UUID included, once they are updated to the same build; only if that fails does it
search every disk by filesystem UUID.

A boot is unfinished until `holo-boot.service` runs. After 3 unfinished boots of a slot, steamcl
shows its boot menu for 30 s and then tries the same slot again; after 6 it selects the other
slot and boots it when the menu times out (2 minutes). This is Valve's behaviour, unchanged.

**Older boot paths.** The ROCKNIX ABL (`\KERNEL`) and U-Boot's extlinux (`\extlinux\extlinux.conf`)
can't choose between slots. Kettle keeps them on the `esp` and rewrites them to the newly
installed slot at the end of each update (`kettle-boot-legacy`), so they get every update but
have no automatic fallback. For fallback, boot through EFI (U-Boot EFI, or the ABL's EFI
chainload). U-Boot usually tries extlinux before EFI: if the Portal's U-Boot does, the SD card
system boots without fallback until extlinux is dropped from the image (an internal install
has no extlinux and always boots through steamcl).

## Updating

1. `atomupd-daemon` (on Steam's request, or `steamos-update`) asks the server what the newest
   build is for this device's variant and branch.
2. `steamos-atomupd-client` has RAUC install that build's bundle into the other slot. RAUC
   checks the bundle's signature against `/etc/rauc/trusted_keys`, and downloads only the
   chunks that differ from the running image (desync, seeded from the running slot).
3. The RAUC post-install hook syncs `/var` into the other slot, runs the new image's
   `holo-finalize-install` in a chroot (steamcl onto the `esp` with `--no-efi --flags restricted`,
   since U-Boot's EFI variables can't be written; GRUB onto `efi-X`), marks the slot for its
   first boot, and (Kettle) rewrites the older boot paths.
4. On reboot steamcl starts the new slot. If it never reaches the desktop or Game Mode, the
   old slot boots again.

The update server is static files (see `scripts/publish-update.sh`):

```
<meta>/kettle/<variant>/<arch>/<branch>/…   builds.json per branch (what atomupd reads)
<images>/…/kettle-<buildid>-<variant>.raucb  the bundle
<images>/…/kettle-<buildid>-<variant>.castr  desync chunk store
```

`KETTLE_UPDATE_URL` (in `local.env`) is baked into the image at build time; without it the
image has no update server and updates come as new images.

## Signing

Bundles are signed with a Kettle key; the image trusts its certificate
(`/etc/rauc/trusted_keys`). `KETTLE_RAUC_KEY` and `KETTLE_RAUC_CERT` (in `local.env`) point at
the release key. Without them the build makes a development key in `cache/keys/` and images
built with it trust only development bundles. Keep the release key off the build tree.

## Working on a device

- `sudo holo-readonly disable` makes the running root writable (for debugging; the next update
  replaces it anyway). `status`, `enable` as expected.
- `sudo holo-bootconf list-images`, `holo-bootconf this-image`: slots and boot state.
- `sudo steamos-select-branch beta` then `steamos-update`: follow another branch.
- `sudo rauc install file.raucb`: install a bundle from a file (no server needed). Its chunk
  store, `file.castr/`, must be in the same directory.
- Steam's factory reset (Settings > System) formats this installation's `var-A`, `var-B` and
  `home` on the next boot, found by partition UUID. The system image is not touched.
