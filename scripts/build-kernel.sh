#!/usr/bin/env bash
# Build a Kettle Linux kernel: pinned kernel.org source + the flavour's patches/*/ (in order,
# --fuzz=0) + its dts + its base.config merged with its $FRAGMENTS. Cross-compiles with LLVM;
# no GCC cross toolchain needed.
#
# One kernel per SoC family (scripts/lib.sh kernel_flavour): qcom, the default, is kernel/ and
# goes to out/kernel; another flavour is kernel/<flavour>/ and goes to out/kernel-<flavour>.
# The flavour is KERNEL_FLAVOUR, else KETTLE_DEVICE's (its device.conf), else qcom.
#
# Usage: scripts/build-kernel.sh [prepare|config|build|all]   (default: all)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/lib.sh"
if [ -z "${KERNEL_FLAVOUR:-}" ] && [ -n "${KETTLE_DEVICE:-}" ]; then
  [ -f "$ROOT/device/$KETTLE_DEVICE/device.conf" ] || die "no device '$KETTLE_DEVICE'"
  KERNEL_FLAVOUR="$(. "$ROOT/device/$KETTLE_DEVICE/device.conf"; echo "${KERNEL_FLAVOUR:-qcom}")"
fi
kernel_flavour "${KERNEL_FLAVOUR:-qcom}"
# Merged in order over base.config; the qcom kernel serves every Qualcomm device, so each SoC
# adds its own. A flavour's kernel.conf sets its own FRAGMENTS.
FRAGMENTS=(steamos.config qcom.config sm8250.config sm8750.config)
source "$KDIR/kernel.conf"

CACHE="$ROOT/cache"
KSRC="$ROOT/build/linux-$KERNEL_VERSION-kettle"
[ "$KFLAVOUR" = qcom ] || KSRC+="-$KFLAVOUR"
OUT="$KOUT"
be_nice   # sets JOBS
KMAKE=(make -C "$KSRC" ARCH=arm64 LLVM=1 -j"$JOBS")

# The kernel needs bc; fall back to the timeconst-only shim if the host lacks it.
command -v bc >/dev/null || export PATH="$ROOT/tools:$PATH"

# a fragment from the flavour's config/, else the shared kernel/config/
fragment() {
  if [ -f "$KDIR/config/$1" ]; then echo "$KDIR/config/$1"; else echo "$ROOT/kernel/config/$1"; fi
}
# the flavour's own Qualcomm device trees (only qcom has any)
our_dts() { (shopt -s nullglob; for d in "$KDIR"/dts/qcom/*.dts; do echo "$d"; done); }

fetch() {
  local tar="$CACHE/${KERNEL_SOURCE_URL##*/}"
  mkdir -p "$CACHE"
  [ -f "$tar" ] || curl -fLo "$tar" "$KERNEL_SOURCE_URL"
  echo "$KERNEL_SOURCE_SHA256  $tar" | sha256sum -c --quiet || die "checksum mismatch: $tar"
}

prepare() {
  fetch
  log "extracting linux-$KERNEL_VERSION (fresh tree, $KFLAVOUR)"
  rm -rf "$KSRC"
  mkdir -p "$ROOT/build/$KFLAVOUR.extract"
  tar -xf "$CACHE/${KERNEL_SOURCE_URL##*/}" -C "$ROOT/build/$KFLAVOUR.extract"
  mv "$ROOT/build/$KFLAVOUR.extract/linux-$KERNEL_VERSION" "$KSRC"
  rmdir "$ROOT/build/$KFLAVOUR.extract"

  local dir p n=0
  for dir in "$KDIR"/patches/*/; do
    for p in "$dir"*.patch; do
      [ -f "$p" ] || continue
      patch -d "$KSRC" -p1 -N --fuzz=0 --no-backup-if-mismatch -s <"$p" \
        || die "patch failed: ${p#"$ROOT"/}"
      n=$((n + 1))
    done
  done
  log "applied $n patches"

  [ -d "$KDIR/dts" ] || return 0
  log "installing device trees"
  cp -r "$KDIR"/dts/. "$KSRC/arch/arm64/boot/dts/"
  local mk="$KSRC/arch/arm64/boot/dts/qcom/Makefile" dts name
  for dts in $(our_dts); do
    name="$(basename "$dts" .dts)"
    grep -q "$name.dtb" "$mk" || echo "dtb-\$(CONFIG_ARCH_QCOM)	+= $name.dtb" >>"$mk"
  done
}

config() {
  [ -d "$KSRC" ] || die "no source tree; run: $0 prepare"
  log "merging base.config + ${FRAGMENTS[*]} ($KFLAVOUR)"
  cp "$KDIR/config/base.config" "$KSRC/.config"
  local frags=() frag
  for frag in "${FRAGMENTS[@]}"; do frags+=("$(fragment "$frag")"); done
  (cd "$KSRC" && ARCH=arm64 LLVM=1 scripts/kconfig/merge_config.sh -m .config "${frags[@]}" >/dev/null)
  "${KMAKE[@]}" olddefconfig >/dev/null

  # olddefconfig silently drops symbols whose dependencies are unmet: assert.
  local line bad=0
  for frag in "${frags[@]}"; do
    while IFS= read -r line; do
      case "$line" in CONFIG_*=*) ;; *) continue ;; esac
      grep -qxF "$line" "$KSRC/.config" || { echo "  not applied (${frag##*/}): $line"; bad=1; }
    done <"$frag"
  done
  [ "$bad" = 0 ] || die "config fragment options dropped by olddefconfig"
  cp "$KSRC/.config" "$KDIR/config/generated.config"
}

