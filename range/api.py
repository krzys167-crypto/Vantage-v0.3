#!/usr/bin/env python3
"""Hosted range API + web panel: what a logged-in trainee clicks instead of the CLI.

    python range/api.py [--port 8780]

The browser logs in with Supabase Auth (or any IdP the grader trusts) and sends
the access token as "Authorization: Bearer <jwt>". The API verifies it exactly
like the grader does (grader/server.py authenticate: JWKS or platform token),
then drives range/range.sh for that user:

  GET  /                          panel (range/panel/index.html)
  GET  /config.json               public config for the panel (Supabase URL + publishable key)
  GET  /api/scenarios             scenarios that run on the hosted range
  POST /api/sessions              {scenario} -> start an incident (one per user)
  GET  /api/sessions/mine         status of my session
  GET  /api/sessions/mine/kubeconfig   my scoped kubeconfig (only mine)
  POST /api/sessions/mine/grade   assertions on the platform + signed grade
  POST /api/sessions/mine/stop    tear down
  GET  /api/profile, /api/league  my signed profile / the league, proxied from the grader

Env: GRADER_URL, the grader's identity settings (GRADER_JWKS_URL + GRADER_JWT_ISSUER
and/or GRADER_USER_SECRET), RANGE_MAX_SESSIONS (3), RANGE_SESSION_TTL_S (14400),
PANEL_SUPABASE_URL / PANEL_SUPABASE_KEY (publishable, public by design),
RANGE_SH (override for tests). Sessions live in memory; a restart forgets them
(their namespaces are reaped by `range.sh stop` from the evidence directory).
"""
import argparse
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "grader"))
import server as grader  # noqa: E402  (authenticate: same identity rules as the grader)

RANGE_SH = os.environ.get("RANGE_SH", os.path.join(ROOT, "range", "range.sh"))
SESSIONS_DIR = os.environ.get("RANGE_SESSIONS", os.path.join(ROOT, "range", ".sessions"))
MAX_SESSIONS = int(os.environ.get("RANGE_MAX_SESSIONS", "3"))
TTL_S = float(os.environ.get("RANGE_SESSION_TTL_S", "14400"))
PANEL = os.path.join(ROOT, "range", "panel", "index.html")
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def scenarios():
    out = []
    for name in sorted(os.listdir(os.path.join(ROOT, "scenarios"))):
        d = os.path.join(ROOT, "scenarios", name)
        if os.path.exists(os.path.join(d, "k8s", "trainee-role.yaml")):
            with open(os.path.join(d, "scenario.yaml")) as f:
                y = f.read()
            title = re.search(r"^\s+title:\s*(.+)$", y, re.M)
            diff = re.search(r"^\s+difficulty:\s*(\d+)", y, re.M)
            mins = re.search(r"^\s+est_minutes:\s*(\d+)", y, re.M)
            out.append({"id": name, "title": title.group(1).strip() if title else name,
                        "difficulty": int(diff.group(1)) if diff else None,
                        "est_minutes": int(mins.group(1)) if mins else None})
    return out


class Range:
    def __init__(self):
        self.lock = threading.Lock()
        self.by_user = {}          # user -> session dict

    def active(self):
        return [s for s in self.by_user.values() if s["status"] in ("starting", "ready", "grading", "graded")]

    def run(self, s, *args, env_extra=None, timeout=900):
        env = dict(os.environ, **(env_extra or {}))
        p = subprocess.run(["bash", RANGE_SH, *args], capture_output=True, text=True, env=env, timeout=timeout)
        s["log"] = (s.get("log", "") + p.stdout + p.stderr)[-4000:]
        return p

    def start(self, user, scenario, token):
        if scenario not in {x["id"] for x in scenarios()}:
            return 400, {"error": f"unknown scenario {scenario!r}"}
        with self.lock:
            mine = self.by_user.get(user)
            if mine and mine["status"] in ("starting", "ready", "grading", "graded"):
                return 409, {"error": "you already have a running incident: stop it first", "session": self.view(mine)}
            if len(self.active()) >= MAX_SESSIONS:
                return 429, {"error": "the range is full right now, try again in a few minutes"}
            s = {"user": user, "scenario": scenario, "status": "starting", "created": time.time(), "id": None}
            self.by_user[user] = s

        def work():
            try:
                # the user's own IdP token creates the graded attempt: the grader sees who it is
                p = self.run(s, "start", scenario, user, env_extra={"VANTAGE_USER_TOKEN": token})
                lines = [l for l in p.stdout.strip().splitlines() if l.strip()]
                if p.returncode == 0 and lines and re.fullmatch(r"[0-9a-f]{8}", lines[-1]):
                    s.update(id=lines[-1], status="ready", ready_at=time.time())
                else:
                    s["status"] = "failed"
            except subprocess.TimeoutExpired:
                s["status"] = "failed"
        threading.Thread(target=work, daemon=True).start()
        return 202, {"session": self.view(s)}

    def grade(self, user):
        s = self.by_user.get(user)
        if not s or s["status"] != "ready":
            return 409, {"error": "no incident ready to grade"}
        s["status"] = "grading"
        p = self.run(s, "grade", s["id"], timeout=600)
        report = os.path.join(SESSIONS_DIR, s["id"], "state", "evidence", "server_report.json")
        if p.returncode in (0, 1) and os.path.exists(report):
            with open(report) as f:
                s.update(status="graded", result=json.load(f)["result"])
            return 200, {"session": self.view(s), "result": s["result"]}
        s["status"] = "ready"            # nothing was submitted: the trainee may try again
        return 502, {"error": "grading did not complete", "log": s["log"][-1500:]}

    def stop(self, user):
        s = self.by_user.get(user)
        if not s:
            return 404, {"error": "no session"}
        if s.get("id"):
            self.run(s, "stop", s["id"], timeout=300)
        s["status"] = "stopped"
        return 200, {"session": self.view(s)}

    def kubeconfig(self, user):
        s = self.by_user.get(user)
        if not s or s["status"] not in ("ready", "grading", "graded"):
            return 404, {"error": "no running incident"}
        with open(os.path.join(SESSIONS_DIR, s["id"], "trainee.kubeconfig")) as f:
            return 200, f.read()

    def reap(self):
        for s in list(self.by_user.values()):
            if s["status"] in ("ready", "graded") and time.time() - s["created"] > TTL_S:
                self.stop(s["user"])
                s["status"] = "expired"

    @staticmethod
    def view(s):
        return {k: s.get(k) for k in ("scenario", "status", "created", "ready_at", "id")} | {
            "expires": s["created"] + TTL_S, "tier": (s.get("result") or {}).get("tier"),
            "score": (s.get("result") or {}).get("score"),
            "log_tail": s.get("log", "")[-600:] if s["status"] == "failed" else None}


