"""
Who's on the net.

A device counts as "on the net" if it shows up in ANY of:
  1. dnsmasq DHCP leases        -> IP, MAC, hostname  (DHCP clients)
  2. the ARP/neighbor table     -> IP, MAC            (catches STATIC-IP devices,
                                                        e.g. ATAK on 192.168.10.123)
  3. established TCP to taky     -> who's actually on the CoT server (:8087)
  4. callsigns.json             -> IP -> ATAK callsign, written by the CoT tap

Relying on leases alone misses statically-addressed devices, so we union all
four. All reads are unprivileged. Off-Pi (no leases file) returns mock users.
"""

import json
import subprocess

LEASES_FILE = "/var/lib/misc/dnsmasq.leases"
CALLSIGNS_FILE = "/run/haphazard/callsigns.json"
TAK_PORT = 8087
SDR_IP = "192.168.99.234"          # the SDR feed (tagged separately)
AP_PREFIX = "192.168.10."          # AP client subnet
SELF_IPS = {"192.168.10.1", "192.168.99.1"}   # the Pi's own addresses


def _read_leases():
    """Parse dnsmasq.leases -> {ip: {mac, hostname}}. None if the file is absent."""
    out = {}
    try:
        with open(LEASES_FILE) as f:
            for line in f:
                p = line.split()
                if len(p) >= 4:
                    out[p[2]] = {"mac": p[1],
                                 "hostname": None if p[3] == "*" else p[3]}
    except FileNotFoundError:
        return None  # signals "not on Pi" -> mock
    except Exception:
        return {}
    return out


def _neighbors():
    """`ip neigh` -> {ip: mac} for live entries (unprivileged). Catches static IPs."""
    out = {}
    try:
        res = subprocess.run(["ip", "neigh", "show"],
                             capture_output=True, text=True, timeout=3)
        for line in res.stdout.splitlines():
            toks = line.split()
            if not toks or "lladdr" not in toks:
                continue
            state = toks[-1].upper()
            if state not in ("REACHABLE", "STALE", "DELAY", "PROBE"):
                continue
            ip = toks[0]
            out[ip] = toks[toks.index("lladdr") + 1]
    except Exception:
        pass
    return out


def _tak_connected_ips():
    ips = set()
    try:
        res = subprocess.run(
            ["ss", "-tnH", "state", "established", f"( sport = :{TAK_PORT} )"],
            capture_output=True, text=True, timeout=3,
        )
        for line in res.stdout.splitlines():
            cols = line.split()
            if len(cols) >= 4:
                ips.add(cols[3].rsplit(":", 1)[0].strip("[]"))
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
        {"callsign": "SDR", "hostname": "sensor", "ip": SDR_IP,
         "mac": "00:1a:2b:3c:4d:5e", "tak_connected": False, "is_sdr": True},
    ]


def list_clients():
    """Union of leases + neighbors + taky conns + callsigns. Mock off-Pi."""
    leases = _read_leases()
    if leases is None:
        return _mock()

    neigh = _neighbors()
    tak_ips = _tak_connected_ips()
    callsigns = _callsigns()

    # every IP we've seen from any source, then keep AP clients + the SDR feed
    candidates = set(leases) | set(neigh) | set(tak_ips) | set(callsigns)
    users = []
    for ip in candidates:
        if ip in SELF_IPS:
            continue
        if not (ip.startswith(AP_PREFIX) or ip == SDR_IP):
            continue
        lease = leases.get(ip, {})
        cs = callsigns.get(ip)
        users.append({
            "callsign": (cs.get("callsign") if isinstance(cs, dict) else cs),
            "hostname": lease.get("hostname"),
            "ip": ip,
            "mac": lease.get("mac") or neigh.get(ip),
            "tak_connected": ip in tak_ips,
            "is_sdr": ip == SDR_IP,
        })
    # TAK-connected first, then by IP
    users.sort(key=lambda u: (not u["tak_connected"], u["ip"]))
    return users


def count(users=None):
    users = users if users is not None else list_clients()
    return {
        "total": len(users),
        "tak_connected": sum(1 for u in users if u["tak_connected"]),
    }
