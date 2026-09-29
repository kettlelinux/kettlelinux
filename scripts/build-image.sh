#!/usr/bin/env bash
# Build a Kettle Linux release for one device — rootless: the SD card image and the signed
# update bundle made from the same system image. See docs/UPDATES.md for the layout.
#
# Runs itself inside a user+mount+pid namespace (subuid-mapped fake root) with a
# namespace-local binfmt_misc entry for tools/qemu-aarch64-static, so pacman can
# install into an aarch64 root and run package scriptlets/hooks in a chroot.
#
# Inputs: out/kernel (scripts/build-kernel.sh), our local repo (scripts/build-packages.sh)
# Output: out/kettle-<buildid>-<device>.img     SD card image (SteamOS partition layout, slot A)
#         out/kettle-<buildid>-<device>.raucb   update bundle (RAUC, casync), with its chunk
#         out/kettle-<buildid>-<device>.castr/  store; publish with scripts/publish-update.sh
#
# Env (also read from ./local.env, gitignored):
#   KETTLE_DEVICE          the device to build for, a directory under device/ (default:
#                          odin2portal); docs/PORTING.md has what a device directory holds
#   WIFI_SSID / WIFI_PSK   preconfigure Wi-Fi (NetworkManager) for SSH access
#   SSH_PUBKEY             public key file to authorize for user kettle
#   USER_PASSWORD          password for user "kettle" (default: kettle); part of the system
#                          image, so of its update bundle too
#   KETTLE_UPDATE_URL      update server (…/meta, …/images); without it the image has none
#   KETTLE_BRANCH          update branch the image follows (default: beta)
#   KETTLE_BUILD_ID        YYYYMMDD.N (default: today's date .1)
#   KETTLE_RAUC_KEY/_CERT  release signing key and certificate (default: a development key in
#                          cache/keys/, made on first use)
#   KETTLE_NO_BUNDLE=1     skip the update bundle (faster; the image only)
#   KETTLE_RELEASE=1       an image to hand out: WIFI_*, SSH_PUBKEY and USER_PASSWORD are ignored
#                          (even from local.env), the SSH server is off by default (every copy
#                          has the same password), and the image is also written compressed,
#                          out/<name>.img.xz, with out/<name>.sha256
# Wi-Fi and the SSH key go into this image's /var (its /etc overlay), never into the system
# image or the bundle.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
WORK="$ROOT/build/image"
RFS="$WORK/rootfs"
STAGE="$WORK/stage"
# The device: device/common/overlay plus its own overlay, packages and settings (device.conf)
VARIANT="${KETTLE_DEVICE:-odin2portal}"
DEVICE="$ROOT/device/$VARIANT"
[ "$VARIANT" != common ] && [ -f "$DEVICE/device.conf" ] || die "no device '$VARIANT' (device/*/device.conf)"
. "$DEVICE/device.conf"
for v in MODEL DTB RAUC_COMPATIBLE PAD_NAME FACE_BUTTONS; do
  [ -n "${!v:-}" ] || die "device/$VARIANT/device.conf: $v not set (docs/PORTING.md)"
done
[[ "$FACE_BUTTONS" =~ ^(xbox|nintendo)$ ]] || die "device/$VARIANT/device.conf: FACE_BUTTONS is xbox or nintendo"
# no Portal defaults for another device's screen: each device says how Game Mode drives it
[ -f "$DEVICE/overlay/usr/lib/kettle/gamescope.conf" ] ||
  die "device/$VARIANT has no overlay/usr/lib/kettle/gamescope.conf (docs/PORTING.md)"
VERSION="$(sed -e 's/#.*//' -e '/^\s*$/d' "$ROOT/image/version")"
BUILD_ID="${KETTLE_BUILD_ID:-$(date +%Y%m%d).1}"
BRANCH="${KETTLE_BRANCH:-beta}"
NAME="kettle-$BUILD_ID-$VARIANT"
IMG="$ROOT/out/$NAME.img"

if [ "${KETTLE_IN_NS:-}" != 1 ]; then
  [ -f "$ROOT/out/kernel/boot/Image" ] || die "no kernel; run scripts/build-kernel.sh"
  [ -f "$LOCAL_REPO/kettle.db" ] || die "no local repo; run scripts/build-packages.sh"
  [[ "$BUILD_ID" =~ ^[0-9]{8}(\.[0-9]+)?$ ]] || die "KETTLE_BUILD_ID must be YYYYMMDD.N"
