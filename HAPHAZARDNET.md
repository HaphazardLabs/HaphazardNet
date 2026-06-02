# HaphazardNet — Build & Operations Manual

> **HaphazardNet**, brought to you by **HaphazardLabs.**
> A single-box, offline TAK field kit on a Raspberry Pi Zero 2W. It collapses the
> old Pi 5 TAK server *and* the ESP32 SDR bridge into one battery-powered device:
> a WiFi access point, a lightweight CoT server, and an SDR→ATAK bridge, switchable
> between two operating modes from a captive-portal web panel.

Status: **deployed and verified working** (2026-05-31). AP broadcasting, panel live,
Direct↔Net switching confirmed, taky serving CoT, a real client (Galaxy S24) joined
and appeared in the panel. Outstanding: UPS battery chip not seated on I2C (see §10).

---

## 1. What it does

| Capability | How |
|---|---|
| WiFi access point for field devices | `hostapd` on the onboard radio (`wlan0`), SSID `HaphazardTAK` |
| Lightweight TAK / CoT server | `taky` 0.10 on TCP `:8087` (Net mode) |
| SDR → ATAK sensor bridge | `cot_relay.py` over the wired `eth0` SDR segment |
| Web control panel | stdlib Python server on `:80`, HaphazardLabs-themed |
| Two operating modes | `Direct` (bridge only) / `Net` (multi-user server) |
| Battery-powered, untethered | SEENGREAT UPS HAT (A) |

There is **no internet uplink, ever** — the kit is fully standalone in the field.
(Internet is needed *once*, at install time, to fetch packages — see §7.)

---

## 2. Hardware

