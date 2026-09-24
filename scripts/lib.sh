# Shared helpers for the rootless aarch64 build scripts (sourced, not executed).
# Callers set ROOT before sourcing.

QEMU="$ROOT/tools/qemu-aarch64-static"
PKG_CACHE="$ROOT/cache/pkg"
LOCAL_REPO="$ROOT/out/repo/aarch64"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Re-exec the calling script inside a user+mount+pid namespace (subuid-mapped fake root).
enter_ns() {
  [ "${STEAMPORTAL_IN_NS:-}" = 1 ] && return 0
  [ -x "$QEMU" ] || die "missing $QEMU (extract usr/bin/qemu-aarch64-static from Arch's qemu-user-static package)"
  if [ -f "$ROOT/local.env" ]; then set -a; . "$ROOT/local.env"; set +a; fi
  exec env STEAMPORTAL_IN_NS=1 unshare --map-auto --map-root-user --mount --pid --fork \
    --mount-proc "$0" "$@"
}

# Namespace-local binfmt_misc entry so aarch64 binaries run via qemu (kernel >= 6.7).
register_binfmt() {
  [ -e /proc/sys/fs/binfmt_misc/register ] || mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc
  [ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] && return 0
  printf ':qemu-aarch64:M::\\x7fELF\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\xb7\\x00:\\xff\\xff\\xff\\xff\\xff\\xfe\\xfe\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xfe\\xff\\xff\\xff:%s:FC' \
    "$QEMU" >/proc/sys/fs/binfmt_misc/register
}

# Skeleton + API filesystems for a chroot at $1.
chroot_mount() {
  local r="$1"
  install -d -m 0755 "$r"/{dev,run,etc/pacman.d,var/lib/pacman,var/log,var/cache/pacman/pkg}
  install -d -m 0555 "$r"/{proc,sys}
  install -d -m 1777 "$r/tmp"
  mount --rbind /dev "$r/dev"
  mount -t proc proc "$r/proc"
  mount --rbind /sys "$r/sys"
  mount -t tmpfs tmpfs "$r/run"
  mount -t tmpfs tmpfs "$r/tmp"
}

chroot_umount() {
  local r="$1" m
  for m in dev/pts dev sys proc run tmp; do umount -l "$r/$m" 2>/dev/null || true; done
}

# pacman.conf for build time: image/pacman.conf plus our local repo (if built) ahead of Valve's.
build_pacman_conf() {
  local out="$1"
  if [ -f "$LOCAL_REPO/steamportal.db" ]; then
    awk -v repo="$LOCAL_REPO" '
      /^\[deckard-arch-hotfixes/ && !done { print "[steamportal]\nSigLevel = Never\nServer = file://" repo "\n"; done=1 }
      { print }' "$ROOT/image/pacman.conf" >"$out"
  else
    cp "$ROOT/image/pacman.conf" "$out"
  fi
}

# pacman against a root at $1 (extra args follow).
pacman_root() {
  local r="$1"; shift
  pacman --root "$r" --dbpath "$r/var/lib/pacman" --config "$PACMAN_CONF" \
    --cachedir "$PKG_CACHE" --noconfirm --noprogressbar "$@"
}
