#!/bin/bash
# Build + install the RTL8812AU driver for the ALFA AWUS036AC (needs internet once).
# The driver is NOT in the repos and NOT in mainline, so it's a dkms source build
# against the running kernel's headers. ~18 min compile on a Pi Zero 2W.
set -e
sudo apt-get update
sudo apt-get install -y git build-essential dkms bc "linux-headers-$(uname -r)"
rm -rf ~/8812au-20210820
git clone --depth 1 https://github.com/morrownr/8812au-20210820.git ~/8812au-20210820
cd ~/8812au-20210820
sudo dkms add .                 # registers rtl8812au/<ver>
V=$(dkms status | awk -F', ' '/rtl8812au/{print $1; exit}')   # e.g. rtl8812au/5.13.6-23
sudo dkms build  "$V" -k "$(uname -r)"
sudo dkms install "$V" -k "$(uname -r)"
sudo modprobe 8812au
echo "Done. New radio should appear (see deploy/net/10-wlan-alfa.link to pin it as wlan0)."
