#!/usr/bin/env python3
"""User identity tokens: the platform vouches for who starts an attempt.

    python grader/identity.py issue <user> [--team T] [--ttl-h 8]   (needs GRADER_USER_SECRET)

Token: base64url(payload JSON) "." base64url(HMAC-SHA256(secret, payload)),
payload {"sub", "team", "iat", "exp"}. The platform (SSO login, hosted-range
controller) and the grader share GRADER_USER_SECRET; the trainee only ever
holds a short-lived token for their own user. With the secret set, the grader
takes the user from the token and ignores the request body's `user`.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time

USER_RE = re.compile(r"^[^\s\x00-\x1f]{1,200}$")
MAX_TTL_S = 7 * 86400


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(secret, user, team=None, ttl_s=8 * 3600, now=None):
    if not USER_RE.match(user):
        raise ValueError("user id: 1-200 printable characters, no spaces")
    now = int(now or time.time())
    payload = json.dumps({"sub": user, "team": team, "iat": now, "exp": now + min(int(ttl_s), MAX_TTL_S)},
                         sort_keys=True, separators=(",", ":")).encode()
    mac = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(mac)}"


def verify(secret, token, now=None):
    """Claims dict, or raises PermissionError with the reason."""
    try:
        p64, m64 = (token or "").split(".")
        payload, mac = _unb64(p64), _unb64(m64)
    except ValueError:
        raise PermissionError("malformed user token")
    if not hmac.compare_digest(hmac.new(secret.encode(), payload, hashlib.sha256).digest(), mac):
        raise PermissionError("user token signature does not verify")
    claims = json.loads(payload)
    if (now or time.time()) >= claims.get("exp", 0):
        raise PermissionError("user token expired")
    if not USER_RE.match(str(claims.get("sub", ""))):
        raise PermissionError("user token has no valid subject")
    return claims


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2 or a[0] != "issue":
        sys.exit(__doc__)
    secret = os.environ.get("GRADER_USER_SECRET") or sys.exit("GRADER_USER_SECRET is not set")
    team = a[a.index("--team") + 1] if "--team" in a else None
    ttl = float(a[a.index("--ttl-h") + 1]) * 3600 if "--ttl-h" in a else 8 * 3600
    print(issue(secret, a[1], team, ttl))