fi
be_nice
enter_ns "$@"

# ---------------------------------------------------------------- inside the namespace
RELEASE=${KETTLE_RELEASE:-0}
SSHD=sshd
if [ "$RELEASE" = 1 ]; then
  unset WIFI_SSID WIFI_PSK SSH_PUBKEY USER_PASSWORD
  SSHD=
fi
# the signing key: the release key if given, else a development key kept in cache/keys
if [ -n "${KETTLE_RAUC_KEY:-}" ] || [ -n "${KETTLE_RAUC_CERT:-}" ]; then
  KEY="${KETTLE_RAUC_KEY:?KETTLE_RAUC_CERT set without KETTLE_RAUC_KEY}"
  CERT="${KETTLE_RAUC_CERT:?KETTLE_RAUC_KEY set without KETTLE_RAUC_CERT}"
else
  KEY="$ROOT/cache/keys/dev.key" CERT="$ROOT/cache/keys/dev.crt"
  if [ ! -f "$KEY" ]; then
    log "making a development signing key (cache/keys/); images built with it trust only it"
    install -d -m 0700 "$ROOT/cache/keys"
    openssl req -x509 -newkey rsa:4096 -nodes -days 3650 -keyout "$KEY" -out "$CERT" \
      -subj "/O=Kettle Linux/CN=Kettle Linux development updates" 2>/dev/null
  fi
fi
[ -f "$KEY" ] && [ -f "$CERT" ] || die "signing key or certificate missing: $KEY $CERT"

trap 'umount "$RFS/mnt/stage" 2>/dev/null || true; chroot_umount "$RFS"' EXIT
register_binfmt
PACMAN_CONF="$ROOT/build/pacman.image.conf"
build_pacman_conf "$PACMAN_CONF"

log "preparing rootfs at ${RFS#"$ROOT"/} (Kettle Linux $VERSION, build $BUILD_ID, $BRANCH)"
rm -rf "$WORK"
mkdir -p "$RFS" "$STAGE" "$PKG_CACHE"
chroot_mount "$RFS"

