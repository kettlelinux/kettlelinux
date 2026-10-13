#!/bin/bash
exec >/home/kettle/update/vrr-static2.log 2>&1
systemctl stop sddm
sleep 3
/home/kettle/update/vrr-probe DSI-1 /home/kettle/update/static2.csv 12 static
dmesg | grep -iE 'dpu.*(err|fail|timeout)|dsi.*(err|fail|timeout)|underrun' | tail -10
systemctl start sddm
echo done
