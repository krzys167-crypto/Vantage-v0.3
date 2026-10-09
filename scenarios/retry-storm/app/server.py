"""Retry Storm services (stdlib only).

ROLE=inventory  POST-like GET /reserve: one unit of work. A request waits for a
                worker slot (bounded backlog, beyond it 503 "overloaded"), then
                takes service_ms of "CPU". Work for clients that already gave up
                is still done, as in real servers.
                /config/inventory.json (read live): workers, cpu_millicores,
                base_service_ms, queue_max.
ROLE=api        GET /checkout: reserves at inventory with the retry policy in
                /config/api.json (read live): timeout_ms, retries, backoff_ms,
                jitter, fallback_static.
ROLE=loadgen    open-loop traffic: rps requests per second whatever the
                answers, like real users. Admin: GET /burst?seconds=N&factor=F.
Both inventory and api expose GET /metrics?window=S.
"""
import collections
import hashlib
import hmac
import http.server
import json
import os
import random
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

ROLE = os.environ["ROLE"]
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("VANTAGE_HOST", "shop.vantage.local")
INVENTORY = os.environ.get("INVENTORY_URL", "http://inventory:8090")
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


def config(name):
    return json.loads(read(f"/config/{name}.json", "{}") or "{}")


def log(msg):
    sys.stderr.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), ROLE, msg))
    sys.stderr.flush()


def p95(values):
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(0.95 * len(v)))], 1)


class Window:
    """Events (ts, fields...) kept for 10 minutes, queried by trailing window."""

    def __init__(self):
        self.ev = collections.deque()
        self.lock = threading.Lock()

    def add(self, *fields):
        now = time.time()
        with self.lock:
            self.ev.append((now,) + fields)
            while self.ev and self.ev[0][0] < now - 600:
                self.ev.popleft()

    def since(self, seconds):
        cut = time.time() - seconds
        with self.lock:
            return [e for e in self.ev if e[0] >= cut]


