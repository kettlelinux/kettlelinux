#!/bin/bash
exec >/tmp/vrr-idle.log 2>&1
systemctl stop sddm
sleep 3
/tmp/vrr-probe DSI-1 /tmp/vrr-idle.csv 6 idle ${1:-}
echo "exit $?"
dmesg | grep -iE 'variable refresh|intf[0-9]|dsi.*err|dpu.*err' | tail -10
systemctl start sddm
