"""Hosted range API without a cluster: a stub range.sh, real JWT checks.

    python -m unittest range/tests/test_api.py -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp()
STUB = os.path.join(TMP, "range.sh")
with open(STUB, "w") as f:
    f.write(r'''#!/usr/bin/env bash
# stand-in for range.sh: records what it was asked, fakes the files the API reads
echo "$*|${VANTAGE_USER_TOKEN:+token}" >> "$RANGE_SESSIONS/calls.log"
case "$1" in
  start) [[ "$2" == boom ]] && { echo "xx cluster on fire" >&2; exit 1; }
         id=$(printf '%08x' $RANDOM$RANDOM); mkdir -p "$RANGE_SESSIONS/$id/state/evidence"
         echo "apiVersion: v1 # for $3" > "$RANGE_SESSIONS/$id/trainee.kubeconfig"
         echo "==> session $id"; echo "$id" ;;
  grade) echo '{"result": {"tier": "merit", "score": 84.2, "attested": true}}' > "$RANGE_SESSIONS/$2/state/evidence/server_report.json" ;;
  stop)  echo stopped ;;
esac
''')
os.environ.update(RANGE_SH=STUB, RANGE_SESSIONS=TMP, RANGE_MAX_SESSIONS="2", GRADER_URL="http://127.0.0.1:9")
sys.path.insert(0, os.path.join(ROOT, "range"))
sys.path.insert(0, os.path.join(ROOT, "grader"))
import api  # noqa: E402
import test_jwks  # noqa: E402

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = test_jwks.Key(TMP, "EC", "idp-1")
        path = os.path.join(TMP, "jwks.json")
        json.dump({"keys": [cls.key.jwk]}, open(path, "w"))
        api.grader.JWKS_URL, api.grader.JWT_ISSUER = "file://" + path, test_jwks.ISS
        cls.rng, cls.srv = api.serve(0)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    def call(self, method, path, email=None, body=None, token=None):
        tok = token or (self.key.token(test_jwks.claims(email=email)) if email else None)
        req = urllib.request.Request(self.url + path, method=method, data=json.dumps(body or {}).encode()
                                     if method == "POST" else None,
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {tok}"} if tok else {})})
        try:
            with OP.open(req, timeout=10) as r:
                raw = r.read()
                return r.status, json.loads(raw) if "json" in r.headers.get("Content-Type", "") else raw.decode()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait(self, email, status):
        for _ in range(50):
            s = self.call("GET", "/api/sessions/mine", email)[1]["session"]
            if s and s["status"] == status:
                return s
            time.sleep(0.1)
        self.fail(f"session of {email} never became {status}: {s}")

    def test_panel_and_public_endpoints(self):
        code, html = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn("Vantage Range", html)
        scn = self.call("GET", "/api/scenarios")[1]["scenarios"]
        self.assertEqual({s["id"] for s in scn}, {"certificate-apocalypse", "clock-drift", "dns-poison", "retry-storm"})

    def test_login_is_required(self):
        self.assertEqual(self.call("GET", "/api/sessions/mine")[0], 401)
        forged = self.key.token(test_jwks.claims(email="a@x")).rsplit(".", 1)[0] + "." + test_jwks.b64u(b"\0" * 64)
        self.assertEqual(self.call("POST", "/api/sessions", body={"scenario": "dns-poison"}, token=forged)[0], 401)

    def test_full_flow_for_one_user(self):
        u = "flow@x"
        self.assertEqual(self.call("POST", "/api/sessions", u, {"scenario": "nope"})[0], 400)
        self.assertEqual(self.call("POST", "/api/sessions", u, {"scenario": "dns-poison"})[0], 202)
        self.assertEqual(self.call("POST", "/api/sessions", u, {"scenario": "clock-drift"})[0], 409)   # one at a time
        self.wait(u, "ready")
        code, kc = self.call("GET", "/api/sessions/mine/kubeconfig", u)
        self.assertEqual(code, 200)
        self.assertIn(f"for {u}", kc)
        # nobody else gets my kubeconfig
        self.assertEqual(self.call("GET", "/api/sessions/mine/kubeconfig", "intruder@x")[0], 404)
        code, res = self.call("POST", "/api/sessions/mine/grade", u)
        self.assertEqual((code, res["result"]["tier"]), (200, "merit"))
        self.assertEqual(self.call("POST", "/api/sessions/mine/stop", u)[1]["session"]["status"], "stopped")
        calls = open(os.path.join(TMP, "calls.log")).read()
        self.assertIn(f"start dns-poison {u}|token", calls)      # the user's own IdP token reaches the grader
        # the admin funnel saw this user's whole path, and only admins see it
        self.assertEqual(self.call("GET", "/api/admin/funnel", u)[0], 403)
        api.ADMIN_TOKEN = "admin-secret"
        self.addCleanup(setattr, api, "ADMIN_TOKEN", "")
        req = urllib.request.Request(self.url + "/api/admin/funnel", headers={"X-Admin-Token": "admin-secret"})
        with OP.open(req, timeout=10) as r:
            f = json.loads(r.read())
        self.assertGreaterEqual(f["stages"]["graded"], 1)
        self.assertGreaterEqual(f["stages"]["kubeconfig"], 1)

    def test_failed_start_is_reported_and_capacity_is_bounded(self):
        self.call("POST", "/api/sessions", "boom@x", {"scenario": "dns-poison"})
        # a failing start (the stub fails for "boom", which the API itself would refuse as unknown)
        s = self.rng.by_user.setdefault("broken@x", {"user": "broken@x", "scenario": "boom", "status": "starting",
                                                     "created": time.time(), "id": None})
        p = self.rng.run(s, "start", "boom", "broken@x")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("cluster on fire", s["log"])
        s["status"] = "failed"
        self.wait("boom@x", "ready")
        self.call("POST", "/api/sessions", "second@x", {"scenario": "retry-storm"})
        code, res = self.call("POST", "/api/sessions", "third@x", {"scenario": "retry-storm"})
        self.assertEqual(code, 429, res)                           # RANGE_MAX_SESSIONS=2
        for u in ("boom@x", "second@x"):
            self.wait(u, "ready")
            self.call("POST", "/api/sessions/mine/stop", u)


class Funnel(unittest.TestCase):
    def test_stages_conversion_stuck_and_return(self):
        import telemetry
        t = telemetry.Telemetry(os.path.join(TMP, "funnel.db"))
        self.addCleanup(t.db.close)
        clock = [1_790_000_000.0]
        real = telemetry.time.time
        telemetry.time.time = lambda: clock[0]
        self.addCleanup(setattr, telemetry.time, "time", real)

        def at(dt, user, ev, **kw):
            clock[0] += dt
            t.record(user, ev, scenario="dns-poison", **kw)
        # ann: full pass; bob: never downloads the kubeconfig; cid: fails, comes back next day and passes
        at(0, "ann@x", "start"); at(60, "ann@x", "ready"); at(30, "ann@x", "kubeconfig")
        at(600, "ann@x", "graded", tier="merit", attested=True)
        at(5, "bob@x", "start"); at(90, "bob@x", "ready")
        at(5, "cid@x", "start"); at(70, "cid@x", "ready"); at(10, "cid@x", "kubeconfig")
        at(900, "cid@x", "graded", tier="fail", attested=True)
        at(86400, "cid@x", "start"); at(60, "cid@x", "ready"); at(20, "cid@x", "kubeconfig")
        at(400, "cid@x", "graded", tier="pass", attested=True)
        f = t.funnel()
        self.assertEqual(f["stages"], {"start": 4, "ready": 4, "kubeconfig": 3, "graded": 3, "passed": 2})
        self.assertEqual(f["stuck_after"]["ready"], 1)          # bob
        self.assertEqual(f["stuck_after"]["graded"], 1)         # cid's failed first try
        self.assertEqual((f["users"], f["returned_users"]), (3, 1))
        self.assertEqual(f["median_times"]["start->ready_s"], 65.0)
        self.assertEqual(f["conversion"]["ready->kubeconfig"], 0.75)
        self.assertNotIn("ann@x", json.dumps(f))                # aliases only
        rows = t.db.execute("SELECT DISTINCT user FROM events").fetchall()
        self.assertTrue(all(r[0].startswith("u-") for r in rows))
        with self.assertRaises(ValueError):
            t.record("ann@x", "keystrokes")                     # only the declared events


if __name__ == "__main__":
    unittest.main()