def grader_get(path):
    url = os.environ.get("GRADER_URL", "http://127.0.0.1:8700").rstrip("/") + path
    try:
        with NOPROXY.open(url, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": f"grader: http {e.code}"}
    except OSError as e:
        return 502, {"error": f"grader unreachable: {e}"}


def make_handler(rng):
    class H(http.server.BaseHTTPRequestHandler):
        def reply(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def user(self):
            tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            user, _team, _source = grader.authenticate(tok)
            return user, tok

        def route(self, method):
            path = urllib.parse.urlsplit(self.path).path
            try:
                if method == "GET" and path == "/":
                    with open(PANEL) as f:
                        return self.reply(200, f.read(), "text/html; charset=utf-8")
                if method == "GET" and path == "/config.json":
                    return self.reply(200, {"supabase_url": os.environ.get("PANEL_SUPABASE_URL", ""),
                                            "supabase_key": os.environ.get("PANEL_SUPABASE_KEY", "")})
                if method == "GET" and path == "/api/scenarios":
                    return self.reply(200, {"scenarios": scenarios()})
                if method == "GET" and path == "/api/league":
                    return self.reply(*grader_get("/v1/league"))
                if not path.startswith("/api/"):
                    return self.reply(404, {"error": "not found"})
                user, tok = self.user()
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(min(n, 10_000)) or b"{}")
                routes = {
                    ("POST", "/api/sessions"): lambda: rng.start(user, str(body.get("scenario", "")), tok),
                    ("GET", "/api/sessions/mine"): lambda: (200, {"user": user, "session": rng.view(rng.by_user[user])})
                    if user in rng.by_user else (200, {"user": user, "session": None}),
                    ("GET", "/api/sessions/mine/kubeconfig"): lambda: rng.kubeconfig(user),
                    ("POST", "/api/sessions/mine/grade"): lambda: rng.grade(user),
                    ("POST", "/api/sessions/mine/stop"): lambda: rng.stop(user),
                    ("GET", "/api/profile"): lambda: grader_get(f"/v1/users/{urllib.parse.quote(user, safe='')}/profile"),
                }
                fn = routes.get((method, path))
                if not fn:
                    return self.reply(404, {"error": "not found"})
                code, out = fn()
                return self.reply(code, out, "application/yaml" if isinstance(out, str) else "application/json")
            except PermissionError as e:
                return self.reply(401, {"error": str(e)})
            except json.JSONDecodeError:
                return self.reply(400, {"error": "invalid json"})
            except Exception as e:  # never drop the connection without an answer
                sys.stderr.write(f"range api error: {type(e).__name__}: {e}\n")
                return self.reply(500, {"error": "internal error"})

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def log_message(self, fmt, *args):
            sys.stderr.write("%s range-api %s\n" % (time.strftime("%H:%M:%S"), fmt % args))
    return H


def serve(port):
    rng = Range()

    def reaper():
        while True:
            time.sleep(60)
            rng.reap()
    threading.Thread(target=reaper, daemon=True).start()
    return rng, http.server.ThreadingHTTPServer(("0.0.0.0", port), make_handler(rng))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("RANGE_API_PORT", "8780")))
    rng, srv = serve(ap.parse_args().port)
    sys.stderr.write(f"range api + panel on :{srv.server_address[1]}\n")
    srv.serve_forever()
