"""
Who's on the net.

Combines three sources to describe each connected user:
  1. dnsmasq DHCP leases   -> IP, MAC, hostname  (who joined the AP)
  2. established TCP conns  -> who is actually connected to taky (:8087)
  3. callsigns.json         -> IP -> ATAK callsign, written by the CoT tap/relay

Off-Pi (no leases file) it returns mock users so the UI renders.
"""

import json
import os
import subprocess
import time

LEASES_FILE = "/var/lib/misc/dnsmasq.leases"
CALLSIGNS_FILE = "/run/haphazard/callsigns.json"  # ip -> {"callsign":..., "ts":...}
TAK_PORT = 8087


def _read_leases():
    """Parse dnsmasq.leases -> [{expiry, mac, ip, hostname}]. Empty list if absent."""
    out = []
    try:
        with open(LEASES_FILE) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    out.append({
                        "expiry": int(parts[0]) if parts[0].isdigit() else None,
                        "mac": parts[1],
                        "ip": parts[2],
                        "hostname": None if parts[3] == "*" else parts[3],
                    })
    except FileNotFoundError:
        return None  # signal "not on Pi" to the caller
    except Exception:
        return []
    return out


def _tak_connected_ips():
    """IPs with an ESTABLISHED TCP connection to the taky CoT port."""
    ips = set()
    try:
        res = subprocess.run(
            ["ss", "-tnH", "state", "established", f"( sport = :{TAK_PORT} )"],
            capture_output=True, text=True, timeout=3,
        )
        for line in res.stdout.splitlines():
            cols = line.split()
            if len(cols) >= 4:
                peer = cols[3]  # ip:port (handles IPv4; strip last :port)
                ip = peer.rsplit(":", 1)[0].strip("[]")
                ips.add(ip)
    except Exception:
        pass
    return ips


def _callsigns():
    try:
        with open(CALLSIGNS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _mock():
    return [
        {"callsign": "WOXOF", "hostname": "rocket-tab", "ip": "192.168.10.123",
         "mac": "ac:3d:cb:ea:f2:22", "tak_connected": True, "is_sdr": False},
        {"callsign": "SLY", "hostname": "sly-pixel", "ip": "192.168.10.131",
         "mac": "de:ad:be:ef:00:11", "tak_connected": True, "is_sdr": False},
        {"callsign": None, "hostname": "lotor-wintak", "ip": "192.168.10.142",
         "mac": "de:ad:be:ef:00:22", "tak_connected": False, "is_sdr": False},
        {"callsign": "SDR", "hostname": "sensor", "ip": "192.168.99.234",
         "mac": "00:1a:2b:3c:4d:5e", "tak_connected": False, "is_sdr": True},
    ]


def list_clients():
    """Return [{callsign, hostname, ip, mac, tak_connected, is_sdr}], mock off-Pi."""
    leases = _read_leases()
    if leases is None:
        return _mock()

    tak_ips = _tak_connected_ips()
    callsigns = _callsigns()
    users = []
    for lease in leases:
        ip = lease["ip"]
        cs = callsigns.get(ip)
        users.append({
            "callsign": (cs or {}).get("callsign") if isinstance(cs, dict) else cs,
            "hostname": lease["hostname"],
            "ip": ip,
            "mac": lease["mac"],
            "tak_connected": ip in tak_ips,
            "is_sdr": ip.startswith("192.168.99."),
        })
    # Sort: TAK-connected first, then by IP
    users.sort(key=lambda u: (not u["tak_connected"], u["ip"]))
    return users


def count(users=None):
    users = users if users is not None else list_clients()
    return {
        "total": len(users),
        "tak_connected": sum(1 for u in users if u["tak_connected"]),
    }