# Re-run dtc at W=1 strength on our boards' preprocessed sources (kbuild keeps them): a warning
# in one of our kernel/dts files fails the build; upstream dtsi noise is only counted.
dtc_check() {
  [ -n "$(our_dts)" ] || return 0
  local qcom="$KSRC/arch/arm64/boot/dts/qcom" ours dts name out line bad=0 noise=0
  ours="$(cd "$KDIR/dts/qcom" && ls | sed 's/[.]/[.]/g' | paste -sd'|')"
  for dts in $(our_dts); do
    name="$(basename "$dts" .dts)"
    out="$(cd "$KSRC" && scripts/dtc/dtc -o /dev/null -b 0 -i arch/arm64/boot/dts/qcom/ \
      -i scripts/dtc/include-prefixes -Wno-unique_unit_address -Wunique_unit_address_if_enabled \
      "$qcom/.$name.dtb.dts.tmp" 2>&1)" || die "dtc check failed: $name"
    while IFS= read -r line; do
      case "$line" in "" | " "*) continue ;; esac   # "  also defined at": the line above's
      if grep -qE "(^|/)($ours):" <<<"$line"; then echo "  $name: $line"; bad=1
      else noise=$((noise + 1)); fi
    done <<<"$out"
  done
  [ "$noise" = 0 ] || log "dtc: $noise W=1 warnings from upstream dtsi files (not ours; ignored)"
  [ "$bad" = 0 ] || die "dtc warnings in kernel/dts"
}

build() {
  [ -f "$KSRC/.config" ] || config
  local targets=(Image modules)
  [ -z "$(our_dts)" ] || targets+=(dtbs)
  log "building ${targets[*]} ($KFLAVOUR, $JOBS jobs)"
  "${KMAKE[@]}" "${targets[@]}"
  dtc_check

  local rel; rel="$("${KMAKE[@]}" -s kernelrelease)"
  log "staging $rel into ${OUT#"$ROOT"/}"
  rm -rf "$OUT"; mkdir -p "$OUT/boot/dtbs/qcom"
  cp "$KSRC/arch/arm64/boot/Image" "$OUT/boot/Image"
  cp "$KSRC/.config" "$OUT/boot/config-$rel"
  cp "$KSRC/System.map" "$OUT/boot/System.map-$rel"
  local dts name
  for dts in $(our_dts); do
    name="$(basename "$dts" .dts)"
    cp "$KSRC/arch/arm64/boot/dts/qcom/$name.dtb" "$OUT/boot/dtbs/qcom/" \
      || die "dtb not built: $name"
  done
  "${KMAKE[@]}" modules_install INSTALL_MOD_PATH="$OUT/usr" INSTALL_MOD_STRIP=1 \
    DEPMOD=/bin/true >/dev/null
  depmod -b "$OUT/usr" "$rel"
  echo "$rel" >"$OUT/kernelrelease"
  echo "$KFLAVOUR" >"$OUT/flavour"
  kernel_src_hash "$KFLAVOUR" >"$OUT/.source-hash"   # build-image.sh warns when its tree changed since
  log "done: ${OUT#"$ROOT"/} (kernelrelease $rel)"
}

case "${1:-all}" in
  prepare) prepare ;;
  config) config ;;
  build) build ;;
  all) prepare; config; build ;;
  *) die "usage: $0 [prepare|config|build|all]" ;;
esac
