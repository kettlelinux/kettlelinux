#!/usr/bin/env bash
# Freeze Valve's deckard repos (the [repo]/Server pairs in image/pacman.conf) into a local
# mirror, cache/mirror/<repo>/, so builds keep working when Valve prunes a snapshot. The
# hotfix repo (release/0.4.x) isn't a snapshot at all: Valve updates it in place, so the
# mirror is also what pins it. Once a mirror exists the build scripts install from it
# (lib.sh build_pacman_conf); KETTLE_MIRROR=<url> points them at a hosted copy instead.
#
# Usage: scripts/mirror-repos.sh [--full] [--refresh]
#   default    the packages our builds use: everything the image (image/packages.txt), the
#              build chroot (base base-devel) and every PKGBUILD's depends/makedepends pull
#              in (~3 GB, hard-linked from cache/pkg where possible)
#   --full     every package in the repos (~32 GB)
#   --refresh  fetch the repo databases again (moves the hotfix repo forward); without it an
#              existing mirror keeps the databases it was made with
# Every package is checked against its sha256 in the repo database. Needs the local repo
# (scripts/build-packages.sh) so our own packages' dependencies can be resolved.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
MIRROR="$ROOT/cache/mirror"

full=0 refresh=0
for a in "$@"; do
  case "$a" in
    --full) full=1 ;;
    --refresh) refresh=1 ;;
    *) die "usage: $0 [--full] [--refresh]" ;;
  esac
done

if [ "${KETTLE_IN_NS:-}" != 1 ]; then
  [ -f "$LOCAL_REPO/kettle.db" ] || die "no local repo; run scripts/build-packages.sh"
fi
be_nice
enter_ns "$@"

# ---------------------------------------------------------------- inside the namespace
# repo name -> upstream URL, straight from image/pacman.conf ($arch expanded)
declare -A UPSTREAM
while read -r repo url; do
  UPSTREAM[$repo]="${url//\$repo/$repo}"
  UPSTREAM[$repo]="${UPSTREAM[$repo]//\$arch/aarch64}"
done < <(awk '/^\[/ { r = substr($0, 2, length($0) - 2) }
              r != "options" && /^Server *=/ { sub(/^Server *= */, ""); print r, $0 }' "$ROOT/image/pacman.conf")
[ ${#UPSTREAM[@]} -gt 0 ] || die "no repos in image/pacman.conf"

mkdir -p "$MIRROR"
for repo in "${!UPSTREAM[@]}"; do
  db="$MIRROR/$repo/$repo.db"
  if [ "$refresh" = 1 ] || [ ! -f "$db" ]; then
    log "fetching $repo database"
    mkdir -p "$MIRROR/$repo"
    curl -fsSLo "$db.part" "${UPSTREAM[$repo]}/$repo.db"
    mv "$db.part" "$db"
    printf '%s\n' "${UPSTREAM[$repo]}" >"$MIRROR/$repo/UPSTREAM"
    date -u +%Y-%m-%dT%H:%MZ >"$MIRROR/$repo/FETCHED"
  fi
done

# filename -> sha256 for every package the (mirrored) databases list
declare -A SHA OF_REPO
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for repo in "${!UPSTREAM[@]}"; do
  mkdir -p "$TMP/db/$repo"
  tar -xf "$MIRROR/$repo/$repo.db" -C "$TMP/db/$repo"
  while read -r f s; do
    SHA[$f]=$s
    OF_REPO[$f]=$repo
  done < <(awk '/^%FILENAME%/ { getline; f = $0 } /^%SHA256SUM%/ { getline; print f, $0 }' "$TMP/db/$repo"/*/desc)
done

# which files to mirror
if [ "$full" = 1 ]; then
  mapfile -t WANT < <(printf '%s\n' "${!SHA[@]}" | sort)
else
  # resolve against the mirrored databases (so the set matches what builds will see) plus
  # our local repo, from an empty root: the full dependency closure of each target list
  conf="$TMP/pacman.conf"
  KETTLE_MIRROR="file://$MIRROR" build_pacman_conf "$conf"
  mkdir -p "$TMP/root/var/lib/pacman" "$TMP/nocache"
  pm() { pacman --config "$conf" --root "$TMP/root" --dbpath "$TMP/root/var/lib/pacman" \
           --cachedir "$TMP/nocache" --noconfirm --noprogressbar "$@"; }
  pm -Sy >/dev/null

  # our own packages (packages/*/PKGBUILD) resolve through their depends/makedepends, so they
  # can be left out of the image list: they may not be built yet
  declare -A OURS
  for src in "$ROOT"/packages/*/PKGBUILD; do
    for n in $(bash -c ". '$src'; echo \${pkgname[@]}" 2>/dev/null); do OURS[$n]=1; done
  done
  theirs() { local p out=(); for p in "$@"; do [ -z "${OURS[${p%%[<>=]*}]:-}" ] && out+=("$p"); done; echo "${out[*]}"; }
  targets=("build-chroot:base base-devel" "bundle-tools:rauc casync squashfs-tools")
  for src in "$ROOT"/packages/*/PKGBUILD; do
    deps="$(theirs $(bash -c ". '$src'; echo \${depends[@]} \${makedepends[@]}" 2>/dev/null))"
    [ -n "$deps" ] && targets+=("$(basename "$(dirname "$src")"):$deps")
  done
  targets+=("image:$(theirs $(sed -e 's/#.*//' -e '/^\s*$/d' "$ROOT/image/packages.txt"))")

  : >"$TMP/want"
  for t in "${targets[@]}"; do
    name="${t%%:*}"
    # repo and URL of every package the transaction would download
    pm -Sp --print-format '%r %l' ${t#*:} >"$TMP/out" 2>"$TMP/err" \
      || die "resolving $name failed: $(tail -3 "$TMP/err")"
    awk '$1 != "kettle" { n = split($2, u, "/"); print u[n] }' "$TMP/out" >>"$TMP/want"
  done
  mapfile -t WANT < <(sort -u "$TMP/want")
fi

log "mirroring ${#WANT[@]} packages into ${MIRROR#"$ROOT"/}"
have=0 linked=0 fetched=0
for f in "${WANT[@]}"; do
  repo="${OF_REPO[$f]:-}"
  [ -n "$repo" ] || die "$f is not in any mirrored database"
  dest="$MIRROR/$repo/$f"
  if [ -f "$dest" ]; then
    have=$((have + 1))
    continue
  fi
  if [ -f "$PKG_CACHE/$f" ] && [ "$(sha256sum <"$PKG_CACHE/$f" | cut -d' ' -f1)" = "${SHA[$f]}" ]; then
    ln "$PKG_CACHE/$f" "$dest" 2>/dev/null || cp "$PKG_CACHE/$f" "$dest"
    linked=$((linked + 1))
    continue
  fi
  curl -fsSLo "$dest.part" "$(cat "$MIRROR/$repo/UPSTREAM")/$f" || die "downloading $f failed"
  [ "$(sha256sum <"$dest.part" | cut -d' ' -f1)" = "${SHA[$f]}" ] \
    || { rm -f "$dest.part"; die "$f doesn't match its sha256 in the $repo database"; }
  mv "$dest.part" "$dest"
  fetched=$((fetched + 1))
  [ $((fetched % 25)) = 0 ] && log "  downloaded $fetched so far"
done
log "done: $have already mirrored, $linked from cache/pkg, $fetched downloaded ($(du -sh "$MIRROR" | cut -f1) total)"
for repo in "${!UPSTREAM[@]}"; do
  log "  $repo: database from $(cat "$MIRROR/$repo/FETCHED")"
done
