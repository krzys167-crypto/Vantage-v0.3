#!/usr/bin/env bash
# Public assertions (the trainee sees names and details) + hidden assertions
# (only an ID and pass/fail). Writes .state/assertions.json.
# Exit 0 only when every public assertion passes.
source "$(dirname "$0")/../scripts/lib.sh"
require_state

WINDOW="${STABLE_WINDOW:-60}"
assert_begin; tmp="$ASSERT_TMP"

# One checkout plus both services' metrics over the stability window.
in_net "$WINDOW" > "$tmp/net.json" 2>"$tmp/net.err" <<'PY' || true
import json, sys, time, urllib.request, urllib.error
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
w = sys.argv[1]
out = {}
t0 = time.time()
try:
    r = op.open("http://api:8080/checkout", timeout=10)
    out["code"], out["flag"], out["body"] = r.status, r.headers.get("X-Vantage-Flag", ""), r.read().decode()[:200]
except urllib.error.HTTPError as e:
    out["code"], out["flag"], out["body"] = e.code, "", e.read().decode()[:200]
except Exception as e:
    out["code"], out["flag"], out["body"] = 0, "", str(e)
out["call_ms"] = round((time.time() - t0) * 1000)
for svc, port in (("inventory", 8090), ("api", 8080)):
    try:
        out[svc] = json.load(op.open(f"http://{svc}:{port}/metrics?window={w}", timeout=5))
    except Exception as e:
        out[svc] = {"error": str(e)}
print(json.dumps(out))
PY
j() { "$PY" -c '
import json, sys
v = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."):
    v = v.get(k) if isinstance(v, dict) else None
print("" if v is None else (json.dumps(v) if isinstance(v, (dict, list)) else v))' "$tmp/net.json" "$1" 2>/dev/null; }
le() { "$PY" -c 'import sys; a, b = sys.argv[1:]; print(1 if a not in ("", "None") and float(a) <= float(b) else 0)' "$1" "$2" 2>/dev/null || echo 0; }

echo "public:"
flag="$(j flag)"
[[ "$(j code)" == 200 && -n "$flag" ]] && p=1 || p=0
record A1 public checkout_ok "$p" "http=$(j code) in $(j call_ms) ms $(j body | cut -c1-60)"

util="$(j inventory.utilization)"; q95="$(j inventory.p95_queue_ms)"
[[ "$(le "$util" 0.6)" == 1 && "$(le "${q95:-0}" 50)" == 1 ]] && p=1 || p=0
record A2 public inventory_headroom "$p" "utilization=${util:-?} (max 0.6), p95 queue=${q95:-?} ms (max 50), $(j inventory.effective_workers) effective workers"

amp="$(j api.amplification)"
[[ "$(le "$amp" 1.2)" == 1 ]] && p=1 || p=0
record A3 public retry_amplification "$p" "inventory attempts per checkout=${amp:-?} (max 1.2) over ${WINDOW}s"

lat="$(j api.p95_ms)"
[[ "$(le "$lat" 150)" == 1 ]] && p=1 || p=0
record A4 public checkout_latency_slo "$p" "p95=${lat:-?} ms (SLO 150 ms) over ${WINDOW}s, $(j api.ok)/$(j api.checkouts) ok"

assert_stable_window A5 "$WINDOW"

errs="$(svc_logs api "$WINDOW" | grep -c 'upstream timeout' || true)"
[[ "$errs" == 0 ]] && p=1 || p=0
record A6 public log_absence_upstream_timeouts "$p" "$errs failed checkouts in api logs in last ${WINDOW}s"

run_hidden_pack

assert_finish
