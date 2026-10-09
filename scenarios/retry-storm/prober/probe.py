"""Synthetic client: GET api /checkout every 0.5 s, one JSON line per attempt."""
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API_URL", "http://api:8080")
OUT = os.environ.get("OUT", "/evidence/probes.jsonl")
INTERVAL = float(os.environ.get("INTERVAL", "0.5"))
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe():
    t0 = time.time()
    rec = {"ts": round(t0, 3), "ok": False, "code": 0, "lat_ms": None, "flag": None, "err": None}
    try:
        with NOPROXY.open(f"{API}/checkout", timeout=5) as r:
            rec["code"], rec["flag"] = r.status, r.headers.get("X-Vantage-Flag")
            r.read()
    except urllib.error.HTTPError as e:
        rec["code"] = e.code
        try:
            rec["err"] = json.loads(e.read()).get("error")
        except Exception:
            rec["err"] = f"http {e.code}"
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
