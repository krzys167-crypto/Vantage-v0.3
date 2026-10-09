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
import debrief as pm  # noqa: E402  (framework/, on the path via server)

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

    def start(self, scenario="certificate-apocalypse", user="t@x", headers=None):
        code, a = self.call("POST", "/v1/attempts", {"user": user, "scenario": scenario}, headers=headers)
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

    # --- post-mortem helpers ----------------------------------------------------
    def user_key(self):
        path = os.path.join(self.tmp, f"user-{time.time_ns()}.key")
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", path], check=True, capture_output=True)
        pub = subprocess.run(["openssl", "pkey", "-in", path, "-pubout"], check=True, capture_output=True, text=True)
        return path, pub.stdout

    def incident(self, scenario="retry-storm", user="t@x", headers=None):
        """Graded attempt that fails for a moment, then recovers; returns (attempt, recovery time)."""
        a = self.start(scenario, user, headers)
        self.ev(a, "break", {"host": a["host"]})
        self.live(a, 3, ok=False, dt=0.3)
        recovered = time.time()
        self.live(a, 15, ok=True, flag=a["flag"], dt=0.3)
        code, res = self.submit(a)
        self.assertEqual(code, 200, res)
        return a, recovered

    @staticmethod
    def postmortem(a, causes, mitigated, detected=None, evidence=""):
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))  # noqa: E731
        hm = lambda t: time.strftime("%H:%M:%SZ", time.gmtime(t))  # noqa: E731
        t0 = mitigated - 5
        return f"""---
attempt: {a['attempt_id']}
detected: {iso(detected or t0)}
mitigated: {iso(mitigated)}
causes: {', '.join(causes)}
---
# Post-mortem
## Summary
Checkouts failed.
## Impact
All users for a few seconds.
## Timeline
- {hm(t0)} alert: checkout errors
- {hm(t0 + 1)} inventory metrics: 8x amplification
- {hm(t0 + 2)} retry policy reverted
- {hm(mitigated)} checkouts served again
## Root cause
See causes. {evidence}
## Resolution
Reverted both changes.
## Action items
- [prevent] review retry policies against a load model
- [detect] alert on attempts per checkout
"""

    def send_pm(self, a, md, key):
        path, pub = key
        with tempfile.NamedTemporaryFile() as msg:
            msg.write(pm.message(a["attempt_id"], md))
            msg.flush()
            sig = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", path, "-rawin", "-in", msg.name],
                                 check=True, capture_output=True).stdout
        return self.call("POST", f"/v1/attempts/{a['attempt_id']}/debrief",
                         {"markdown": md, "pubkey": pub, "signature": base64.b64encode(sig).decode()}, a["token"])

    def truth(self, a, scenario="retry-storm"):
        cat = self.g.debrief_cfg(scenario)
        return cat, pm.occurred(cat, a["seed"])

    # --- tests -----------------------------------------------------------------
    def test_postmortem_verified_against_evidence(self):
        a, recovered = self.incident(user="pm-ok@x")
        _, (root, contrib) = self.truth(a)
        self.assertEqual(len(root), 2)
        self.assertEqual(contrib, {"traffic_burst"})
        cat, _ = self.truth(a)
        evidence = "Changes " + " and ".join(pm.facts(cat, a["seed"]).values()) + " went out together."
        md = self.postmortem(a, sorted(root | contrib), recovered + 2, evidence=evidence)
        code, res = self.send_pm(a, md, self.user_key())
        self.assertEqual(code, 200, res)
        r = res["result"]
        self.assertEqual(r["verdict"], "verified", r)
        self.assertEqual(r["causes"]["missed"], [])
        self.assertEqual(r["facts"]["missing"], [])
        self.assertLess(r["timeline"]["mitigated_error_s"], 5)
        self.assertGreaterEqual(r["score"], 95)
        self.assertTrue(r["trust"]["causes"].startswith("local run"))
        # signed by the grader, readable later, and only one per attempt
        _, pem = self.call("GET", "/v1/pubkey")
        with tempfile.TemporaryDirectory() as d:
            for name, data in (("pub.pem", pem), ("msg", server.canonical(r)), ("sig", base64.b64decode(res["signature"]))):
                open(os.path.join(d, name), "wb").write(data)
            v = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", f"{d}/pub.pem", "-rawin",
                                "-in", f"{d}/msg", "-sigfile", f"{d}/sig"], capture_output=True)
            self.assertEqual(v.returncode, 0)
        self.assertEqual(self.call("GET", f"/v1/attempts/{a['attempt_id']}/debrief", token=a["token"])[1]["result"], r)
        self.assertEqual(self.send_pm(a, md, self.user_key())[0], 409)

    def test_postmortem_with_wrong_causes_or_timeline_is_insufficient(self):
        a, recovered = self.incident(user="pm-wrong@x")
        cat, (root, _) = self.truth(a)
        # the other variants of the same faults plus a decoy: plausible, not what happened
        wrong = sorted({c["id"] for c in cat["causes"] if c.get("when")} - root) + ["inventory_memory_leak"]
        md = self.postmortem(a, wrong, recovered + 600)   # and a made-up recovery time
        code, res = self.send_pm(a, md, self.user_key())
        self.assertEqual(code, 200, res)
        r = res["result"]
        self.assertEqual(r["verdict"], "insufficient")
        self.assertEqual(sorted(r["causes"]["missed"]), sorted(root))
        self.assertEqual(len(r["causes"]["wrong"]), 3)
        self.assertEqual(r["parts"]["mitigated"], 0)
        self.assertLess(r["score"], 40)

    def test_postmortem_must_quote_the_evidence(self):
        """Right causes from the catalog alone are not enough: the values only the
        evidence shows (here the change ids) must be in the write-up."""
        a, recovered = self.incident(user="pm-facts@x")
        cat, (root, contrib) = self.truth(a)
        want = pm.facts(cat, a["seed"])
        md = self.postmortem(a, sorted(root | contrib), recovered, evidence="Two changes went out the same day.")
        r = self.send_pm(a, md, self.user_key())[1]["result"]
        self.assertEqual(r["verdict"], "insufficient")
        self.assertEqual(r["facts"]["missing"], sorted(want))
        # the feedback names what to look for, never the values themselves
        self.assertFalse(any(v in json.dumps(r) for v in want.values()), r["facts"])

    def test_fact_values_follow_the_seed_like_the_scenario_scripts(self):
        seed = "0123456789abcdef" * 4
        f = lambda s: pm.facts(self.g.debrief_cfg(s), seed)  # noqa: E731
        self.assertEqual(f("retry-storm"), {"capacity_change": "CHG-6748", "retry_change": "CHG-6749"})   # init.sh: 4000 + 0xabc % 5000
        self.assertEqual(f("dns-poison"), {"legacy_instance": "payments-old-cluster", "poisoned_ttl": "52200"})
        self.assertEqual(f("clock-drift"), {"drift_seconds": "396", "unrelated_idp": "login.acme-hr.example"})
        self.assertNotIn("poisoned_ttl", pm.facts(self.g.debrief_cfg("dns-poison"), "f" * 64))   # hosts.json variant
        for text, value, hit in (("off by -396 s", "396", True), ("396s", "396", True), ("1396", "396", False),
                                 ("rolled back CHG-4000.", "CHG-4000", True), ("CHG-40001", "CHG-4000", False)):
            self.assertEqual(pm.quotes(text, value), hit, (text, value))

    def test_listing_every_cause_is_not_a_strategy(self):
        a, recovered = self.incident(user="pm-all@x")
        cat, _ = self.truth(a)
        md = self.postmortem(a, [c["id"] for c in cat["causes"]], recovered)
        r = self.send_pm(a, md, self.user_key())[1]["result"]
        self.assertEqual(r["causes"]["missed"], [])
        self.assertEqual(r["verdict"], "insufficient", r["parts"])     # recall 1, precision 3/8

    def test_postmortem_needs_submit_signature_and_valid_format(self):
        key = self.user_key()
        a = self.start("retry-storm", "pm-format@x")
        self.ev(a, "break", {"host": a["host"]})
        self.assertEqual(self.send_pm(a, self.postmortem(a, ["traffic_burst"], time.time()), key)[0], 409)
        self.live(a, 12, ok=True, flag=a["flag"], dt=0.4)
        self.assertEqual(self.submit(a)[0], 200)
        md = self.postmortem(a, ["traffic_burst"], time.time())
        # a signature over another text (or no real signature) is refused and changes nothing
        forged = self.call("POST", f"/v1/attempts/{a['attempt_id']}/debrief",
                           {"markdown": md, "pubkey": key[1], "signature": base64.b64encode(b"x" * 64).decode()},
                           a["token"])
        self.assertEqual(forged[0], 403)
        self.assertEqual(self.send_pm(a, md, key)[0], 200)
        # format problems never use up the one post-mortem
        b = self.start("retry-storm", "pm-format@x")
        self.ev(b, "break", {"host": b["host"]})
        self.live(b, 12, ok=True, flag=b["flag"], dt=0.4)
        self.submit(b)
        code, res = self.send_pm(b, self.postmortem(b, ["made_up_cause"], time.time()), key)
        self.assertEqual(code, 422)
        self.assertIn("unknown cause", " ".join(res["problems"]))
        code, res = self.send_pm(b, self.postmortem(a, ["traffic_burst"], time.time()), key)   # other attempt id
        self.assertEqual(code, 422)
        self.assertEqual(self.send_pm(b, self.postmortem(b, ["traffic_burst"], time.time()), key)[0], 200)

    def test_postmortem_key_is_bound_to_the_user(self):
        tok = self.with_identities()          # only users the platform vouches for get a bound key
        a, rec = self.incident(headers=tok("pm-key@x"))
        b, rec_b = self.incident(headers=tok("pm-key@x"))
        self.assertEqual(self.send_pm(a, self.postmortem(a, ["traffic_burst"], rec), self.user_key())[0], 200)
        code, res = self.send_pm(b, self.postmortem(b, ["traffic_burst"], rec_b), self.user_key())
        self.assertEqual(code, 403, res)
        self.assertIn("another key", res["error"])

    def test_profile_and_league_come_from_signed_evidence(self):
        import league
        user = "league@x"
        a, recovered = self.incident(user=user)
        cat, (root, contrib) = self.truth(a)
        evidence = " ".join(pm.facts(cat, a["seed"]).values())
        self.assertEqual(self.send_pm(a, self.postmortem(a, sorted(root | contrib), recovered, evidence=evidence),
                                      self.user_key())[0], 200)
        code, res = self.call("GET", "/v1/users/league%40x/profile")
        self.assertEqual(code, 200, res)
        p = res["result"]
        got = {b["badge"] for b in p["badges"]}
        self.assertTrue({"first_recovery", "forensic", "coroner"} <= got, got)
        self.assertTrue(all(b["attempt_id"] == a["attempt_id"] for b in p["badges"]))
        self.assertEqual(p["scenarios"]["retry-storm"]["best_attempt"], a["attempt_id"])
        _, pem = self.call("GET", "/v1/pubkey")
        with tempfile.TemporaryDirectory() as d:
            for name, data in (("pub.pem", pem), ("msg", server.canonical(p)), ("sig", base64.b64decode(res["signature"]))):
                open(os.path.join(d, name), "wb").write(data)
            v = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", f"{d}/pub.pem", "-rawin",
                                "-in", f"{d}/msg", "-sigfile", f"{d}/sig"], capture_output=True)
            self.assertEqual(v.returncode, 0)
        code, res = self.call("GET", f"/v1/league?season={league.season(time.time())}")
        self.assertEqual(code, 200, res)
        rows = {r["alias"]: r for r in res["result"]["rows"]}
        self.assertIn(league.alias(user), rows)
        self.assertNotIn(user, json.dumps(res))
        self.assertEqual(self.call("GET", "/v1/league?season=oct")[0], 400)

    def with_identities(self):
        """Run the rest of a test against a grader that requires platform user tokens."""
        server.USER_SECRET = "user-secret"
        self.addCleanup(setattr, server, "USER_SECRET", "")
        import identity
        return lambda user, team=None: {"X-Vantage-User": identity.issue("user-secret", user, team)}

    def start_as(self, headers, scenario="retry-storm", user="claimed@x"):
        return self.call("POST", "/v1/attempts", {"user": user, "scenario": scenario}, headers=headers)

    def test_platform_identity_decides_who_the_attempt_belongs_to(self):
        tok = self.with_identities()
        self.assertEqual(self.start_as(None)[0], 401)
        self.assertEqual(self.start_as({"X-Vantage-User": "forged.token"})[0], 401)
        import identity
        expired = identity.issue("user-secret", "jan@x", now=1000)
        self.assertEqual(self.start_as({"X-Vantage-User": expired})[0], 401)
        code, a = self.start_as(tok("jan@x", "sre-waw"), user="ceo@x")      # the body's user is ignored
        self.assertEqual(code, 201, a)
        self.assertEqual((a["user"], a["identity"]), ("jan@x", "platform token"))
        a["host"] = f"api-{a['seed'][:6]}.vantage.local"
        a["flag"] = server.expected_flag(a["seed"], a["host"])
        self.ev(a, "break", {"host": a["host"]})
        self.live(a, 12, ok=True, flag=a["flag"], dt=0.4)
        r = self.submit(a)[1]["result"]
        self.assertEqual((r["user"], r["team"], r["trust"]["identity"]), ("jan@x", "sre-waw", "platform token"))

    def test_self_declared_names_cannot_squat_a_post_mortem_key(self):
        # without identities an attacker starts an attempt as the victim and signs with their own key
        a, rec = self.incident(user="victim@x")
        r = self.send_pm(a, self.postmortem(a, ["traffic_burst"], rec), self.user_key())[1]["result"]
        self.assertIn("not bound", r["trust"]["author"])
        # once the platform vouches for the victim, their own key binds without a fight
        tok = self.with_identities()
        code, b = self.start_as(tok("victim@x"))
        self.assertEqual(code, 201, b)
        b["host"] = f"api-{b['seed'][:6]}.vantage.local"
        b["flag"] = server.expected_flag(b["seed"], b["host"])
        self.ev(b, "break", {"host": b["host"]})
        self.live(b, 3, ok=False, dt=0.3)
        rec_b = time.time()
        self.live(b, 12, ok=True, flag=b["flag"], dt=0.3)
        self.assertEqual(self.submit(b)[0], 200)
        code, res = self.send_pm(b, self.postmortem(b, ["traffic_burst"], rec_b), self.user_key())
        self.assertEqual(code, 200, res)
        self.assertIn("bound now", res["result"]["trust"]["author"])
        # and self-declared attempts no longer count on the league or profile
        p = self.call("GET", "/v1/users/victim%40x/profile")[1]["result"]
        self.assertEqual(p["scenarios"]["retry-storm"]["attempts"], 1)

    def test_identity_provider_jwt_starts_an_attempt(self):
        """Supabase-style login: ES256 JWT checked against the provider's JWKS."""
        import jwks
        import test_jwks
        key = test_jwks.Key(self.tmp, "EC", "idp-1")
        path = os.path.join(self.tmp, "idp-jwks.json")
        json.dump({"keys": [key.jwk]}, open(path, "w"))
        for name, value in (("JWKS_URL", "file://" + path), ("JWT_ISSUER", test_jwks.ISS)):
            self.addCleanup(setattr, server, name, getattr(server, name))
            setattr(server, name, value)
        tok = key.token(test_jwks.claims(email="ola@firma.pl"))
        code, a = self.start_as({"X-Vantage-User": tok}, user="ceo@x")
        self.assertEqual(code, 201, a)
        self.assertEqual((a["user"], a["identity"]), ("ola@firma.pl", "identity provider"))
        team = self.g.identity_of(a["attempt_id"])[1]
        self.assertEqual(team, "sre-waw")         # app_metadata (admin-set), not user_metadata
        forged = tok.rsplit(".", 1)[0] + "." + test_jwks.b64u(b"\x00" * 64)
        self.assertEqual(self.start_as({"X-Vantage-User": forged})[0], 401)
        self.assertEqual(self.start_as(None)[0], 401)
        self.assertIsInstance(jwks.claim({"a": {"b": 1}}, "a.b"), int)

    def test_cause_catalogs_cover_every_seed_branch(self):
        for scn in ("certificate-apocalypse", "clock-drift", "dns-poison", "retry-storm"):
            cat = self.g.debrief_cfg(scn)
            for nib in "0123456789abcdef":
                seed = nib * 64
                root, _ = pm.occurred(cat, seed)
                self.assertEqual(len(root), 2, (scn, seed, root))   # every scenario injects two faults

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
