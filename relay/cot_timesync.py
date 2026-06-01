#!/usr/bin/env python3
"""
HaphazardNet "time over CoT" — clock sync from connected TAK devices.

The field kit has no RTC and no internet, so its clock drifts/resets each boot.
But every ATAK/WinTAK CoT <event> carries the device's GPS/cell-synced UTC time.
We tap taky's CoT stream, read the event time, and step the Pi's clock when it
has drifted past a threshold. Any connected TAK device keeps the kit on time.

Runs as root (needs to set the clock). Net mode only (devices talk to taky).
Pure stdlib.
"""

import calendar
import re
import socket
import subprocess
import time

TAKY = ("127.0.0.1", 8087)
THRESHOLD = 10          # seconds of drift before we correct
MIN_EPOCH = 1735689600  # 2025-01-01 — reject obviously bogus timestamps
RESYNC_GAP = 5          # min seconds between clock steps

TIME_RE = re.compile(rb'<event\b[^>]*\btime="([^"]+)"')
ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})")


def parse_epoch(raw):
    """ISO-8601 UTC (e.g. 2026-05-31T23:51:00.000Z) -> epoch seconds, or None."""
    m = ISO_RE.match(raw.decode("ascii", "ignore"))
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        return calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))
    except Exception:
        return None


def set_clock(epoch):
    subprocess.run(["date", "-u", "-s", "@%d" % int(epoch)],
                   capture_output=True)
    print(f"[timesync] clock set to {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))}",
          flush=True)


def main():
    # taky replays each client's last-known event on connect, so individual
    # events can be stale. The NEWEST event time we've seen ~= "now" (events are
    # generated at-or-before real time); sync the clock to that, never to an old
    # replayed event. A short initial gather avoids acting on the first stale one.
    last_set = 0
    while True:
        try:
            sock = socket.create_connection(TAKY, timeout=10)
            sock.settimeout(60)
            print("[timesync] tapping taky", flush=True)
            buf = b""
            newest = 0
            gather_until = time.time() + 4
            while True:
                data = sock.recv(8192)
                if not data:
                    break
                buf += data
                for m in TIME_RE.finditer(buf):
                    ep = parse_epoch(m.group(1))
                    if ep and ep >= MIN_EPOCH and ep > newest:
                        newest = ep
                buf = buf[-2048:]   # keep tail for split tags
                now = time.time()
                if now < gather_until or not newest:
                    continue
                if abs(newest - now) > THRESHOLD and (now - last_set) > RESYNC_GAP:
                    set_clock(newest)
                    last_set = time.time()
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[timesync] {e}; retrying", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
