#!/bin/bash
# usage: run-top.sh WHAT [args...]   (WHAT: static, idle, dynamic; extra args passed through)
exec >/home/kettle/update/vrr-top.log 2>&1
systemctl stop sddm
sleep 3
/home/kettle/update/vrr-probe DSI-2 /home/kettle/update/top.csv "$@"
echo "exit $?"
dmesg | grep -iE 'variable refresh|icna35xx|dpu.*(err|fail|timeout)|dsi.*(err|fail|timeout)|underrun' | tail -15
systemctl start sddm
echo done
