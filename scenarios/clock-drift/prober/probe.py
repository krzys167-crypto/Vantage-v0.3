"""Synthetic client: fetch a token from auth, call api with it, one JSON line per
attempt. Records the api's rejection reason as evidence.

AUTH_URL, API_URL  service URLs (same names in docker and k8s)
OUT                file to append to, or "-" for stdout (k8s)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

AUTH = os.environ.get("AUTH_URL", "http://auth:8081")
API = os.environ.get("API_URL", "http://api:8080")
OUT = os.environ.get("OUT", "/evidence/probes.jsonl")
INTERVAL = float(os.environ.get("INTERVAL", "0.5"))
TIMEOUT = float(os.environ.get("TIMEOUT", "2"))
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with NOPROXY.open(req, timeout=TIMEOUT) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def probe():
    t0 = time.time()
    rec = {"ts": round(t0, 3), "ok": False, "code": 0, "lat_ms": None, "flag": None, "err": None}
    try:
        code, _, body = get(f"{AUTH}/token?sub=prober&aud=api")
        if code != 200:
            rec["err"] = f"auth http {code}"
        else:
            token = json.loads(body)["access_token"]
            code, headers, body = get(f"{API}/orders", {"Authorization": f"Bearer {token}"})
            rec["code"] = code
            rec["flag"] = headers.get("X-Vantage-Flag")
            if code != 200:
                rec["err"] = f"api {code} {json.loads(body).get('error', '?')}"
    except Exception as e:
        rec["err"] = f"{type(e).__name__}: {e}"[:200]
    rec["lat_ms"] = round((time.time() - t0) * 1000, 1)
    rec["ok"] = rec["code"] == 200 and bool(rec["flag"])
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