- **Raspberry Pi Zero 2W** — quad Cortex-A53 @ 1 GHz, **512 MB RAM** (the defining constraint — too small for real TAK Server, hence `taky`).
- **Waveshare ETH/USB HUB HAT** — adds a wired RJ45 (`eth0`, a Realtek RTL815x USB-Ethernet, MAC `00:e0:4c:36:0b:94`) plus a 3-port USB hub, all on the Zero's single USB 2.0 line. `eth0` carries the SDR segment.
- **SunFounder PiPower 5 UPS** — 5 V/5 A out, USB-C PD in, 2S pack. Powers the Pi + hub HAT + ALFA (fixed the brownouts the original SEENGREAT couldn't). Battery telemetry via its MCU on **I2C bus 1 at `0x5c`** (little-endian regs: r8 batt mV, r10 mA signed, r12 %, r18 charging). Needs SunFounder's `dtoverlay=sunfounder-pipower5` (run their installer) **and the PiPower 5 sitting directly on the GPIO** — a HAT between it and the Pi that doesn't pass GPIO 2/3 leaves the bus empty.
- **ALFA AWUS036AC** (RTL8812AU) — the AP radio (range). Driver built from source (`deploy/alfa-driver.sh`); pinned to `wlan0` by MAC; onboard radio → `wlan1` (spare).
- *(Planned)* Inland ILI9486 3.5" SPI TFT status screen; USB-WiFi dongle for range + a future Mesh mode.

**Power is not optional plumbing.** The Pi Zero 2W + the ETH/USB hub HAT draw more than the UPS battery alone can deliver during boot — on battery only it browns out and boot-loops. **Keep the UPS plugged into a solid 5 V / ≥3 A wall source**, especially during setup.

---

## 3. Software stack

- OS: **Raspberry Pi OS Lite (64-bit), Bookworm** — kernel `6.12.75+rpt-rpi-v8 aarch64`.
- Networking: **NetworkManager** (for general use) with `wlan0`+`eth0` handed to **systemd-networkd** for static IPs; `hostapd` + `dnsmasq` for the AP; `nftables` for NAT.
- TAK server: **taky 0.10** in a venv at `/opt/taky/venv` (plain TCP CoT, no TLS).
- Panel + relay: **pure Python stdlib** (no pip deps) so they run on the offline box. App lives at `/opt/haphazardnet`.
- I2C: `i2c-dev` kernel module (for the UPS INA219).

---

## 4. Network topology & addressing

**Field configuration (current, after `stage2-field.sh`):**

```
        HaphazardTAK WiFi (AP)                 wired SDR segment
   ATAK/WinTAK devices  ───────►  wlan0        eth0  ◄───────  SDR
   192.168.10.100-200            192.168.10.1  192.168.99.1    192.168.99.234
                                   (Pi)          (Pi)          gw 192.168.99.1
                                        │  Pi forwards + NATs  │
                                        └──────────────────────┘
```

| Interface | Address | Role |
|---|---|---|
| `wlan0` | `192.168.10.1/24` | AP `HaphazardTAK`; DHCP `.100–.200`; the Pi is clients' gateway + DNS |
| `eth0`  | `192.168.99.1/24` | SDR segment; the Pi is the SDR's gateway |

- **SDR:** `192.168.99.234` (gateway `192.168.99.1`).
- AP clients reach the SDR by its IP (`http://192.168.99.234`, gRPC `:8000`) — the Pi forwards + masquerades (`nft-haphazard.conf`), so no client-side routes are needed (the Pi is their default gateway).
- **No internet** in field config. During *setup*, `eth0` is temporarily on a home router for DHCP/internet (see §7).

**Reaching the box for management:**
- Field: join WiFi `HaphazardTAK` → `http://192.168.10.1`.
- For maintenance/SSH: move `eth0` to a router + cold-cycle → it gets DHCP again; SSH by key as `haphazardlabs`.

---

## 5. Operating modes

Mode is stored in `/etc/haphazard/mode.json` and applied by the mode applier (§6).
Switch it from the panel (Mode card) or `POST /api/mode {"mode":"..."}`.

### Direct — bridge only, one device
- `taky` **off**. Lowest RAM/latency. For a solo operator.
- SDR CoT arrives on `eth0:4242` → `cot_relay.py --broadcast` rebroadcasts it to the AP broadcast `192.168.10.255:4242` so the connected device receives it.
- gRPC/SAPIENT and the SDR web UI are reached directly at `192.168.99.234` through the Pi's NAT.

### Net — multi-user TAK server
- `taky` **on** (`:8087`). Multiple devices connect and share one picture.
- SDR CoT arrives on `eth0:4242` → `cot_relay.py --inject` forwards it into taky over TCP, so **every** connected user sees the SDR tracks *and* each other.
- **Stream nuance:** CoT fans out to everyone via taky. gRPC (SDR plugin control) and SAPIENT are inherently point-to-point — they target **one designated operator device**, not all users.

---

## 6. Services & files

App root `/opt/haphazardnet` (mirror of this repo). State in `/etc/haphazard`.

| systemd unit | Purpose |
|---|---|
| `hostapd` | AP on `wlan0` (`/etc/hostapd/hostapd.conf`) |
| `dnsmasq` | DHCP + captive-portal DNS on `wlan0` (`/etc/dnsmasq.d/haphazardnet.conf`) |
| `systemd-networkd` | static IPs (`/etc/systemd/network/{10-eth0,20-wlan0}.network`) |
| `haphazardnet-panel` | web panel, `:80`, runs as user `haphazardnet` (group `i2c`, `CAP_NET_BIND_SERVICE`) |
| `haphazard-mode.path` | watches `/etc/haphazard/mode.json` |
| `haphazard-mode.service` | runs `apply-mode.sh` on boot + every mode change |
| `haphazard-cot-broadcast` | SDR CoT → AP broadcast (Direct) |
| `haphazard-cot-inject` | SDR CoT → taky (Net) |
| `haphazard-roster` | polls `takyctl status` → writes callsigns.json (Net) |
| `haphazard-timesync` | sets the clock from connected devices' CoT time (Net) |
| `taky` | CoT server, venv at `/opt/taky/venv`, config `/etc/taky/taky.conf` |

**Clock (no RTC, no internet):** `haphazard-timesync` taps taky's CoT stream and
reads the device-supplied `<event time="…Z">` (ATAK clients are GPS/cell-synced),
syncing the Pi's clock to the **newest** event time when it drifts past 10 s. So
any connected TAK device keeps the kit on time — "time over CoT." Net mode only
(devices must be talking to taky); it locks on within a device's report interval.

**Callsigns:** in Net mode `haphazard-roster` runs `takyctl status` (taky's client
table — the only place the IP↔callsign map lives, since CoT contact endpoints are
server-routed) and writes `ip -> {callsign,uid}` to `/run/haphazard/callsigns.json`,
which `clients.py` merges so each device shows its ATAK callsign.

**Mode applier flow:** panel (unprivileged) writes `mode.json` → `haphazard-mode.path` fires → `haphazard-mode.service` runs `apply-mode.sh` as root → it sets `ip_forward`, loads `nft-haphazard.conf`, ensures `hostapd`/`dnsmasq`, then toggles `taky` + the relay for the chosen mode and writes `current` back.

**Panel API:** `GET /api/status` (mode + battery + system), `GET /api/clients` (who's on the net), `GET|POST /api/mode`, `POST /api/shutdown`, `POST /api/reboot`. OS captive-portal probes 302 to `/`.

**Power controls** (bottom of the panel): **Reboot** (amber) above **Shutdown** (red). Each is two-step — tap to arm, then **slide to confirm** (so it can't fire by accident; touch + mouse). They `POST` `/api/reboot` / `/api/shutdown`; the panel replies, then runs `sudo systemctl reboot|poweroff` 2 s later. The unprivileged panel user is granted *only* those two commands in `/etc/sudoers.d/haphazardnet-shutdown` (`deploy/shutdown-sudoers`). On shutdown, wait for the activity LED to stop before cutting power; on reboot, the AP drops briefly (eth0/SDR may need a cold cycle, but `wlan0` comes back on its own). Battery is read from the INA219 over raw `/dev/i2c-1` (`haphazard/battery.py`); if the chip is absent it returns simulated data flagged `mock:true`.

**Reference / credentials:**
- Hostname `haphazardnet`; user `haphazardlabs` / `CHANGEME`; passwordless sudo (`/etc/sudoers.d/010-haphazard`); SSH key installed.
- AP SSID `HaphazardTAK` / `CHANGEME`.

---

## 7. Deploying from scratch

### 7.1 Image the card (Raspberry Pi Imager)
- **Raspberry Pi OS Lite (64-bit)**.
- In **Edit Settings**: hostname `haphazardnet`; user `haphazardlabs`/`CHANGEME`; **enable SSH with your public key**; set WiFi country (hostapd needs the regdom).
- *Headless gotcha:* if the user account doesn't get created (SSH says "valid user not set up", login refused), write `userconf.txt` to the boot partition: `printf 'haphazardlabs:%s\n' "$(openssl passwd -6 'CHANGEME')" > /boot/firmware/userconf.txt`, plus an empty `ssh` file. Enable interfaces too: `dtparam=i2c_arm=on` and `dtparam=spi=on` in `config.txt`.

### 7.2 First boot (do this on WALL POWER)
- Let it complete its first boot fully (it reboots itself once). On battery alone it browns out — keep it on a 5 V/≥3 A wall source.
- The USB-Ethernet adapter only enumerates on a **cold** boot; after the first-boot auto-reboot it may be dead — **cold power-cycle once** to bring `eth0` up.

### 7.3 Install (needs internet ONCE)
Plug the Pi's RJ45 into your **home router** (DHCP + internet), SSH in, then:
```bash
# copy the repo to the Pi, then:
sudo /opt/haphazardnet/deploy/install.sh     # or run from the repo dir
```
`install.sh` sets hostname, installs `hostapd dnsmasq nftables i2c-tools` + `taky` (with `setuptools<81`), enables `i2c-dev`, deploys configs/units, and enables everything.

> Two-stage alternative used in the field build: `deploy/stage1-online.sh` brings the AP up on `wlan0` while **leaving `eth0` on the router** (so SSH survives), then `deploy/stage2-field.sh` switches `eth0` to the SDR segment when you're ready to deploy.

### 7.4 Go to field
```bash
sudo /opt/haphazardnet/deploy/stage2-field.sh   # eth0 -> 192.168.99.1
```
After this, `eth0` is the SDR segment (no internet); manage via the AP at `192.168.10.1`. Plug the SDR into the Pi's RJ45.

---

## 8. Operating the kit

1. Power on (wall or charged UPS). Wait ~1–2 min.
2. On any device, join WiFi **`HaphazardTAK`** (`CHANGEME`).
3. Open **`http://192.168.10.1`** — the panel shows status, battery, who's on the net, and the **Mode** switch.
4. **Direct**: point one ATAK device at the kit; SDR CoT is rebroadcast to it. **Net**: multiple devices connect to taky at `192.168.10.1:8087` and share the picture; SDR feeds in automatically.
5. Reach the SDR directly at `http://192.168.99.234` (web) / `:8000` (gRPC) from any AP client.

---

## 9. Troubleshooting (everything we actually hit)

| Symptom | Cause | Fix |
|---|---|---|
| Boot loops / hangs, "stuck" with blinking LED | UPS **battery alone** can't power Pi + ETH HAT | Plug UPS into a 5 V/≥3 A wall source |
| `eth0` dead after a reboot (carrier up, no traffic) | USB-Ethernet doesn't re-enumerate on **soft** reboot | **Cold** power-cycle; prefer managing over the AP (`wlan0` survives reboots) |
| SSH "Connection refused" on a booted Pi | `sshd` not enabled | empty `ssh` file on boot partition |
| SSH "valid user not set up" / password rejected | Imager didn't create the user | write `userconf.txt` (see §7.1) |
| Can't find the Pi on the subnet | laptop on a **VLAN** (`192.168.4.x`), Pi on main LAN | use the router's client list / mDNS (`raspberrypi.local`); routing across the VLAN works |
| Panel battery shows simulated | INA219 not on I2C | `i2cdetect -y 1` should show `0x43`; if empty, reseat the UPS HAT (see §10) |
| `/dev/i2c-1` missing | `i2c-dev` module not loaded | `/etc/modules-load.d/i2c-dev.conf` = `i2c-dev` (install.sh does this) |
| taky crash-loops, `No module named 'pkg_resources'` | setuptools 82+ removed it | `pip install 'setuptools<81'` into the taky venv |
| taky log: "Unable to open management socket /var/taky/…" | dir missing | `mkdir -p /var/taky` (non-fatal) |
| Mode switch from panel does nothing | `haphazard-mode.service` had `RemainAfterExit=yes` (oneshot no-ops on re-`start`) | remove `RemainAfterExit` (already fixed) |
| **No `HaphazardTAK` AP after a reboot**; `hostapd` restart-loops with `rfkill: WLAN soft blocked` | Pi Zero 2W boots with WLAN rfkill **soft-blocked** | hostapd drop-in `ExecStartPre=/usr/sbin/rfkill unblock wlan` (`deploy/ap/hostapd-rfkill.conf`); applier also unblocks |
| **Panel dead after a reboot**; service fails `226/NAMESPACE`, `/run/haphazard: No such file or directory` | `/run` is tmpfs, wiped each boot; panel needs `/run/haphazard` | `systemd-tmpfiles` rule recreates it each boot (`deploy/haphazard-tmpfiles.conf` → `/etc/tmpfiles.d/`) |

Discovery over the direct Dell↔Pi Ethernet link (no DHCP, IPv6 link-local only):
`ping6 -I <iface> ff02::1%<iface>` then match the Realtek MAC `00:e0:4c…` and
`ssh haphazardlabs@<fe80::…>%<iface>`.

---

## 10. Known issues & future work

- **UPS battery not reading (open):** the SEENGREAT UPS HAT (A) INA219 does not appear on either I2C bus (`i2cdetect` empty on 1 and 2), so the panel battery is simulated. I2C is enabled and `/dev/i2c-1` works — the chip just isn't responding, i.e. a **physical seating issue** (GPIO 2/3 contact, likely the HAT stacking with the ETH/USB hub HAT). Reseat / restack the HATs and confirm `0x43` appears.
- **USB-Ethernet soft-reboot quirk (open):** SDR link drops on a soft reboot until a cold cycle. Candidate fixes: a USB power/reset quirk, or a `udev`/systemd action to rebind the adapter at boot. Manage via the AP to avoid relying on it.
- **taky config:** validated as a plain `:8087` CoT server; revisit `/etc/taky/taky.conf` if a future taky version changes the schema.
- **User list callsigns:** the panel maps the SDR feed's callsign; mapping ATAK client callsigns→IPs is a future enhancement (currently shows hostname/IP/TAK-connected).
- **Planned:** GPIO button to cycle modes + TFT status mirror; USB-WiFi dongle for range and a third **Mesh/Link** mode chaining multiple kits.

---

## 11. Repository layout

```
server.py              stdlib web panel + API + captive redirects
haphazard/             battery.py (raw I2C INA219) · clients.py · mode.py · sysinfo.py
relay/cot_relay.py     SDR CoT relay: --broadcast (Direct) / --inject (Net)
web/                   index.html · haphazard.css · app.js · logo.png  (themed UI)
deploy/
  install.sh           one-shot installer (needs internet once)
  stage1-online.sh     bring up AP, keep eth0 on the router (preserves SSH)
  stage2-field.sh      switch eth0 to the SDR segment (field)
  ap/                  hostapd.conf · dnsmasq.conf
  net/                 10-eth0.network · 20-wlan0.network · 99-unmanage.conf
  mode/                apply-mode.sh · haphazard-mode.{service,path} ·
                       haphazard-cot-{broadcast,inject}.service · nft-haphazard.conf
  taky/                taky.conf · taky.service
  haphazardnet-panel.service
README.md              quickstart
HAPHAZARDNET.md        this manual
```
