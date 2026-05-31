#!/bin/bash
# HaphazardNet mode applier (runs as root via haphazard-mode.service).
# Reads the desired mode from /etc/haphazard/mode.json (written by the panel),
# brings up the always-on base (AP + NAT), then toggles the per-mode services.
#
#   direct : taky OFF. SDR CoT rebroadcast to the AP for a single device.
#   net    : taky ON (:8087). SDR CoT injected into taky for all users.
#
# Idempotent: safe to run at boot and on every mode.json change.
set -uo pipefail

STATE=/etc/haphazard/mode.json
log() { logger -t haphazard-mode "$*"; echo "haphazard-mode: $*"; }

# --- desired mode (requested wins; fall back to current; default direct) ---
MODE=$(python3 -c "import json;d=json.load(open('$STATE'));print(d.get('requested') or d.get('current') or 'direct')" 2>/dev/null || echo direct)
case "$MODE" in direct|net) ;; *) MODE=direct ;; esac
log "applying mode: $MODE"

# --- always-on base: forwarding, NAT, AP ---
sysctl -wq net.ipv4.ip_forward=1
nft -f /etc/haphazard/nft-haphazard.conf || log "WARN: nft load failed"
/usr/sbin/rfkill unblock wlan 2>/dev/null || true   # WLAN is soft-blocked at boot
systemctl is-active --quiet hostapd || systemctl restart hostapd
systemctl is-active --quiet dnsmasq || systemctl restart dnsmasq

# --- per-mode services ---
if [ "$MODE" = "net" ]; then
  systemctl stop  haphazard-cot-broadcast 2>/dev/null
  systemctl start taky                || log "WARN: taky failed to start"
  systemctl start haphazard-cot-inject || log "WARN: cot-inject failed"
else
  systemctl stop  haphazard-cot-inject 2>/dev/null
  systemctl stop  taky                 2>/dev/null
  systemctl start haphazard-cot-broadcast || log "WARN: cot-broadcast failed"
fi

# --- record what we actually applied (panel reads this back) ---
python3 - "$MODE" <<'PY'
import json, sys, time
p = "/etc/haphazard/mode.json"
try:
    d = json.load(open(p))
except Exception:
    d = {}
d["current"] = sys.argv[1]
d["applied_ts"] = int(time.time())
json.dump(d, open(p, "w"), indent=2)
PY
log "mode $MODE applied"
