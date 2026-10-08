#!/usr/bin/env python3
"""Vantage grader: issues attempts, receives evidence live, scores and signs.

    python grader/server.py [--port 8700] [--data DIR] [--scenarios DIR]

What it guarantees (see docs/grader.md for the full threat model):
  * the seed is random per attempt and only exists once the attempt starts;
  * break / hint / submit times are the server's clock, not the client's;
  * only probes that arrived live (timestamp within SKEW of server time,
    strictly increasing) count, and a probe only counts as healthy if it
    carries the flag the server expects for this attempt;
  * the score is computed here from the server's own copy of the scenario's
    scoring config and signed with the server's ed25519 key.
What it cannot guarantee while the environment runs on the trainee's machine:
assertion results are client-reported, and a live forged prober is possible.

API (JSON; per-attempt bearer token returned at creation):
  POST /v1/attempts                      {user, scenario}         -> {attempt_id, seed, token}
  POST /v1/attempts/<id>/events          {type, data}             -> {ts}
  POST /v1/attempts/<id>/probes          {probes: [...]}          -> {accepted, rejected}
  POST /v1/attempts/<id>/submit          {assertions, baseline, current, mode} -> signed result
  GET  /v1/attempts/<id>/result                                   -> signed result
  GET  /v1/pubkey                                                 -> PEM
"""
import argparse
import base64
import hashlib
import hmac
import http.server
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "framework"))
from scoring import compute  # noqa: E402

SKEW_S = float(os.environ.get("GRADER_SKEW_S", "15"))          # live window for probe timestamps
STABLE_WINDOW = float(os.environ.get("GRADER_STABLE_WINDOW", "60"))
MAX_GAP_S = 3.0                                                 # same rule as assert_stable_window
ATTEST_MAX_GAP_S = 10.0                                         # longest blind spot allowed for attestation
SCENARIO_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
  id TEXT PRIMARY KEY, user TEXT, scenario TEXT, seed TEXT, token_sha TEXT,
  created REAL, break_ts REAL, host TEXT, submitted REAL, result TEXT, signature TEXT, clock_offset REAL);
