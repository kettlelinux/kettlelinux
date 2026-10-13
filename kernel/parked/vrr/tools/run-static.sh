#!/bin/bash
# Stops the game session, runs vrr-probe on the bottom panel, restarts it.
exec >/tmp/vrr-run.log 2>&1
systemctl stop sddm
sleep 3
/tmp/vrr-probe DSI-1 /tmp/vrr-static.csv 8 all
echo "exit $?"
dmesg | tail -20 | grep -iE 'dsi|dpu|msm|drm' 
systemctl start sddm
