"""Authoritative DNS for *.internal, behaving like a secondary that only accepts
a reloaded zone when its serial increased.

UDP :53   queries
TCP :8053 admin: GET /reload, GET /zone (what is being served right now)
"""
import http.server
import json
import os
import socket
import sys
import threading
import time

from dnslib import build_response, load_zone

ZONE_FILE = os.environ.get("ZONE_FILE", "/zone/internal.zone")
LOCK = threading.Lock()
STATE = {"zone": load_zone(ZONE_FILE), "loaded_at": time.time()}


def log(msg):
    sys.stderr.write("%s dns %s\n" % (time.strftime("%H:%M:%S"), msg))


def reload_zone():
    new = load_zone(ZONE_FILE)
    with LOCK:
        old = STATE["zone"]
        if new["serial"] <= old["serial"]:
            msg = f"zone serial {new['serial']} not greater than loaded {old['serial']}: keeping old zone"
            log("WARN " + msg)
            return False, msg
        STATE["zone"], STATE["loaded_at"] = new, time.time()
    msg = f"zone reloaded, serial {old['serial']} -> {new['serial']}"
    log(msg)
    return True, msg


def serve_udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", 53))
    while True:
        data, addr = s.recvfrom(512)
        try:
            with LOCK:
                zone = STATE["zone"]
            resp, rcode, qname = build_response(data, zone)
            s.sendto(resp, addr)
            if rcode:
                log(f"NXDOMAIN {qname} from {addr[0]}")
        except Exception as e:  # malformed query: drop it, like a real server
            log(f"bad query from {addr[0]}: {e}")


class Admin(http.server.BaseHTTPRequestHandler):
    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/reload":
            ok, msg = reload_zone()
            return self.reply(200 if ok else 409, {"reloaded": ok, "message": msg})
        if self.path == "/zone":
            with LOCK:
                z = STATE["zone"]
            return self.reply(200, {"serial": z["serial"], "negttl": z["negttl"], "records": z["records"]})
        self.reply(404, {"error": "not_found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    log(f"serving zone serial {STATE['zone']['serial']} ({len(STATE['zone']['records'])} names)")
    threading.Thread(target=serve_udp, daemon=True).start()
    http.server.ThreadingHTTPServer(("0.0.0.0", 8053), Admin).serve_forever()