mapfile -t PKGS < <(sed -e 's/#.*//' -e '/^\s*$/d' "$ROOT/image/packages.txt" "$DEVICE/packages.txt")
log "installing ${#PKGS[@]} packages for the $MODEL (kettle + deckard mash-20240428.1 + release-0.4 hotfixes)"
pacman_root "$RFS" --logfile "$WORK/pacman.log" -Sy --needed "${PKGS[@]}"
install -m 0644 "$ROOT/image/pacman.conf" "$RFS/etc/pacman.conf"
# The host's pacman 7 records %INSTALLED_DB%, which the image's pacman 6.1 warns about
# on every run: drop the field (key line, value line, blank line) from the local db.
for d in "$RFS"/var/lib/pacman/local/*/desc; do
  sed -i '/^%INSTALLED_DB%$/,/^$/d' "$d"
done

KVER="$(cat "$ROOT/out/kernel/kernelrelease")"
log "installing kernel $KVER and modules"
cp -a --no-preserve=ownership "$ROOT/out/kernel/usr/lib/modules/." "$RFS/usr/lib/modules/"
install -d "$RFS/boot/dtbs/qcom"
install -m 0644 "$ROOT/out/kernel/boot/Image" "$RFS/boot/Image"
install -m 0644 "$ROOT"/out/kernel/boot/dtbs/qcom/*.dtb "$RFS/boot/dtbs/qcom/"

log "applying overlays: common, $VARIANT"
# --no-preserve=ownership: new files become root-owned; never chown -R package dirs
cp -a --no-preserve=ownership "$ROOT/device/common/overlay/." "$RFS/"
cp -a --no-preserve=ownership "$DEVICE/overlay/." "$RFS/"
chmod 0750 "$RFS/etc/sudoers.d"; chmod 0440 "$RFS"/etc/sudoers.d/*
# the device's settings, for scripts on the device (kettle_device.py, or sourced from shell)
{ echo "# device/$VARIANT/device.conf, installed by scripts/build-image.sh"
  echo "DEVICE=$VARIANT"
  cat "$DEVICE/device.conf"; } >"$RFS/usr/lib/kettle/device.conf"
chmod 0644 "$RFS/usr/lib/kettle/device.conf"
# this device's devicetree for GRUB and extlinux
sed -i "s|^DTB=@DTB@\$|DTB=$DTB|" "$RFS/usr/lib/kettle/boot.conf"
grep -qx "DTB=$DTB" "$RFS/usr/lib/kettle/boot.conf" || die "boot.conf: DTB not set"
[ -f "$RFS/boot/dtbs/$DTB" ] || die "no $DTB in out/kernel"
# this device's update compatible (RAUC) and update variant (steamos-atomupd, which also offers
# the variants in client.conf); steamos-customizations-kettle ships the Portal's
sed -i "s|^compatible=.*|compatible=$RAUC_COMPATIBLE|" "$RFS/etc/rauc/system.conf"
sed -i "s|^Variants = .*|Variants = $VARIANT|" "$RFS/usr/lib/steamos-atomupd/client.conf"
grep -qx "compatible=$RAUC_COMPATIBLE" "$RFS/etc/rauc/system.conf" || die "rauc system.conf: compatible not set"
grep -qx "Variants = $VARIANT" "$RFS/usr/lib/steamos-atomupd/client.conf" || die "atomupd client.conf: variant not set"

# What the update client and the About pages read (steamos-atomupd: ID, VERSION_CODENAME,
# VARIANT_ID, VERSION_ID, BUILD_ID). ID stays steamos, as the Steam client knows it.
cat >"$RFS/usr/lib/os-release" <<EOF
NAME="Kettle Linux"
PRETTY_NAME="Kettle Linux $VERSION"
ID=steamos
ID_LIKE=arch
VERSION_ID=$VERSION
VERSION_CODENAME=kettle
BUILD_ID=$BUILD_ID
VARIANT="$MODEL"
VARIANT_ID=$VARIANT
STEAMOS_DEFAULT_UPDATE_BRANCH=$BRANCH
ANSI_COLOR="38;2;205;127;50"
LOGO=kettle
EOF

# The root filesystem, /var and the /etc overlay are mounted by the initramfs, /home and the
# boot partitions by units (steamos-customizations-kettle): nothing for fstab.
cat >"$RFS/etc/fstab" <<'EOF'
# Kettle Linux mounts its partitions by slot (SteamOS layout, see /dev/disk/by-partsets):
# /, /var and the /etc overlay in the initramfs; /home, /efi and /esp by systemd units.
EOF

if [ -n "${KETTLE_UPDATE_URL:-}" ]; then
  log "update server: $KETTLE_UPDATE_URL"
  rm -f "$RFS/etc/steamos-atomupd/client.conf"
  sed -e "s|^ImagesUrl = .*|ImagesUrl = ${KETTLE_UPDATE_URL%/}/images|" \
      -e "s|^MetaUrl = .*|MetaUrl = ${KETTLE_UPDATE_URL%/}/meta|" \
      "$RFS/usr/lib/steamos-atomupd/client.conf" >"$RFS/etc/steamos-atomupd/client.conf"
else
  warn_no_server=1
fi
# RAUC trusts this certificate (hashed name, as openssl looks certificates up)
install -D -m 0644 "$CERT" "$RFS/etc/rauc/trusted_keys/$(openssl x509 -hash -noout -in "$CERT").0"

log "configuring system (in aarch64 chroot)"
USER_PASSWORD="${USER_PASSWORD:-kettle}"
chroot "$RFS" /bin/bash -euo pipefail -s <<EOF
sed -i 's/^#\(en_US.UTF-8 UTF-8\)/\1/' /etc/locale.gen
locale-gen >/dev/null
echo LANG=en_US.UTF-8 >/etc/locale.conf
ln -sf /usr/share/zoneinfo/UTC /etc/localtime
# the home directory is made on first boot (holo-create-homedir), on the home partition
useradd -M -G wheel,video,input,audio,render -s /bin/bash kettle
# subordinate ids for rootless podman (Lepton's Android containers); usermod needs the files
touch /etc/subuid /etc/subgid
usermod --add-subuids 100000-165535 --add-subgids 100000-165535 kettle
echo 'kettle:$USER_PASSWORD' | chpasswd
passwd -l root >/dev/null
systemctl enable NetworkManager $SSHD bluetooth systemd-timesyncd sddm >/dev/null 2>&1
systemctl set-default graphical.target >/dev/null 2>&1
# SteamOS services: session switching (system + user daemon). scx_lavd (SteamOS's scheduler)
# stays installed but off: on the SM8550's 3+4+1 big.LITTLE layout the kernel's energy-aware
# scheduler measured better -- Skyrim 9.0 W at 34.9 fps vs lavd 9.6-9.9 W at 33.6-34.3 fps,
# idle 1.71 W vs 1.80 W (lavd holds the little cluster at max clock and sends ~5x the IPIs).
systemctl enable steamos-manager kettle-mangoapp-tracefs kettle-steam-unpack >/dev/null 2>&1
# kettle-powerd: CPU/GPU caps, power budget, fan and charge limit, behind Steam's own power
# controls (steamos-manager remotes.d) and the Power plugin
systemctl enable kettle-powerd >/dev/null 2>&1
# Decky Loader (Game Mode plugins); its unit name is fixed by the loader itself
systemctl enable plugin_loader >/dev/null 2>&1
systemctl --global enable steamos-manager.service kettle-steam-bootstrap.service \
  kettle-desktop-controller.service kettle-qam-button.service >/dev/null 2>&1
systemctl mask systemd-firstboot.service >/dev/null 2>&1
: >/etc/machine-id
mkinitcpio -k $KVER -g /boot/initramfs-linux.img
steamos-atomupd-mkmanifest >/etc/steamos-atomupd/manifest.json
EOF
[ -s "$RFS/boot/initramfs-linux.img" ] || die "no initramfs"
# the update server's record of this build (scripts/publish-update.sh)
mkdir -p "$ROOT/out"
cp "$RFS/etc/steamos-atomupd/manifest.json" "$ROOT/out/$NAME.manifest.json"

# ---------------------------------------------------------------- partitions
# Slot A and a small /home are built now. On first boot systemd-repart grows home to fill the
# card and creates rootfs-B after it (their definitions go into this image's /etc overlay), so
# the image stays one slot's size. Every partition UUID is fixed here: the slot partition sets,
# the bootloaders and repart agree.
uuid() { cat /proc/sys/kernel/random/uuid; }
ESP_PARTUUID=$(uuid) EFIA_PARTUUID=$(uuid) EFIB_PARTUUID=$(uuid)
ROOTA_PARTUUID=$(uuid) ROOTB_PARTUUID=$(uuid)
VARA_PARTUUID=$(uuid) VARB_PARTUUID=$(uuid) HOME_PARTUUID=$(uuid)
ROOT_FSUUID=$(uuid) VARA_FSUUID=$(uuid) VARB_FSUUID=$(uuid) HOME_FSUUID=$(uuid)
volid() { printf '%08X' $((RANDOM << 16 | RANDOM)); }
ESP_MB=512 EFI_MB=64 ROOTFS_MB=12288 VAR_MB=256

log "boot: steamcl, slot A's GRUB, \\KERNEL and extlinux"
mkdir -p "$STAGE"/{esp,efi-A,var-A} "$RFS/mnt/stage"
mount --bind "$STAGE" "$RFS/mnt/stage"
chroot "$RFS" /bin/bash -euo pipefail -s <<EOF
HOLO_ROOT_UUID=$ROOT_FSUUID HOLO_VAR_UUID=$VARA_FSUUID \
  /usr/lib/holo/holo-grub-mkimage --format=arm64-efi --output=/mnt/stage/efi-A/EFI/steamos/grubaa64.efi
EFI=/mnt/stage/efi-A HOLO_ROOT_UUID=$ROOT_FSUUID HOLO_ROOT_PARTUUID=$ROOTA_PARTUUID HOLO_ROOT_PARTNUM=4 \
  HOLO_EFI_PARTUUID=$EFIA_PARTUUID update-grub >/dev/null
mkdir -p /mnt/stage/esp/SteamOS/conf
holo-bootconf --conf-dir /mnt/stage/esp/SteamOS/conf create --image A >/dev/null
holo-bootconf --conf-dir /mnt/stage/esp/SteamOS/conf config --image A \
  --set title "Kettle Linux-A-$VERSION-$BUILD_ID" --set comment "$BUILD_ID" >/dev/null
kettle-boot-legacy --root / --esp /mnt/stage/esp --efi-partuuid $EFIA_PARTUUID
EOF
umount "$RFS/mnt/stage"; rmdir "$RFS/mnt/stage"

# /home comes in the image, with kettle's home directory as holo-create-homedir makes it and the
# Steam client (2.5 GB in 14,000 files) already unpacked: written while the card is flashed
# instead of on the device's first boot, which on an SD card took minutes. The first boot only
# grows it to fill the card. After a factory reset (/home formatted), holo-create-homedir and
# kettle-steam-unpack.service make both again.
log "home: kettle's home directory, with the Steam client unpacked"
install -d "$STAGE/home"
mount --bind "$STAGE/home" "$RFS/home"
trap 'umount "$RFS/home" 2>/dev/null || true; chroot_umount "$RFS"' EXIT
chroot "$RFS" /bin/bash -euo pipefail -s <<'EOF'
/usr/lib/holo/holo-create-homedir 1000 >/dev/null
s=/home/kettle/.local/share/Steam
install -d "$s"
tar -xf /usr/lib/steam/steam.tar.zst -C "$s" --no-same-owner
touch "$s/.kettle-unpacked"   # what run-steam and kettle-steam-unpack.service look for
chown -R 1000:1000 /home/kettle
EOF
umount "$RFS/home"
trap 'chroot_umount "$RFS"' EXIT

# steamcl on the esp, where steamcl-install puts it (and at the firmware's fallback path).
# steamcl-restricted keeps it to the slots on its own disk: without it, steamcl on the SD card
# would also pick up an internal install's slots (they are named A and B too), and the other
# way round. Updates keep the flag (STEAMCL_INSTALL_ARGS in steamos-customizations-kettle).
cl="$RFS/usr/lib/holo-efi/aarch64-efi/steamcl.efi"
for d in "$STAGE/esp/EFI/steamos" "$STAGE/esp/EFI/BOOT"; do
  install -D -m 0644 "$RFS/usr/share/holo-efi/default.pf2" "$d/fonts/default.pf2"
  : >"$d/steamcl-restricted"
done
install -m 0644 "$cl" "$STAGE/esp/EFI/steamos/steamcl.efi"
install -m 0644 "$cl" "$STAGE/esp/EFI/BOOT/BOOTAA64.EFI"
install -m 0644 "$RFS/usr/share/holo-efi/steamcl-version" "$STAGE/esp/EFI/steamos/"

# Both slots' partition sets (what holo-partsets would write: <link name> <partuuid>), on each
# slot's efi partition. steamcl knows a slot by the file named after it (A or B) whose efi entry
# is that partition, so efi-B needs its set before the first update writes it (Valve's
# post-install only fills in all, shared, self and other).
mkdir -p "$STAGE/efi-B"
for slot in A B; do
  ps="$STAGE/efi-$slot/SteamOS/partsets"; mkdir -p "$ps"
  printf 'esp %s\nhome %s\n' "$ESP_PARTUUID" "$HOME_PARTUUID" >"$ps/shared"
  printf 'efi %s\nrootfs %s\nvar %s\n' "$EFIA_PARTUUID" "$ROOTA_PARTUUID" "$VARA_PARTUUID" >"$ps/A"
  printf 'efi %s\nrootfs %s\nvar %s\n' "$EFIB_PARTUUID" "$ROOTB_PARTUUID" "$VARB_PARTUUID" >"$ps/B"
  printf '%s %s\n' esp "$ESP_PARTUUID" efi-A "$EFIA_PARTUUID" efi-B "$EFIB_PARTUUID" \
    rootfs-A "$ROOTA_PARTUUID" rootfs-B "$ROOTB_PARTUUID" var-A "$VARA_PARTUUID" \
    var-B "$VARB_PARTUUID" home "$HOME_PARTUUID" >"$ps/all"
done
cp "$STAGE/efi-A/SteamOS/partsets/A" "$STAGE/efi-A/SteamOS/partsets/self"
cp "$STAGE/efi-A/SteamOS/partsets/B" "$STAGE/efi-A/SteamOS/partsets/other"
cp "$STAGE/efi-B/SteamOS/partsets/B" "$STAGE/efi-B/SteamOS/partsets/self"
cp "$STAGE/efi-B/SteamOS/partsets/A" "$STAGE/efi-B/SteamOS/partsets/other"

chroot_umount "$RFS"; trap - EXIT
rm -rf "$RFS"/var/cache/pacman/pkg/* "$RFS"/tmp/* "$RFS"/var/log/pacman.log "$RFS/home/kettle"
# the package database belongs to the (read-only) system image, as on SteamOS 3.5+
install -d "$RFS/usr/lib/holo"
mv "$RFS/var/lib/pacman" "$RFS/usr/lib/holo/pacmandb"
install -d "$RFS/var/lib/pacman"
sed -i 's|^\[options\]$|[options]\nDBPath = /usr/lib/holo/pacmandb/|' "$RFS/etc/pacman.conf"

# ---------------------------------------------------------------- slot A's /var
log "var-A: /var, with this image's own settings in the /etc overlay"
cp -a "$RFS/var/." "$STAGE/var-A/"
up="$STAGE/var-A/lib/overlays/etc/upper"
install -d "$up/repart.d" "$STAGE/var-A/lib/overlays/etc/work"
cat >"$up/repart.d/40-rootfs-A.conf" <<EOF
# This image's slot A (listed so the rootfs-B definition doesn't match it)
[Partition]
Type=root-arm64
Label=rootfs-A
SizeMinBytes=${ROOTFS_MB}M
SizeMaxBytes=${ROOTFS_MB}M
EOF
cat >"$up/repart.d/41-rootfs-B.conf" <<EOF
# Slot B, created empty on first boot; its first update fills it
[Partition]
Type=root-arm64
Label=rootfs-B
UUID=$ROOTB_PARTUUID
SizeMinBytes=${ROOTFS_MB}M
SizeMaxBytes=${ROOTFS_MB}M
EOF
cat >"$up/repart.d/90-home.conf" <<EOF
# /home, grown on first boot to the rest of the card (less rootfs-B, which goes after it);
# home.mount grows the filesystem (systemd-growfs). Format= only applies if it were missing.
[Partition]
Type=home
Label=home
UUID=$HOME_PARTUUID
Format=ext4
EOF
if [ -n "${SSH_PUBKEY:-}" ] && [ -f "$SSH_PUBKEY" ]; then
  log "authorizing SSH key ${SSH_PUBKEY##*/} for kettle"
  install -d -m 0755 "$up/ssh/authorized_keys.d"
  install -m 0644 "$SSH_PUBKEY" "$up/ssh/authorized_keys.d/kettle"
