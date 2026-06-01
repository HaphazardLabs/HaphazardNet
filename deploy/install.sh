#!/bin/bash
# HaphazardNet one-shot installer. Run ON THE PI as root:  sudo ./deploy/install.sh
#
# Needs internet ONCE (apt + pip). Easiest: plug the Pi's Ethernet into your
# home router for this install, then move it back to the offline SDR/Dell link.
# After install it never needs internet again.
#
# Set the AP WiFi password (the repo ships a CHANGEME placeholder):
#   sudo AP_PASSPHRASE='your-wifi-pass' ./deploy/install.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/haphazardnet
say() { echo -e "\n=== $* ==="; }

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }

say "Setting hostname -> haphazardnet"
hostnamectl set-hostname haphazardnet 2>/dev/null || true
grep -q haphazardnet /etc/hosts || sed -i 's/raspberrypi/haphazardnet/g' /etc/hosts 2>/dev/null || true

say "Checking internet (needed for apt/pip)"
if ! timeout 8 apt-get update -qq 2>/dev/null; then
  echo "WARNING: apt update failed — no internet? Plug into your router and re-run."
fi

say "Installing packages"
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  hostapd dnsmasq nftables python3-venv i2c-tools

say "Installing taky into a venv (/opt/taky/venv)"
python3 -m venv /opt/taky/venv
/opt/taky/venv/bin/pip install --upgrade pip
# taky 0.10 imports pkg_resources -> needs setuptools<81 (82+ removed it)
/opt/taky/venv/bin/pip install 'setuptools<81' || echo "WARN: setuptools install failed"
/opt/taky/venv/bin/pip install taky || echo "WARN: taky pip install failed (need internet)"
mkdir -p /var/taky   # taky (runs as root) wants this for its management socket

say "Enabling i2c-dev (creates /dev/i2c-1 for the UPS HAT INA219)"
echo i2c-dev > /etc/modules-load.d/i2c-dev.conf
modprobe i2c-dev 2>/dev/null || true

say "Copying app to $DEST"
mkdir -p "$DEST"
cp -r "$REPO"/{server.py,haphazard,web,relay,deploy} "$DEST"/
chmod +x "$DEST"/deploy/mode/apply-mode.sh "$DEST"/relay/cot_relay.py

say "Creating service user + state dirs"
id haphazardnet &>/dev/null || useradd -r -s /usr/sbin/nologin -G i2c haphazardnet
install -d -o haphazardnet -g haphazardnet /etc/haphazard
install -d -o haphazardnet -g haphazardnet /run/haphazard
[ -f /etc/haphazard/mode.json ] || echo '{"current":"direct","requested":"direct"}' > /etc/haphazard/mode.json
chown haphazardnet:haphazardnet /etc/haphazard/mode.json
# /run is tmpfs (wiped each boot) — recreate /run/haphazard early via tmpfiles
cp "$REPO"/deploy/haphazard-tmpfiles.conf /etc/tmpfiles.d/haphazard.conf
systemd-tmpfiles --create /etc/tmpfiles.d/haphazard.conf

say "Network: hand wlan0+eth0 to systemd-networkd, static IPs"
cp "$REPO"/deploy/net/99-unmanage.conf  /etc/NetworkManager/conf.d/
cp "$REPO"/deploy/net/10-eth0.network   /etc/systemd/network/
cp "$REPO"/deploy/net/20-wlan0.network  /etc/systemd/network/
systemctl enable systemd-networkd
systemctl restart NetworkManager 2>/dev/null || true

say "Access point: hostapd + dnsmasq"
cp "$REPO"/deploy/ap/hostapd.conf /etc/hostapd/hostapd.conf
# AP passphrase is a CHANGEME placeholder in the repo — set the real one here.
if [ -n "${AP_PASSPHRASE:-}" ]; then
  sed -i "s|^wpa_passphrase=.*|wpa_passphrase=${AP_PASSPHRASE}|" /etc/hostapd/hostapd.conf
else
  echo "NOTE: AP password is still 'CHANGEME' — set it via /etc/hostapd/hostapd.conf or re-run with AP_PASSPHRASE=yourpass"
fi
sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null || true
# Pi Zero 2W boots with WLAN rfkill soft-blocked -> hostapd fails. Unblock first.
install -d /etc/systemd/system/hostapd.service.d
cp "$REPO"/deploy/ap/hostapd-rfkill.conf /etc/systemd/system/hostapd.service.d/rfkill.conf
cp "$REPO"/deploy/ap/dnsmasq.conf /etc/dnsmasq.d/haphazardnet.conf
systemctl unmask hostapd          # RPi OS masks hostapd by default
systemctl enable hostapd dnsmasq

say "taky config + service"
install -d /etc/taky
[ -f /etc/taky/taky.conf ] || cp "$REPO"/deploy/taky/taky.conf /etc/taky/taky.conf
cp "$REPO"/deploy/taky/taky.service /etc/systemd/system/

say "Mode applier + relay + panel services"
cp "$REPO"/deploy/mode/nft-haphazard.conf        /etc/haphazard/
cp "$REPO"/deploy/mode/haphazard-mode.service    /etc/systemd/system/
cp "$REPO"/deploy/mode/haphazard-mode.path       /etc/systemd/system/
cp "$REPO"/deploy/mode/haphazard-cot-broadcast.service /etc/systemd/system/
cp "$REPO"/deploy/mode/haphazard-cot-inject.service    /etc/systemd/system/
cp "$REPO"/deploy/mode/haphazard-roster.service        /etc/systemd/system/
cp "$REPO"/deploy/mode/haphazard-timesync.service      /etc/systemd/system/
cp "$REPO"/deploy/haphazardnet-panel.service     /etc/systemd/system/
# let the panel user power off (slide-to-confirm Shutdown button) — only that
install -m440 "$REPO"/deploy/shutdown-sudoers     /etc/sudoers.d/haphazardnet-shutdown

say "Enabling services"
systemctl daemon-reload
systemctl enable haphazard-mode.service haphazard-mode.path haphazardnet-panel.service

say "DONE. Reboot to bring it all up:  sudo reboot"
echo "After reboot: join WiFi 'HaphazardTAK' (the password you set), open http://192.168.10.1"
echo "Mode starts in DIRECT. Switch to NET from the panel."
