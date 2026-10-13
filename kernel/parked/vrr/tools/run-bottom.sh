#!/bin/bash
# usage: run-bottom.sh SECONDS [static|idle|dynamic] [vrr] ...   (env passed through)
exec >/home/kettle/update/vrr-bottom.log 2>&1
systemctl stop sddm
sleep 3
/home/kettle/update/vrr-probe DSI-1 /home/kettle/update/bottom.csv "$@"
echo "exit $?"
dmesg | grep -iE 'variable refresh|dsi.*(err|fail|timeout)|dpu.*(err|fail|timeout)|underrun' | tail -8
systemctl start sddm
echo done
