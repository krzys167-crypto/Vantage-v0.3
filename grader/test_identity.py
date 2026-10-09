"""Identity tokens (pure).

    python -m unittest grader/test_identity.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import identity  # noqa: E402

S = "platform-user-secret"


class Tokens(unittest.TestCase):
    def test_roundtrip(self):
        c = identity.verify(S, identity.issue(S, "jan@firma.pl", team="sre-waw"))
        self.assertEqual((c["sub"], c["team"]), ("jan@firma.pl", "sre-waw"))

    def test_rejections(self):
        good = identity.issue(S, "jan@firma.pl")
        p, m = good.split(".")
        forged_payload = identity.issue("guessed", "admin@firma.pl").split(".")[0] + "." + m
        cases = {
            "wrong secret": (identity.issue("other", "jan@firma.pl"), "signature"),
            "payload swapped": (forged_payload, "signature"),
            "expired": (identity.issue(S, "jan@firma.pl", ttl_s=10, now=1000), "expired"),
            "malformed": ("not-a-token", "malformed"),
            "empty": ("", "malformed"),
        }
        for name, (tok, why) in cases.items():
            with self.assertRaises(PermissionError, msg=name) as e:
                identity.verify(S, tok)
            self.assertIn(why, str(e.exception), name)

    def test_ttl_is_capped(self):
        c = identity.verify(S, identity.issue(S, "jan@firma.pl", ttl_s=10 ** 9))
        self.assertLessEqual(c["exp"] - c["iat"], identity.MAX_TTL_S)

    def test_bad_user_ids_are_not_issued(self):
        for bad in ("", "two words", "x" * 201, "nl\nuser"):
            with self.assertRaises(ValueError):
                identity.issue(S, bad)


if __name__ == "__main__":
    unittest.main()
