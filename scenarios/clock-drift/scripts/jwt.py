#!/usr/bin/env python3
"""JWT helper for the trainee and for assertions (HS256, stdlib only).

  jwt.py decode <token>                         header + claims, times as UTC and relative to now
  jwt.py mint --key FILE --kid KID [--aud api] [--sub s] [--iat-offset S] [--ttl S]
"""
import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import sys
import time


def b64e(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def decode(token):
    h, c, _ = token.split(".")
    header, claims = json.loads(b64d(h)), json.loads(b64d(c))
    print("header:", json.dumps(header))
    print("claims:", json.dumps(claims))
    now = time.time()
    for k in ("iat", "nbf", "exp"):
        if k in claims:
            t = dt.datetime.fromtimestamp(claims[k], dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"  {k}: {t}  ({claims[k] - now:+.0f}s vs your clock)")


def mint(a):
    now = int(time.time()) + a.iat_offset
    header = {"alg": "HS256", "typ": "JWT", "kid": a.kid}
    claims = {"iss": "https://auth.vantage.local", "sub": a.sub, "aud": a.aud, "iat": now, "nbf": now, "exp": now + a.ttl}
    signing = f"{b64e(json.dumps(header).encode())}.{b64e(json.dumps(claims).encode())}"
    key = open(a.key).read().strip().encode()
    print(f"{signing}.{b64e(hmac.new(key, signing.encode(), hashlib.sha256).digest())}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode"); d.add_argument("token")
    m = sub.add_parser("mint")
    m.add_argument("--key", required=True); m.add_argument("--kid", required=True)
    m.add_argument("--aud", default="api"); m.add_argument("--sub", default="assert")
    m.add_argument("--iat-offset", type=int, default=0); m.add_argument("--ttl", type=int, default=120)
    a = p.parse_args()
    decode(a.token) if a.cmd == "decode" else mint(a)
