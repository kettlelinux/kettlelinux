#!/bin/bash
# Kettle Linux: format a microSD card for Steam, run by steamos-manager's FormatDevice (Steam's
# Settings > Storage > Format): one ext4 partition owned by the user, then mounted and added to
# Steam by sd-automount, as SteamOS does.
#   format-device.sh --label <label> [--skip-validation] --device <disk>
# Validation (a check for fake-capacity cards) needs f3probe, which Kettle does not ship: it is
# skipped either way. steamos-manager reads only the exit status.
set -euo pipefail
FORMATTING=/run/kettle/sd-formatting
label= device=
while [ $# -gt 0 ]; do
  case $1 in
    --label) label=$2; shift 2 ;;
    --device) device=$2; shift 2 ;;
    --skip-validation) shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case $device in /dev/mmcblk[0-9]|/dev/mmcblk[0-9][0-9]) ;; *) echo "not a microSD card: '$device'" >&2; exit 2 ;; esac
[ -b "$device" ] || { echo "$device: no card inserted" >&2; exit 1; }
root=$(findmnt -no SOURCE /)
if [ "/dev/$(lsblk -no PKNAME "$root" 2>/dev/null)" = "$device" ]; then
  echo "$device: Kettle runs from this card" >&2; exit 1
fi

mkdir -p "${FORMATTING%/*}"
touch "$FORMATTING"
trap 'rm -f "$FORMATTING"' EXIT
for unit in $(systemctl list-units --plain --no-legend "kettle-sd-automount@${device#/dev/}p*" | cut -d' ' -f1); do
  systemctl stop "$unit"
done
# Anything else still mounted from the card (a terminal mount, say) is in use: leave it be
if findmnt -rno SOURCE | grep -q "^${device}p"; then
  echo "$device: a partition is still mounted" >&2; exit 1
fi

echo "formatting $device as '$label'"
wipefs -aq "$device"p* 2>/dev/null || true
wipefs -aq "$device"
parted -s -a optimal "$device" mklabel gpt mkpart steam ext4 0% 100%
udevadm settle
part=${device}p1
wipefs -aq "$part"
# As SteamOS: no reserved blocks, casefolding available, the root directory owned by the user
mkfs.ext4 -q -F -m 0 -O casefold -E nodiscard,root_owner=1000:1000 -L "${label:0:16}" "$part"
sync
rm -f "$FORMATTING"
udevadm settle
systemctl restart "kettle-sd-automount@${part#/dev/}.service"
echo "formatted $device"
