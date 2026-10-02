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
| 1 | `esp` | FAT | 512 MiB | `\EFI\BOOT\BOOTAA64.EFI` = steamcl, `\SteamOS\conf\{A,B}.conf` (boot state); also the older boot paths (below) |
| 2 | `efi-A` | FAT | 64 MiB | slot A's GRUB (`\EFI\steamos\grubaa64.efi` + `grub.cfg`) and `\SteamOS\partsets` |
| 3 | `efi-B` | FAT | 64 MiB | the same for slot B |
| 4 | `rootfs-A` | btrfs, read-only | 12 GiB | the system, including the kernel (`/boot/Image`, dtbs, initramfs) |
| 5 | `rootfs-B` | btrfs, read-only | 12 GiB | the other system image |
| 6 | `var-A` | ext4 | 256 MiB | slot A's `/var`, with the `/etc` overlay (`/var/lib/overlays/etc/upper`) |
| 7 | `var-B` | ext4 | 256 MiB | slot B's |
| 8 | `home` | ext4 | the rest | `/home`, grown to fill the disk on first boot; large `/var` directories are bind-mounted from `/home/.steamos/offload` |

SteamOS also has `verity-A`/`verity-B` for dm-verity; Kettle leaves them out for now.

The SD card image carries one slot and a small `home` (about 16 GiB in all), with the Steam
client already unpacked in `/home/kettle`, so flashing the card does that writing rather than
the device's first boot. On first boot `systemd-repart` grows `home` to the rest of the card and
creates `rootfs-B` after it, from definitions in the image's `/etc` overlay (with the partition
UUIDs the slot configuration already names), and `systemd-growfs` grows the filesystem. On the
card the partition numbers therefore differ from the table (`var-A` 5, `var-B` 6, `home` 7,
`rootfs-B` 8); partitions are found by UUID, and each slot's GRUB reads its number when it is
written.

An internal install is partitioned in full by the Kettle Installer, and
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
have no automatic fallback. For fallback, boot through EFI (U-Boot EFI, or the ROCKNIX ABL's
EFI chainload up to v1.1.8; v1.1.9 dropped it and only starts `\KERNEL`). U-Boot usually tries
extlinux before EFI: if the Portal's U-Boot does, the SD card system boots without fallback
until extlinux is dropped from the image. An internal install has `\KERNEL` (for the ROCKNIX
ABL; `kettle-install-internal --boot-files` adds it to older installs) but no extlinux, so
U-Boot always boots it through steamcl; `kettle-boot-legacy` refreshes each of the two only
where it is already on the `esp`.

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

`KETTLE_UPDATE_URL` (in `local.env`) is baked into the image at build time; without it the
image has no update server and updates come as new images. Kettle's is
`https://updates.kettlelinux.org`. It can't change for images already out there, so it is the
project's own domain, whichever host is behind it.

## Update server

The update server is static files (made by `scripts/publish-update.sh`):

```
meta/kettle/<variant>/<arch>/<branch>/…      builds.json per branch (what atomupd reads)
images/…/kettle-<buildid>-<variant>.raucb    the bundle (signed; about 2 MB)
images/…/kettle-<buildid>-<variant>.castr/   desync chunk store (about 3 GB, 50,000 chunks)
store/                                       the chunks of every release, once
```

