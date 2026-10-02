#!/usr/bin/env bash
# Add a built release to the update server tree and regenerate what devices read from it.
#
# Usage: scripts/publish-update.sh out/kettle-<buildid>-<device>.raucb [BRANCH]
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
# Each device keeps its newest KETTLE_KEEP_RELEASES releases on each branch (default 3; 0 keeps
# all): older ones leave the tree, and the chunks only they used leave store/;
# scripts/upload-update.sh then removes both from the server.
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
# Valve's server tool refuses two releases with the same version and build ID, whatever their
# variant: each device's builds need build IDs of their own (KETTLE_BUILD_ID)
buildid="$(jq -r .buildid <<<"$manifest")"
for m in "$TREE"/images/*/"$version"/*.manifest.json; do
  [ -e "$m" ] && [ "$(basename "$m")" != "$name.manifest.json" ] || continue
  [ "$(jq -r .buildid "$m")" != "$buildid" ] ||
    die "build $buildid ($version) is already published as $(basename "${m%.manifest.json}"); rebuild with another KETTLE_BUILD_ID"
done
log "publishing $name on $branch -> ${dest#"$ROOT"/}"
mkdir -p "$dest"
rm -rf "$dest/$name".{raucb,castr,manifest.json}
cp --reflink=auto "$bundle" "$dest/"
cp -r --reflink=auto "$base.castr" "$dest/"
mkdir -p "$TREE/store"
cp -rn --reflink=auto "$base.castr/." "$TREE/store/"
jq --arg b "$branch" '.branch = $b | .default_update_branch = $b' <<<"$manifest" >"$dest/$name.manifest.json"

# the newest KEEP of each device's releases on each branch stay; a branch is never emptied
keep="${KETTLE_KEEP_RELEASES:-3}"
if [ "$keep" -gt 0 ] 2>/dev/null; then
  removed=0
  for vdir in "$TREE"/images/*/; do
    for b in stable beta main; do
      while read -r _ m; do
        log "removing $(basename "${m%.manifest.json}") from the tree (keeping the newest $keep on $b)"
        rm -rf "${m%.manifest.json}".{raucb,castr,manifest.json}
        removed=1
      done < <(for m in "$vdir"*/*.manifest.json; do
                 [ -e "$m" ] && [ "$(jq -r .branch "$m")" = "$b" ] && echo "$(jq -r .buildid "$m") $m"
               done | sort -t' ' -k1,1V | head -n -"$keep")
    done
  done
  if [ "$removed" = 1 ]; then
    # chunks no remaining release's .castr/ has
    used="$(mktemp)" all="$(mktemp)"
    find "$TREE/images" -path '*.castr/*' -type f -printf '%P\n' | sed 's|^.*\.castr/||' | sort -u >"$used"
    find "$TREE/store" -type f -printf '%P\n' | sort >"$all"
    n="$(comm -23 "$all" "$used" | wc -l)"
    comm -23 "$all" "$used" | (cd "$TREE/store" && xargs -r rm -f)
    find "$TREE/store" -mindepth 1 -type d -empty -delete
    rm -f "$used" "$all"
    log "removed $n chunks no release uses any more from store/"
  fi
fi

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
# every device with releases in the tree (images/<variant>/): a variant left out gets no meta
# files, and its devices' update check fails (Steam: "unable to download the required updates")
variants="$(find "$TREE/images" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | paste -sd' ')"
log "variants: $variants"
cat >"$TREE/.server.conf" <<EOF
[Images]
PoolDir = /mnt/tree/images
Product = steamos
Release = kettle
Variants = $variants
Branches = stable beta main
Archs = aarch64
# a branch may have no releases yet (stable, while Kettle is in beta)
StrictPoolValidation = false

# a branch's followers are also offered the newer releases of the steadier branches
[Images.BranchesToConsider]
beta = stable
main = beta stable

[Images.ProvideRemoteInfoConfig.aarch64]
Variants = $variants
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
