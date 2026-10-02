#!/usr/bin/env bash
# Upload the update server tree (made by scripts/publish-update.sh) to the bucket behind
# KETTLE_UPDATE_URL.
#
# Usage: scripts/upload-update.sh
#
# Env (also read from ./local.env, gitignored):
#   KETTLE_UPDATE_REMOTE   rclone remote and bucket, e.g. r2:kettle-updates (see docs/UPDATES.md)
#   KETTLE_UPDATE_DIR      the tree (default out/update-server)
#   RCLONE_BWLIMIT         rclone's own, e.g. 5M, to leave the connection usable meanwhile
#
# The per-release .castr/ directories are not uploaded: the server answers
# images/…/<name>.castr/<chunk> from store/<chunk> (a URL rewrite rule, docs/UPDATES.md).
# Order matters: chunks and bundles go up before meta/, so no device is ever pointed at a
# release that isn't all there, and removed releases (and the chunks only they used) are deleted
# only after meta/ stops naming them.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
if [ -f "$ROOT/local.env" ]; then set -a; . "$ROOT/local.env"; set +a; fi
TREE="${KETTLE_UPDATE_DIR:-$ROOT/out/update-server}"
REMOTE="${KETTLE_UPDATE_REMOTE:?set KETTLE_UPDATE_REMOTE (e.g. r2:kettle-updates) in local.env}"

command -v rclone >/dev/null || die "rclone not found (pacman -S rclone)"
[ -d "$TREE/meta" ] && [ -d "$TREE/store" ] || die "no tree in $TREE; run scripts/publish-update.sh"
be_nice

forever=(--header-upload "Cache-Control: public, max-age=31536000, immutable")
brief=(--header-upload "Cache-Control: public, max-age=60")
rc() { rclone --s3-no-check-bucket --transfers 16 --checkers 32 --stats-one-line --stats 30s "$@"; }

log "chunks -> $REMOTE/store"
rc copy --ignore-existing "${forever[@]}" "$TREE/store" "$REMOTE/store"
log "bundles -> $REMOTE/images"
rc copy --ignore-existing "${forever[@]}" --include '*.raucb' "$TREE/images" "$REMOTE/images"
rc copy "${brief[@]}" --include '*.manifest.json' "$TREE/images" "$REMOTE/images"
log "meta -> $REMOTE/meta"
rc sync "${brief[@]}" "$TREE/meta" "$REMOTE/meta"
log "removing releases no longer in the tree"
rc sync --exclude '*.castr/**' "$TREE/images" "$REMOTE/images"
# last: chunks publish-update.sh dropped from store/ because no remaining release uses them.
# Nothing the server's meta names needs them by now (meta went up first).
log "removing chunks no release uses any more"
rc sync --ignore-existing "${forever[@]}" "$TREE/store" "$REMOTE/store"

log "done."
