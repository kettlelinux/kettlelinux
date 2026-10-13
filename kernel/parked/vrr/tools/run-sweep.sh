#!/bin/bash
exec >/home/kettle/update/vrr-sweep.log 2>&1
systemctl stop sddm
sleep 3
VRR_STATIC_HZ=55,54,53,52,51 /home/kettle/update/vrr-probe DSI-1 /home/kettle/update/sweep.csv 12 static
dmesg | grep -iE 'dpu.*(err|fail|timeout)|dsi.*(err|fail|timeout)|underrun' | tail -10
systemctl start sddm
echo done
