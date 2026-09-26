# Shared helpers for the rootless aarch64 build scripts (sourced, not executed).
# Callers set ROOT before sourcing.

QEMU="$ROOT/tools/qemu-aarch64-static"
PKG_CACHE="$ROOT/cache/pkg"
LOCAL_REPO="$ROOT/out/repo/aarch64"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Keep builds from taking over the machine: lowest CPU and idle I/O priority, and at most
# JOBS cores (default half), set as CPU affinity so everything sizing itself with nproc
# (makepkg's -j, upstream build scripts, make -j) follows it. Inherited by all children.
be_nice() {
  renice -n 19 -p $$ >/dev/null 2>&1 || true
  ionice -c 3 -p $$ 2>/dev/null || true
  local n; n=$(nproc)
  JOBS="${JOBS:-$(( n > 2 ? n / 2 : 1 ))}"
  [ "$JOBS" -lt "$n" ] && taskset -pc "0-$((JOBS - 1))" $$ >/dev/null 2>&1 || true
  export JOBS
}

# Re-exec the calling script inside a user+mount+pid namespace (subuid-mapped fake root).
enter_ns() {
  [ "${KETTLE_IN_NS:-}" = 1 ] && return 0
  [ -x "$QEMU" ] || die "missing $QEMU (extract usr/bin/qemu-aarch64-static from Arch's qemu-user-static package)"
  if [ -f "$ROOT/local.env" ]; then set -a; . "$ROOT/local.env"; set +a; fi
  exec env KETTLE_IN_NS=1 unshare --map-auto --map-root-user --mount --pid --fork \
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

# Where builds get Valve's packages: KETTLE_MIRROR (a URL with one directory per repo), else
# the local mirror from scripts/mirror-repos.sh if there is one, else Valve's servers.
mirror_url() {
  if [ -n "${KETTLE_MIRROR:-}" ]; then
    printf '%s\n' "${KETTLE_MIRROR%/}"
  elif [ -d "$ROOT/cache/mirror" ]; then
    printf 'file://%s\n' "$ROOT/cache/mirror"
  fi
}

# pacman.conf for build time: image/pacman.conf with Valve's repos on the mirror (if any) first
# and Valve's servers after it, for packages the mirror doesn't have yet (a new dependency: the
# next scripts/mirror-repos.sh freezes it too), plus our local repo (if built) ahead of them. The image's own /etc/pacman.conf keeps Valve's URLs.
build_pacman_conf() {
  local out="$1" mirror
  mirror="$(mirror_url)"
  [ -n "$mirror" ] && log "Valve's repos from ${mirror#file://"$ROOT"/}"
  awk -v repo="$LOCAL_REPO" -v haslocal="$([ -f "$LOCAL_REPO/kettle.db" ] && echo 1)" -v m="$mirror" '
    /^\[deckard-arch-hotfixes/ && haslocal && !done { print "[kettle]\nSigLevel = Never\nServer = file://" repo "\n"; done=1 }
    /^\[/ { r = substr($0, 2, length($0) - 2) }
    m && r != "options" && /^Server *=/ { print "Server = " m "/" r }
    { print }' "$ROOT/image/pacman.conf" >"$out"
}

# pacman against a root at $1 (extra args follow).
pacman_root() {
  local r="$1"; shift
  pacman --root "$r" --dbpath "$r/var/lib/pacman" --config "$PACMAN_CONF" \
    --cachedir "$PKG_CACHE" --noconfirm --noprogressbar "$@"
}
