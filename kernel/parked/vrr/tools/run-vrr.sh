#!/bin/bash
exec >/home/kettle/update/vrr-test.log 2>&1
systemctl stop sddm
sleep 3
echo "### idle, VRR off"
/home/kettle/update/vrr-probe DSI-1 /home/kettle/update/idle-off.csv 6 idle
echo "### idle, VRR on"
/home/kettle/update/vrr-probe DSI-1 /home/kettle/update/idle-on.csv 6 idle vrr
echo "### dynamic, VRR on"
/home/kettle/update/vrr-probe DSI-1 /home/kettle/update/dyn-on.csv 8 dynamic vrr
echo "### dmesg"
dmesg | grep -iE 'variable refresh|intf[0-9]:|dpu.*(err|fail|timeout)|dsi.*(err|fail|timeout)|underrun' | tail -20
systemctl start sddm
echo done
