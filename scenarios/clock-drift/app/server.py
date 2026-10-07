"""Clock Drift services. ROLE=auth issues HS256 JWTs, ROLE=api verifies them.

Each service reads its clock as real time + /clock/<role> (seconds), which
stands in for the host clock and its NTP discipline. Keys, config and clock are
re-read on every request, so fixes on disk apply without restarts (docker).
"""
import base64
import hashlib
import hmac
import http.server
import json
import os
import sys
import time
from urllib.parse import parse_qs, urlsplit

ROLE = os.environ["ROLE"]
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("VANTAGE_HOST", "api.vantage.local")
DECOY = os.environ.get("DECOY_IDP", "partner-idp.example")


def b64e(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


def clock():
    return time.time() + float(read(f"/clock/{ROLE}", "0") or 0)


def config():
    return json.loads(read(f"/config/{ROLE}.json", "{}") or "{}")


def log(msg):
    sys.stderr.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), ROLE, msg))


# --- auth ------------------------------------------------------------------
def issue(sub, aud):
    cfg = config()
    kid = read("/keys/active_kid")
    key = read(f"/keys/{kid}.key").encode()
    now = int(clock())
    header = {"alg": "HS256", "typ": "JWT", "kid": kid}
    claims = {"iss": cfg.get("issuer", "https://auth.vantage.local"), "sub": sub, "aud": aud,
              "iat": now, "nbf": now, "exp": now + int(cfg.get("ttl_s", 120))}
    signing = f"{b64e(json.dumps(header).encode())}.{b64e(json.dumps(claims).encode())}"
    return f"{signing}.{b64e(hmac.new(key, signing.encode(), hashlib.sha256).digest())}"


# --- api -------------------------------------------------------------------
def verify(token):
    """Return (claims, None) or (None, reason)."""
    cfg = config()
    leeway = float(cfg.get("leeway_s", 5))
    try:
        h64, c64, s64 = token.split(".")
        header, claims = json.loads(b64d(h64)), json.loads(b64d(c64))
    except Exception:
        return None, "malformed_token"
    if header.get("alg") != "HS256":
        return None, "unsupported_alg"
    key = read(f"/keyring/{header.get('kid')}.key")
    if key is None:
        return None, "unknown_kid"
    if cfg.get("verify_signature", True):
        good = hmac.new(key.encode(), f"{h64}.{c64}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(good, b64d(s64)):
            return None, "bad_signature"
    if cfg.get("verify_audience", True) and claims.get("aud") != cfg.get("audience", "api"):
        return None, "bad_audience"
    now = clock()
    if claims.get("nbf", 0) - leeway > now:
        return None, "token_not_yet_valid"
    if claims.get("exp", 0) + leeway <= now:
        return None, "token_expired"
    return claims, None


def unverified_sub(token):
    """For logs only: who the token claims to be, signature not checked."""
    try:
        return json.loads(b64d(token.split(".")[1])).get("sub", "?")
    except Exception:
        return "?"


def flag():
    secret = read("/secret/flag_secret", "").encode()
    return hmac.new(secret, HOST.encode(), hashlib.sha256).hexdigest()[:24]


class Handler(http.server.BaseHTTPRequestHandler):
    def reply(self, code, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/debug/time":
            # what `chronyc tracking` would read on this host
            return self.reply(200, {"service": ROLE, "time": clock()})
        if ROLE == "auth" and url.path == "/token":
            q = parse_qs(url.query)
            return self.reply(200, {"access_token": issue(q.get("sub", ["anon"])[0], q.get("aud", ["api"])[0]),
                                    "token_type": "Bearer"})
        if ROLE == "api" and url.path == "/orders":
            auth = self.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else ""
            claims, err = verify(token)
            if err:
                log(f"reject 401 {err} sub={unverified_sub(token)} from {self.client_address[0]}")
                return self.reply(401, {"error": err}, {"WWW-Authenticate": f'Bearer error="{err}"'})
            return self.reply(200, {"orders": [], "sub": claims["sub"]}, {"X-Vantage-Flag": flag()})
        self.reply(404, {"error": "not_found"})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    if ROLE == "auth":
        log(f"WARN jwks refresh for {DECOY} failed: connection timed out (will retry)")
    log(f"listening on :{PORT}")
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
