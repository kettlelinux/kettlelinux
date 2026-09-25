# Shared by kettle-backup-ufs, kettle-restore-ufs, kettle-install-internal and
# kettle-uninstall-internal (sourced, not run).
#
# Every tool takes --progress, used by the kettle-installer wizard: normal output then goes only
# to the log, and stdout carries one line per event:
#   @step <text>     a new step started      @pct <0-100>   progress within the step
#   @error <text>    the tool failed         @done <text>   the tool finished
# Without it output is for a terminal. Either way everything is logged under /var/log/kettle.

DISK=/dev/sda                      # UFS LUN 0: Android, and Kettle once installed
BACKUPS=/var/lib/kettle/ufs-backup # on the SD card system
ESP_LABEL=kettle-esp
ROOT_LABEL=kettle-ufs-root         # SD image root is "kettle-root"
PARTIAL_LABEL=kettle-ufs-root.partial   # root while an install is being written
ESP_TYPE=C12A7328-F81F-11D2-BA4B-00A0C93EC93B
ROOT_TYPE=B921B045-1DF0-41C3-AF44-4C6F280D3FAE   # root-arm64
MIN_BATTERY=50                     # % needed to start without the charger
PROGRESS=0 YES=0

say() { if [ "$PROGRESS" = 1 ]; then echo "@step $*" >&3; fi; printf '\033[1;34m==>\033[0m %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
pct() { if [ "$PROGRESS" = 1 ]; then echo "@pct $1" >&3; fi; }
die() { if [ "$PROGRESS" = 1 ]; then echo "@error $*" >&3; fi; echo "error: $*" >&2; exit 1; }
done_msg() { if [ "$PROGRESS" = 1 ]; then echo "@done $*" >&3; fi; say "$*"; }
ask() { [ "$YES" = 1 ] && return 0; [ "$PROGRESS" = 0 ] || return 1; local a; read -rp "$1 [y/N]: " a; [[ $a =~ ^[Yy]$ ]]; }

# Start logging; in --progress mode also move normal output off stdout (fd 3 keeps it).
start_log() {
  mkdir -p /var/log/kettle
  LOG=/var/log/kettle/$1-$(date +%Y%m%d-%H%M%S).log
  exec 3>&1
  if [ "$PROGRESS" = 1 ]; then
    [ "$YES" = 1 ] || die "--progress needs --yes (it cannot ask questions)"
    # Events go through a relay that outlives its reader: if the wizard's window is closed,
    # a write must not kill the tool (or its dd) half way through a partition table or LUN
    exec 3> >(trap '' PIPE; while IFS= read -r l; do printf '%s\n' "$l" 2>/dev/null; done)
    exec >>"$LOG" 2>&1
  else
    exec > >(tee -a "$LOG") 2>&1
  fi
  echo "# $0 $* ($(date -Is))" >>"$LOG"
}

need_root() { [ "$(id -u)" = 0 ] || die "run as root (sudo $0)"; }
need_sd_root() {
  case "$(findmnt -no SOURCE /)" in
    /dev/mmcblk*) ;;
    *) die "run this from the SD card system (the running root is $(findmnt -no SOURCE /))" ;;
  esac
}

# Re-run the calling tool under systemd-inhibit, so sleep, the power key and shutdown requests
# cannot interrupt it. Usage: inhibit "why" "$@"
inhibit() {
  [ -n "${KETTLE_INHIBITED:-}" ] && return 0
  local why=$1; shift
  export KETTLE_INHIBITED=1
  exec systemd-inhibit --mode=block --who="$(basename "$0")" --why="$why" \
    --what=sleep:shutdown:idle:handle-power-key:handle-suspend-key:handle-lid-switch "$0" "$@"
}

