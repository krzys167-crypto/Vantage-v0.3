#!/usr/bin/env bash
# What a client sees: fetch a token from auth and call api with it (runs inside
# the network, works the same on docker and k3d).
source "$(dirname "$0")/lib.sh"
require_state
svc_exec prober python - <<'PY'
import json, urllib.request, urllib.error
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
tok = json.load(op.open("http://auth:8081/token?sub=you&aud=api", timeout=3))["access_token"]
print("token:", tok)
req = urllib.request.Request("http://api:8080/orders", headers={"Authorization": f"Bearer {tok}"})
try:
    r = op.open(req, timeout=3); print("api:", r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print("api:", e.code, e.headers.get("WWW-Authenticate"), e.read().decode())
PY
