#!/bin/bash
# Stage 2: switch eth0 to the static SDR segment (192.168.99.1) for field use.
# Run this ONCE you've moved eth0 off the setup router and onto the SDR.
#
# AFTER THIS: eth0 has no internet; manage the box via the HaphazardTAK AP
# (http://192.168.10.1). The SDR (192.168.99.234, gateway 192.168.99.1) is
# reachable, and CoT/gRPC/SAPIENT relay through the Pi per the active mode.
set -e
SRC="$HOME/HaphazardNet"
sudo cp "$SRC"/deploy/net/10-eth0.network /etc/systemd/network/
printf '[keyfile]\nunmanaged-devices=interface-name:wlan0;interface-name:eth0\n' \
  | sudo tee /etc/NetworkManager/conf.d/99-unmanage.conf >/dev/null
sudo systemctl reload NetworkManager || sudo systemctl restart NetworkManager
sudo systemctl restart systemd-networkd
sleep 3
echo "eth0 now: $(ip -br addr show eth0)"
echo "Done — eth0 on the SDR segment (192.168.99.1). Manage via the AP at 192.168.10.1."
