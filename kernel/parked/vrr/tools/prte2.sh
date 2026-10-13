#!/bin/bash
exec >/home/kettle/update/prte2.log 2>&1
F=/sys/kernel/debug/dri/0/DSI-1/panel/icna35xx_regs
r() { echo "$1" > $F 2>/dev/null && cat $F || echo "$1: failed"; }
enc=$(grep -l "intf:2 " /sys/kernel/debug/dri/0/encoder-*/status | head -1)
cnt() { grep -o "vsync: *[0-9]*" $enc | grep -o "[0-9]*$"; }
te() { local a=$(cnt); sleep 1; echo "  TE/rd_ptr in 1 s: $(( $(cnt) - a ))"; }
scan() { local mx=0 v s=""; for i in $(seq 1 40); do echo "r 45 3" > $F 2>/dev/null; set -- $(cat $F); v=$(( 0x$3*65536 + 0x$4*256 + 0x$5 )); [ $v -gt $mx ] && mx=$v; [ $i -le 12 ] && s="$s $v"; done; echo "  scanline max $mx (vtotal 2348); first:$s"; }
rte() { local a=$(cnt); for i in $(seq 1 20); do echo "d 32" > $F 2>/dev/null; sleep 0.05; done; echo "  20 x 32h: TE/rd_ptr during $(( $(cnt) - a ))"; }
run() {
  echo "##### $1"
  r "w 69 00"; sleep 0.3; echo "# msync off"; te; scan
  r "w 69 01"; sleep 0.3; echo "# msync on"; te; scan; rte
  r "w 65 84 1b 2c 09 00"; sleep 0.3; echo "# msync on + 65h 7044/2348"; te; scan; rte; r "r 68 2"
  r "w 65 ff 7f 2c 09 00"; sleep 0.3; echo "# msync on + 65h 7fff/2348"; te; scan; rte; r "r 68 2"
  r "w 65 00 00 00 00 00"; r "w 69 01"
}
systemctl stop sddm
sleep 8
/home/kettle/update/vrr-probe DSI-1 /home/kettle/update/rte2.csv 30 idle &
P=$!; sleep 3; run "idle (one frame)"; kill $P; wait $P; sleep 2
VRR_ALT=1 VRR_RATES=30 /home/kettle/update/vrr-probe DSI-1 /home/kettle/update/rte3.csv 30 dynamic vrr 55 &
P=$!; sleep 3; run "frames at 30 fps"; kill $P; wait $P
echo "### errors"; r "r 8f 1"; r "r 05 1"; r "r 0a 1"
dmesg | grep -ciE "kickoff timeout|wait_for_idle"
systemctl start sddm
echo done
