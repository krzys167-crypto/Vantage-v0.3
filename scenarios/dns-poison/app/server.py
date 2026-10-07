"""Split-Brain DNS services.

ROLE=payments | legacy | fx   upstreams: GET /data returns JSON signed with
                              X-Signature = HMAC(/secret/<role>.key, body)
ROLE=api                      GET /checkout: resolves payments.internal and
                              fx.internal through its caching resolver (plus
                              static overrides in /config/hosts.json), calls
                              both, verifies their signatures.
  admin: /debug/resolve?name=..  /admin/dns/flush
"""
import hashlib
import hmac
import http.server
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

from dnslib import CachingResolver

ROLE = os.environ["ROLE"]
PORT = int(os.environ.get("PORT", "8090"))
HOST = os.environ.get("VANTAGE_HOST", "shop.vantage.local")
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


def config():
    return json.loads(read("/config/api.json", "{}") or "{}")


def log(msg):
    sys.stderr.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), ROLE, msg))


def sign(key, body):
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


RESOLVER = CachingResolver(os.environ.get("RESOLVER", "dns"), max_ttl=86400) if ROLE == "api" else None
UPSTREAMS = {"payments": "payments.internal", "fx": "fx.internal"}


def resolve(name):
    overrides = json.loads(read("/config/hosts.json", "{}") or "{}")
    if name in overrides:
        return {"rcode": 0, "ips": [overrides[name]], "source": "hosts.json override", "ttl_left": None}
    return RESOLVER.resolve(name)


def call_upstream(svc):
    cfg = config()
    r = resolve(UPSTREAMS[svc])
    if r["rcode"] != 0 or not r["ips"]:
        return None, f"{svc}: {UPSTREAMS[svc]} NXDOMAIN ({r['source']})"
    url = f"http://{r['ips'][0]}:8090/data"
    try:
        with NOPROXY.open(url, timeout=2) as resp:
            body, sig = resp.read(), resp.headers.get("X-Signature", "")
    except (urllib.error.URLError, OSError) as e:
        return None, f"{svc}: {url} unreachable: {e}"
    if cfg.get("verify_upstream_signature", True):
        key = read(f"/secret/{svc}.key", "")
        if not hmac.compare_digest(sign(key, body), sig):
            return None, f"{svc}: bad upstream signature from {r['ips'][0]} ({r['source']})"
    return json.loads(body), None


def flag():
    return hmac.new(read("/secret/flag_secret", "").encode(), HOST.encode(), hashlib.sha256).hexdigest()[:24]


class Handler(http.server.BaseHTTPRequestHandler):
    def reply(self, code, body, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if ROLE != "api":
            if url.path == "/data":
                body = json.dumps({"service": ROLE, "instance": os.environ.get("INSTANCE", ROLE),
                                   "ts": int(time.time())}).encode()
                key = read(f"/secret/{ROLE}.key", "")
                return self.reply(200, body, {"X-Signature": sign(key, body)})
            return self.reply(404, {"error": "not_found"})

        if url.path == "/checkout":
            results = {}
            for svc in UPSTREAMS:
                data, err = call_upstream(svc)
                if err:
                    log(f"upstream error {err}")
                    return self.reply(502, {"error": err})
                results[svc] = data["instance"]
            return self.reply(200, {"status": "ok", "upstreams": results}, {"X-Vantage-Flag": flag()})
        if url.path == "/debug/resolve":
            name = parse_qs(url.query).get("name", ["payments.internal"])[0]
            r = resolve(name)
            r.pop("expires", None)
            return self.reply(200, dict(r, name=name))
        if url.path == "/admin/dns/flush":
            n = RESOLVER.flush()
            log(f"dns cache flushed ({n} entries)")
            return self.reply(200, {"flushed": n})
        self.reply(404, {"error": "not_found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    log(f"listening on :{PORT}")
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