# Power loss while a partition table or firmware is being written can leave the device
# unbootable. power_ok: charger connected or battery >= MIN_BATTERY; sets BATTERY (%, or empty)
power_ok() {
  local s ac=0
  BATTERY=""
  for s in /sys/class/power_supply/*; do
    case "$(cat "$s/type" 2>/dev/null)" in
      Battery) BATTERY=$(cat "$s/capacity" 2>/dev/null || true) ;;
      *) [ "$(cat "$s/online" 2>/dev/null)" = 1 ] && ac=1 ;;
    esac
  done
  [ "$ac" = 1 ] || [ -z "$BATTERY" ] || [ "$BATTERY" -ge "$MIN_BATTERY" ]
}
need_power() {
  power_ok || die "battery at ${BATTERY}%: connect the charger (or charge above ${MIN_BATTERY}%) first"
}

# UFS LUNs, as "<lun> <dev>" (LUN number = SCSI device 0:0:0:<lun> under the UFS host)
ufs_luns() {
  local d
  for d in /sys/block/sd*; do
    readlink -f "$d" | grep -q 'ufshc' || continue
    [ "$(cat "$d/size")" -gt 0 ] || continue
    echo "$(basename "$(readlink -f "$d/device")" | awk -F: '{print $4}') /dev/${d##*/}"
  done | sort -n
}
lun_dev() { ufs_luns | awk -v l="$1" '$1 == l { print $2 }'; }
none_mounted() { ! findmnt -rno SOURCE | grep -q "^$1"; }

# Per-chip serial: backups hold device-unique calibration and keys, so they must never be
# written to another unit
device_serial() { cat /sys/devices/soc0/serial_number 2>/dev/null || echo unknown; }

part_by_label() { blkid -c /dev/null -t PARTLABEL="$1" -o device 2>/dev/null | grep "^$DISK" | head -1 || true; }
partnum() { cat "/sys/class/block/$(basename "$1")/partition"; }
part_start_b() { echo $(( $(cat "/sys/class/block/$(basename "$1")/start") * 512 )); }
part_size_b() { echo $(( $(cat "/sys/class/block/$(basename "$1")/size") * 512 )); }
# The partition that starts last on $DISK (by position, not number)
last_part() {
  sfdisk -d "$DISK" | awk -F'[ ,=]+' '/^\/dev\// {
    for (i = 1; i < NF; i++) if ($i == "start") s = $(i + 1) + 0
    if (s >= m) { m = s; p = $1 } } END { print p }'
}
# Partition table dump with device names replaced, to compare tables across boots
pt_norm() { sfdisk -d "$1" 2>/dev/null | sed -e 's|^/dev/[a-z]*\([0-9]*\) |p\1 |' -e '/^device:/d'; }

