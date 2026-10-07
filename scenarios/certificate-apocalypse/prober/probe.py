"""Synthetic client: verifies TLS against the public root only (like a real
browser would) and appends one JSON line per request to OUT."""
import json
import os
import ssl
import time
import urllib.error
import urllib.request

TARGET = os.environ["TARGET"]
OUT = os.environ.get("OUT", "/evidence/probes.jsonl")
INTERVAL = float(os.environ.get("INTERVAL", "0.5"))
TIMEOUT = float(os.environ.get("TIMEOUT", "2"))


def ctx():
    # Re-read the CA every request so the probe never caches trust state.
    c = ssl.create_default_context(cafile=os.environ["CA_FILE"])
    c.minimum_version = ssl.TLSVersion.TLSv1_2
    return c


def probe():
    t0 = time.time()
    rec = {"ts": round(t0, 3), "ok": False, "code": 0, "lat_ms": None, "flag": None, "err": None}
    try:
        with urllib.request.urlopen(TARGET, timeout=TIMEOUT, context=ctx()) as r:
            rec["code"] = r.status
            rec["flag"] = r.headers.get("X-Vantage-Flag")
            r.read()
    except urllib.error.HTTPError as e:
        rec["code"] = e.code
        rec["err"] = f"http {e.code}"
    except Exception as e:  # TLS / DNS / timeout: record the reason as evidence
        reason = getattr(e, "reason", e)
        rec["err"] = f"{type(reason).__name__}: {reason}"[:200]
    rec["lat_ms"] = round((time.time() - t0) * 1000, 1)
    rec["ok"] = rec["code"] == 200 and bool(rec["flag"])
    return rec


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    while True:
        start = time.time()
        with open(OUT, "a") as f:
            f.write(json.dumps(probe()) + "\n")
        time.sleep(max(0.0, INTERVAL - (time.time() - start)))
