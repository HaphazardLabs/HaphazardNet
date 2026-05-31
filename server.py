#!/usr/bin/env python3
"""
HaphazardNet control panel — stdlib HTTP server (no pip deps), same style as
the HaphazardLabs.com site server.

Serves the themed web UI and a small JSON API:
    GET  /                 -> web/index.html
    GET  /api/status       -> mode + battery + system + service state
    GET  /api/clients      -> users on the net (+ counts)
    GET  /api/mode         -> mode state
    POST /api/mode {mode}  -> request a mode change (root applier acts on it)
    POST /api/shutdown     -> safe power off (slide-to-confirm in the UI)

Also answers OS captive-portal probes with a redirect to the panel, so phones
that join the AP pop the "sign in to network" sheet straight into this UI.

Run:  python3 server.py [--port 80] [--host 0.0.0.0]
On the Zero it binds :80 (needs cap_net_bind_service or root); for dev use 8765.
"""

import argparse
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from haphazard import battery, clients, mode, sysinfo

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PORTAL_HOST = None  # set at startup to the AP IP for captive redirects

# Paths OSes hit to detect a captive portal -> redirect them to the panel.
CAPTIVE_PROBES = {
    "/generate_204", "/gen_204", "/hotspot-detect.html",
    "/library/test/success.html", "/connecttest.txt", "/ncsi.txt",
    "/canonical.html", "/success.txt",
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".png": "image/png",
    ".svg": "image/svg+xml", ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "HaphazardNet/1.0"

    def log_message(self, *args):
        pass  # quiet; systemd journal would double-log

    # ---- helpers -------------------------------------------------------
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, relpath):
        path = os.path.normpath(os.path.join(WEB_DIR, relpath.lstrip("/")))
        if not path.startswith(WEB_DIR) or not os.path.isfile(path):
            self.send_error(404)
            return
        ext = os.path.splitext(path)[1]
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    # ---- routing -------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in CAPTIVE_PROBES:
            self._redirect(f"http://{PORTAL_HOST or self.headers.get('Host', '')}/")
            return

        if path == "/" or path == "/index.html":
            self._file("index.html")
        elif path == "/api/status":
            self._json({
                "mode": mode.get(),
                "battery": battery.read(),
                "system": sysinfo.summary(),
            })
        elif path == "/api/clients":
            users = clients.list_clients()
            self._json({"clients": users, "counts": clients.count(users)})
        elif path == "/api/mode":
            self._json(mode.get())
        elif path.startswith("/"):
            self._file(path)
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/mode":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                state = mode.request(data["mode"])
                self._json(state)
            except ValueError as e:
                self._json({"error": str(e)}, status=400)
            except Exception as e:
                self._json({"error": f"bad request: {e}"}, status=400)
        elif path == "/api/shutdown":
            # Confirmed via the UI's slide-to-power-off. Reply first, then power
            # off a couple seconds later so the response reaches the browser.
            self._json({"status": "shutting down"})
            try:
                self.wfile.flush()
            except Exception:
                pass
            threading.Timer(2.0, lambda: subprocess.Popen(
                ["sudo", "-n", "/usr/bin/systemctl", "poweroff"])).start()
        else:
            self.send_error(404)


def main():
    global PORTAL_HOST
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--portal-ip", default="192.168.10.1",
                    help="AP IP used for captive-portal redirects")
    args = ap.parse_args()
    PORTAL_HOST = args.portal_ip

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"HaphazardNet panel on http://{args.host}:{args.port}  (portal {PORTAL_HOST})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
