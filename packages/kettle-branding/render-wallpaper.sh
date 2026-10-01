#!/bin/sh
# Kettle Linux wallpaper: the kettle as a faint ghost on pure black. Mostly-black keeps OLED
# panels (the Thor's) cool and their pixels off, and the logo is dim enough that a desktop left
# open doesn't burn it in. Usage: render-wallpaper.sh <kettle.svg> <width> <height> <out.png>
set -eu
art=$1 w=$2 h=$3 out=$4
# the kettle a third of the screen's shorter side, the drawing (about x 42-242, y 68-218 in
# kettle.svg's 256x256 box) centred
s=$(((w < h ? w : h) / 3))
x=$((w / 2 - 142 * s / 256)) y=$((h / 2 - 143 * s / 256))
# kettle.svg's contents without its own <svg> element, scaled from its 256x256 box
body=$(sed '1d;$d' "$art")
cat >"$out.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="$w" height="$h" viewBox="0 0 $w $h">
  <rect width="$w" height="$h" fill="#000"/>
  <g opacity="0.1" transform="translate($x $y) scale($s) scale(0.00390625)">
$body
  </g>
</svg>
EOF
rsvg-convert "$out.svg" -o "$out"
rm "$out.svg"