fi
if [ -n "${WIFI_SSID:-}" ]; then
  log "preconfiguring Wi-Fi '$WIFI_SSID'"
  f="$up/NetworkManager/system-connections/$WIFI_SSID.nmconnection"
  install -d -m 0700 "$(dirname "$f")"
  cat >"$f" <<EOF
[connection]
id=$WIFI_SSID
type=wifi
autoconnect=true

[wifi]
mode=infrastructure
ssid=$WIFI_SSID

[wifi-security]
key-mgmt=wpa-psk
psk=${WIFI_PSK:-}

[ipv4]
method=auto

[ipv6]
method=auto
EOF
  chmod 0600 "$f"
fi

# ---------------------------------------------------------------- slot A's system image
# btrfs, zstd-compressed, at its smallest (mkfs.btrfs --rootdir would otherwise size the file
# for the uncompressed contents). On a slot's first boot kettle-readonly-root grows it to the
# slot and sets the read-only flag. The bundle carries the same file.
log "rootfs-A: btrfs system image"
ROOTFS_IMG="$WORK/rootfs.img"
rm -f "$ROOTFS_IMG"
mkfs.btrfs -q --rootdir "$RFS" --compress zstd:3 --shrink -U "$ROOT_FSUUID" -L rootfs \
  -f "$ROOTFS_IMG" >/dev/null
