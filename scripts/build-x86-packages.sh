#!/usr/bin/env bash
# Build the packages/<name> whose PKGBUILD sets _kettle_buildhost=x86_64 into our local repo
# (out/repo/aarch64, repo "kettle"), as build-packages.sh does the others: rootless, but in an
# x86_64 Arch chroot (build/x86root), run by the build machine itself (no qemu).
#
# Their packages install on the aarch64 devices, but they are built from x86 code or tools:
# - x86 libraries for the rootfs Steam's FEX runs games in (deckard-mesa-linux-deps-x86_64:
#   glibc 2.41, GCC 15, LLVM 20), which must not link anything newer. The chroot is Arch as of
#   the archive of 2025-07-15, which has those versions (from 06n-arch's Dockerfile).
# - aarch64 code that needs an LLVM toolchain Valve's aarch64 repos lack (mesa-panfrost's CL
#   shaders: LLVM, libclc and the SPIR-V translator of one version), cross-compiled against
#   build/x86root/sysroot: Valve's aarch64 packages a PKGBUILD names in _kettle_sysroot.
#
# Usage: scripts/build-x86-packages.sh [name...]   (default: every package with _kettle_buildhost)
# The chroot is created once and reused; delete build/x86root to start clean.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
[ "$(uname -m)" = x86_64 ] || die "needs an x86_64 build machine"
be_nice
enter_ns "$@"

X="$ROOT/build/x86root"
SYSROOT="$X/sysroot"
# Arch's bootstrap of that month and the archive day its packages come from
BOOTSTRAP_URL=https://archive.archlinux.org/iso/2025.07.01/archlinux-bootstrap-2025.07.01-x86_64.tar.zst
BOOTSTRAP_SHA256=bc943f1d3d25d9350a23574b7eacdd8e00badd8f546ce05929d233b404bfd155
SNAPSHOT=2025/07/15
mkdir -p "$ROOT/build" "$PKG_CACHE" "$LOCAL_REPO"
lock "$X.lock"