# Bytes from the start of $DISK to the end of its usable area (GPT last-lba)
disk_end_b() {
  sfdisk -d "$DISK" | awk '/^last-lba:/ { l = $2 } /^sector-size:/ { s = $2 } END { print (l + 1) * (s ? s : 512) }'
}
# What copying this SD system to the internal storage takes: "<system bytes> <game bytes>"
# (Steam game files, left out by --no-games; backups on the SD card are never copied)
copy_bytes() {
  local sys bk games=0 h
  sys=$(df -B1 --output=used / | tail -1)
  bk=$(du -sbx "$BACKUPS" 2>/dev/null | cut -f1 || true)
  for h in /home/*/.local/share/Steam/steamapps; do
    [ -d "$h" ] && games=$(( games + $(du -sbxc "$h/common" "$h/downloading" 2>/dev/null | tail -1 | cut -f1) ))
  done
  echo "$(( sys - ${bk:-0} - games )) $games"
}
# Smallest Kettle root partition for a copy of $1 bytes: 10% + 8 GiB to grow, at least 32 GiB
kettle_min_bytes() {
  local b=$(( $1 + $1 / 10 + 8 * 1024**3 ))
  [ "$b" -ge $(( 32 * 1024**3 )) ] || b=$(( 32 * 1024**3 ))
  echo "$b"
}
ESP_MIB=512
MIN_ANDROID_GB=16                  # "minimal Android": room to boot and set up, little else

# What is on the internal storage: none | partial | installed
install_state() {
  if [ -n "$(part_by_label $ROOT_LABEL)" ]; then echo installed
  elif [ -n "$(part_by_label $PARTIAL_LABEL)" ] || [ -n "$(part_by_label $ESP_LABEL)" ]; then echo partial
  else echo none; fi
}

# Estimated zstd size of a device (byte range $2..$2+$3 skipped): sampled blocks that read back as
# zeros (never written or trimmed) compress to nothing; anything else is counted as
# incompressible, which Android's encrypted userdata is.
estimate_bytes() {
  python3 - "$@" <<'EOF'
import os, sys
dev, skip_off, skip_len = sys.argv[1], int(sys.argv[2] if len(sys.argv) > 2 else 0), int(sys.argv[3] if len(sys.argv) > 3 else 0)
STEP, SAMPLE = 64 << 20, 256 << 10
fd = os.open(dev, os.O_RDONLY)
size = os.lseek(fd, 0, os.SEEK_END)
zero = bytes(SAMPLE)
used = total = 0
for off in range(0, size, STEP):
    if skip_len and skip_off <= off < skip_off + skip_len:
        continue
    total += 1
    if os.pread(fd, SAMPLE, off) != zero:
        used += 1
covered = size - skip_len
print(int(covered * used / total) if total else 0)
EOF
}

# Backups (made by kettle-backup-ufs) whose partition tables match the internal storage right
# now, newest first, as "<dir> <kind>"
matching_backups() {
  local d l dev ok serial
  serial=$(device_serial)
  for d in $(ls -d "$BACKUPS"/*/ 2>/dev/null | sort -r); do
    d=${d%/}
    [ -f "$d/SHA256SUMS" ] && [ -f "$d/manifest" ] || continue
    grep -qx "serial=$serial" "$d/manifest" || continue
    ok=1
    while read -r l dev; do
      [ -f "$d/lun$l.sfdisk" ] || { ok=0; break; }
      diff -q <(pt_norm "$dev") <(sed -e 's|^/dev/[a-z]*\([0-9]*\) |p\1 |' -e '/^device:/d' "$d/lun$l.sfdisk") \
        >/dev/null || { ok=0; break; }
    done < <(ufs_luns)
    [ "$ok" = 1 ] && echo "$d $(sed -n 's/^kind=//p' "$d/manifest")"
  done
}

# Feed dd's status=progress (on stdin) out as @pct for a copy of $1 bytes; errors go to the log
dd_pct() {
  tr '\r' '\n' | awk -v t="$1" -v p="$PROGRESS" '
    /^[0-9]+ bytes/ { if (p == 1 && t > 0) { n = int($1 * 100 / t); if (n != last) { print "@pct " n > "/dev/fd/3"; fflush("/dev/fd/3"); last = n } }
                      else { printf "\r%s", $0 > "/dev/stderr" } ; next }
    NF { print > "/dev/stderr" }'
}

# Ask Android's recovery to factory-reset userdata on its next start (bootloader_message in misc:
# command[32] "boot-recovery", status[32], recovery[768] "recovery\n--wipe_data\n"), which
# also clears the keys in /metadata. Android would otherwise find userdata unreadable and ask
# ("Cannot load Android system": choose Factory data reset).
request_android_wipe() {
  local misc f
  misc=$(part_by_label misc)
  if [ -z "$misc" ]; then note "no misc partition: Android will offer the factory reset itself"; return 0; fi
  if [ -n "$(head -c 32 "$misc" | tr -d '\0')" ]; then
    note "misc already holds a boot command; left alone (Android will offer the factory reset itself)"
    return 0
  fi
  f=$(mktemp)
  truncate -s 832 "$f"
  printf 'boot-recovery' | dd of="$f" conv=notrunc status=none
  printf 'recovery\n--wipe_data\n--reason=kettle\n' | dd of="$f" bs=1 seek=64 conv=notrunc status=none
  dd if="$f" of="$misc" conv=notrunc,fsync status=none
  rm -f "$f"
  note "Android's recovery will reset its data on the next Android start"
}
