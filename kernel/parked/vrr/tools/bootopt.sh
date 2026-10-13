#!/bin/bash
# usage: bootopt.sh "kernel options"   test options for the next boots
#        bootopt.sh off                back to the image's own command line
set -e
F=/etc/kettle/boot.conf
if [ "$1" = off ]; then
  rm -f $F $F.before-vrr
  rmdir /etc/kettle 2>/dev/null || true
else
  mkdir -p /etc/kettle
  printf '# VRR test (temporary): bootopt.sh off undoes it\nCMDLINE="$CMDLINE %s"\n' "$1" > $F
  cat $F
fi
update-grub | tail -1
grep -o 'linux /boot/Image [^\n]*' /efi/EFI/steamos/grub.cfg | head -1 | tr ' ' '\n' | grep -E 'icna|ch13726a|systemd.unit' || echo "(no test options in grub.cfg)"
