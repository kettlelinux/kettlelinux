#!/usr/bin/env bash
# Upload a release SD card image to the bucket behind KETTLE_UPDATE_URL, for the website's
# Download section, and list it in downloads/releases.json.
#
# Usage: scripts/upload-image.sh out/kettle-<buildid>-<variant>.img.xz
#   (made by KETTLE_RELEASE=1 scripts/build-image.sh, with <name>.sha256 and
#   <name>.manifest.json beside it)
#
# Env (also read from ./local.env, gitignored):
#   KETTLE_UPDATE_REMOTE   rclone remote and bucket, e.g. r2:kettle-updates (docs/UPDATES.md)
#   KETTLE_KEEP_IMAGES     how many images stay up, newest by build ID (default 3); older ones
#                          are removed from the index and the bucket
#   RCLONE_BWLIMIT         rclone's own, e.g. 5M, to leave the connection usable meanwhile
#
# On the server:
#   downloads/<variant>/<name>.img.xz, <name>.sha256
#   downloads/releases.json   {"images": [...]}, newest first; what the website reads
# The image goes up before the index names it, and old images are deleted only after the
# index stops naming them.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
if [ -f "$ROOT/local.env" ]; then set -a; . "$ROOT/local.env"; set +a; fi
REMOTE="${KETTLE_UPDATE_REMOTE:?set KETTLE_UPDATE_REMOTE (e.g. r2:kettle-updates) in local.env}"
KEEP="${KETTLE_KEEP_IMAGES:-3}"

xzimg="${1:?usage: $0 out/kettle-<buildid>-<variant>.img.xz}"
case "$xzimg" in *.img.xz) ;; *) die "expected an .img.xz (KETTLE_RELEASE=1 scripts/build-image.sh)" ;; esac
xzimg="$(realpath "$xzimg")"
name="$(basename "${xzimg%.img.xz}")"
dir="$(dirname "$xzimg")"
[ -f "$dir/$name.sha256" ] && [ -f "$dir/$name.manifest.json" ] \
  || die "need $name.sha256 and $name.manifest.json beside the image"
command -v rclone >/dev/null || die "rclone not found (pacman -S rclone)"
command -v jq >/dev/null || die "jq not found (pacman -S jq)"
be_nice

manifest="$(cat "$dir/$name.manifest.json")"
variant="$(jq -r .variant <<<"$manifest")"
sum() { awk -v f="$1" '$2 == f || $2 == "*" f { print $1 }' "$dir/$name.sha256"; }
sha_xz="$(sum "$name.img.xz")" sha_img="$(sum "$name.img")"
[ -n "$sha_xz" ] || die "$name.sha256 has no line for $name.img.xz"
log "checking $name.img.xz against $name.sha256"
[ "$(sha256sum "$xzimg" | cut -d' ' -f1)" = "$sha_xz" ] || die "$name.img.xz doesn't match its checksum"

forever=(--header-upload "Cache-Control: public, max-age=31536000, immutable")
brief=(--header-upload "Cache-Control: public, max-age=60")
rc() { rclone --s3-no-check-bucket --stats-one-line --stats 30s "$@"; }

dest="$REMOTE/downloads/$variant"
log "$name.img.xz ($(du -h "$xzimg" | cut -f1)) -> $dest"
rc copyto "${forever[@]}" "$xzimg" "$dest/$name.img.xz"
rc copyto "${forever[@]}" "$dir/$name.sha256" "$dest/$name.sha256"

# the current index, if there is one (a failed listing stops here rather than starting over)
index="$REMOTE/downloads/releases.json"
if [ -n "$(rc lsf --files-only --include releases.json "$REMOTE/downloads")" ]; then current="$(rc cat "$index")"; else current='{"images": []}'; fi
entry="$(jq -n --argjson m "$manifest" --arg name "$name" --arg variant "$variant" \
  --arg file "downloads/$variant/$name.img.xz" --arg sums "downloads/$variant/$name.sha256" \
  --argjson size "$(stat -c %s "$xzimg")" --argjson image_size "$(stat -c %s "$dir/$name.img" 2>/dev/null || echo null)" \
  --arg sha256 "$sha_xz" --arg sha256_img "$sha_img" --arg date "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{name: $name, variant: $variant, version: $m.version, buildid: $m.buildid,
    branch: ($m.default_update_branch // $m.branch), date: $date, file: $file, sha256: $sha256,
    size: $size, image_size: $image_size, sha256_img: (if $sha256_img == "" then null else $sha256_img end), sums: $sums}')"
new="$(jq --argjson e "$entry" \
  '.images = ([.images[] | select(.name != $e.name)] + [$e]
              | sort_by(.buildid | split(".") | map(tonumber)) | reverse)' <<<"$current")"
kept="$(jq --argjson n "$KEEP" '.images = .images[:$n]' <<<"$new")"

log "index -> $index ($(jq '.images | length' <<<"$kept") images)"
rc rcat "${brief[@]}" "$index" <<<"$kept"

jq -r --argjson n "$KEEP" '.images[$n:][] | .file, .sums' <<<"$new" | while read -r old; do
  log "removing $old"
  rc deletefile "$REMOTE/$old" || true
done
log "done. Download: ${KETTLE_UPDATE_URL:-<KETTLE_UPDATE_URL>}/downloads/$variant/$name.img.xz"