size=$(( ($(stat -c %s "$ROOTFS_IMG") + 1048575) / 1048576 ))
[ "$size" -le "$ROOTFS_MB" ] || die "system image is ${size} MiB, the slots have ${ROOTFS_MB} MiB"
log "  $(du -sm "$RFS" | cut -f1) MiB of files -> ${size} MiB image (slot: ${ROOTFS_MB} MiB)"

# ---------------------------------------------------------------- update bundle
BUNDLE="$ROOT/out/$NAME.raucb"
if [ "${KETTLE_NO_BUNDLE:-}" != 1 ]; then
  log "update bundle: ${BUNDLE#"$ROOT"/} (casync, signed with ${CERT#"$ROOT"/})"
  # made in the build chroot, which has rauc, casync and squashfs-tools
  TOOLS="$ROOT/build/pkgroot"
  [ -d "$TOOLS/usr" ] || die "no build chroot; run scripts/build-packages.sh"
  B="$WORK/bundle"; mkdir -p "$B/content" "$B/keys" "$TOOLS/mnt/bundle"
  ln "$ROOTFS_IMG" "$B/content/rootfs.img" 2>/dev/null || cp "$ROOTFS_IMG" "$B/content/rootfs.img"
  cat >"$B/content/manifest.raucm" <<EOF