names=("$@")
if [ ${#names[@]} = 0 ]; then
  for d in "$ROOT"/packages/*/; do
    d="$(basename "$d")"
    [ "$(bash -c ". '$ROOT/packages/$d/PKGBUILD'; echo \${_kettle_buildhost:-}")" = x86_64 ] && names+=("$d")
  done
fi
[ ${#names[@]} -gt 0 ] || die "no package sets _kettle_buildhost=x86_64"
for name in "${names[@]}"; do
  [ -f "$ROOT/packages/$name/PKGBUILD" ] || die "no PKGBUILD in packages/$name"
  [ "$(bash -c ". '$ROOT/packages/$name/PKGBUILD'; echo \${_kettle_buildhost:-}")" = x86_64 ] ||
    die "packages/$name is built by build-packages.sh (no _kettle_buildhost=x86_64)"
done

register_binfmt   # the sysroot's package hooks are aarch64 programs
trap 'chroot_umount "$SYSROOT"; chroot_umount "$X"' EXIT
# .kettle-ready marks a finished setup: a half-made chroot is made again
if [ ! -e "$X/.kettle-ready" ]; then
  log "creating the x86_64 build chroot (Arch, archive of $SNAPSHOT)"
  rm -rf "$X"
  tar="$ROOT/cache/${BOOTSTRAP_URL##*/}"
  [ -f "$tar" ] || curl -fL --retry 3 -o "$tar" "$BOOTSTRAP_URL"
  echo "$BOOTSTRAP_SHA256  $tar" | sha256sum -c --quiet || die "checksum mismatch: $tar"
  rm -rf "$X.new"; mkdir -p "$X.new"
  tar -xf "$tar" -C "$X.new" --numeric-owner
  mv "$X.new/root.x86_64" "$X"; rm -rf "$X.new"
  echo "Server = https://archive.archlinux.org/repos/$SNAPSHOT/\$repo/os/\$arch" >"$X/etc/pacman.d/mirrorlist"
  # the archive throttles parallel connections; multilib for the i686 builds. No CheckSpace:
  # in the chroot pacman finds no mount point for its cache and refuses every transaction.
  sed -i -e 's/^#\?ParallelDownloads.*/ParallelDownloads = 2/' -e '/^\[options\]/a DisableDownloadTimeout' \
    -e 's/^CheckSpace/#CheckSpace/' "$X/etc/pacman.conf"
  printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>"$X/etc/pacman.conf"
  # GnuPG as of the snapshot day: the packager keys' certifications have expired since
  install -d -m 0755 "$X/etc/pacman.d/gnupg"
  echo "faked-system-time ${SNAPSHOT//\//}T120000" >"$X/etc/pacman.d/gnupg/gpg.conf"
  chroot_mount "$X"
  cp /etc/resolv.conf "$X/etc/resolv.conf"
  chroot "$X" pacman-key --init >/dev/null
  chroot "$X" pacman-key --populate archlinux >/dev/null
  chroot "$X" pacman -Syu --noconfirm --needed base-devel
  chroot "$X" useradd -m -u 1000 builder
  # CARCH=aarch64: the packages install on the devices, whatever code is in them. The rest of
  # makepkg.conf (CFLAGS, strip) stays the build machine's.
  sed -e 's/^CARCH=.*/CARCH="aarch64"/' -e 's/^#\?MAKEFLAGS=.*/MAKEFLAGS="-j$(nproc)"/' \
    -e 's/^OPTIONS=(\(.*\)debug/OPTIONS=(\1!debug/' "$X/etc/makepkg.conf" >"$X/etc/makepkg-kettle.conf"
  chroot_umount "$X"
  : >"$X/.kettle-ready"
fi
chroot_mount "$X"
cp /etc/resolv.conf "$X/etc/resolv.conf"

# the aarch64 sysroot: Valve's packages, as the image has them (image/pacman.conf, our repo)
PACMAN_CONF="$ROOT/build/pacman.x86-sysroot.conf"
build_pacman_conf "$PACMAN_CONF"
sysroot_pkgs=()
for name in "${names[@]}"; do
  sysroot_pkgs+=($(bash -c ". '$ROOT/packages/$name/PKGBUILD'; echo \${_kettle_sysroot[@]}"))
done
if [ ${#sysroot_pkgs[@]} -gt 0 ]; then
  log "aarch64 sysroot: ${sysroot_pkgs[*]}"
  mkdir -p "$SYSROOT"
  chroot_mount "$SYSROOT"
  lock "$ROOT/out/repo.lock" -s   # not while build-packages.sh is adding to the repo
  pacman_root "$SYSROOT" -Syu --needed "${sysroot_pkgs[@]}" >/dev/null
  exec {LOCK_FD}>&-
  chroot_umount "$SYSROOT"
fi

for name in "${names[@]}"; do
  src="$ROOT/packages/$name"
  log "building $name (x86_64 chroot)"
  # the x86 build dependencies come from the pinned archive; depends are the devices' packages
  deps="$(bash -c ". '$src/PKGBUILD'; echo \${makedepends[@]}")"
  [ -z "$deps" ] || chroot "$X" pacman -S --noconfirm --needed $deps >/dev/null
  rm -rf "$X/build/$name"; mkdir -p "$X/build"
  cp -r "$src" "$X/build/$name"
  # a file shared with another package is a symlink at the top of the package dir: copy its target
  find "$src" -mindepth 1 -maxdepth 1 -type l -printf '%f\n' | while read -r l; do
    rm "$X/build/$name/$l"; cp -rL "$src/$l" "$X/build/$name/$l"
  done
  if [ -d "$ROOT/cache/src/$name" ]; then cp -a "$ROOT/cache/src/$name/." "$X/build/$name/"; fi
  chown -R 1000:1000 "$X/build/$name"
  src_sum="$(src_hash "packages/$name")"
  clean_env=(PATH=/usr/local/sbin:/usr/local/bin:/usr/bin HOME=/home/builder USER=builder LOGNAME=builder
       LANG=C.UTF-8 TERM="${TERM:-dumb}")
  for v in http_proxy https_proxy no_proxy HTTP_PROXY HTTPS_PROXY NO_PROXY; do
    if [ -n "${!v:-}" ]; then clean_env+=("$v=${!v}"); fi
  done
  # (the sysroot is the chroot's /sysroot, where the aarch64 cross files look for it)
  chroot "$X" /usr/bin/env -i "${clean_env[@]}" runuser -u builder -- \
    bash -c "cd /build/$name && mkdir -p .out && PKGDEST=/build/$name/.out makepkg --config /etc/makepkg-kettle.conf --nodeps --noconfirm --clean -f"
  # keep what it downloaded (remote sources, by local name), as build-packages.sh does
  mkdir -p "$ROOT/cache/src/$name"
  bash -c ". '$src/PKGBUILD'; for s in \"\${source[@]}\"; do
      case \"\$s\" in *://*) ;; *) continue ;; esac
      n=\"\${s%%::*}\"; [ \"\$n\" = \"\$s\" ] && { n=\"\${s%%[#?]*}\"; n=\"\${n##*/}\"; n=\"\${n%.git}\"; }
      echo \"\$n\"; done" | while read -r b; do
    if [ -e "$X/build/$name/$b" ]; then cp -a --no-preserve=ownership "$X/build/$name/$b" "$ROOT/cache/src/$name/"; fi
  done
  # the repo only while adding to it: the build takes a while, and others read the repo
  lock "$ROOT/out/repo.lock"
  for p in "$X/build/$name"/.out/*.pkg.tar.zst; do
    cp "$p" "$LOCAL_REPO/"
    rm -f "$PKG_CACHE/$(basename "$p")"
    repo-add -q -R "$LOCAL_REPO/kettle.db.tar.zst" "$LOCAL_REPO/$(basename "$p")"
    log "added $(basename "$p")"
  done
  mkdir -p "$ROOT/out/repo/.source"
  echo "$src_sum" >"$ROOT/out/repo/.source/$name"
  exec {LOCK_FD}>&-
done
