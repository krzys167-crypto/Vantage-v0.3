#!/usr/bin/env bash
# Public assertions (the trainee sees names and details) + hidden assertions
# (only an ID and pass/fail). Writes .state/assertions.json.
# Exit 0 only when every public assertion passes.
source "$(dirname "$0")/../scripts/lib.sh"
require_state

WINDOW="${STABLE_WINDOW:-60}"
assert_begin; tmp="$ASSERT_TMP"

# Everything network-side is gathered in one pass from inside the prober.
in_net > "$tmp/net.json" 2>"$tmp/net.err" <<'PY' || true
import json, sys, urllib.request, urllib.error
sys.path.insert(0, "/app")
import dnslib
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(url):
    try:
        r = op.open(url, timeout=5); return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()
    except Exception as e:
        return 0, {}, str(e)
out = {}
for n in ("payments", "fx"):
    try:
        out[f"dig_{n}"] = dnslib.query("dns", f"{n}.internal")
    except Exception as e:
        out[f"dig_{n}"] = {"rcode": -1, "ips": [], "ttl": 0, "error": str(e)}
    c, _, b = get(f"http://api:8080/debug/resolve?name={n}.internal")
    out[f"api_{n}"] = json.loads(b) if c == 200 else {"error": b}
c, h, b = get("http://api:8080/checkout")
out["checkout_code"], out["flag"], out["checkout_body"] = c, h.get("X-Vantage-Flag", ""), b[:200]
c, _, b = get("http://dns:8053/zone")
out["zone"] = json.loads(b) if c == 200 else {}
print(json.dumps(out))
PY
j() { "$PY" -c '
import json, sys
v = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."):
    v = v.get(k) if isinstance(v, dict) else (v[int(k)] if isinstance(v, list) and len(v) > int(k) else None)
print("" if v is None else (json.dumps(v) if isinstance(v, (dict, list)) else v))' "$tmp/net.json" "$1" 2>/dev/null; }

echo "public:"
[[ "$(j dig_payments.ips.0)" == "$PAY_IP" ]] && p=1 || p=0
record A1 public dns_payments_correct "$p" "dns: payments.internal -> $(j dig_payments.ips) ttl=$(j dig_payments.ttl)"

[[ "$(j dig_fx.ips.0)" == "$FX_IP" ]] && p=1 || p=0
record A2 public dns_fx_resolves "$p" "dns: fx.internal rcode=$(j dig_fx.rcode) -> $(j dig_fx.ips)"

[[ "$(j api_payments.ips.0)" == "$PAY_IP" && "$(j api_fx.ips.0)" == "$FX_IP" ]] && p=1 || p=0
record A3 public api_view_consistent "$p" "api sees payments=$(j api_payments.ips) ($(j api_payments.source)), fx=$(j api_fx.ips) ($(j api_fx.source))"

flag="$(j flag)"
# served by the live payments instance, not by whatever answers on a stale address
served_by="$("$PY" -c 'import json,sys; print(json.loads(sys.argv[1]).get("upstreams",{}).get("payments",""))' "$(j checkout_body)" 2>/dev/null || true)"
[[ "$(j checkout_code)" == 200 && -n "$flag" && "$served_by" == payments ]] && p=1 || p=0
record A4 public checkout_ok "$p" "http=$(j checkout_code) payments served by: ${served_by:-?}"

assert_stable_window A5 "$WINDOW"

errs="$(svc_logs api "$WINDOW" | grep -c 'upstream error' || true)"
[[ "$errs" == 0 ]] && p=1 || p=0
record A6 public log_absence_upstream_errors "$p" "$errs upstream errors in last ${WINDOW}s"

hidden_assertions "$(dirname "$0")"

assert_finish
