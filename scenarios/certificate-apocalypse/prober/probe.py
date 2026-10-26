"""Synthetic client: verifies TLS against the public root only (like a real
browser would) and emits one JSON line per request.

TARGET           https://<public-host>:<port>/<path>  (host = SNI + verified name)
CONNECT_ADDR     optional host:port to dial instead of TARGET's host (k8s Service)
OUT              file to append to, or "-" for stdout (k8s: collected via kubectl logs)
FLAG_SECRET_FILE backend flag secret (default /pki/backend/flag_secret); the prober sends a
                 fresh nonce with every request and only counts a 200 whose X-Vantage-Canary
                 matches it, i.e. a response that the real backend produced just now.
"""
import hashlib
import hmac
import http.client
import json
import os
import secrets
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit

TARGET = urlsplit(os.environ["TARGET"])
SNI = TARGET.hostname
DIAL = os.environ.get("CONNECT_ADDR") or f"{TARGET.hostname}:{TARGET.port or 443}"
OUT = os.environ.get("OUT", "/evidence/probes.jsonl")
INTERVAL = float(os.environ.get("INTERVAL", "0.5"))
TIMEOUT = float(os.environ.get("TIMEOUT", "2"))
with open(os.environ.get("FLAG_SECRET_FILE", "/pki/backend/flag_secret"), "rb") as _f:
    SECRET = _f.read().strip()


def canary(nonce):
    return hmac.new(SECRET, f"canary:{SNI}:{nonce}".encode(), hashlib.sha256).hexdigest()[:24]


class Conn(http.client.HTTPSConnection):
    def connect(self):
        host, port = DIAL.rsplit(":", 1)
        sock = socket.create_connection((host, int(port)), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=SNI)


def ctx():
    # Re-read the CA every request so the probe never caches trust state.
    c = ssl.create_default_context(cafile=os.environ["CA_FILE"])
    c.minimum_version = ssl.TLSVersion.TLSv1_2
    return c


def probe():
    t0 = time.time()
    nonce = secrets.token_hex(8)
    rec = {"ts": round(t0, 3), "ok": False, "code": 0, "lat_ms": None, "flag": None,
           "nonce": nonce, "canary": None, "canary_ok": False, "err": None}
    conn = Conn(SNI, TARGET.port or 443, timeout=TIMEOUT, context=ctx())
    try:
        conn.request("GET", TARGET.path or "/", headers={"Host": SNI, "X-Vantage-Nonce": nonce})
        r = conn.getresponse()
        r.read()
        rec["code"] = r.status
        rec["flag"] = r.getheader("X-Vantage-Flag")
        rec["canary"] = r.getheader("X-Vantage-Canary")
        rec["canary_ok"] = hmac.compare_digest(rec["canary"] or "", canary(nonce))
        if r.status != 200:
            rec["err"] = f"http {r.status}"
        elif not rec["canary_ok"]:
            rec["err"] = "canary mismatch: the 200 was not produced by the backend for this request"
    except Exception as e:  # TLS / DNS / timeout: record the reason as evidence
        rec["err"] = f"{type(e).__name__}: {e}"[:200]
    finally:
        conn.close()
    rec["lat_ms"] = round((time.time() - t0) * 1000, 1)
    rec["ok"] = rec["code"] == 200 and bool(rec["flag"]) and rec["canary_ok"]
    return rec


if __name__ == "__main__":
    if OUT != "-":
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
    while True:
        start = time.time()
        line = json.dumps(probe()) + "\n"
        if OUT == "-":
            sys.stdout.write(line)
            sys.stdout.flush()
        else:
            with open(OUT, "a") as f:
                f.write(line)
        time.sleep(max(0.0, INTERVAL - (time.time() - start)))