# --- inventory ------------------------------------------------------------------
class Pool:
    """Worker slots sized from config on every request, so changes apply live."""

    def __init__(self):
        self.cv = threading.Condition()
        self.busy = 0
        self.waiting = 0

    _cache = (0.0, None)

    @classmethod
    def params(cls):
        if time.time() - cls._cache[0] < 0.5:      # config is re-read twice a second
            return cls._cache[1]
        c = config("inventory")
        cpu = max(50, int(c.get("cpu_millicores", 1000)))
        workers = max(1, int(c.get("workers", 8)))
        # CPU caps parallelism (one core-eighth per worker) and slows each unit
        effective = max(1, min(workers, cpu // 125))
        service_ms = float(c.get("base_service_ms", 40)) * 1000.0 / cpu
        p = {"workers": workers, "cpu_millicores": cpu, "effective_workers": effective,
             "service_ms": round(service_ms, 1), "queue_max": int(c.get("queue_max", 200))}
        cls._cache = (time.time(), p)
        return p

    def run(self):
        p = self.params()
        t0 = time.time()
        with self.cv:
            if self.waiting >= p["queue_max"]:
                return None, p
            self.waiting += 1
            while self.busy >= self.params()["effective_workers"]:
                self.cv.wait(0.1)
            self.waiting -= 1
            self.busy += 1
        waited = (time.time() - t0) * 1000
        time.sleep(p["service_ms"] / 1000.0)
        with self.cv:
            self.busy -= 1
            self.cv.notify()
        return waited, p


POOL = Pool() if ROLE == "inventory" else None
INV = Window()    # (ts, outcome, wait_ms, service_ms)
API = Window()    # (ts, ok, attempts, latency_ms, fallback)


def reservation_sig(body):
    return hmac.new(read("/secret/inventory.key").encode(), body, hashlib.sha256).hexdigest()


def inventory_metrics(window):
    ev = INV.since(window)
    served = [e for e in ev if e[1] == "served"]
    p = POOL.params()
    busy_s = sum(e[3] for e in served) / 1000.0
    return {"window_s": window, "arrived": len(ev), "served": len(served),
            "rejected": sum(1 for e in ev if e[1] == "rejected"),
            "rps": round(len(ev) / window, 1),
            "p95_queue_ms": p95([e[2] for e in served]),
            "utilization": round(busy_s / (p["effective_workers"] * window), 3),
            "busy": POOL.busy, "waiting": POOL.waiting, **p}


# --- api --------------------------------------------------------------------------
def reserve_once(timeout_s):
    with NOPROXY.open(f"{INVENTORY}/reserve", timeout=timeout_s) as r:
        body, sig = r.read(), r.headers.get("X-Signature", "")
    if not hmac.compare_digest(reservation_sig(body), sig):
        raise ValueError("bad reservation signature")
    return json.loads(body)


def checkout():
    c = config("api")
    if c.get("fallback_static"):
        # "degraded mode": answer from a static stock snapshot, inventory untouched
        return {"status": "ok", "served_by": "fallback"}, 1, True, None
    retries = max(0, int(c.get("retries", 2)))
    timeout_s = max(0.01, float(c.get("timeout_ms", 1000)) / 1000.0)
    backoff_ms = max(0.0, float(c.get("backoff_ms", 100)))
    err = None
    for attempt in range(retries + 1):
        try:
            res = reserve_once(timeout_s)
            return {"status": "ok", "served_by": "inventory", "reservation": res["id"]}, attempt + 1, False, None
        except urllib.error.HTTPError as e:
            err = f"inventory http {e.code}"
        except (socket.timeout, TimeoutError):
            err = "inventory timeout"
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = f"inventory unreachable: {getattr(e, 'reason', e)}"
        if attempt < retries:
            delay = backoff_ms * (2 ** attempt) / 1000.0
            if c.get("jitter", True):
                delay *= random.uniform(0.5, 1.5)
            time.sleep(delay)
    return None, retries + 1, False, err


def flag():
    return hmac.new(read("/secret/flag_secret").encode(), HOST.encode(), hashlib.sha256).hexdigest()[:24]


def api_metrics(window):
    ev = API.since(window)
    n = len(ev)
    return {"window_s": window, "checkouts": n, "ok": sum(1 for e in ev if e[1]),
            "attempts": sum(e[2] for e in ev), "fallback": sum(1 for e in ev if e[4]),
            "amplification": round(sum(e[2] for e in ev) / n, 2) if n else None,
            "p95_ms": p95([e[3] for e in ev]), "policy": config("api")}


# --- loadgen ----------------------------------------------------------------------
BURST = {"until": 0.0, "factor": 1.0}


def loadgen():
    target = os.environ.get("API_URL", "http://api:8080") + "/checkout"
    rps = float(os.environ.get("RPS", "40"))

    def one():
        try:
            with NOPROXY.open(target, timeout=10) as r:
                r.read()
        except Exception:
            pass
    nxt = time.time()
    while True:
        factor = BURST["factor"] if time.time() < BURST["until"] else 1.0
        threading.Thread(target=one, daemon=True).start()
        nxt += 1.0 / (rps * factor)
        time.sleep(max(0.0, nxt - time.time()))
        if nxt < time.time() - 1:      # never build up a backlog of sends
            nxt = time.time()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def reply(self, code, body, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass        # the client gave up long ago

    def window(self, url):
        return max(1.0, float(parse_qs(url.query).get("window", ["60"])[0]))

    def do_GET(self):
        url = urlsplit(self.path)
        if ROLE == "inventory":
            if url.path == "/reserve":
                waited, p = POOL.run()
                if waited is None:
                    INV.add("rejected", 0.0, 0.0)
                    return self.reply(503, {"error": "overloaded", "waiting": POOL.waiting})
                INV.add("served", waited, p["service_ms"])
                body = json.dumps({"id": "r-%x" % random.getrandbits(40), "ts": time.time()}).encode()
                return self.reply(200, body, {"X-Signature": reservation_sig(body)})
            if url.path == "/metrics":
                return self.reply(200, inventory_metrics(self.window(url)))
        elif ROLE == "api":
            if url.path == "/checkout":
                t0 = time.time()
                res, attempts, fallback, err = checkout()
                API.add(res is not None, attempts, (time.time() - t0) * 1000, fallback)
                if res is None:
                    log(f"upstream timeout: checkout failed after {attempts} attempts ({err})")
                    return self.reply(503, {"error": err, "attempts": attempts})
                return self.reply(200, res, {"X-Vantage-Flag": flag()})
            if url.path == "/metrics":
                return self.reply(200, api_metrics(self.window(url)))
        elif ROLE == "loadgen" and url.path == "/burst":
            q = parse_qs(url.query)
            BURST["factor"] = float(q.get("factor", ["3"])[0])
            BURST["until"] = time.time() + float(q.get("seconds", ["10"])[0])
            log(f"traffic burst x{BURST['factor']} for {q.get('seconds', ['10'])[0]}s")
            return self.reply(200, {"burst": BURST})
        self.reply(404, {"error": "not_found"})

    def log_message(self, *a):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 512


if __name__ == "__main__":
    if ROLE == "loadgen":
        threading.Thread(target=loadgen, daemon=True).start()
    log(f"listening on :{PORT}")
    Server(("0.0.0.0", PORT), Handler).serve_forever()
