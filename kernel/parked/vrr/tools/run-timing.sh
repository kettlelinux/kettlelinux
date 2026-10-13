#!/bin/bash
exec >/home/kettle/update/vrr-timing.log 2>&1
systemctl stop sddm
sleep 3
echo "### 60 Hz mode"
VRR_STATIC_HZ= VRR_MODE_HZ=60 /home/kettle/update/vrr-probe DSI-2 /home/kettle/update/t60.csv 15 static
echo "### 120 Hz, VFP 76"
VRR_STATIC_HZ= VRR_MODE_VFP=76 /home/kettle/update/vrr-probe DSI-2 /home/kettle/update/t120.csv 15 static
dmesg | grep -iE 'dsi.*(err|fail|timeout)|dpu.*(err|fail|timeout)|underrun' | tail -5
systemctl start sddm
echo done
