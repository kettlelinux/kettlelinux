#!/bin/bash
set -e
rm -f /etc/kettle/boot.conf
[ -f /etc/kettle/boot.conf.before-vrr ] && mv /etc/kettle/boot.conf.before-vrr /etc/kettle/boot.conf
update-grub
