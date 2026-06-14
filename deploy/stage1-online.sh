#!/bin/bash
# Stage 1: deploy everything + bring up the AP on wlan0, WITHOUT touching eth0
# (eth0 stays on the router/DHCP so the SSH session survives). Run on the Pi.
# Stage 2 (later, going to field) switches eth0 to the static SDR segment.
set -e
# Repo root, derived from this script's own location — works regardless of the
# clone's directory name or whether the script is run via sudo (where $HOME=/root).
SRC="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
DEST=/opt/haphazardnet
say(){ echo "=== $* ==="; }

say "Copy app -> $DEST"
sudo mkdir -p "$DEST"
sudo cp -rT "$SRC" "$DEST"
sudo chmod +x "$DEST"/deploy/mode/apply-mode.sh "$DEST"/relay/cot_relay.py

say "Service user + state dirs"
id haphazardnet &>/dev/null || sudo useradd -r -s /usr/sbin/nologin -G i2c haphazardnet
sudo install -d -o haphazardnet -g haphazardnet /etc/haphazard /run/haphazard
[ -f /etc/haphazard/mode.json ] || echo '{"current":"direct","requested":"direct"}' | sudo tee /etc/haphazard/mode.json >/dev/null
sudo chown haphazardnet:haphazardnet /etc/haphazard/mode.json
# /run is tmpfs (wiped each boot). Install the tmpfiles rule so /run/haphazard is
# recreated on EVERY boot — without it the panel comes up now but dies after a
# reboot (systemd ReadWritePaths fails: /run/haphazard missing -> 226/NAMESPACE).
sudo cp "$SRC"/deploy/haphazard-tmpfiles.conf /etc/tmpfiles.d/haphazard.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/haphazard.conf

say "wlan0 -> systemd-networkd (eth0 left on router)"
printf '[keyfile]\nunmanaged-devices=interface-name:wlan0\n' | sudo tee /etc/NetworkManager/conf.d/99-unmanage.conf >/dev/null
sudo cp "$SRC"/deploy/net/20-wlan0.network /etc/systemd/network/
sudo systemctl enable systemd-networkd

say "AP: hostapd + dnsmasq"
sudo cp "$SRC"/deploy/ap/hostapd.conf /etc/hostapd/hostapd.conf
sudo sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null || true
sudo cp "$SRC"/deploy/ap/dnsmasq.conf /etc/dnsmasq.d/haphazardnet.conf
sudo rfkill unblock wlan 2>/dev/null || true
sudo systemctl unmask hostapd
sudo systemctl enable hostapd dnsmasq

say "taky config + service"
sudo install -d /etc/taky
[ -f /etc/taky/taky.conf ] || sudo cp "$SRC"/deploy/taky/taky.conf /etc/taky/taky.conf
sudo cp "$SRC"/deploy/taky/taky.service /etc/systemd/system/

say "nft + mode applier + relay + panel units"
sudo cp "$SRC"/deploy/mode/nft-haphazard.conf /etc/haphazard/
sudo cp "$SRC"/deploy/mode/haphazard-mode.service /etc/systemd/system/
sudo cp "$SRC"/deploy/mode/haphazard-mode.path /etc/systemd/system/
sudo cp "$SRC"/deploy/mode/haphazard-cot-broadcast.service /etc/systemd/system/
sudo cp "$SRC"/deploy/mode/haphazard-cot-inject.service /etc/systemd/system/
sudo cp "$SRC"/deploy/haphazardnet-panel.service /etc/systemd/system/

say "Apply (reload NM so wlan0 releases; eth0 keeps its lease)"
sudo systemctl daemon-reload
sudo systemctl reload NetworkManager || sudo systemctl restart NetworkManager
sudo systemctl restart systemd-networkd
sleep 3
sudo systemctl enable --now haphazardnet-panel.service haphazard-mode.path
sudo systemctl enable haphazard-mode.service   # applies the saved mode at boot
sudo systemctl restart hostapd dnsmasq
sudo systemctl start haphazard-mode.service || true
sleep 2

say "STATUS"
echo "wlan0: $(ip -br addr show wlan0 2>/dev/null)"
echo "eth0:  $(ip -br addr show eth0 2>/dev/null)"
for s in systemd-networkd hostapd dnsmasq haphazardnet-panel; do
  echo "$s: $(systemctl is-active $s)"
done
echo "panel local check:"; curl -s -o /dev/null -w "http %{http_code}\n" http://192.168.10.1/ 2>&1 || echo "panel not answering yet"
