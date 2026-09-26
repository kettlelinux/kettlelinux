#!/usr/bin/env bash
# Build the Kettle Linux kernel: pinned kernel.org source + kernel/patches/*/ (in
# order, --fuzz=0) + kernel/dts + base.config merged with steamos.config.
# Cross-compiles with LLVM; no GCC cross toolchain needed.
#
# Usage: scripts/build-kernel.sh [prepare|config|build|all]   (default: all)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/kernel/kernel.conf"

CACHE="$ROOT/cache"
KSRC="$ROOT/build/linux-$KERNEL_VERSION-kettle"
OUT="$ROOT/out/kernel"
. "$ROOT/scripts/lib.sh"
be_nice   # sets JOBS
KMAKE=(make -C "$KSRC" ARCH=arm64 LLVM=1 -j"$JOBS")

# The kernel needs bc; fall back to the timeconst-only shim if the host lacks it.
command -v bc >/dev/null || export PATH="$ROOT/tools:$PATH"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

fetch() {
  local tar="$CACHE/linux-$KERNEL_VERSION.tar.xz"
  mkdir -p "$CACHE"
  [ -f "$tar" ] || curl -fLo "$tar" "$KERNEL_SOURCE_URL"
  echo "$KERNEL_SOURCE_SHA256  $tar" | sha256sum -c --quiet || die "checksum mismatch: $tar"
}

prepare() {
  fetch
  log "extracting linux-$KERNEL_VERSION (fresh tree)"
  rm -rf "$KSRC"
  mkdir -p "$ROOT/build"
  tar -xf "$CACHE/linux-$KERNEL_VERSION.tar.xz" -C "$ROOT/build"
  mv "$ROOT/build/linux-$KERNEL_VERSION" "$KSRC"

  local dir p n=0
  for dir in "$ROOT"/kernel/patches/*/; do
    for p in "$dir"*.patch; do
      [ -f "$p" ] || continue
      patch -d "$KSRC" -p1 -N --fuzz=0 --no-backup-if-mismatch -s <"$p" \
        || die "patch failed: ${p#"$ROOT"/}"
      n=$((n + 1))
    done
  done
  log "applied $n patches"

  log "installing device trees"
  cp -r "$ROOT"/kernel/dts/. "$KSRC/arch/arm64/boot/dts/"
  local mk="$KSRC/arch/arm64/boot/dts/qcom/Makefile" dts name
  for dts in "$ROOT"/kernel/dts/qcom/*.dts; do
    name="$(basename "$dts" .dts)"
    grep -q "$name.dtb" "$mk" || echo "dtb-\$(CONFIG_ARCH_QCOM)	+= $name.dtb" >>"$mk"
  done
}

config() {
  [ -d "$KSRC" ] || die "no source tree; run: $0 prepare"
  log "merging base.config + steamos.config"
  cp "$ROOT/kernel/config/base.config" "$KSRC/.config"
  (cd "$KSRC" && ARCH=arm64 LLVM=1 scripts/kconfig/merge_config.sh -m .config \
     "$ROOT/kernel/config/steamos.config" >/dev/null)
  "${KMAKE[@]}" olddefconfig >/dev/null

  # olddefconfig silently drops symbols whose dependencies are unmet: assert.
  local line bad=0
  while IFS= read -r line; do
    case "$line" in CONFIG_*=*) ;; *) continue ;; esac
    grep -qxF "$line" "$KSRC/.config" || { echo "  not applied: $line"; bad=1; }
  done <"$ROOT/kernel/config/steamos.config"
  [ "$bad" = 0 ] || die "steamos.config options dropped by olddefconfig"
  cp "$KSRC/.config" "$ROOT/kernel/config/generated.config"
}

build() {
  [ -f "$KSRC/.config" ] || config
  log "building Image, modules, dtbs ($JOBS jobs)"
  "${KMAKE[@]}" Image modules dtbs

  local rel; rel="$("${KMAKE[@]}" -s kernelrelease)"
  log "staging $rel into out/kernel"
  rm -rf "$OUT"; mkdir -p "$OUT/boot/dtbs/qcom"
  cp "$KSRC/arch/arm64/boot/Image" "$OUT/boot/Image"
  cp "$KSRC/.config" "$OUT/boot/config-$rel"
  cp "$KSRC/System.map" "$OUT/boot/System.map-$rel"
  local dts name
  for dts in "$ROOT"/kernel/dts/qcom/*.dts; do
    name="$(basename "$dts" .dts)"
    cp "$KSRC/arch/arm64/boot/dts/qcom/$name.dtb" "$OUT/boot/dtbs/qcom/" \
      || die "dtb not built: $name"
  done
  "${KMAKE[@]}" modules_install INSTALL_MOD_PATH="$OUT/usr" INSTALL_MOD_STRIP=1 \
    DEPMOD=/bin/true >/dev/null
  depmod -b "$OUT/usr" "$rel"
  echo "$rel" >"$OUT/kernelrelease"
  log "done: $OUT (kernelrelease $rel)"
}

case "${1:-all}" in
  prepare) prepare ;;
  config) config ;;
  build) build ;;
  all) prepare; config; build ;;
  *) die "usage: $0 [prepare|config|build|all]" ;;
esac
