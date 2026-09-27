#!/usr/bin/env bash
# Add a built release to the update server tree and regenerate what devices read from it.
#
# Usage: scripts/publish-update.sh out/kettle-<buildid>-odin2portal.raucb [BRANCH]
#   BRANCH   stable, beta or main (default: the branch the build was made for)
#
# The tree (KETTLE_UPDATE_DIR, default out/update-server) is static files; copy all of it to
# the server behind KETTLE_UPDATE_URL, as is:
#   images/<variant>/<version>/kettle-<buildid>-<variant>.{raucb,castr/,manifest.json}
#   store/…  every release's chunks, once (reflinked, so free on btrfs)
#   meta/…   what steamos-atomupd-client asks for: per image, the update to take next
# The tree works as is from any static server; scripts/upload-update.sh uploads it without the
# per-release .castr/ directories, and the server answers those from store/ (docs/UPDATES.md).
# The meta files come from Valve's own server tool (steamos-atomupd's staticserver), run over
# every release in images/, so publishing again (or removing a release) rewrites them all.
# Releases on stable are offered to beta and main followers too, as on SteamOS.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
TREE="${KETTLE_UPDATE_DIR:-$ROOT/out/update-server}"
TOOLS="$ROOT/build/pkgroot"

bundle="${1:?usage: $0 out/kettle-<buildid>-<variant>.raucb [stable|beta|main]}"
branch="${2:-}"
if [ "${KETTLE_IN_NS:-}" != 1 ]; then
  bundle="$(realpath "$bundle")"
  base="${bundle%.raucb}"
  [ -f "$bundle" ] && [ -d "$base.castr" ] && [ -f "$base.manifest.json" ] \
    || die "need $base.{raucb,castr/,manifest.json} (made by scripts/build-image.sh)"
  case "${branch:-beta}" in stable|beta|main) ;; *) die "branch must be stable, beta or main" ;; esac
  [ -d "$TOOLS/usr" ] || die "no build chroot; run scripts/build-packages.sh"
  set -- "$bundle" "$branch"
fi
enter_ns "$@"

# ---------------------------------------------------------------- inside the namespace
bundle="$1" base="${1%.raucb}" name="$(basename "${1%.raucb}")"
manifest="$(cat "$base.manifest.json")"
variant="$(jq -r .variant <<<"$manifest")" version="$(jq -r .version <<<"$manifest")"
[ -n "$branch" ] || branch="$(jq -r '.default_update_branch // .branch' <<<"$manifest")"

dest="$TREE/images/$variant/$version"
log "publishing $name on $branch -> ${dest#"$ROOT"/}"
mkdir -p "$dest"
rm -rf "$dest/$name".{raucb,castr,manifest.json}
cp --reflink=auto "$bundle" "$dest/"
cp -r --reflink=auto "$base.castr" "$dest/"
mkdir -p "$TREE/store"
cp -rn --reflink=auto "$base.castr/." "$TREE/store/"
jq --arg b "$branch" '.branch = $b | .default_update_branch = $b' <<<"$manifest" >"$dest/$name.manifest.json"

# Valve's staticserver, in the build chroot (it has steamos-atomupd and its Python modules)
trap 'umount "$TOOLS/mnt/tree" 2>/dev/null || true; chroot_umount "$TOOLS"' EXIT
register_binfmt
chroot_mount "$TOOLS"
cp /etc/resolv.conf "$TOOLS/etc/resolv.conf"
PACMAN_CONF="$ROOT/build/pacman.pkgbuild.conf"
build_pacman_conf "$PACMAN_CONF"
pacman_root "$TOOLS" -Sy --needed steamos-atomupd-client python-pyinotify python-semantic-version >/dev/null
mkdir -p "$TOOLS/mnt/tree" "$TREE/meta"
mount --bind "$TREE" "$TOOLS/mnt/tree"
cat >"$TREE/.server.conf" <<EOF
[Images]
PoolDir = /mnt/tree/images
Product = steamos
Release = kettle
Variants = odin2portal
Branches = stable beta main
Archs = aarch64
# a branch may have no releases yet (stable, while Kettle is in beta)
StrictPoolValidation = false

# a branch's followers are also offered the newer releases of the steadier branches
[Images.BranchesToConsider]
beta = stable
main = beta stable

[Images.ProvideRemoteInfoConfig.aarch64]
Variants = odin2portal
Branches = stable beta main
EOF
# (Valve's steamos-atomupd is built for Python 3.12, the snapshot's Python is 3.11: see docs/UPDATES.md)
chroot "$TOOLS" /bin/bash -euo pipefail -c \
  'cd /mnt/tree/meta && PYTHONPATH=/usr/lib/python3.12/site-packages python3 -c "import sys; from steamosatomupd import staticserver; sys.exit(staticserver.main())" --config /mnt/tree/.server.conf'
umount "$TOOLS/mnt/tree"; chroot_umount "$TOOLS"; trap - EXIT
rm -f "$TREE/.server.conf" "$TREE/meta/.lockfile.lock"
chown -R "$(stat -c %u:%g "$ROOT")" "$TREE" 2>/dev/null || true

log "done. Upload it with scripts/upload-update.sh (or copy ${TREE#"$ROOT"/}/ to the server as is)."
log "  releases: $(find "$TREE/images" -name '*.manifest.json' | wc -l), meta files: $(find "$TREE/meta" -name '*.json' | wc -l)"
