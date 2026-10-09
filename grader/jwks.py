"""JWT verification against an identity provider's JWKS (e.g. Supabase Auth).

Stdlib + the openssl CLI, like the rest of the grader. Only asymmetric
algorithms are accepted (ES256, RS256): the grader holds no shared secret, so a
leaked grader config cannot mint users, and "alg: none" / HS256-with-the-public-
key confusion is refused by construction.

    v = JWKSVerifier(url, issuer, audience="authenticated")
    claims = v.verify(token)            # raises PermissionError with the reason

url may be https://... or file://... (tests, air-gapped platforms).
"""
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.request

ALGS = {"ES256": "EC", "RS256": "RSA"}
EC_P256_SPKI_PREFIX = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")


def b64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def der_len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def der(tag, body):
    return bytes([tag]) + der_len(len(body)) + body


def der_int(b):
    b = b.lstrip(b"\x00") or b"\x00"
    return der(0x02, b"\x00" + b if b[0] & 0x80 else b)


def jwk_to_der(jwk):
    """SubjectPublicKeyInfo DER for an EC P-256 or RSA public JWK."""
    if jwk.get("kty") == "EC" and jwk.get("crv") == "P-256":
        x, y = b64u(jwk["x"]), b64u(jwk["y"])
        if len(x) != 32 or len(y) != 32:
            raise ValueError("bad P-256 point")
        return EC_P256_SPKI_PREFIX + b"\x04" + x + y
    if jwk.get("kty") == "RSA":
        rsa_key = der(0x30, der_int(b64u(jwk["n"])) + der_int(b64u(jwk["e"])))
        alg_id = der(0x30, bytes.fromhex("06092a864886f70d0101010500"))     # rsaEncryption, NULL
        return der(0x30, alg_id + der(0x03, b"\x00" + rsa_key))
    raise ValueError(f"unsupported key type {jwk.get('kty')}/{jwk.get('crv')}")


def ecdsa_raw_to_der(sig):
    """JWS ES256 signatures are r||s (64 bytes); openssl wants DER SEQUENCE{r, s}."""
    if len(sig) != 64:
        raise ValueError("ES256 signature must be 64 bytes")
    return der(0x30, der_int(sig[:32]) + der_int(sig[32:]))


def openssl_verify(spki_der, message, signature):
    with tempfile.TemporaryDirectory() as d:
        paths = {n: os.path.join(d, n) for n in ("key.der", "msg", "sig")}
        for n, data in (("key.der", spki_der), ("msg", message), ("sig", signature)):
            with open(paths[n], "wb") as f:
                f.write(data)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", paths["key.der"], "-keyform", "DER",
                            "-signature", paths["sig"], paths["msg"]], capture_output=True)
        return r.returncode == 0


def claim(claims, path):
    """Dotted lookup: "app_metadata.team" -> claims["app_metadata"]["team"]."""
    cur = claims
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


class JWKSVerifier:
    def __init__(self, url, issuer, audience="authenticated", ttl_s=600, leeway_s=30):
        self.url, self.issuer, self.audience = url, issuer.rstrip("/"), audience
        self.ttl_s, self.leeway_s = ttl_s, leeway_s
        self.keys, self.fetched, self.lock = {}, 0.0, threading.Lock()

    def fetch(self):
        if self.url.startswith("file://"):
            with open(self.url[len("file://"):]) as f:
                doc = json.load(f)
        else:
            op = urllib.request.build_opener()
            with op.open(self.url, timeout=10) as r:
                doc = json.load(r)
        keys = {}
        for k in doc.get("keys", []):
            if k.get("kid") and k.get("use", "sig") == "sig":
                try:
                    keys[k["kid"]] = (k, jwk_to_der(k))
                except (ValueError, KeyError):
                    continue           # unknown key types are skipped, not fatal
        self.keys, self.fetched = keys, time.time()

    def key(self, kid):
        with self.lock:
            stale = time.time() - self.fetched > self.ttl_s
            if stale or kid not in self.keys:
                # unknown kid: the provider may have rotated; refetch at most every 10 s
                if stale or time.time() - self.fetched > 10:
                    self.fetch()
            return self.keys.get(kid)

    def verify(self, token, now=None):
        try:
            h64, p64, s64 = token.split(".")
            header, claims, sig = json.loads(b64u(h64)), json.loads(b64u(p64)), b64u(s64)
        except (ValueError, AttributeError):
            raise PermissionError("malformed JWT")
        alg = header.get("alg")
        if alg not in ALGS:
            raise PermissionError(f"JWT alg {alg!r} not accepted (ES256 or RS256 only)")
        try:
            entry = self.key(header.get("kid"))
        except OSError as e:
            raise PermissionError(f"cannot fetch JWKS: {e}")
        if not entry:
            raise PermissionError("JWT signed with an unknown key")
        jwk, spki = entry
        if jwk.get("kty") != ALGS[alg] or jwk.get("alg", alg) != alg:
            raise PermissionError("JWT alg does not match its key")
        try:
            raw = ecdsa_raw_to_der(sig) if alg == "ES256" else sig
        except ValueError as e:
            raise PermissionError(str(e))
        if not openssl_verify(spki, f"{h64}.{p64}".encode(), raw):
            raise PermissionError("JWT signature does not verify")
        now = now or time.time()
        if now >= float(claims.get("exp", 0)) + self.leeway_s:
            raise PermissionError("JWT expired")
        if "nbf" in claims and now + self.leeway_s < float(claims["nbf"]):
            raise PermissionError("JWT not valid yet")
        if str(claims.get("iss", "")).rstrip("/") != self.issuer:
            raise PermissionError("JWT issuer is not this platform's")
        aud = claims.get("aud")
        if self.audience and self.audience not in (aud if isinstance(aud, list) else [aud]):
            raise PermissionError("JWT audience is not this platform's")
        if not claims.get("sub"):
            raise PermissionError("JWT has no subject")
        return claims


def fingerprint(spki_der):
    return hashlib.sha256(spki_der).hexdigest()[:16]