A device installs a bundle with `rauc install <url>.raucb`, and RAUC fetches its chunks from
`<url>.castr/`. Consecutive releases share almost all of them (about 94% between two builds a
day apart), so a device downloads only a few hundred MB per update. The server keeps each chunk
once, in `store/`, and answers `images/…/<name>.castr/<chunk>` from `store/<chunk>`: a URL
rewrite on the server, so devices, bundles and offline `rauc install file.raucb` (with
`file.castr/` beside it) are unchanged. (RAUC's `[casync] storepath` would do this on the device
instead, but it replaces the bundle's own store everywhere, offline installs included.)

The server doesn't have to be trusted: a bundle installs only if it is signed with the Kettle
key (below). A compromised server could only withhold updates.

**Hosting: Cloudflare R2** behind `updates.kettlelinux.org`. R2 doesn't charge for downloads,
which is what an update server mostly does (updates, and the 4 GB images for new installs);
storage is about $0.015/GB a month. One-time setup:

1. Add `kettlelinux.org` to Cloudflare (free plan) and point the domain's nameservers at
   Cloudflare's in Namecheap. `kettlelinux.com` too, redirected to `.org`.
2. R2: create a bucket (e.g. `kettle-updates`); under its settings, *Custom Domains*, connect
   `updates.kettlelinux.org`. Leave the public `r2.dev` URL off.
3. The chunk rewrite: *Rules > Transform Rules > Rewrite URL*, for the zone:
   - when (expression editor): `http.request.uri.path wildcard "/images/*.castr/*"`
   - path, dynamic: `wildcard_replace(http.request.uri.path, "/images/*.castr/*", "/store/${2}")`
4. R2 API token (*Manage R2 API Tokens*, Object Read & Write, this bucket only), then
   `rclone config`: an `s3` remote named `r2`, provider `Cloudflare`, the token's key ID and
   secret, endpoint `https://<account id>.r2.cloudflarestorage.com`, `no_check_bucket = true`.
5. In `local.env`: `KETTLE_UPDATE_URL=https://updates.kettlelinux.org` and
   `KETTLE_UPDATE_REMOTE=r2:kettle-updates`.

Check the rewrite once something is uploaded: a chunk path from a published release's
`.castr/` should answer 200 under both `/images/…` and `/store/…`:

```
curl -sI https://updates.kettlelinux.org/images/<variant>/<version>/<name>.castr/0000/<chunk>.cacnk
```

**Releasing:** `scripts/publish-update.sh out/kettle-<buildid>-<variant>.raucb [branch]`, then
`scripts/upload-update.sh`. The upload sends only new chunks, bundles before `meta/`, so no
device is pointed at a release that isn't all there. Chunks and bundles are cached for good
(`immutable`); `meta/` for a minute.

**How many are kept**, per device:
| What | Kept | Setting |
|---|---|---|
| Builds in `out/` (image, bundle, chunk store) | the newest 3; older ones are deleted after each build | `KETTLE_KEEP_BUILDS` (build-image.sh) |
| Releases on the update server | the newest 3 on each branch; older ones leave the tree when a release is published, with the chunks only they used, and leave the server on the next upload (after `meta/` stops naming them) | `KETTLE_KEEP_RELEASES` (publish-update.sh) |
| SD card images for download | the newest 3 | `KETTLE_KEEP_IMAGES` (upload-image.sh) |

`0` keeps everything. A device that missed releases still updates: it gets the newest one, and
only that release's chunks.

**SD card images** for new installs are in the same bucket, under `downloads/`, and the website
(kettlelinux.org, `site/`) lists them from `downloads/releases.json`. Build with
`KETTLE_RELEASE=1 scripts/build-image.sh`, then
`scripts/upload-image.sh out/kettle-<buildid>-<variant>.img.xz`. It uploads the image and its
`.sha256`, adds it to the index with its release notes (`releases/<variant>/<buildid>.md`) and
keeps each device's newest three (`KETTLE_KEEP_IMAGES`), deleting older ones. The website shows
each device's newest image, with its notes. The website reads the index from another origin, so the bucket needs a CORS policy
once (R2 bucket *Settings > CORS Policy*):

```json
[{ "AllowedOrigins": ["https://kettlelinux.org", "http://localhost:8000"],
   "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600 }]
```

and, so a cached copy without CORS headers is never served, a *Cache Rule* bypassing the cache
for `http.request.uri.path eq "/downloads/releases.json"` (it's 2 KB and cached a minute anyway).

Another host works the same way: any static file server with the same rewrite (nginx:
`rewrite ^/images/.+?\.castr/(.*)$ /store/$1 last;`), or with the tree copied as is, `.castr/`
directories included.

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
