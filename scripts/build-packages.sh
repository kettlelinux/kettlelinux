#!/usr/bin/env bash
# Build packages/<name>/PKGBUILD for aarch64 into our local repo (out/repo/aarch64,
# repo "kettle"), rootless: makepkg runs in an aarch64 chroot via qemu binfmt.
#
# Usage: scripts/build-packages.sh [name...]     (default: every dir under packages/)
# The build chroot (build/pkgroot) is created once and reused; delete it to start clean.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
be_nice
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
  echo 'MAKEFLAGS="-j$(nproc)"' >>"$CHROOT/etc/makepkg.conf"   # nproc follows be_nice's core limit
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
  # dependencies as root (makepkg -s would need sudo in the chroot); -y also picks up
  # packages built earlier in this run
  deps="$(bash -c ". '$src/PKGBUILD'; echo \${depends[@]} \${makedepends[@]}")"
  pacman_root "$CHROOT" -Sy --needed $deps
  rm -rf "$CHROOT/build/$name"; mkdir -p "$CHROOT/build"
  cp -r "$src" "$CHROOT/build/$name"
  # a file shared with another package is a symlink at the top of the package dir (e.g.
  # u-boot-retroidpocket/mkbootimg.py): copy what it points to (deeper links, node_modules, stay)
  find "$src" -mindepth 1 -maxdepth 1 -type l -printf '%f\n' | while read -r l; do
    rm "$CHROOT/build/$name/$l"; cp -rL "$src/$l" "$CHROOT/build/$name/$l"
  done
  # reuse the sources a previous build downloaded (cache/src/<name>), so a build doesn't
  # depend on upstream still having them
  [ -d "$ROOT/cache/src/$name" ] && cp -a "$ROOT/cache/src/$name/." "$CHROOT/build/$name/"
  chown -R 1000:1000 "$CHROOT/build/$name"
  # PKGDEST apart from the sources, so a package used as a source isn't taken for ours
  chroot "$CHROOT" runuser -u builder -- bash -c "cd /build/$name && mkdir -p .out && PKGDEST=/build/$name/.out makepkg --nodeps --noconfirm --clean -f"
  # ... and keep what this one downloaded: the PKGBUILD's remote sources, by local name
  # ("name::url", else the URL's last part; git sources are bare clones without .git)
  mkdir -p "$ROOT/cache/src/$name"
  bash -c ". '$src/PKGBUILD'; for s in \"\${source[@]}\" \"\${source_aarch64[@]}\"; do
      case \"\$s\" in *://*) ;; *) continue ;; esac
      n=\"\${s%%::*}\"; [ \"\$n\" = \"\$s\" ] && { n=\"\${s%%[#?]*}\"; n=\"\${n##*/}\"; n=\"\${n%.git}\"; }
      echo \"\$n\"; done" | while read -r b; do
    [ -e "$CHROOT/build/$name/$b" ] && cp -a --no-preserve=ownership "$CHROOT/build/$name/$b" "$ROOT/cache/src/$name/"
  done
  for p in "$CHROOT/build/$name"/.out/*.pkg.tar.zst; do
    cp "$p" "$LOCAL_REPO/"
    # a rebuild keeps its version: drop pacman's cached copy of the old build
    rm -f "$PKG_CACHE/$(basename "$p")"
    repo-add -q -R "$LOCAL_REPO/kettle.db.tar.zst" "$LOCAL_REPO/$(basename "$p")"
    log "added $(basename "$p")"
  done
done
