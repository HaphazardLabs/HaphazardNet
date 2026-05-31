"""
System + service status, stdlib only (no psutil) to stay light on the Zero 2W.
All readers fail soft so the UI always renders.
"""

import subprocess
import time

WATCHED_SERVICES = ["taky", "hostapd", "dnsmasq"]


def cpu_temp_c():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        return None


def mem_percent():
    try:
        total = avail = None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])
                if total and avail:
                    break
        if total and avail:
            return round((total - avail) / total * 100.0, 1)
    except Exception:
        pass
    return None


def uptime():
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        if d:
            return f"{d}d{h}h"
        if h:
            return f"{h}h{m}m"
        return f"{m}m"
    except Exception:
        return None


def load_avg():
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except Exception:
        return None


def service_active(name):
    try:
        res = subprocess.run(["systemctl", "is-active", name],
                             capture_output=True, text=True, timeout=3)
        return res.stdout.strip() == "active"
    except Exception:
        return None  # unknown (e.g. off-Pi)


def services():
    return {name: service_active(name) for name in WATCHED_SERVICES}


def summary():
    return {
        "cpu_temp_c": cpu_temp_c(),
        "mem_percent": mem_percent(),
        "uptime": uptime(),
        "load": load_avg(),
        "services": services(),
        "ts": int(time.time()),
    }
