#!/usr/bin/env python3
"""
HaphazardNet SDR CoT relay. Pure stdlib (no deps) so it runs on the offline Pi.

The SDR emits Cursor-on-Target (CoT) XML over UDP to the Pi (eth0, :4242).
What we do with it depends on the mode:

  --broadcast  (DIRECT mode): rebroadcast each CoT datagram to the AP broadcast
               address so the single connected device receives it. No server.

  --inject     (NET mode): forward each CoT datagram to taky over TCP (:8087) so
               taky fans it out to ALL connected users (shared picture). Also
               taps the callsign out of each event and writes callsigns.json so
               the panel can label the SDR feed.

Usage:
  cot_relay.py --broadcast [--listen 0.0.0.0:4242] [--bcast 192.168.10.255:4242]
  cot_relay.py --inject    [--listen 0.0.0.0:4242] [--taky 127.0.0.1:8087]
"""

import argparse
import json
import os
import re
import socket
import time

CALLSIGNS_FILE = "/run/haphazard/callsigns.json"
_CALLSIGN_RE = re.compile(rb'callsign="([^"]+)"')


def _host_port(s, default_port):
    if ":" in s:
        h, p = s.rsplit(":", 1)
        return h, int(p)
    return s, default_port


def _tap_callsign(data, src_ip):
    """Best-effort: record the callsign seen from a source IP for the panel."""
    m = _CALLSIGN_RE.search(data)
    if not m:
        return
    callsign = m.group(1).decode("utf-8", "replace")
    try:
        os.makedirs(os.path.dirname(CALLSIGNS_FILE), exist_ok=True)
        try:
            table = json.load(open(CALLSIGNS_FILE))
        except Exception:
            table = {}
        table[src_ip] = {"callsign": callsign, "ts": int(time.time())}
        tmp = CALLSIGNS_FILE + ".tmp"
        json.dump(table, open(tmp, "w"))
        os.replace(tmp, CALLSIGNS_FILE)
    except Exception:
        pass


def run_broadcast(listen, bcast):
    lh, lp = _host_port(listen, 4242)
    bh, bp = _host_port(bcast, 4242)
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind((lh, lp))
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    print(f"[broadcast] {lh}:{lp} -> {bh}:{bp}", flush=True)
    while True:
        data, addr = rx.recvfrom(65535)
        _tap_callsign(data, addr[0])
        try:
            tx.sendto(data, (bh, bp))
        except OSError as e:
            print(f"[broadcast] send error: {e}", flush=True)


def run_inject(listen, taky):
    lh, lp = _host_port(listen, 4242)
    th, tp = _host_port(taky, 8087)
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind((lh, lp))
    print(f"[inject] {lh}:{lp} -> taky {th}:{tp}", flush=True)
    sock = None
    while True:
        data, addr = rx.recvfrom(65535)
        _tap_callsign(data, addr[0])
        for _try in range(2):
            try:
                if sock is None:
                    sock = socket.create_connection((th, tp), timeout=5)
                    print("[inject] connected to taky", flush=True)
                if not data.endswith(b"\n"):
                    data += b"\n"
                sock.sendall(data)
                break
            except OSError as e:
                print(f"[inject] taky send failed ({e}); reconnecting", flush=True)
                try:
                    sock.close()
                except Exception:
                    pass
                sock = None
                time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--broadcast", action="store_true")
    g.add_argument("--inject", action="store_true")
    ap.add_argument("--listen", default="0.0.0.0:4242")
    ap.add_argument("--bcast", default="192.168.10.255:4242")
    ap.add_argument("--taky", default="127.0.0.1:8087")
    args = ap.parse_args()
    if args.broadcast:
        run_broadcast(args.listen, args.bcast)
    else:
        run_inject(args.listen, args.taky)


if __name__ == "__main__":
    main()
