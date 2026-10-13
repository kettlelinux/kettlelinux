#!/bin/bash
# Experimental: ICNA35xx video mode (40-kettle/1435) through the kernel command line.
set -e
F=/etc/kettle/boot.conf
[ -f $F ] && cp $F $F.before-vrr
cat > $F <<'CONF'
# VRR test (temporary): ICNA35xx in video mode. Remove this file and run update-grub to undo.
CMDLINE="$CMDLINE panel_chipone_icna35xx.video_mode=1 ${VRR_EXTRA:-}"
CONF
sed -i "s|\${VRR_EXTRA:-}|${1:-}|" $F
cat $F
update-grub
