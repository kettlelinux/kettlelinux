#!/usr/bin/env bash
# Install out/kernel onto a running Portal over SSH (no reflash):
#   /flash (boot FAT): Image + dtbs, used by extlinux and systemd-boot
#   /usr/lib/modules/<release>
# The ABL \KERNEL is not rebuilt here; re-run build-image.sh for ABL users.
#
# Usage: scripts/push-kernel.sh steamos@<ip>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:?usage: $0 user@host}"
K="$ROOT/out/kernel"
REL="$(cat "$K/kernelrelease")"

echo "==> pushing $REL to $HOST"
tar -C "$K" -cf - boot/Image boot/dtbs "usr/lib/modules/$REL" | ssh "$HOST" 'cat >/tmp/steamportal-kernel.tar'
ssh -t "$HOST" "sudo bash -euc '
  cd /tmp && rm -rf spk && mkdir spk && tar -C spk -xf steamportal-kernel.tar
  mountpoint -q /flash || mount /flash
  cp /flash/Image /flash/Image.prev
  cp spk/boot/Image /flash/Image.new && mv /flash/Image.new /flash/Image
  cp -r spk/boot/dtbs/. /flash/dtbs/
  # fallback boot entries for the previous kernel (systemd-boot menu / extlinux menu)
  sed -e \"s|^title .*|title      Steam Portal (previous kernel)|\" -e \"s|^linux .*|linux      /Image.prev|\" \\
    /flash/loader/entries/steamportal.conf >/flash/loader/entries/steamportal-prev.conf
  grep -q \"label steamportal-prev\" /flash/extlinux/extlinux.conf || awk \"/^label steamportal\$/{p=1} p\" /flash/extlinux/extlinux.conf \\
    | sed -e \"s/^label steamportal/label steamportal-prev/\" -e \"s|menu label .*|menu label Steam Portal (previous kernel)|\" -e \"s|linux /Image|linux /Image.prev|\" \\
    >>/flash/extlinux/extlinux.conf
  rm -rf /usr/lib/modules/$REL && cp -a spk/usr/lib/modules/$REL /usr/lib/modules/
  chown -R root:root /usr/lib/modules/$REL
  sync; rm -rf spk steamportal-kernel.tar
  echo \"installed $REL (previous Image kept as /flash/Image.prev) - reboot to use it\"
'"
