#!/bin/bash
# usage: regs.sh "r 0a 1" "w 6b 01" ...   one command per argument, prints each result
F=/sys/kernel/debug/dri/0/DSI-1/panel/icna35xx_regs
for c in "$@"; do
  if echo "$c" > $F 2>&1; then cat $F; else echo "$c: failed"; fi
done
