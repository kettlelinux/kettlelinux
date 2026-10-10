#!/usr/bin/env bash
# Install out/kernel onto a running device over SSH (no reflash), into the running slot:
#   /boot/Image + dtbs, /usr/lib/modules/<release>, a new initramfs (/boot/initramfs-linux.img)
# The slot's GRUB already boots /boot/Image; \KERNEL and extlinux on the SD card's esp are
# rebuilt too (kettle-boot-legacy). The previous kernel stays as /boot/Image.prev.
#
# The system image is read-only (docs/UPDATES.md): this makes the running slot writable
# (holo-readonly disable), and it stays so until `sudo holo-readonly enable`. The next system
# update installs its own kernel into the other slot; this one is gone once that slot boots.
#
# Usage: scripts/push-kernel.sh kettle@<ip>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:?usage: $0 user@host}"
K="$ROOT/out/kernel"
REL="$(cat "$K/kernelrelease")"

echo "==> pushing $REL to $HOST"
tar -C "$K" -cf - boot/Image boot/dtbs "usr/lib/modules/$REL" | ssh "$HOST" 'cat >/tmp/kettle-kernel.tar'
ssh -t "$HOST" "sudo bash -euc '
  holo-readonly status >/dev/null && holo-readonly disable
  cd /tmp && rm -rf spk && mkdir spk && tar -C spk -xf kettle-kernel.tar
  cp /boot/Image /boot/Image.prev
  # modules and the initramfs first, the Image last: a push that fails part way leaves the
  # slot booting the old kernel, not the new one without its modules
  rm -rf /usr/lib/modules/$REL && cp -a spk/usr/lib/modules/$REL /usr/lib/modules/
  chown -R root:root /usr/lib/modules/$REL
  mkinitcpio -k $REL -g /boot/initramfs-linux.img.new
  cp spk/boot/Image /boot/Image.new
  cp -r spk/boot/dtbs/. /boot/dtbs/
  chown -R root:root /boot
  sync
  mv /boot/initramfs-linux.img.new /boot/initramfs-linux.img && mv /boot/Image.new /boot/Image
  kettle-boot-legacy \$(holo-bootconf this-image)
  sync; rm -rf spk kettle-kernel.tar
  echo \"installed $REL in slot \$(holo-bootconf this-image) (previous: /boot/Image.prev) - reboot to use it\"
  echo \"the root file system is writable now; sudo holo-readonly enable locks it again\"
'"
