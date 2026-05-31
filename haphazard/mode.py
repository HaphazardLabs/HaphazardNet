"""
Operating-mode state for HaphazardNet.

Two modes (offline field kit, no internet uplink):

  direct : Bridge-only. taky OFF. SDR pushes CoT/SAPIENT/gRPC straight through
           the Pi to a single connected device. Lowest RAM/latency, solo op.

  net    : taky CoT server ON (:8087), multi-user. A Pi-side relay injects the
           SDR's CoT into taky so every connected user shares one picture.
           gRPC/SAPIENT control still targets one designated operator device.

The web UI (unprivileged) only WRITES the desired mode here. A root systemd
path-unit (deploy/haphazard-mode.*) watches the file and runs the idempotent
apply script that rewrites hostapd/dnsmasq/nftables and (re)starts taky.
State persists across reboot, mirroring the ESP32's NVS "mode" key.
"""

import json
import os
import time

STATE_DIR = "/etc/haphazard"
STATE_FILE = os.path.join(STATE_DIR, "mode.json")
# dev fallback when /etc/haphazard isn't writable (running off-Pi)
_DEV_FILE = os.path.join(os.path.dirname(__file__), "..", "mode.local.json")

MODES = {
    "direct": {
        "id": "direct",
        "label": "DIRECT",
        "tagline": "SDR → one device · server off",
        "taky": False,
    },
    "net": {
        "id": "net",
        "label": "NET",
        "tagline": "TAK server · multi-user shared picture",
        "taky": True,
    },
}
DEFAULT_MODE = "direct"


def _path():
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        if os.access(STATE_DIR, os.W_OK):
            return STATE_FILE
    except Exception:
        pass
    return os.path.abspath(_DEV_FILE)


def get():
    """Return {current, requested, modes, applied_ts}. Never raises."""
    state = {"current": DEFAULT_MODE, "requested": None, "applied_ts": None}
    for p in (STATE_FILE, os.path.abspath(_DEV_FILE)):
        try:
            with open(p) as f:
                state.update(json.load(f))
                break
        except Exception:
            continue
    state["modes"] = MODES
    return state


def request(mode_id):
    """Record a mode-change request for the root applier. Returns the new state."""
    if mode_id not in MODES:
        raise ValueError(f"unknown mode: {mode_id}")
    state = get()
    payload = {
        "current": state.get("current", DEFAULT_MODE),
        "requested": mode_id,
        "requested_ts": int(time.time()),
        "applied_ts": state.get("applied_ts"),
    }
    p = _path()
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, p)  # atomic; the path-unit fires on this
    return get()
