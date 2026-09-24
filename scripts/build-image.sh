#!/usr/bin/env bash
# Build a bootable SD-card test image for the Odin 2 Portal — rootless.
#
# Runs itself inside a user+mount+pid namespace (subuid-mapped fake root) with a
# namespace-local binfmt_misc entry for tools/qemu-aarch64-static, so pacman can
# install into an aarch64 root and run package scriptlets/hooks in a chroot.
#
# Inputs: out/kernel (scripts/build-kernel.sh), out/firmware (scripts/build-firmware.sh)
# Output: out/steamportal-<date>.img  (GPT: p1 FAT "STEAMPORTAL" with \KERNEL for the
#         ROCKNIX ABL, p2 ext4 root)
#
# Env: WIFI_SSID / WIFI_PSK  preconfigure Wi-Fi (NetworkManager) for SSH access;
#      SSH_PUBKEY            public key file to authorize for user steamos
#                            (all of these are also read from ./local.env, gitignored)
#      USER_PASSWORD         password for user "steamos" (default: steamos)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
WORK="$ROOT/build/image"
RFS="$WORK/rootfs"
DEVICE="$ROOT/device/odin2portal"
IMG="$ROOT/out/steamportal-$(date +%Y%m%d).img"

if [ "${STEAMPORTAL_IN_NS:-}" != 1 ]; then
  [ -f "$ROOT/out/kernel/boot/Image" ] || die "no kernel; run scripts/build-kernel.sh"
  [ -d "$ROOT/out/firmware" ] || die "no firmware; run scripts/build-firmware.sh"
  [ -f "$LOCAL_REPO/steamportal.db" ] || die "no local repo; run scripts/build-packages.sh"
fi
enter_ns "$@"

# ---------------------------------------------------------------- inside the namespace
trap 'chroot_umount "$RFS"' EXIT
register_binfmt
PACMAN_CONF="$ROOT/build/pacman.image.conf"
build_pacman_conf "$PACMAN_CONF"

log "preparing rootfs at ${RFS#"$ROOT"/}"
rm -rf "$WORK"
mkdir -p "$RFS" "$PKG_CACHE"
chroot_mount "$RFS"

