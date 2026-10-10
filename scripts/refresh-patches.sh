#!/usr/bin/env bash
# Rebase kernel/patches onto the pinned kernel: apply each patch with normal fuzz
# in a scratch git tree; any patch that needed fuzz/offsets is rewritten from the
# resulting diff (original mail header kept), so build-kernel.sh can stay --fuzz=0.
# Review the resulting `git diff kernel/patches` before committing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/kernel/kernel.conf"
WORK="$ROOT/build/refresh"

TAR="$ROOT/cache/linux-$KERNEL_VERSION.tar.xz"
[ -f "$TAR" ] || { echo "no $TAR; run scripts/build-kernel.sh prepare"; exit 1; }
# the pinned source, as build-kernel.sh checks it
echo "$KERNEL_SOURCE_SHA256  $TAR" | sha256sum -c --quiet || { echo "checksum mismatch: $TAR"; exit 1; }

rm -rf "$WORK"; mkdir -p "$WORK"
tar -xf "$TAR" -C "$WORK"
cd "$WORK/linux-$KERNEL_VERSION"
git init -q && git add -A && git -c user.name=r -c user.email=r@r commit -qm base

refreshed=0
for p in "$ROOT"/kernel/patches/*/*.patch; do
  if patch -p1 -N --fuzz=0 --dry-run -s <"$p" >/dev/null 2>&1; then
    patch -p1 -N --fuzz=0 --no-backup-if-mismatch -s <"$p"
  else
    out="$(patch -p1 -N --no-backup-if-mismatch <"$p")" \
      || { echo "$out"; echo "FAILED even with fuzz: ${p#"$ROOT"/}"; exit 1; }
    find . -name '*.orig' -delete
    # keep everything before the first diff as the header
    awk '/^(diff |--- |Index: )/{exit} {print}' "$p" >"$p.new"
    git add -A
    git diff --cached --no-color --no-renames >>"$p.new"
    mv "$p.new" "$p"
    echo "refreshed: ${p#"$ROOT"/}"
    refreshed=$((refreshed + 1))
  fi
  git add -A && git -c user.name=r -c user.email=r@r commit -qm "$(basename "$p")" --allow-empty
done
echo "done, $refreshed patch(es) refreshed"
