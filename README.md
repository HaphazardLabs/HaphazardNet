# HaphazardNet — control panel

> **HaphazardNet**, brought to you by **HaphazardLabs**.
>
> 📖 **Full build & operations manual: [HAPHAZARDNET.md](HAPHAZARDNET.md)** — architecture,
> network topology, modes, deployment from scratch, and the complete troubleshooting catalog.
> This README is the quickstart.

The web control panel + mode switcher for the single-box HaphazardTAK field kit
on a Raspberry Pi Zero 2W (offline, no internet). It collapses the old Pi 5 TAK
kit and the ESP32 SDR bridge into one battery-powered box.

## What it shows
- **Mode** switcher — **DIRECT** (SDR → one device, server off) vs **NET**
  (taky CoT server on, multi-user shared picture).
- **On the Net** — every device on the AP, with ATAK callsign, hostname, IP, and
  whether it's connected to taky. The SDR feed is tagged.
- **Power** — live battery % / voltage / draw / runtime from the SEENGREAT UPS
  HAT (A) INA219 (`i2c 0x43`).
- **System** — taky / AP status, CPU temp, RAM, uptime, load.

HaphazardLabs theme: black / `#39ff14` lime / raccoon, faint CRT scanlines.

## Hardware
- Raspberry Pi Zero 2W (512 MB)
- Waveshare ETH/USB HUB HAT — `eth0` → SDR, plus a USB hub
- SEENGREAT UPS HAT (A) — INA219 @ I2C `0x43`, 3.7 V LiPo (~1500 mAh)
- (later) USB WiFi dongle → range + a future Mesh/Link mode

## Run it (preview, any machine)
No pip deps — pure stdlib, like the HaphazardLabs.com site server.
```bash
cd HaphazardNet
python3 server.py --port 8780        # then open http://localhost:8780
```
Off-Pi it serves **mock** battery + client data (so the UI is fully previewable);
system stats are real. On the Pi it reads the real INA219, dnsmasq leases, and
`ss` connections to taky.

## Deploy on the Pi
```bash
sudo useradd -r -s /usr/sbin/nologin haphazardnet
sudo cp -r . /opt/haphazardnet
sudo pip3 install smbus2            # only dep, only for the UPS HAT
sudo install -d -o haphazardnet /etc/haphazard
sudo cp deploy/haphazardnet-panel.service /etc/systemd/system/
sudo systemctl enable --now haphazardnet-panel
```
The panel binds `:80` via `CAP_NET_BIND_SERVICE` and runs unprivileged.

## API
| Route | Method | Returns |
|---|---|---|
| `/` | GET | the themed UI |
| `/api/status` | GET | `{mode, battery, system}` |
| `/api/clients` | GET | `{clients[], counts}` |
| `/api/mode` | GET | mode state |
| `/api/mode` | POST `{ "mode": "net" }` | requests a switch |
| `/api/shutdown` | POST | safe power-off (slide-to-confirm in the UI) |

OS captive-portal probes (`/generate_204`, `/hotspot-detect.html`, …) 302 to `/`
so phones joining the AP pop straight into the panel.

## Layout
```
server.py              stdlib HTTP server + API + captive redirects
haphazard/
  battery.py           INA219 @ 0x43 (32V/2A cal), mock fallback off-Pi
  clients.py           dnsmasq leases + ss(:8087) + callsigns.json
  mode.py              mode state, atomic write to /etc/haphazard/mode.json
  sysinfo.py           cpu/temp/mem/uptime/load/services (stdlib only)
web/                   index.html · haphazard.css · app.js · logo.png
deploy/                systemd unit(s)
```

## Deploy on the Pi (full bundle)
One-shot installer. **Needs internet once** (apt + pip) — easiest is to plug the
Pi's Ethernet into your home router for the install, then move it back to the
offline SDR/Dell link. After that it never needs internet again.
```bash
sudo ./deploy/install.sh
sudo reboot
```
Then join WiFi **HaphazardTAK** (the password you set via `AP_PASSPHRASE`) and open **http://192.168.10.1**.
Boots in **Direct**; switch to **Net** from the panel.

What `install.sh` sets up:
- `deploy/ap/` — **hostapd** (SSID HaphazardTAK, ch6 2.4GHz) + **dnsmasq** (DHCP +
  captive-portal DNS hijack to the panel).
- `deploy/net/` — systemd-networkd statics: `eth0`=192.168.99.1 (SDR segment,
  matches the SDR's gateway), `wlan0`=192.168.10.1 (AP); NetworkManager unmanages both.
- `deploy/mode/` — the **mode applier**: `haphazard-mode.path` watches
  `/etc/haphazard/mode.json` (what the panel writes) → `apply-mode.sh` toggles
  taky + the relay and loads `nft-haphazard.conf` (bidirectional eth0⇄wlan0 NAT).
- `relay/cot_relay.py` — SDR CoT relay: **--broadcast** (Direct → AP) /
  **--inject** (Net → taky :8087), plus a callsign tap feeding the user list.
- `deploy/taky/` — taky in a venv + plain-CoT config on :8087.

## ⚠ Hardware notes (learned the hard way)
- **Power the UPS from the wall.** The UPS HAT (A) battery *alone* can't run the
  Pi Zero 2W + the ETH/USB hub HAT — it browns out and boot-loops. Keep the UPS
  plugged into a solid 5V/3A source, especially during setup.
- **USB-Ethernet doesn't survive a soft reboot.** The hub HAT's Realtek adapter
  only re-enumerates on a *cold* power-cycle, so after any `reboot` the `eth0`
  (SDR) link drops until power is cycled. The `wlan0` AP is onboard and is fine
  across reboots. (A power/reset quirk fix is TODO.)

## Still to build
- Verify/adjust `taky.conf` against the installed taky version.
- Map ATAK client callsigns→IPs in the user list (currently labels the SDR feed).
- Optional GPIO button to cycle modes + mirror status on the TFT.
- USB-WiFi dongle → range + a future **Mesh/Link** mode.