mapfile -t PKGS < <(sed -e 's/#.*//' -e '/^\s*$/d' "$ROOT/image/packages.txt")
log "installing ${#PKGS[@]} packages (steamportal + deckard mash-20240428.1 + release-0.4 hotfixes)"
pacman_root "$RFS" --logfile "$WORK/pacman.log" -Sy --needed "${PKGS[@]}"
install -m 0644 "$ROOT/image/pacman.conf" "$RFS/etc/pacman.conf"
# The host's pacman 7 records %INSTALLED_DB%, which the image's pacman 6.1 warns about
# on every run: drop the field (key line, value line, blank line) from the local db.
for d in "$RFS"/var/lib/pacman/local/*/desc; do
  sed -i '/^%INSTALLED_DB%$/,/^$/d' "$d"
done

log "installing kernel $(cat "$ROOT/out/kernel/kernelrelease"), modules, firmware"
cp -a --no-preserve=ownership "$ROOT/out/kernel/usr/lib/modules/." "$RFS/usr/lib/modules/"
install -d "$RFS/boot/dtbs/qcom"
install -m 0644 "$ROOT/out/kernel/boot/Image" "$RFS/boot/Image"
install -m 0644 "$ROOT"/out/kernel/boot/dtbs/qcom/*.dtb "$RFS/boot/dtbs/qcom/"
cp -a --no-preserve=ownership "$ROOT/out/firmware/usr/lib/firmware/." "$RFS/usr/lib/firmware/"

log "installing AYN-Odin2 ALSA UCM profile"
ucm="$WORK/ucm"; mkdir -p "$ucm"
git -C "$ucm" init -q
for p in "$DEVICE"/ucm/*.patch; do git -C "$ucm" apply "$p"; done
# alsa-lib looks up conf.d/<driver>/<card longname>.conf. Booted via EFI the longname is
# "ayn-AYNOdin2" (DMI vendor-product); ROCKNIX only aliases "AYN-Odin2" and "ayn-AYNOdin2-".
ln -sf ../../AYN/Odin2/AYN-Odin2.conf "$ucm/ucm2/conf.d/sm8550/ayn-AYNOdin2.conf"
cp -a --no-preserve=ownership "$ucm/ucm2/." "$RFS/usr/share/alsa/ucm2/"

log "applying device overlay"
# --no-preserve=ownership: new files become root-owned; never chown -R package dirs
cp -a --no-preserve=ownership "$DEVICE/overlay/." "$RFS/"
chmod 0750 "$RFS/etc/sudoers.d"; chmod 0440 "$RFS"/etc/sudoers.d/*

# Partition identity: fixed at build time so cmdline and fstab agree.
BOOT_PARTUUID="$(cat /proc/sys/kernel/random/uuid)"
ROOT_PARTUUID="$(cat /proc/sys/kernel/random/uuid)"
ROOT_FSUUID="$(cat /proc/sys/kernel/random/uuid)"
BOOT_VOLID="$(printf '%08X' $((RANDOM << 16 | RANDOM)))"

# noinit_itable: growfs adds ~7 GB of never-zeroed inode tables on a 512 GB card, and
# ext4lazyinit zeroing them in the background saturates slow SD cards for hours.
cat >"$RFS/etc/fstab" <<EOF
# <device>                                    <dir>   <type> <options>                       <dump> <fsck>
PARTUUID=$ROOT_PARTUUID  /       ext4   rw,noatime,noinit_itable,x-systemd.growfs 0 1
PARTUUID=$BOOT_PARTUUID  /flash  vfat   rw,noatime,nofail,umask=0077    0 2
EOF
install -d -m 0700 "$RFS/flash"

log "configuring system (in aarch64 chroot)"
USER_PASSWORD="${USER_PASSWORD:-steamos}"
chroot "$RFS" /bin/bash -euo pipefail -s <<EOF
sed -i 's/^#\(en_US.UTF-8 UTF-8\)/\1/' /etc/locale.gen
locale-gen >/dev/null
echo LANG=en_US.UTF-8 >/etc/locale.conf
ln -sf /usr/share/zoneinfo/UTC /etc/localtime
useradd -m -G wheel,video,input,audio,render -s /bin/bash steamos
echo 'steamos:$USER_PASSWORD' | chpasswd
passwd -l root >/dev/null
systemctl enable NetworkManager sshd bluetooth systemd-timesyncd sddm >/dev/null 2>&1
systemctl set-default graphical.target >/dev/null 2>&1
# SteamOS services: session switching (system + user daemon). scx_lavd (SteamOS's scheduler)
# stays installed but off: on the SM8550's 3+4+1 big.LITTLE layout the kernel's energy-aware
# scheduler measured better -- Skyrim 9.0 W at 34.9 fps vs lavd 9.6-9.9 W at 33.6-34.3 fps,
# idle 1.71 W vs 1.80 W (lavd holds the little cluster at max clock and sends ~5x the IPIs).
systemctl enable steamos-manager steamportal-mangoapp-tracefs >/dev/null 2>&1
systemctl --global enable steamos-manager.service steamportal-steam-bootstrap.service >/dev/null 2>&1
systemctl mask systemd-firstboot.service >/dev/null 2>&1
: >/etc/machine-id
EOF

if [ -n "${SSH_PUBKEY:-}" ] && [ -f "$SSH_PUBKEY" ]; then
  log "authorizing SSH key ${SSH_PUBKEY##*/} for steamos"
  install -d -m 0700 -o 1000 -g 1000 "$RFS/home/steamos/.ssh"
  install -m 0600 -o 1000 -g 1000 "$SSH_PUBKEY" "$RFS/home/steamos/.ssh/authorized_keys"
fi

if [ -n "${WIFI_SSID:-}" ]; then
  log "preconfiguring Wi-Fi '$WIFI_SSID'"
  f="$RFS/etc/NetworkManager/system-connections/$WIFI_SSID.nmconnection"
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

