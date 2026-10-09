"""JWT verification against a JWKS (pure, keys generated per run).

    python -m unittest grader/test_jwks.py -v
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jwks  # noqa: E402

ISS = "https://example.supabase.co/auth/v1"


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def run(*cmd, data=None):
    return subprocess.run(cmd, input=data, capture_output=True, check=True).stdout


def der_to_raw(sig):
    """DER SEQUENCE{INTEGER r, INTEGER s} -> r||s, 32 bytes each."""
    assert sig[0] == 0x30
    i, out = 2 if sig[1] < 0x80 else 3, b""
    for _ in range(2):
        n = sig[i + 1]
        out += sig[i + 2:i + 2 + n].lstrip(b"\x00").rjust(32, b"\x00")
        i += 2 + n
    return out


class Key:
    def __init__(self, d, kind, kid):
        self.kind, self.kid = kind, kid
        self.path = tempfile.mkstemp(suffix=".pem", dir=d)[1]      # two keys may share a kid
        if kind == "EC":
            run("openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", self.path)
            spki = run("openssl", "pkey", "-in", self.path, "-pubout", "-outform", "DER")
            point = spki[-64:]
            self.jwk = {"kty": "EC", "crv": "P-256", "kid": kid, "alg": "ES256", "use": "sig",
                        "x": b64u(point[:32]), "y": b64u(point[32:])}
            self.alg = "ES256"
        else:
            run("openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", self.path)
            mod = run("openssl", "rsa", "-in", self.path, "-noout", "-modulus").decode().strip().split("=")[1]
            self.jwk = {"kty": "RSA", "kid": kid, "alg": "RS256", "use": "sig",
                        "n": b64u(bytes.fromhex(mod)), "e": b64u((65537).to_bytes(3, "big"))}
            self.alg = "RS256"

    def token(self, claims, header=None):
        h = b64u(json.dumps(header or {"alg": self.alg, "kid": self.kid, "typ": "JWT"}).encode())
        p = b64u(json.dumps(claims).encode())
        sig = run("openssl", "dgst", "-sha256", "-sign", self.path, data=f"{h}.{p}".encode())
        return f"{h}.{p}.{b64u(der_to_raw(sig) if self.kind == 'EC' else sig)}"


def claims(**kw):
    now = int(time.time())
    c = {"iss": ISS, "aud": "authenticated", "sub": "8f1c-uuid", "email": "jan@firma.pl", "role": "authenticated",
         "iat": now, "exp": now + 3600, "app_metadata": {"team": "sre-waw"}, "user_metadata": {"team": "admins"}}
    c.update(kw)
    return c


class JWKS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.ec, cls.rsa, cls.other = Key(cls.d, "EC", "ec-1"), Key(cls.d, "RSA", "rsa-1"), Key(cls.d, "EC", "ec-1")
        cls.path = os.path.join(cls.d, "jwks.json")
        json.dump({"keys": [cls.ec.jwk, cls.rsa.jwk]}, open(cls.path, "w"))
        cls.v = jwks.JWKSVerifier("file://" + cls.path, ISS)

    def test_es256_and_rs256_verify(self):
        for k in (self.ec, self.rsa):
            c = self.v.verify(k.token(claims()))
            self.assertEqual((c["email"], jwks.claim(c, "app_metadata.team")), ("jan@firma.pl", "sre-waw"), k.alg)

    def rejected(self, token, why):
        with self.assertRaises(PermissionError) as e:
            self.v.verify(token)
        self.assertIn(why, str(e.exception))

    def test_forgeries_are_rejected(self):
        good = self.ec.token(claims())
        h, p, s = good.split(".")
        promoted = b64u(json.dumps(claims(email="ceo@firma.pl", app_metadata={"team": "board"})).encode())
        self.rejected(f"{h}.{promoted}.{s}", "signature")                                  # edited claims
        self.rejected(self.other.token(claims()), "signature")                             # same kid, other key
        self.rejected(self.ec.token(claims(), {"alg": "none", "kid": "ec-1"}), "not accepted")
        self.rejected(self.ec.token(claims(), {"alg": "HS256", "kid": "ec-1"}), "not accepted")
        self.rejected(self.ec.token(claims(), {"alg": "RS256", "kid": "ec-1"}), "does not match")
        self.rejected(self.ec.token(claims(), {"alg": "ES256", "kid": "nope"}), "unknown key")
        self.rejected("a.b", "malformed")

    def test_claims_are_enforced(self):
        self.rejected(self.ec.token(claims(exp=int(time.time()) - 3600)), "expired")
        self.rejected(self.ec.token(claims(iss="https://evil.supabase.co/auth/v1")), "issuer")
        self.rejected(self.ec.token(claims(aud="anon")), "audience")
        self.rejected(self.ec.token(claims(sub="")), "subject")
        self.rejected(self.ec.token(claims(nbf=int(time.time()) + 3600)), "not valid yet")

    def test_rotated_key_is_fetched(self):
        new = Key(self.d, "EC", "ec-2")
        json.dump({"keys": [self.ec.jwk, new.jwk]}, open(self.path, "w"))
        self.v.fetched = time.time() - 11          # past the refetch guard
        self.assertEqual(self.v.verify(new.token(claims()))["sub"], "8f1c-uuid")


if __name__ == "__main__":
    unittest.main()