[update]
compatible=$RAUC_COMPATIBLE
version=$VERSION
build=$BUILD_ID
description=Kettle Linux $VERSION ($BUILD_ID) for the $MODEL

[bundle]
format=verity

[image.rootfs]
filename=rootfs.img
EOF
  cp "$KEY" "$B/keys/key.pem"; cp "$CERT" "$B/keys/cert.pem"
  trap 'umount "$TOOLS/mnt/bundle" 2>/dev/null || true; rm -rf "$B/keys"; chroot_umount "$TOOLS"' EXIT
  chroot_mount "$TOOLS"
  cp /etc/resolv.conf "$TOOLS/etc/resolv.conf"
  PACMAN_CONF="$ROOT/build/pacman.pkgbuild.conf"
  pacman_root "$TOOLS" -Sy --needed rauc casync squashfs-tools >/dev/null
  mount --bind "$B" "$TOOLS/mnt/bundle"
  chroot "$TOOLS" /bin/bash -euo pipefail -s <<EOF
cd /mnt/bundle
k=(--cert=keys/cert.pem --key=keys/key.pem --keyring=keys/cert.pem)
rauc bundle "\${k[@]}" content plain.raucb >/dev/null
rauc convert "\${k[@]}" plain.raucb $NAME.raucb >/dev/null
rm plain.raucb
rauc extract --keyring=keys/cert.pem $NAME.raucb extracted >/dev/null
EOF
  umount "$TOOLS/mnt/bundle"; chroot_umount "$TOOLS"; trap - EXIT
  rm -rf "$B/keys" "$ROOT/out/$NAME.castr"
  mv "$B/$NAME.raucb" "$BUNDLE"; mv "$B/$NAME.castr" "$ROOT/out/"
  # the running slot's chunk index, seeding the next update's download (post-install.sh
  # copies each update's own into the slot it installs)
  install -D -m 0644 "$B/extracted/rootfs.img.caibx" "$STAGE/var-A/lib/steamos-atomupd/rootfs.caibx"
  rm -rf "$B"