CREATE TABLE IF NOT EXISTS events (attempt TEXT, ts REAL, type TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS probes (
  attempt TEXT, recv REAL, ts REAL, ok INTEGER, claimed_ok INTEGER, lat_ms REAL, flag_ok INTEGER, err TEXT);
CREATE TABLE IF NOT EXISTS rejects (attempt TEXT, recv REAL, ts REAL, reason TEXT);
"""


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def expected_flag(seed, host):
    """Same derivation the scenarios use: secret = sha256(seed:flag), flag = HMAC(secret, host)[:24]."""
    secret = hashlib.sha256(f"{seed}:flag".encode()).hexdigest()
    return hmac.new(secret.encode(), host.encode(), hashlib.sha256).hexdigest()[:24]


class Grader:
    def __init__(self, data_dir, scenarios_dir):
        os.makedirs(data_dir, exist_ok=True)
        self.scenarios_dir = scenarios_dir
        self.key = os.path.join(data_dir, "grader.key")
        if not os.path.exists(self.key):
            subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", self.key], check=True)
            os.chmod(self.key, 0o600)
        self.pubkey = subprocess.run(["openssl", "pkey", "-in", self.key, "-pubout"],
                                     check=True, capture_output=True, text=True).stdout
        secret_path = os.path.join(data_dir, "seed.secret")
        if not os.path.exists(secret_path):
            with open(secret_path, "w") as f:
                f.write(secrets.token_hex(32))
            os.chmod(secret_path, 0o600)
        with open(secret_path) as f:
            self.seed_secret = f.read().strip().encode()
        self.db = sqlite3.connect(os.path.join(data_dir, "grader.db"), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.migrate()
        self.lock = threading.Lock()

    def migrate(self):
        """Additive migrations for databases created by older versions."""
        for table, column, decl in (("attempts", "clock_offset", "REAL"), ("probes", "claimed_ok", "INTEGER")):
            cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        self.db.commit()

    # --- helpers -------------------------------------------------------------
    def sign(self, payload):
        # ed25519 is one-shot: OpenSSL 3.0 needs a regular file, not a pipe, for -rawin
        with tempfile.NamedTemporaryFile() as msg:
            msg.write(canonical(payload))
            msg.flush()
            p = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", self.key, "-rawin", "-in", msg.name],
                               capture_output=True, check=True)
        return base64.b64encode(p.stdout).decode()

    def attempt(self, aid, token):
        row = self.db.execute("SELECT id, user, scenario, seed, token_sha, created, break_ts, host, submitted, "
                              "result, signature, clock_offset FROM attempts WHERE id=?", (aid,)).fetchone()
        if not row:
            raise KeyError("unknown attempt")
        if not hmac.compare_digest(row[4], hashlib.sha256((token or "").encode()).hexdigest()):
            raise PermissionError("bad token")
        keys = ["id", "user", "scenario", "seed", "token_sha", "created", "break_ts", "host", "submitted",
                "result", "signature", "clock_offset"]
        return dict(zip(keys, row))

    def scoring_cfg(self, scenario):
        path = os.path.join(self.scenarios_dir, scenario, "generated", "scoring.json")
        if not SCENARIO_RE.match(scenario) or not os.path.exists(path):
            raise KeyError(f"unknown scenario {scenario}")
        with open(path) as f:
            return json.load(f)

    # --- API -----------------------------------------------------------------
    def create(self, body):
        scenario = str(body.get("scenario", ""))
        self.scoring_cfg(scenario)  # validates the scenario exists
        aid, token = secrets.token_hex(8), secrets.token_urlsafe(24)
        seed = hmac.new(self.seed_secret, f"{aid}:{scenario}".encode(), hashlib.sha256).hexdigest()
        now = time.time()
        # Measured once, at the start: an honest machine with a wrong clock still
        # streams "live" probes, just shifted. Changing the clock later does not help.
        try:
            offset = float(body["client_time"]) - now
        except (KeyError, TypeError, ValueError):
            offset = 0.0
        if abs(offset) > 3600:
            return 400, {"error": f"client clock is off by {offset:.0f}s; fix NTP first"}
        with self.lock:
            self.db.execute("INSERT INTO attempts (id, user, scenario, seed, token_sha, created, clock_offset) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (aid, str(body.get("user", "anonymous"))[:200], scenario, seed,
                             hashlib.sha256(token.encode()).hexdigest(), now, offset))
            self.db.commit()
        return 201, {"attempt_id": aid, "seed": seed, "token": token, "clock_offset_s": round(offset, 3)}

    def event(self, a, body):
        etype = str(body.get("type", ""))
        if etype not in ("break", "hint", "fix", "note"):
            return 400, {"error": "unknown event type"}
        if a["submitted"]:
            return 409, {"error": "attempt already submitted"}
        now = time.time()
        data = body.get("data") or {}
        with self.lock:
            if etype == "break":
                if a["break_ts"]:
                    return 409, {"error": "break already recorded"}
                host = str(data.get("host", ""))
                if a["seed"][:6] not in host:
                    return 400, {"error": "host does not belong to this attempt's seed"}
                self.db.execute("UPDATE attempts SET break_ts=?, host=? WHERE id=?", (now, host, a["id"]))
            self.db.execute("INSERT INTO events VALUES (?,?,?,?)", (a["id"], now, etype, json.dumps(data)[:2000]))
            self.db.commit()
        return 200, {"ts": now}

    def probes(self, a, body):
        if a["submitted"]:
            return 409, {"error": "attempt already submitted"}
        now = time.time()
        client_now = now + (a["clock_offset"] or 0.0)   # probe ts are on the client's clock
        flag = expected_flag(a["seed"], a["host"]) if a["host"] else None
        accepted = rejected = 0
        with self.lock:
            last = self.db.execute("SELECT MAX(ts) FROM probes WHERE attempt=?", (a["id"],)).fetchone()[0] or 0
            for p in (body.get("probes") or [])[:2000]:
                try:
                    ts = float(p["ts"])
                except (KeyError, TypeError, ValueError):
                    rejected += 1
                    continue
                reason = None
                if abs(ts - client_now) > SKEW_S:
                    reason = "not_live"            # back-filled or future-dated
                elif ts <= last:
                    reason = "non_monotonic"       # replayed or reordered
                if reason:
                    rejected += 1
                    self.db.execute("INSERT INTO rejects VALUES (?,?,?,?)", (a["id"], now, ts, reason))
                    continue
                flag_ok = bool(flag) and hmac.compare_digest(str(p.get("flag") or ""), flag)
                ok = bool(p.get("ok")) and flag_ok
                self.db.execute("INSERT INTO probes VALUES (?,?,?,?,?,?,?,?)",
                                (a["id"], now, ts, int(ok), int(bool(p.get("ok"))), float(p.get("lat_ms") or 0),
                                 int(flag_ok),
                                 str(p.get("err") or "")[:200]))
                last = ts
                accepted += 1
            self.db.commit()
        return 200, {"accepted": accepted, "rejected": rejected}

    def submit(self, a, body):
        if a["submitted"]:
            return 409, {"error": "attempt already submitted"}
        if not a["break_ts"]:
            return 409, {"error": "no break recorded"}
        cfg = self.scoring_cfg(a["scenario"])
        now = time.time()
        rows = self.db.execute("SELECT ts, ok, lat_ms FROM probes WHERE attempt=? ORDER BY ts",
                               (a["id"],)).fetchall()
        off = a["clock_offset"] or 0.0                   # back to server time for scoring
        probes = [{"ts": r[0] - off, "ok": bool(r[1]), "lat_ms": r[2]} for r in rows]
        hints = self.db.execute("SELECT COUNT(*) FROM events WHERE attempt=? AND type='hint'", (a["id"],)).fetchone()[0]
        rejects = dict(self.db.execute("SELECT reason, COUNT(*) FROM rejects WHERE attempt=? GROUP BY reason",
                                       (a["id"],)).fetchall())
        # healthy-looking probes whose flag the server did not issue: fabricated or replayed
        bad_flags = self.db.execute("SELECT COUNT(*) FROM probes WHERE attempt=? AND ts>=? AND claimed_ok=1 "
                                    "AND flag_ok=0", (a["id"], a["break_ts"] + off)).fetchone()[0]

        # Server's own stability check (replaces the client's A5-style claim).
        win = [p for p in probes if p["ts"] >= now - STABLE_WINDOW]
        ts = [now - STABLE_WINDOW] + [p["ts"] for p in win] + [now]
        stable_gap = max(b - c for c, b in zip(ts, ts[1:]))
        stable_ok = bool(win) and all(p["ok"] for p in win) and stable_gap <= MAX_GAP_S
        # Longest blind spot during the incident: long gaps mean the prober was not live.
        inc_ts = [a["break_ts"]] + [p["ts"] for p in probes if p["ts"] >= a["break_ts"]] + [now]
        incident_gap = max(b - c for c, b in zip(inc_ts, inc_ts[1:]))

        asr = body.get("assertions") or {}
        try:
            client_public = bool(asr["public_pass"])
            asr = {"assertions": asr["assertions"], "hidden_pass": int(asr["hidden_pass"]),
                   "hidden_total": int(asr["hidden_total"]), "public_pass": client_public and stable_ok}
        except (KeyError, TypeError, ValueError):
            return 400, {"error": "assertions missing or malformed"}
        try:
            r = compute(cfg, str(body.get("mode", "docker")), STABLE_WINDOW, a["break_ts"], now, hints, probes, asr,
                        body.get("baseline") or {}, body.get("current") or {})
        except ValueError as e:
            return 422, {"error": str(e)}

        integrity = {
            "server_stable_window_s": STABLE_WINDOW, "server_stable_ok": stable_ok,
            "max_gap_in_window_s": round(stable_gap, 2), "max_gap_during_incident_s": round(incident_gap, 2),
            "rejected_probes": rejects, "probes_with_wrong_flag": bad_flags,
            "client_clock_offset_s": round(off, 3),
        }
        attested = incident_gap <= ATTEST_MAX_GAP_S and not rejects and bad_flags == 0
        if not attested:
            # Evidence was tampered with or incomplete: the number stays informative,
            # but no tier (and so no certification) is awarded.
            r["tier"] = "unverified"
        result = dict({"attempt_id": a["id"], "user": a["user"], "scenario": a["scenario"],
                       "seed_prefix": a["seed"][:12], "submitted_at": now,
                       "attested": attested,
                       "trust": {"timeline": "server", "probes": "server-received live, flag-checked",
                                 "assertions": "client-reported", "scoring_config": "server"}},
                      **r, integrity=integrity, assertions=asr)
        sig = self.sign(result)
        with self.lock:
            self.db.execute("UPDATE attempts SET submitted=?, result=?, signature=? WHERE id=?",
                            (now, json.dumps(result), sig, a["id"]))
            self.db.commit()
        return 200, {"result": result, "signature": sig, "alg": "ed25519", "signed": "canonical JSON of result"}

    def result(self, a):
        if not a["submitted"]:
            return 404, {"error": "not submitted"}
        return 200, {"result": json.loads(a["result"]), "signature": a["signature"], "alg": "ed25519"}


def make_handler(g):
    class Handler(http.server.BaseHTTPRequestHandler):
        def reply(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def route(self, method):
            parts = [p for p in self.path.split("?")[0].split("/") if p]
            try:
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > 2_000_000:
                        return self.reply(413, {"error": "too large"})
                    body = json.loads(self.rfile.read(n) or b"{}")
                if parts == ["v1", "pubkey"] and method == "GET":
                    return self.reply(200, g.pubkey, "application/x-pem-file")
                if parts == ["v1", "attempts"] and method == "POST":
                    return self.reply(*g.create(body))
                if len(parts) >= 3 and parts[:2] == ["v1", "attempts"]:
                    token = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
                    a = g.attempt(parts[2], token)
                    action = parts[3] if len(parts) > 3 else ""
                    handlers = {("POST", "events"): lambda: g.event(a, body),
                                ("POST", "probes"): lambda: g.probes(a, body),
                                ("POST", "submit"): lambda: g.submit(a, body),
                                ("GET", "result"): lambda: g.result(a)}
                    if (method, action) in handlers:
                        return self.reply(*handlers[(method, action)]())
                self.reply(404, {"error": "not found"})
            except PermissionError as e:
                self.reply(403, {"error": str(e)})
            except KeyError as e:
                self.reply(404, {"error": str(e).strip("'\"")})
            except json.JSONDecodeError:
                self.reply(400, {"error": "invalid json"})
            except Exception as e:  # never drop the connection without an answer
                sys.stderr.write(f"grader error: {type(e).__name__}: {e}\n")
                self.reply(500, {"error": "internal error"})

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def log_message(self, fmt, *args):
            sys.stderr.write("%s grader %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    return Handler


def serve(port, data_dir, scenarios_dir):
    g = Grader(data_dir, scenarios_dir)
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), make_handler(g))
    return g, srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("GRADER_PORT", "8700")))
    ap.add_argument("--data", default=os.environ.get("GRADER_DATA", os.path.join(ROOT, "grader", ".data")))
    ap.add_argument("--scenarios", default=os.path.join(ROOT, "scenarios"))
    args = ap.parse_args()
    _, srv = serve(args.port, args.data, args.scenarios)
    sys.stderr.write(f"grader listening on :{args.port}, data in {args.data}\n")
    srv.serve_forever()
