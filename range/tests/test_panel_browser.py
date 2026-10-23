"""The panel in a real Chromium: start an incident, grade it, write a post-mortem, sign it with
WebCrypto Ed25519 and have it verified by the grader's own verifier.

Only the outside world is stubbed: supabase-js (a fake client that hands out a valid IdP JWT),
range.sh (no cluster) and the grader's debrief endpoint (it verifies the signature for real).

    pip install playwright && python -m unittest range/tests/test_panel_browser.py -v
    CHROMIUM=/path/to/chrome picks the browser; without it Playwright's own is used.
    Skipped when there is no browser, unless VANTAGE_REQUIRE_BROWSER=1 (CI), where it must run.
"""
import base64
import glob
import json
import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_api as T  # noqa: E402  (stub range.sh, JWT helpers, env setup)
import server  # noqa: E402
import debrief as pm  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                   # pragma: no cover
    sync_playwright = None

REQUIRED = os.environ.get("VANTAGE_REQUIRE_BROWSER") == "1"
CHROME = os.environ.get("CHROMIUM") or next(iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))), "")
AID = "aaaabbbbccccdddd"


class VerifyingGrader(T.FakeGrader):
    """FakeGrader whose POST checks the browser's signature with the real verifier."""
    def __init__(self):
        super().__init__()
        import http.server
        outer = self
        base = self.srv.RequestHandlerClass

        class H(base):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.received.append(body)
                key_sha = server.ed25519_verify(body["pubkey"], pm.message(AID, body["markdown"]),
                                                base64.b64decode(body["signature"]))
                if not key_sha:
                    return self.reply(403, {"error": "post-mortem signature does not verify"})
                doc = pm.parse(body["markdown"])
                outer.done = {"signature": "grader-sig", "result": {
                    "kind": "debrief", "score": 88.0, "verdict": "verified", "author_key_sha256": key_sha,
                    "causes": {"confirmed": doc["causes"], "contributing": [], "missed": [], "wrong": []},
                    "timeline": {"mitigated_error_s": 1.2, "tolerance_s": 30},
                    "facts": {"missing": [], "hints": {}}}}
                self.reply(200, outer.done)
        self.srv.RequestHandlerClass = H


@unittest.skipUnless(sync_playwright and (REQUIRED or (CHROME and os.path.exists(CHROME))),
                     "needs playwright and a Chromium (VANTAGE_REQUIRE_BROWSER=1 makes this a failure)")
class PanelInBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = VerifyingGrader()
        cls.fake.start()
        os.environ.update(GRADER_URL=cls.fake.url, PANEL_SUPABASE_URL="http://supabase.stub", PANEL_SUPABASE_KEY="sb_publishable_stub")
        cls.key = T.test_jwks.Key(T.TMP, "EC", "e2e-1")
        jwks_path = os.path.join(T.TMP, "e2e-jwks.json")
        with open(jwks_path, "w") as f:
            json.dump({"keys": [cls.key.jwk]}, f)
        T.api.grader.JWKS_URL, T.api.grader.JWT_ISSUER = "file://" + jwks_path, T.test_jwks.ISS
        cls.rng, cls.srv = T.api.serve(0)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.token = cls.key.token(T.test_jwks.claims(email="e2e@x"))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.rng.t.db.close()

    def test_incident_to_signed_post_mortem(self):
        stub = ("window.supabase = { createClient: () => ({ auth: {"
                f" getSession: async () => ({{ data: {{ session: {{ access_token: {json.dumps(self.token)}, user: {{ email: 'e2e@x', id: 'u1' }} }} }} }}),"
                " onAuthStateChange: () => {}, signOut: async () => {}, signInWithOtp: async () => ({}) } }) };")
        with sync_playwright() as p:
            browser = p.chromium.launch(**({"executable_path": CHROME} if CHROME else {}), args=["--no-sandbox"])
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("dialog", lambda d: d.accept())
            page.route("**/supabase.min.js", lambda r: r.fulfill(body=stub, content_type="text/javascript"))
            page.goto(self.url + "/")

            page.get_by_role("button", name="Retry Storm").click()
            page.get_by_text("INCYDENT TRWA").wait_for(timeout=10000)
            page.get_by_role("button", name="Gotowe: oceń naprawę").click()
            page.get_by_text("ocenione").wait_for(timeout=10000)

            # the post-mortem card: causes arrive as a checklist without any hint which are decoys
            page.locator("#pmText").wait_for(timeout=10000)
            self.assertEqual(page.locator(".cause input").count(), 8)
            self.assertIn("attempt: " + AID, page.input_value("#pmText"))
            # an empty template does not pass the format check, and nothing is sent
            page.get_by_role("button", name="Sprawdź format").click()
            page.get_by_text("'detected' is missing").wait_for(timeout=5000)
            self.assertEqual(self.fake.received, [])

            for cause in ("inventory_cpu_limit_cut", "retries_7x_120ms_no_backoff"):
                page.locator(f'.cause input[value="{cause}"]').check()
            md = page.input_value("#pmText")
            md = md.replace("detected:", "detected: 2026-10-09T22:53:25Z", 1).replace("mitigated:", "mitigated: 2026-10-09T22:54:10Z", 1)
            md = md.replace("## Timeline\n- 22:53:20Z incident started (grader: break)",
                            "## Timeline\n- 22:53:20Z incident started (grader: break)\n- 22:53:30Z alert fired\n"
                            "- 22:53:50Z inventory: 8x requests, zażądano zbyt wiele\n- 22:54:10Z service recovered")
            page.fill("#pmText", md)
            page.get_by_role("button", name="Sprawdź format").click()
            page.get_by_text("Format w porządku").wait_for(timeout=5000)

            page.get_by_role("button", name="Podpisz i wyślij").click()
            page.get_by_text("verified").first.wait_for(timeout=10000)
            browser.close()

        self.assertEqual(errors, [])
        sent = self.fake.received[-1]
        self.assertIn("causes: inventory_cpu_limit_cut, retries_7x_120ms_no_backoff", sent["markdown"])   # from the checkboxes
        self.assertIn("zażądano", sent["markdown"])                                                       # UTF-8 survived the trip
        self.assertTrue(server.ed25519_verify(sent["pubkey"], pm.message(AID, sent["markdown"]),
                                              base64.b64decode(sent["signature"])))                       # signed in the browser
        self.assertFalse(sent.get("rotate_key"))


if __name__ == "__main__":
    unittest.main()
