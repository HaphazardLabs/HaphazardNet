#!/usr/bin/env python3
"""
HaphazardNet TAK client roster (Net mode).

Polls `takyctl status` (taky's own client table — the authoritative IP↔callsign
map, since CoT contact endpoints are server-routed `*:-1:stcp`) and writes
ip -> {callsign, uid} into /run/haphazard/callsigns.json, which the panel's
clients.py already merges. This is what labels each device by its ATAK callsign.

Runs as root (the taky management socket is root-owned). Pure stdlib.
"""

import json
import os
import re
import subprocess
import time

CALLSIGNS_FILE = "/run/haphazard/callsigns.json"
TAKYCTL = ["/opt/taky/venv/bin/takyctl", "-c", "/etc/taky/taky.conf", "status"]
INTERVAL = 8        # seconds between polls
STALE = 120         # forget entries not refreshed within 2 min

# row: "WOXOF | ANDROID-a11... | 00h 00m 49s | 192.168.10.123 | 00h 00m 04s"
ROW = re.compile(r"^(.+?)\s*\|\s*(\S+)\s*\|\s*[^|]+\|\s*(\d+\.\d+\.\d+\.\d+)\s*\|")


def poll():
    """Return {ip: {callsign, uid, ts}} from takyctl, or {} on any error."""
    try:
        out = subprocess.run(TAKYCTL, capture_output=True, text=True,
                             timeout=15).stdout
    except Exception:
        return {}
    res = {}
    now = int(time.time())
    for line in out.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        callsign, uid, ip = m.group(1).strip(), m.group(2).strip(), m.group(3)
        if callsign and callsign.lower() != "callsign":
            res[ip] = {"callsign": callsign, "uid": uid, "ts": now}
    return res


def write(table):
    try:
        os.makedirs(os.path.dirname(CALLSIGNS_FILE), exist_ok=True)
        tmp = CALLSIGNS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(table, f)
        os.replace(tmp, CALLSIGNS_FILE)
    except Exception:
        pass


def main():
    while True:
        fresh = poll()
        try:
            table = json.load(open(CALLSIGNS_FILE))
            if not isinstance(table, dict):
                table = {}
        except Exception:
            table = {}
        table.update(fresh)  # refresh taky clients, keep other taps (e.g. SDR)
        now = int(time.time())
        table = {ip: v for ip, v in table.items()
                 if isinstance(v, dict) and now - v.get("ts", now) <= STALE}
        write(table)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