chroot_umount "$RFS"; trap - EXIT
rm -rf "$RFS"/var/cache/pacman/pkg/* "$RFS"/tmp/* "$RFS"/var/log/pacman.log

# ---------------------------------------------------------------- boot partition
# One FAT partition serving every loader the Portal may be running:
#   ROCKNIX ABL      \KERNEL + \KERNEL.md5 (boot.img v0: gzip(Image) + all SM8550 dtbs)
#   U-Boot extlinux  \extlinux\extlinux.conf -> \Image + Portal dtb
#   UEFI (U-Boot EFI or ABL EFI chainload)  \EFI\BOOT\BOOTAA64.EFI = systemd-boot
DTB=dtbs/qcom/qcs8550-ayn-odin2portal.dtb
CMDLINE="root=PARTUUID=$ROOT_PARTUUID rootfstype=ext4 rootwait rw console=tty0 \
allow_mismatched_32bit_el0 fw_devlink.strict=1 pcie_ports=compat irqaffinity=0-2 \
nosoftlockup usbcore.interrupt_interval_override=045e:028e:2 \
ufshcd_core.uic_cmd_timeout=3000 mem_sleep_default=s2idle"
B="$WORK/boot"; F="$B/fat"
mkdir -p "$F/dtbs/qcom" "$F/extlinux" "$F/EFI/BOOT" "$F/loader/entries"

log "boot: \\KERNEL for the ROCKNIX ABL"
gzip -9n -c "$ROOT/out/kernel/boot/Image" >"$B/kernel.gz"
cat "$ROOT"/out/kernel/boot/dtbs/qcom/*.dtb >>"$B/kernel.gz"   # ABL picks by its Device model setting
printf '' | cpio -o -H newc --quiet >"$B/ramdisk"
python3 "$ROOT/scripts/mkbootimg.py" --kernel "$B/kernel.gz" --ramdisk "$B/ramdisk" \
  --cmdline "$CMDLINE" --os_patch_level "$(date +%Y-%m)" -o "$F/KERNEL"
printf '%s  KERNEL\n' "$(md5sum "$F/KERNEL" | cut -d' ' -f1)" >"$F/KERNEL.md5"

log "boot: Image + dtbs, extlinux.conf (U-Boot), systemd-boot (UEFI)"
cp "$ROOT/out/kernel/boot/Image" "$F/Image"
cp "$ROOT"/out/kernel/boot/dtbs/qcom/*.dtb "$F/dtbs/qcom/"
cat >"$F/extlinux/extlinux.conf" <<EOF
default steamportal
timeout 3
menu title Steam Portal

label steamportal
    menu label Steam Portal ($(cat "$ROOT/out/kernel/kernelrelease"))
    linux /Image
    fdt /$DTB
    append $CMDLINE
EOF
cp "$RFS/usr/lib/systemd/boot/efi/systemd-bootaa64.efi" "$F/EFI/BOOT/BOOTAA64.EFI"
printf 'default steamportal.conf\ntimeout 3\nconsole-mode keep\n' >"$F/loader/loader.conf"
cat >"$F/loader/entries/steamportal.conf" <<EOF
title      Steam Portal
version    $(cat "$ROOT/out/kernel/kernelrelease")
linux      /Image
devicetree /$DTB
options    $CMDLINE
EOF

# ---------------------------------------------------------------- filesystems + disk
BOOT_MB=256
used_mb=$(du -sm "$RFS" | cut -f1)
ROOT_MB=$(( (used_mb * 5 / 4 + 768 + 63) / 64 * 64 ))
log "root filesystem: ${used_mb} MiB used -> ${ROOT_MB} MiB ext4 (grows to fill the card on first boot)"

rm -f "$B/boot.fat" "$WORK/root.ext4"
mkfs.vfat -F 32 -n STEAMPORTAL -i "$BOOT_VOLID" -C "$B/boot.fat" $((BOOT_MB * 1024)) >/dev/null
mcopy -s -i "$B/boot.fat" "$F"/* ::/
mke2fs -q -t ext4 -L steamportal-root -U "$ROOT_FSUUID" -d "$RFS" "$WORK/root.ext4" "${ROOT_MB}M"

mkdir -p "$ROOT/out"; rm -f "$IMG"
truncate -s $(( (1 + BOOT_MB + ROOT_MB + 1) * 1024 * 1024 )) "$IMG"
sfdisk -q "$IMG" <<EOF
label: gpt
first-lba: 2048
start=1MiB, size=${BOOT_MB}MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, uuid=$BOOT_PARTUUID, name=STEAMPORTAL, attrs="LegacyBIOSBootable"
start=$((1 + BOOT_MB))MiB, size=${ROOT_MB}MiB, type=B921B045-1DF0-41C3-AF44-4C6F280D3FAE, uuid=$ROOT_PARTUUID, name=steamportal-root
EOF
dd if="$B/boot.fat" of="$IMG" bs=1M seek=1 conv=notrunc,sparse status=none
dd if="$WORK/root.ext4" of="$IMG" bs=1M seek=$((1 + BOOT_MB)) conv=notrunc,sparse status=none
chown "$(stat -c %u:%g "$ROOT")" "$IMG" 2>/dev/null || true
rm -f "$WORK/root.ext4" "$B/boot.fat"

log "done: ${IMG#"$ROOT"/} ($(du -h --apparent-size "$IMG" | cut -f1))"
