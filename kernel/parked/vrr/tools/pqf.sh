#!/bin/bash
exec >/home/kettle/update/pqf.log 2>&1
F=/sys/kernel/debug/dri/0/DSI-1/panel/icna35xx_regs
r() { echo "$1" > $F 2>/dev/null; cat $F; }
sample() { echo "### $1"; for i in $(seq 1 $2); do echo "r 45 3" > $F 2>/dev/null; echo "$(date +%s%N) $(cat $F)"; done; }
systemctl stop sddm
sleep 8
VRR_ALT=1 VRR_RATES=30 /home/kettle/update/vrr-probe DSI-1 /home/kettle/update/qf.csv 20 dynamic vrr 55 &
P=$!
sleep 2
r "w 69 00"
sample "frames 30 fps, qsync off" 50
r "w 6b 01"; sleep 0.3
sample "frames 30 fps, qsync on" 80
r "w 6b 00"
wait $P
r "w 69 01"
systemctl start sddm
echo done
