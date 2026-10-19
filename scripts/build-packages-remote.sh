#!/usr/bin/env bash
# scripts/build-packages.sh on a native aarch64 build host instead of under qemu: build-packages.sh
# hands over to this when KETTLE_BUILD_HOST (user@host, e.g. kettle@192.168.12.102 for the Radxa
# O6N) is set, in the environment or local.env. KETTLE_BUILD_HOST= on the command line builds here.
#
# The host runs build-packages.sh itself, rootless as here, in its own copy of the tree:
# KETTLE_BUILD_DIR (default kettle-build, under its home, so a Kettle A/B update keeps it), with
# its own build chroot and package cache. It needs pacman, rsync and user namespaces with a
# subuid range for its user; a Kettle image has all three. It gets scripts/, packages/ (as on
# disk, like a local build), image/pacman.conf, the local repo, the mirror and the source cache
# of the packages being built; the packages it built and their source caches come back.
#   KETTLE_BUILD_JOBS   cores the host builds with (default all of them: it's a build box)
# (KETTLE_BUILD_DIR and KETTLE_BUILD_JOBS can go in local.env too.)
# One SSH connection carries everything (ControlMaster), so a password is asked once.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
HOST="${KETTLE_BUILD_HOST:?set KETTLE_BUILD_HOST}"
# the other settings can be in local.env too (the environment wins)
for v in KETTLE_BUILD_DIR KETTLE_BUILD_JOBS KETTLE_MIRROR; do
  if [ -z "${!v+set}" ] && [ -f "$ROOT/local.env" ]; then
    printf -v "$v" %s "$(. "$ROOT/local.env"; echo "${!v:-}")"
  fi
done
DIR="${KETTLE_BUILD_DIR:-kettle-build}"

mkdir -p "$ROOT/cache/src" "$PKG_CACHE" "$LOCAL_REPO"
# a socket under ROOT would be too long a path for one
SSH=(ssh -o ControlMaster=auto -o ControlPath="${XDG_RUNTIME_DIR:-/tmp}/kettle-build-%C" -o ControlPersist=120)
trap '"${SSH[@]}" -O exit "$HOST" 2>/dev/null || true' EXIT
"${SSH[@]}" -o ServerAliveInterval=30 -fN "$HOST"
sync_to() { rsync -a --delete -e "${SSH[*]}" "$@"; }

names=("$@")
[ ${#names[@]} -gt 0 ] || mapfile -t names < <(find "$ROOT/packages" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
# src_hash needs git, which the host may not have: the sums of what goes over, for those it builds
declare -A SUM
for name in "${names[@]}"; do SUM[$name]="$(src_hash "packages/$name")"; done

log "copying the tree to $HOST:$DIR"
"${SSH[@]}" "$HOST" "mkdir -p '$DIR/image' '$DIR/out/repo/aarch64' '$DIR/cache/src'"
sync_to "$ROOT/scripts" "$ROOT/packages" "$HOST:$DIR/"
sync_to "$ROOT/image/pacman.conf" "$HOST:$DIR/image/"
# the repo as it is now (a build adding to it waits); local builds go on while the host builds
lock "$ROOT/out/repo.lock" -s
sync_to "$LOCAL_REPO/" "$HOST:$DIR/out/repo/aarch64/"
exec {LOCK_FD}>&-
if [ -z "${KETTLE_MIRROR:-}" ] && [ -d "$ROOT/cache/mirror" ]; then
  sync_to "$ROOT/cache/mirror" "$HOST:$DIR/cache/"
fi
srcs=()
for name in "${names[@]}"; do [ ! -d "$ROOT/cache/src/$name" ] || srcs+=("$ROOT/cache/src/$name"); done
[ ${#srcs[@]} = 0 ] || sync_to "${srcs[@]}" "$HOST:$DIR/cache/src/"

log "building on $HOST"
tty=(); [ -t 0 ] && tty=(-t)
q=""; for a in "$@"; do q+=" $(printf '%q' "$a")"; done
rc=0
"${SSH[@]}" "${tty[@]}" "$HOST" "cd '$DIR' && mkdir -p build && touch build/.remote-start &&
  JOBS=${KETTLE_BUILD_JOBS:-\$(nproc)} ${KETTLE_MIRROR:+KETTLE_MIRROR=$(printf '%q' "$KETTLE_MIRROR")} \
  scripts/build-packages.sh$q" || rc=$?

# what got built comes back even when a later package failed: the packages (the host's repo
# copy has only these newer than the run) into ours, and their source caches
pkgs="$("${SSH[@]}" "$HOST" "cd '$DIR' && find out/repo/aarch64 -maxdepth 1 -name '*.pkg.tar.zst' -newer build/.remote-start -printf '%f\n'" || true)"
built="$("${SSH[@]}" "$HOST" "cd '$DIR' && find out/repo/.source -type f -newer build/.remote-start -printf '%f\n' 2>/dev/null" || true)"
if [ -n "$pkgs" ]; then
  log "fetching the packages"
  in=$(mktemp -d "$ROOT/build/remote-pkgs.XXXXXX")
  rsync -a -e "${SSH[*]}" $(printf "$HOST:$DIR/out/repo/aarch64/%s " $pkgs) "$in/"
  lock "$ROOT/out/repo.lock"
  for f in $pkgs; do
    mv "$in/$f" "$LOCAL_REPO/"
    # a rebuild keeps its version: drop pacman's cached copy of the old build
    rm -f "$PKG_CACHE/$f"
    repo-add -q -R "$LOCAL_REPO/kettle.db.tar.zst" "$LOCAL_REPO/$f"
    log "added $f"
  done
  rmdir "$in"
  mkdir -p "$ROOT/out/repo/.source"
  for name in $built; do
    if [ -n "${SUM[$name]:-}" ]; then echo "${SUM[$name]}" >"$ROOT/out/repo/.source/$name"; fi
    rsync -a -e "${SSH[*]}" "$HOST:$DIR/cache/src/$name" "$ROOT/cache/src/" 2>/dev/null || true
  done
fi
[ "$rc" = 0 ] || die "build on $HOST failed"
