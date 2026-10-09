"""Grader tests: the happy path plus the attacks it is meant to stop.

    python -m unittest grader/test_grader.py -v
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ASSERTIONS = {"public_pass": True, "hidden_pass": 6, "hidden_total": 6,
              "assertions": [{"id": f"H{i}", "visibility": "hidden", "pass": True} for i in range(1, 7)]}


class GraderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.STABLE_WINDOW = 4.0          # short windows keep the tests fast
        cls.tmp = tempfile.mkdtemp()
        server.PLATFORM_TOKEN = "platform-secret"
        server.HIDDEN_PACKS = os.path.join(cls.tmp, "packs.json")
        json.dump({"certificate-apocalypse": ["a" * 64]}, open(server.HIDDEN_PACKS, "w"))
        cls.g, cls.srv = server.serve(0, cls.tmp, os.path.join(ROOT, "scenarios"))
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, method, path, body=None, token=None, headers=None):
        req = urllib.request.Request(self.url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {token}"} if token else {}),
                                              **(headers or {})})
        try:
            with OP.open(req, timeout=5) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def start(self, scenario="certificate-apocalypse"):
        code, a = self.call("POST", "/v1/attempts", {"user": "t@x", "scenario": scenario})
        self.assertEqual(code, 201)
        a["host"] = f"api-{a['seed'][:6]}.vantage.local"
        a["flag"] = server.expected_flag(a["seed"], a["host"])
        return a

    def ev(self, a, etype, data=None):
        return self.call("POST", f"/v1/attempts/{a['attempt_id']}/events", {"type": etype, "data": data or {}}, a["token"])

    def send(self, a, probes):
        return self.call("POST", f"/v1/attempts/{a['attempt_id']}/probes", {"probes": probes}, a["token"])

    def live(self, a, n, ok, flag=None, dt=0.5):
        """Send n probes in (accelerated) real time: ts = now, one batch per probe."""
        for _ in range(n):
            self.send(a, [{"ts": time.time(), "ok": ok, "lat_ms": 5, "flag": flag if ok else None,
                           "err": None if ok else "simulated"}])
            time.sleep(dt)

    def submit(self, a, assertions=ASSERTIONS, headers=None):
        return self.call("POST", f"/v1/attempts/{a['attempt_id']}/submit",
                         {"assertions": assertions, "mode": "docker", "baseline": {}, "current": {}}, a["token"],
                         headers)

    # --- tests -----------------------------------------------------------------
    def test_happy_path_scores_and_signs(self):
        a = self.start()
        self.assertEqual(self.ev(a, "break", {"host": a["host"]})[0], 200)
        self.live(a, 3, ok=False, dt=0.3)
        self.live(a, 18, ok=True, flag=a["flag"], dt=0.3)  # > STABLE_WINDOW of health
        code, res = self.submit(a)
        self.assertEqual(code, 200, res)
        r = res["result"]
        self.assertTrue(r["attested"], r["integrity"])
        self.assertTrue(r["integrity"]["server_stable_ok"])
        self.assertIsNotNone(r["sli"]["mttr_s"])
        self.assertNotEqual(r["tier"], "fail")
        # signature verifies with the published key over canonical JSON
        _, pem = self.call("GET", "/v1/pubkey")
        with tempfile.TemporaryDirectory() as d:
            for name, data in (("pub.pem", pem), ("msg", server.canonical(r)), ("sig", base64.b64decode(res["signature"]))):
                open(os.path.join(d, name), "wb").write(data)
            v = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", f"{d}/pub.pem", "-rawin",
                                "-in", f"{d}/msg", "-sigfile", f"{d}/sig"], capture_output=True)
            self.assertEqual(v.returncode, 0, v.stdout + v.stderr)

    def test_assertion_trust_needs_the_platform_token(self):
        private = dict(ASSERTIONS, hidden_pack={"source": "private", "sha256": "a" * 64})
        cases = [  # (header, pack) -> trust
            (None, private, ("client-reported", "client-reported")),                 # trainee claims a private pack
            ({"X-Vantage-Platform": "guess"}, private, ("client-reported", "client-reported")),
            ({"X-Vantage-Platform": "platform-secret"}, ASSERTIONS, ("platform", "platform, public pack")),
            ({"X-Vantage-Platform": "platform-secret"}, private, ("platform", "platform, private pack")),
        ]
        for headers, asr, (want_asr, want_hidden) in cases:
            a = self.start()
            self.ev(a, "break", {"host": a["host"]})
            self.live(a, 10, ok=True, flag=a["flag"], dt=0.5)
            code, res = self.submit(a, asr, headers)
            self.assertEqual(code, 200, res)
            t = res["result"]["trust"]
            self.assertEqual((t["assertions"], t["hidden"]), (want_asr, want_hidden), headers)

    def test_unregistered_pack_is_not_private(self):
        g = server.Grader
        self.assertEqual(g.hidden_trust(True, "certificate-apocalypse", {"sha256": "b" * 64}), "platform, public pack")
        self.assertEqual(g.hidden_trust(True, "dns-poison", {"sha256": "a" * 64}), "platform, public pack")
        self.assertEqual(g.hidden_trust(True, "certificate-apocalypse", None), "platform, public pack")

    def test_backfilled_probes_are_rejected(self):
        a = self.start()
        self.ev(a, "break", {"host": a["host"]})
        old = time.time() - 300
        code, r = self.send(a, [{"ts": old + i, "ok": True, "lat_ms": 5, "flag": a["flag"]} for i in range(20)])
        self.assertEqual((r["accepted"], r["rejected"]), (0, 20))

    def test_replayed_probes_are_rejected(self):
        a = self.start()
        self.ev(a, "break", {"host": a["host"]})
        p = {"ts": time.time(), "ok": True, "lat_ms": 5, "flag": a["flag"]}
        self.assertEqual(self.send(a, [p])[1]["accepted"], 1)
        self.assertEqual(self.send(a, [p])[1]["rejected"], 1)

    def test_wrong_flag_never_counts_as_healthy(self):
        a = self.start()
        self.ev(a, "break", {"host": a["host"]})
        self.live(a, 2, ok=False, dt=0.3)
        self.live(a, 14, ok=True, flag="0" * 24, dt=0.3)   # a fake backend's 200s
        code, res = self.submit(a)
        r = res["result"]
        self.assertEqual(r["integrity"]["probes_with_wrong_flag"], 14)
        self.assertFalse(r["attested"])
        self.assertEqual(r["tier"], "unverified")
        self.assertFalse(r["integrity"]["server_stable_ok"])

    def test_honest_client_with_skewed_clock_is_attested(self):
        skew = 120.0                                         # trainee laptop 2 minutes fast
        code, a = self.call("POST", "/v1/attempts", {"user": "t", "scenario": "certificate-apocalypse",
                                                     "client_time": time.time() + skew})
        a["host"] = f"api-{a['seed'][:6]}.vantage.local"
        flag = server.expected_flag(a["seed"], a["host"])
        self.ev(a, "break", {"host": a["host"]})
        for ok, n in ((False, 3), (True, 18)):
            for _ in range(n):
                self.send(a, [{"ts": time.time() + skew, "ok": ok, "lat_ms": 5, "flag": flag if ok else None}])
                time.sleep(0.3)
        r = self.submit(a)[1]["result"]
        self.assertTrue(r["attested"], r["integrity"])
        self.assertIsNotNone(r["sli"]["mttr_s"])
        self.assertLess(r["sli"]["mttr_s"], 5)

    def test_backfill_mixed_with_live_is_not_attested(self):
        a = self.start()
        self.ev(a, "break", {"host": a["host"]})
        self.live(a, 3, ok=False, dt=0.3)
        self.send(a, [{"ts": time.time() - 60 + i, "ok": True, "lat_ms": 1, "flag": a["flag"]} for i in range(30)])
        self.live(a, 18, ok=True, flag=a["flag"], dt=0.3)
        r = self.submit(a)[1]["result"]
        self.assertFalse(r["attested"])
        self.assertEqual(r["tier"], "unverified")

    def test_server_stability_overrides_client_claim(self):
        a = self.start()
        self.ev(a, "break", {"host": a["host"]})
        self.live(a, 2, ok=False, dt=0.3)
        self.live(a, 3, ok=True, flag=a["flag"], dt=0.3)
        time.sleep(4.5)                                      # prober went silent
        code, res = self.submit(a)
        r = res["result"]
        self.assertFalse(r["integrity"]["server_stable_ok"])
        self.assertFalse(r["assertions"]["public_pass"])
        self.assertEqual(r["tier"], "fail")

    def test_break_time_is_the_servers(self):
        a = self.start()
        self.ev(a, "break", {"host": a["host"]})
        code, _ = self.ev(a, "break", {"host": a["host"]})
        self.assertEqual(code, 409)                          # cannot move the incident start

    def test_host_must_match_seed(self):
        a = self.start()
        code, _ = self.ev(a, "break", {"host": "api-000000.vantage.local"})
        self.assertEqual(code, 400)

    def test_token_and_single_submit(self):
        a = self.start()
        self.assertEqual(self.call("POST", f"/v1/attempts/{a['attempt_id']}/events", {"type": "break"}, "nope")[0], 403)
        self.ev(a, "break", {"host": a["host"]})
        self.live(a, 2, ok=False, dt=0.3)
        self.live(a, 18, ok=True, flag=a["flag"], dt=0.3)  # > STABLE_WINDOW of health
        self.assertEqual(self.submit(a)[0], 200)
        self.assertEqual(self.submit(a)[0], 409)
        self.assertEqual(self.send(a, [{"ts": time.time(), "ok": True}])[0], 409)

    def test_unknown_scenario(self):
        code, _ = self.call("POST", "/v1/attempts", {"user": "x", "scenario": "../../etc"})
        self.assertEqual(code, 404)

    def test_seeds_are_per_attempt(self):
        self.assertNotEqual(self.start()["seed"], self.start()["seed"])


if __name__ == "__main__":
    unittest.main()
