#!/bin/bash
exec >/home/kettle/update/pscan.log 2>&1
F=/sys/kernel/debug/dri/0/DSI-1/panel/icna35xx_regs
sample() { # label count
  echo "### $1"
  for i in $(seq 1 $2); do echo "r 45 3" > $F 2>/dev/null; echo "$(date +%s%N) $(cat $F)"; done
}
systemctl stop sddm
sleep 8
/home/kettle/update/vrr-probe DSI-1 /home/kettle/update/scan.csv 28 idle &
P=$!
sleep 2
echo "w 69 00" > $F; sample "msync off, idle" 150
echo "w 69 01" > $F; sleep 1; sample "msync on, idle" 150
wait $P
echo "w 69 01" > $F
systemctl start sddm
echo done
