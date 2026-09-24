#!/usr/bin/env bash
# Build packages/<name>/PKGBUILD for aarch64 into our local repo (out/repo/aarch64,
# repo "steamportal"), rootless: makepkg runs in an aarch64 chroot via qemu binfmt.
#
# Usage: scripts/build-packages.sh [name...]     (default: every dir under packages/)
# The build chroot (build/pkgroot) is created once and reused; delete it to start clean.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
enter_ns "$@"

CHROOT="$ROOT/build/pkgroot"
PACMAN_CONF="$ROOT/build/pacman.pkgbuild.conf"
mkdir -p "$ROOT/build" "$PKG_CACHE" "$LOCAL_REPO"
build_pacman_conf "$PACMAN_CONF"

register_binfmt
trap 'chroot_umount "$CHROOT"' EXIT
new=0; [ -d "$CHROOT/usr" ] || new=1
mkdir -p "$CHROOT"
chroot_mount "$CHROOT"

if [ "$new" = 1 ]; then
  log "creating build chroot"
  pacman_root "$CHROOT" -Sy --needed base base-devel
  chroot "$CHROOT" useradd -m -u 1000 builder
  echo "MAKEFLAGS=\"-j$(nproc)\"" >>"$CHROOT/etc/makepkg.conf"
  sed -i 's/^OPTIONS=(\(.*\)debug/OPTIONS=(\1!debug/' "$CHROOT/etc/makepkg.conf"
fi
cp /etc/resolv.conf "$CHROOT/etc/resolv.conf"
pacman_root "$CHROOT" -Sy >/dev/null

names=("$@")
[ ${#names[@]} -gt 0 ] || mapfile -t names < <(find "$ROOT/packages" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)

for name in "${names[@]}"; do
  src="$ROOT/packages/$name"
  [ -f "$src/PKGBUILD" ] || die "no PKGBUILD in packages/$name"
  log "building $name"
  # dependencies as root (makepkg -s would need sudo in the chroot)
  deps="$(bash -c ". '$src/PKGBUILD'; echo \${depends[@]} \${makedepends[@]}")"
  pacman_root "$CHROOT" -S --needed $deps
  rm -rf "$CHROOT/build/$name"; mkdir -p "$CHROOT/build"
  cp -r "$src" "$CHROOT/build/$name"
  # reuse downloaded sources
  [ -d "$ROOT/cache/src" ] && cp "$ROOT"/cache/src/* "$CHROOT/build/$name/" 2>/dev/null || true
  chown -R 1000:1000 "$CHROOT/build/$name"
  chroot "$CHROOT" runuser -u builder -- bash -c "cd /build/$name && makepkg --nodeps --noconfirm --clean -f"
  for p in "$CHROOT/build/$name"/*.pkg.tar.zst; do
    cp "$p" "$LOCAL_REPO/"
    repo-add -q -R "$LOCAL_REPO/steamportal.db.tar.zst" "$LOCAL_REPO/$(basename "$p")"
    log "added $(basename "$p")"
  done
done
