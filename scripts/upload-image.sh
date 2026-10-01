#!/usr/bin/env bash
# Upload a release SD card image to the bucket behind KETTLE_UPDATE_URL, for the website's
# Download section, and list it in downloads/releases.json.
#
# Usage: scripts/upload-image.sh out/kettle-<buildid>-<variant>.img.xz [NOTES]
#   (made by KETTLE_RELEASE=1 scripts/build-image.sh, with <name>.sha256 and
#   <name>.manifest.json beside it)
#   NOTES   the build's release notes, shown under the website's download button (default
#           releases/<variant>/<buildid>.md; "## " headings, "- " bullets and plain lines).
#           Without one, an entry already in the index keeps its notes.
# Running it again for a build already up only rewrites the index (rclone skips the unchanged
# image), which is how notes are changed after the fact.
#
# Env (also read from ./local.env, gitignored):
#   KETTLE_UPDATE_REMOTE   rclone remote and bucket, e.g. r2:kettle-updates (docs/UPDATES.md)
#   KETTLE_KEEP_IMAGES     how many images stay up per device, newest by build ID (default 3);
#                          older ones are removed from the index and the bucket
#   RCLONE_BWLIMIT         rclone's own, e.g. 5M, to leave the connection usable meanwhile
#   KETTLE_DISCORD_WEBHOOK Discord webhook URL (secret: local.env only); a build new to the index
#                          is announced there with its notes. Unset, nothing is posted.
#
# On the server:
#   downloads/<variant>/<name>.img.xz, <name>.sha256
#   downloads/releases.json   {"images": [...]}, every device's, newest first; what the website
#                             reads (one download per device)
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
# the device's name, as the website shows it (device/<variant>/device.conf's MODEL)
model="$(. "$ROOT/device/$variant/device.conf" && echo "$MODEL")" || die "no device/$variant/device.conf"
notes_file="${2:-$ROOT/releases/$variant/$(jq -r .buildid <<<"$manifest").md}"
if [ -f "$notes_file" ]; then notes="$(cat "$notes_file")"
elif [ -n "${2:-}" ]; then die "no notes file $notes_file"
else notes=""; log "no ${notes_file#"$ROOT"/}: keeping the notes already in the index, if any"; fi
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
entry="$(jq -n --argjson m "$manifest" --arg name "$name" --arg variant "$variant" --arg model "$model" \
  --arg file "downloads/$variant/$name.img.xz" --arg sums "downloads/$variant/$name.sha256" \
  --argjson size "$(stat -c %s "$xzimg")" --argjson image_size "$(stat -c %s "$dir/$name.img" 2>/dev/null || echo null)" \
  --arg sha256 "$sha_xz" --arg sha256_img "$sha_img" --arg date "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg notes "$notes" \
  '{name: $name, variant: $variant, model: $model, version: $m.version, buildid: $m.buildid,
    branch: ($m.default_update_branch // $m.branch), date: $date, file: $file, sha256: $sha256,
    size: $size, image_size: $image_size, sha256_img: (if $sha256_img == "" then null else $sha256_img end), sums: $sums,
    notes: (if $notes == "" then null else $notes end)}')"
new="$(jq --argjson e "$entry" \
  '(first(.images[] | select(.name == $e.name) | .notes) // null) as $old
   | .images = ([.images[] | select(.name != $e.name)] + [$e + {notes: ($e.notes // $old)}]
              | sort_by(.buildid | split(".") | map(tonumber)) | reverse)' <<<"$current")"
# the newest KEEP of each device's images stay; the rest are dropped from the index
kept="$(jq --argjson n "$KEEP" '.images as $all | .images = [range(0; $all | length) as $i
  | $all[$i] | select([$all[:$i][] | select(.variant == $all[$i].variant)] | length < $n)]' <<<"$new")"

log "index -> $index ($(jq '.images | length' <<<"$kept") images)"
rc rcat "${brief[@]}" "$index" <<<"$kept"

jq -r --argjson k "$kept" '($k.images | map(.name)) as $keep
  | .images[] | select(.name as $n | $keep | index($n) | not) | .file, .sums' <<<"$new" | while read -r old; do
  log "removing $old"
  rc deletefile "$REMOTE/$old" || true
done
log "done. Download: ${KETTLE_UPDATE_URL:-<KETTLE_UPDATE_URL>}/downloads/$variant/$name.img.xz"

# announce only a build the index didn't have, so rerunning to change notes doesn't post again;
# a failed post doesn't fail the upload
if [ -n "${KETTLE_DISCORD_WEBHOOK:-}" ] \
   && [ "$(jq --arg n "$name" '[.images[] | select(.name == $n)] | length' <<<"$current")" = 0 ]; then
  command -v curl >/dev/null || die "curl not found (pacman -S curl)"
  log "announcing $name on Discord"
  jq -n --argjson e "$entry" '{username: "Kettle Linux", allowed_mentions: {parse: []}, embeds: [{
      title: "Kettle \($e.version) for the \($e.model)",
      url: "https://kettlelinux.org",
      description: (($e.notes // "A new image is up.")
                    | if length > 4000 then .[:4000] + "\n…" else . end),
      footer: {text: "Build \($e.buildid) · \($e.branch)"}, timestamp: $e.date}]}' \
    | curl -fsS -o /dev/null -H "Content-Type: application/json" --data-binary @- "$KETTLE_DISCORD_WEBHOOK" \
    || log "warning: the Discord announcement failed"
fi
