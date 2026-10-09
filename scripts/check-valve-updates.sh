#!/usr/bin/env bash
# What Valve has changed since our mirror (scripts/mirror-repos.sh) froze its repos: for each repo
# in image/pacman.conf, the packages our builds use (the ones in cache/mirror/<repo>/) whose
# version upstream differs from the mirror's database, and any hotfix release line newer than
# the one pacman.conf names. Run it before a release; taking the changes is
# `scripts/mirror-repos.sh --refresh` and a rebuild.
#
# Each change is marked:
#   ours     we build this package ourselves (packages/*/PKGBUILD); the [kettle] repo comes first,
#            so Valve's update does nothing until our PKGBUILD moves to it
#   ignored  in pacman.conf's IgnorePkg (Valve's kernels and bootloaders)
#
# Usage: scripts/check-valve-updates.sh [--all]
#   --all  every package that changed in the repos, not only the ones our builds use
# Exits 0 when nothing we use changed, 1 when something did (or a newer release line exists).
set -euo pipefail
export LC_ALL=C   # sort and join must collate the same way, whatever the locale

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MIRROR="$ROOT/cache/mirror"
CONF="$ROOT/image/pacman.conf"
all=0
case "${1:-}" in --all) all=1 ;; "") ;; *) echo "usage: $0 [--all]" >&2; exit 2 ;; esac
[ -d "$MIRROR" ] || { echo "no mirror in cache/mirror: run scripts/mirror-repos.sh first" >&2; exit 2; }

TMP="$(mktemp -d "$ROOT/build/check-valve.XXXXXX" 2>/dev/null || mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# name version sha256, one per package in a repo database (the checksum catches a package Valve
# rebuilt without changing its version, which a new hotfix line does: 0.5 rebuilt grub, ibus, ...)
db_versions() {
  local d="$TMP/x$RANDOM"; mkdir -p "$d"; tar -xf "$1" -C "$d"
  awk '/^%NAME%/ { getline; n = $0 } /^%VERSION%/ { getline; v = $0 }
       /^%SHA256SUM%/ { getline; print n, v, $0 }' "$d"/*/desc | sort
}

declare -A OURS IGN
for src in "$ROOT"/packages/*/PKGBUILD; do
  for n in $(bash -c ". '$src'; echo \${pkgname[@]}" 2>/dev/null); do OURS[$n]=1; done
done
for n in $(awk -F= '/^IgnorePkg/ { print $2 }' "$CONF"); do IGN[$n]=1; done

changed=0
while read -r repo url; do
  url="${url//\$repo/$repo}"; url="${url//\$arch/aarch64}"
  [ -f "$MIRROR/$repo/$repo.db" ] || { echo "$repo: not mirrored yet"; changed=1; continue; }
  if ! curl -fsSLo "$TMP/$repo.db" "$url/$repo.db"; then
    echo "$repo: couldn't fetch $url/$repo.db"; changed=1; continue
  fi
  db_versions "$MIRROR/$repo/$repo.db" >"$TMP/mine"
  db_versions "$TMP/$repo.db" >"$TMP/theirs"
  # the packages our builds use: those with a file in the mirror
  find "$MIRROR/$repo" -maxdepth 1 -name '*.pkg.tar.*' -printf '%f\n' \
    | sed -E 's/-[^-]+-[^-]+-[^-]+\.pkg\.tar\..*$//' | sort -u >"$TMP/used"
  out="$(join -a1 "$TMP/mine" "$TMP/theirs" | awk -v all=$all '
      FILENAME == ARGV[1] { used[$1] = 1; next }
      !(all || ($1 in used)) { next }
      $4 == "" { print $1, $2, "(removed)"; next }
      $4 != $2 { print $1, $2, $4; next }
      $5 != $3 { print $1, $2, $4 "(rebuilt)" }' \
      "$TMP/used" - | sort)"
  new="$(join -v2 "$TMP/mine" "$TMP/theirs" | awk -v all=$all 'all { print $1, "(new)", $2 }')"
  out="$(printf '%s\n%s\n' "$out" "$new" | sed '/^$/d')"
  fetched="$(cat "$MIRROR/$repo/FETCHED" 2>/dev/null || echo '?')"
  if [ -z "$out" ]; then
    echo "$repo: no changes since the mirror ($fetched)"
  else
    echo "$repo: changed since the mirror ($fetched):"
    while read -r n a b; do
      mark=""
      [ -n "${OURS[$n]:-}" ] && mark="  [ours]"
      [ -n "${IGN[$n]:-}" ] && mark="  [ignored]"
      printf '  %-44s %s -> %s%s\n' "$n" "$a" "$b" "$mark"
      [ -z "$mark" ] && changed=1
    done <<<"$out"
  fi

  # a newer hotfix release line (release/<major>.<minor>.x) than the one we use
  if [[ "$url" =~ ^(.*/release/)([0-9]+)\.([0-9]+)\.x$ ]]; then
    base="${BASH_REMATCH[1]}" cur="${BASH_REMATCH[2]}.${BASH_REMATCH[3]}"
    lines="$(curl -fsSL "$base" 2>/dev/null | grep -oE 'href="[0-9]+\.[0-9]+\.x/?"' \
      | grep -oE '[0-9]+\.[0-9]+' | sort -uV)" || true
    newest="$(tail -1 <<<"$lines")"
    if [ -n "$newest" ] && [ "$newest" != "$cur" ] \
       && [ "$(printf '%s\n%s\n' "$cur" "$newest" | sort -V | tail -1)" = "$newest" ]; then
      echo "  newer release line: $newest.x (we use $cur.x)"
      changed=1
    fi
  fi
done < <(awk '/^\[/ { r = substr($0, 2, length($0) - 2) }
              r != "options" && /^Server *=/ { sub(/^Server *= */, ""); print r, $0 }' "$CONF")
exit $changed