fi

# ---------------------------------------------------------------- disk image
log "disk image"
fat() {  # name, size MiB, label, dir, sectors per cluster (default: mkfs.vfat's choice)
  rm -f "$WORK/$1.fat"
  mkfs.vfat -F 32 ${5:+-s $5} -n "$3" -i "$(volid)" -C "$WORK/$1.fat" $(($2 * 1024)) >/dev/null
  if [ -n "$4" ] && [ -n "$(ls -A "$4")" ]; then mcopy -s -i "$WORK/$1.fat" "$4"/* ::/; fi
}
# The esp as the SD card images that the ROCKNIX ABL boots (ROCKNIX, ArmadaOS) have it: FAT32
# with 4 KiB clusters, which needs 512 MiB. On a 256 MiB esp with mkfs.vfat's 512-byte clusters
# the ABL found no volume on the card ("No bootable image found").
fat esp $ESP_MB KETTLE "$STAGE/esp" 8
fat efi-A $EFI_MB EFI-A "$STAGE/efi-A"
fat efi-B $EFI_MB EFI-B "$STAGE/efi-B"
mke2fs -q -t ext4 -L var -U "$VARA_FSUUID" -d "$STAGE/var-A" "$WORK/var-A.ext4" "${VAR_MB}M"
mke2fs -q -t ext4 -L var -U "$VARB_FSUUID" "$WORK/var-B.ext4" "${VAR_MB}M"
# home: its files and a tenth more, plus 256 MiB (grown to the card on first boot)
HOME_MB=$(( $(du -sm "$STAGE/home" | cut -f1) * 11 / 10 + 256 ))
mke2fs -q -t ext4 -L home -U "$HOME_FSUUID" -E root_owner=0:0 -d "$STAGE/home" \
  "$WORK/home.ext4" "${HOME_MB}M"

mkdir -p "$ROOT/out"; rm -f "$IMG"
off=1
truncate -s $(( (1 + ESP_MB + 2 * EFI_MB + ROOTFS_MB + 2 * VAR_MB + HOME_MB + 1) * 1024 * 1024 )) "$IMG"
# The esp keeps the GPT name KETTLE (older bootloaders look for it; holo-partsets knows the esp
# by its type) and LegacyBIOSBootable (U-Boot's extlinux scan).
ESP=C12A7328-F81F-11D2-BA4B-00A0C93EC93B DATA=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7
ROOTT=B921B045-1DF0-41C3-AF44-4C6F280D3FAE LINUX=0FC63DAF-8483-4772-8E79-3D69D8477DE4
HOMET=933AC7E1-2EB4-4F13-B844-0E14E2AEF915
# first-lba 34 (right after the partition entries), as in ROCKNIX's SD card images
sfdisk -q "$IMG" <<EOF
label: gpt
first-lba: 34
start=${off}MiB, size=${ESP_MB}MiB, type=$ESP, uuid=$ESP_PARTUUID, name=KETTLE, attrs="LegacyBIOSBootable"
size=${EFI_MB}MiB, type=$DATA, uuid=$EFIA_PARTUUID, name=efi-A
size=${EFI_MB}MiB, type=$DATA, uuid=$EFIB_PARTUUID, name=efi-B
size=${ROOTFS_MB}MiB, type=$ROOTT, uuid=$ROOTA_PARTUUID, name=rootfs-A
size=${VAR_MB}MiB, type=$LINUX, uuid=$VARA_PARTUUID, name=var-A
size=${VAR_MB}MiB, type=$LINUX, uuid=$VARB_PARTUUID, name=var-B
size=${HOME_MB}MiB, type=$HOMET, uuid=$HOME_PARTUUID, name=home
EOF
put() { dd if="$1" of="$IMG" bs=1M seek="$2" conv=notrunc,sparse status=none; }
put "$WORK/esp.fat" $off;   off=$((off + ESP_MB))
put "$WORK/efi-A.fat" $off; off=$((off + EFI_MB))
put "$WORK/efi-B.fat" $off; off=$((off + EFI_MB))
[ "$(stat -c %s "$ROOTFS_IMG")" -le $((ROOTFS_MB * 1048576)) ] || die "system image larger than its slot"
put "$ROOTFS_IMG" $off;     off=$((off + ROOTFS_MB))
put "$WORK/var-A.ext4" $off; off=$((off + VAR_MB))
put "$WORK/var-B.ext4" $off; off=$((off + VAR_MB))
put "$WORK/home.ext4" $off
chown "$(stat -c %u:%g "$ROOT")" "$IMG" "$ROOT"/out/"$NAME".* 2>/dev/null || true
rm -f "$WORK"/*.fat "$WORK"/*.ext4

if [ "$RELEASE" = 1 ]; then
  # nothing of the build machine's may be in an image that is handed out
  up="$STAGE/var-A/lib/overlays/etc/upper"
  [ -z "$(ls -A "$up/NetworkManager/system-connections" 2>/dev/null)" ] ||
    die "release image has Wi-Fi connections in it"
  [ ! -e "$up/ssh/authorized_keys.d" ] || die "release image has SSH keys in it"
  [ ! -e "$RFS/etc/systemd/system/multi-user.target.wants/sshd.service" ] ||
    die "release image starts the SSH server"
  log "compressing ${IMG#"$ROOT"/}.xz"
  rm -f "$IMG.xz"
  xz -T"$JOBS" -6 -k "$IMG"
  ( cd "$ROOT/out" && sha256sum "$NAME.img.xz" "$NAME.img" >"$NAME.sha256" )
  chown "$(stat -c %u:%g "$ROOT")" "$IMG.xz" "$ROOT/out/$NAME.sha256" 2>/dev/null || true
fi

log "done: ${IMG#"$ROOT"/} ($(du -h --apparent-size "$IMG" | cut -f1))"
[ "$RELEASE" != 1 ] || log "      ${IMG#"$ROOT"/}.xz ($(du -h "$IMG.xz" | cut -f1)), $NAME.sha256"
[ "${KETTLE_NO_BUNDLE:-}" = 1 ] || log "      ${BUNDLE#"$ROOT"/} + ${NAME}.castr/ (publish: scripts/publish-update.sh)"
[ -z "${warn_no_server:-}" ] || log "      no KETTLE_UPDATE_URL: this image has no update server"
