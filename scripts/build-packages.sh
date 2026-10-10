#!/usr/bin/env bash
# Build packages/<name>/PKGBUILD for aarch64 into our local repo (out/repo/aarch64,
# repo "kettle"), rootless: makepkg runs in an aarch64 chroot via qemu binfmt.
#
# Usage: scripts/build-packages.sh [name...]     (default: every dir under packages/)
# A package is built after the ones of ours in the same run it depends on (depends,
# makedepends), the rest in the order given (alphabetical by default).
# The build chroot (build/pkgroot) is created once and reused; delete it to start clean.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
be_nice
enter_ns "$@"

CHROOT="$ROOT/build/pkgroot"
PACMAN_CONF="$ROOT/build/pacman.pkgbuild.conf"
mkdir -p "$ROOT/build" "$PKG_CACHE" "$LOCAL_REPO"
# one build at a time in the chroot and the repo (build-image.sh and publish-update.sh use both)
lock "$ROOT/build/pkgroot.lock"
lock "$ROOT/out/repo.lock"
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
# -u too: when the repos move (a new Valve hotfix line), a chroot left on the old versions can't
# install a dependency whose new version breaks an installed package's exact pin (gcc/gcc-libs)
pacman_root "$CHROOT" -Syu >/dev/null

names=("$@")
[ ${#names[@]} -gt 0 ] || mapfile -t names < <(find "$ROOT/packages" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)

# build order: each package after the ones of this run that it depends on (so it builds against
# them, not the repo's older copies); pkgnames map to their directory under packages/
declare -A DIR_OF DEPS_ON DONE
for name in "${names[@]}"; do
  [ -f "$ROOT/packages/$name/PKGBUILD" ] || die "no PKGBUILD in packages/$name"
  for p in $(bash -c ". '$ROOT/packages/$name/PKGBUILD'; echo \${pkgname[@]}"); do DIR_OF[$p]=$name; done
done
for name in "${names[@]}"; do
  DEPS_ON[$name]=""
  for p in $(bash -c ". '$ROOT/packages/$name/PKGBUILD'; echo \${depends[@]} \${makedepends[@]}"); do
    o="${DIR_OF[${p%%[<>=]*}]:-}"
    [ -z "$o" ] || [ "$o" = "$name" ] || DEPS_ON[$name]+=" $o"
  done
done
order=()
while [ ${#order[@]} -lt ${#names[@]} ]; do
  progress=0
  for name in "${names[@]}"; do
    [ -z "${DONE[$name]:-}" ] || continue
    ready=1
    for o in ${DEPS_ON[$name]}; do [ -n "${DONE[$o]:-}" ] || ready=0; done
    if [ "$ready" = 1 ]; then order+=("$name"); DONE[$name]=1; progress=1; fi
  done
  if [ "$progress" = 0 ]; then
    left=(); for name in "${names[@]}"; do [ -n "${DONE[$name]:-}" ] || left+=("$name"); done
    die "dependency cycle among: ${left[*]}"
  fi
done
[ ${#order[@]} -lt 2 ] || log "build order: ${order[*]}"

for name in "${order[@]}"; do
  src="$ROOT/packages/$name"
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
  if [ -d "$ROOT/cache/src/$name" ]; then cp -a "$ROOT/cache/src/$name/." "$CHROOT/build/$name/"; fi
  chown -R 1000:1000 "$CHROOT/build/$name"
  # what the tree looked like for this build (build-image.sh warns when packages/<name> changed since)
  src_sum="$(src_hash "packages/$name")"
  # PKGDEST apart from the sources, so a package used as a source isn't taken for ours. A clean
  # environment: the build's own env holds local.env's secrets (WIFI_PSK, the Discord webhook)
  clean_env=(PATH=/usr/local/sbin:/usr/local/bin:/usr/bin HOME=/home/builder USER=builder LOGNAME=builder
       LANG=C.UTF-8 TERM="${TERM:-dumb}")
  for v in http_proxy https_proxy no_proxy HTTP_PROXY HTTPS_PROXY NO_PROXY; do
    if [ -n "${!v:-}" ]; then clean_env+=("$v=${!v}"); fi
  done
  chroot "$CHROOT" /usr/bin/env -i "${clean_env[@]}" runuser -u builder -- \
    bash -c "cd /build/$name && mkdir -p .out && PKGDEST=/build/$name/.out makepkg --nodeps --noconfirm --clean -f"
  # ... and keep what this one downloaded: the PKGBUILD's remote sources, by local name
  # ("name::url", else the URL's last part; git sources are bare clones without .git)
  mkdir -p "$ROOT/cache/src/$name"
  bash -c ". '$src/PKGBUILD'; for s in \"\${source[@]}\" \"\${source_aarch64[@]}\"; do
      case \"\$s\" in *://*) ;; *) continue ;; esac
      n=\"\${s%%::*}\"; [ \"\$n\" = \"\$s\" ] && { n=\"\${s%%[#?]*}\"; n=\"\${n##*/}\"; n=\"\${n%.git}\"; }
      echo \"\$n\"; done" | while read -r b; do
    if [ -e "$CHROOT/build/$name/$b" ]; then
      cp -a --no-preserve=ownership "$CHROOT/build/$name/$b" "$ROOT/cache/src/$name/"
    fi
  done
  for p in "$CHROOT/build/$name"/.out/*.pkg.tar.zst; do
    cp "$p" "$LOCAL_REPO/"
    # a rebuild keeps its version: drop pacman's cached copy of the old build
    rm -f "$PKG_CACHE/$(basename "$p")"
    repo-add -q -R "$LOCAL_REPO/kettle.db.tar.zst" "$LOCAL_REPO/$(basename "$p")"
    log "added $(basename "$p")"
  done
  mkdir -p "$ROOT/out/repo/.source"
  echo "$src_sum" >"$ROOT/out/repo/.source/$name"
done
