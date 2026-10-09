#!/usr/bin/env bash
# Public assertions (the trainee sees names and details) + hidden assertions
# (only an ID and pass/fail). Writes .state/assertions.json.
# Exit 0 only when every public assertion passes.
source "$(dirname "$0")/../scripts/lib.sh"
require_state

WINDOW="${STABLE_WINDOW:-60}"
assert_begin; tmp="$ASSERT_TMP"
evidence_sync

# --- tokens the api must reject (minted on the host from the real keystore) ---
kid="$(cat "$KEYS/auth/active_kid")"
openssl rand -hex 32 | tr -d '\n' > "$tmp/random.key"
jwt=("$PY" "$SCN_DIR/scripts/jwt.py" mint --kid "$kid" --sub assert-negative)
forged="$("${jwt[@]}" --key "$tmp/random.key")"
expired="$("${jwt[@]}" --key "$KEYS/auth/$kid.key" --iat-offset -900 --ttl 120)"
badaud="$("${jwt[@]}" --key "$KEYS/auth/$kid.key" --aud billing)"

# --- everything that needs the service network runs inside the prober ---------
printf '{"forged": "%s", "expired": "%s", "badaud": "%s"}' "$forged" "$expired" "$badaud" \
| svc_exec prober python -c '
import json, sys, time, urllib.request, urllib.error
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
inp = json.load(sys.stdin)
def get(url, tok=None):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"} if tok else {})
    try:
        r = op.open(req, timeout=3); return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()
    except Exception as e:
        return 0, {}, str(e)
out = {}
code, _, body = get("http://auth:8081/token?sub=assert&aud=api")
out["auth_code"] = code
out["token"] = json.loads(body)["access_token"] if code == 200 else ""
code, h, body = get("http://api:8080/orders", out["token"])
out["api_code"], out["flag"], out["api_body"] = code, h.get("X-Vantage-Flag", ""), body[:120]
for k in ("forged", "expired", "badaud"):
    out[k] = get("http://api:8080/orders", inp[k])[0]
for svc, port in (("auth", 8081), ("api", 8080)):
    t0 = time.time(); c, _, b = get(f"http://{svc}:{port}/debug/time"); t1 = time.time()
    out[f"off_{svc}"] = round(json.loads(b)["time"] - (t0 + t1) / 2, 2) if c == 200 else None
print(json.dumps(out))
' > "$tmp/net.json" 2>"$tmp/net.err" || true
j() { "$PY" -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print("" if v is None else v)' "$tmp/net.json" "$1" 2>/dev/null; }

echo "public:"
token="$(j token)"
[[ "$(j auth_code)" == 200 && "$(tr -cd . <<<"$token" | wc -c)" == 2 ]] && p=1 || p=0
record A1 public token_issued "$p" "auth http=$(j auth_code)"

flag="$(j flag)"
[[ "$(j api_code)" == 200 && -n "$flag" ]] && p=1 || p=0
record A2 public api_accepts_token "$p" "api http=$(j api_code) $(j api_body | cut -c1-60)"

oa="$(j off_auth)"; ob="$(j off_api)"
p=$("$PY" -c 'import sys; print(1 if all(a not in ("",) and abs(float(a)) <= 2 for a in sys.argv[1:]) else 0)' "${oa:-x}" "${ob:-x}" 2>/dev/null || echo 0)
record A3 public clocks_in_sync "$p" "offset auth=${oa:-?}s api=${ob:-?}s (limit 2s)"

a="$(svc_exec auth cat "/keys/$kid.key" 2>/dev/null | openssl dgst -sha256 -r || true)"
b="$(svc_exec api cat "/keyring/$kid.key" 2>/dev/null | openssl dgst -sha256 -r || true)"
[[ -n "$a" && "$a" == "$b" ]] && p=1 || p=0
record A4 public active_kid_trusted "$p" "active kid=$kid $([[ -z "$b" ]] && echo '(missing in api keyring)' || ([[ "$p" == 1 ]] || echo '(key differs)'))"

assert_stable_window A5 "$WINDOW"

# (the negative tests above are expected rejections and carry sub=assert-negative)
errs="$(svc_logs api "$WINDOW" | grep 'reject 401' | grep -vc 'sub=assert-negative' || true)"
[[ "$errs" == 0 ]] && p=1 || p=0
record A6 public log_absence_rejects "$p" "$errs rejected requests in last ${WINDOW}s"

run_hidden_pack

assert_finish
