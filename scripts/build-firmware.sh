#!/usr/bin/env bash
# Assemble the Odin 2 Portal firmware tree into out/firmware/usr/lib/firmware:
#  - DT/driver-requested Portal blobs from ROCKNIX extra-firmware (ADSP/CDSP, amp, topology, WCN7850)
#  - GPU (A740 SQE/GMU/zap) + Bluetooth (HMT) from Arch linux-firmware-{qcom,atheros}
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$ROOT/cache/firmware"
OUT="$ROOT/out/firmware/usr/lib/firmware"

EXTRA_FW_REPO=https://github.com/ROCKNIX/extra-firmware.git
EXTRA_FW_REV=e1eb71af80427aa1fec1659d2967f7ba8bef83b5
LINUX_FW_REPO=https://steamdeck-packages.steamos.cloud/archlinux-deckard/archlinux/mash-20260305/core/os/aarch64
LINUX_FW_VER=20260221-1

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

mkdir -p "$CACHE"
if [ ! -d "$CACHE/extra-firmware/.git" ]; then
  log "fetching ROCKNIX extra-firmware @ ${EXTRA_FW_REV:0:8}"
  git init -q "$CACHE/extra-firmware"
  git -C "$CACHE/extra-firmware" remote add origin "$EXTRA_FW_REPO"
fi
if [ "$(git -C "$CACHE/extra-firmware" rev-parse -q --verify HEAD || true)" != "$EXTRA_FW_REV" ]; then
  git -C "$CACHE/extra-firmware" fetch -q --depth 1 origin "$EXTRA_FW_REV"
  git -C "$CACHE/extra-firmware" checkout -q FETCH_HEAD
fi

for p in linux-firmware-qcom linux-firmware-atheros; do
  f="$CACHE/$p-$LINUX_FW_VER-any.pkg.tar.zst"
  [ -f "$f" ] || { log "fetching $p $LINUX_FW_VER"; curl -fsLo "$f" "$LINUX_FW_REPO/$(basename "$f")"; }
done

rm -rf "$ROOT/out/firmware"; mkdir -p "$OUT"
X="$CACHE/extra-firmware/SM8550"
(cd "$X" && cp --parents -t "$OUT" \
  ath12k/WCN7850/hw2.0/{amss,board-2,m3,regdb}.bin \
  qcom/sm8550/ayn/{cdsp,cdsp_dtb}.mbn \
  qcom/sm8550/ayn/odin2portal/* \
  qcom/sm8550/AYN-Odin2-tplg.bin \
  qcom/vpu/vpu30_p4.mbn)

bsdtar -xf "$CACHE/linux-firmware-qcom-$LINUX_FW_VER-any.pkg.tar.zst" -C "$ROOT/out/firmware" \
  usr/lib/firmware/qcom/a740_sqe.fw.zst \
  usr/lib/firmware/qcom/gmu_gen70200.bin.zst \
  usr/lib/firmware/qcom/sm8550/a740_zap.mbn.zst
bsdtar -xf "$CACHE/linux-firmware-atheros-$LINUX_FW_VER-any.pkg.tar.zst" -C "$ROOT/out/firmware" \
  'usr/lib/firmware/qca/hmtbtfw20.tlv*' 'usr/lib/firmware/qca/hmtnv20*'

log "firmware tree: $(find "$OUT" -type f | wc -l) files, $(du -sh "$OUT" | cut -f1)"
