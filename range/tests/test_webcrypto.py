"""The browser signs post-mortems with WebCrypto Ed25519 (range/panel/sign.js); the grader
must accept exactly those signatures. Runs the real sign.js in Node against the grader's
own verifier and message format.

    python -m unittest range/tests/test_webcrypto.py -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "grader"))
import base64  # noqa: E402
import server  # noqa: E402
import debrief as pm  # noqa: E402


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class WebCryptoSigning(unittest.TestCase):
    def sign_in_node(self, aid, md):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(md)
        self.addCleanup(os.unlink, f.name)
        out = subprocess.run(["node", os.path.join(HERE, "webcrypto_sign.js"), aid, f.name],
                             capture_output=True, text=True, check=True).stdout
        r = json.loads(out)
        if r.get("unsupported"):
            self.skipTest("this Node has no WebCrypto Ed25519")
        return r

    def test_grader_accepts_a_browser_signature(self):
        aid = "0123456789abcdef"
        md = "---\nattempt: 0123456789abcdef\n---\n# Post-mortem\nPrzyczyna: zbyt agresywne ponawianie żądań ✓\n"
        r = self.sign_in_node(aid, md)
        sig = base64.b64decode(r["signature"], validate=True)
        key_sha = server.ed25519_verify(r["pubkey"], pm.message(aid, md), sig)
        self.assertEqual(key_sha, r["fingerprint"])                   # same fingerprint the panel shows
        self.assertFalse(r["private_key_extractable"])                # the key cannot be read out of the browser
        # and it is bound to this text and this attempt
        self.assertFalse(server.ed25519_verify(r["pubkey"], pm.message(aid, md + " "), sig))
        self.assertFalse(server.ed25519_verify(r["pubkey"], pm.message("fedcba9876543210", md), sig))


if __name__ == "__main__":
    unittest.main()
