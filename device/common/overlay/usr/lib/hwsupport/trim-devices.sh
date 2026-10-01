#!/bin/sh
# Kettle Linux: trim the mounted filesystems that support it, run by steamos-manager's
# TrimDevices (what fstrim.service does).
exec fstrim --listed-in /etc/fstab:/proc/self/mountinfo --verbose --quiet-unsupported
