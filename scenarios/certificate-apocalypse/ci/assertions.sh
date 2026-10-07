#!/usr/bin/env bash
# Public assertions (the trainee sees names and details) + hidden assertions
# (only an ID and pass/fail). Writes .state/assertions.json.
# Exit 0 only when every public assertion passes.
source "$(dirname "$0")/../scripts/lib.sh"
require_state

WINDOW="${STABLE_WINDOW:-60}"
ROOT="$PKI/clients/root-ca.pem"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
edge_open 'rm -rf "$tmp"'
evidence_sync
results="$tmp/results.tsv"; : > "$results"

record() { # id visibility name pass(0/1) detail
  printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "${5//$'\t'/ }" >> "$results"
  local mark; mark=$([[ "$4" == 1 ]] && echo PASS || echo FAIL)
  if [[ "$2" == public ]]; then printf '  %-4s %-22s %s  %s\n' "$1" "$3" "$mark" "$5"
  else printf '  %-4s %-22s %s\n' "$1" "(hidden)" "$mark"; fi
}
ok() { "$@" >/dev/null 2>&1 && echo 1 || echo 0; }

# --- capture what the edge serves -------------------------------------------
echo | openssl s_client -connect "127.0.0.1:$GATEWAY_PORT" -servername "$VANTAGE_HOST" \
  -CAfile "$ROOT" -verify_return_error -showcerts > "$tmp/sclient.txt" 2>&1 || true
awk '/BEGIN CERT/{n++} /BEGIN CERT/,/END CERT/{print > (dir "/chain-" n ".pem")}' dir="$tmp" "$tmp/sclient.txt"
leaf="$tmp/chain-1.pem"; nchain=$(ls "$tmp"/chain-*.pem 2>/dev/null | wc -l | tr -d ' ')
cat "$tmp"/chain-[2-9].pem > "$tmp/untrusted.pem" 2>/dev/null || : > "$tmp/untrusted.pem"

echo "public:"
# A1 handshake verified against the public root only (what real clients do)
grep -q "Verify return code: 0 (ok)" "$tmp/sclient.txt" && p=1 || p=0
record A1 public tls_handshake_ok "$p" "$(grep -m1 'Verify return code' "$tmp/sclient.txt" | sed 's/^ *//')"

# A2 served leaf not expired
if [[ -s "$leaf" ]]; then
  p=$(ok openssl x509 -in "$leaf" -noout -checkend 0)
  record A2 public x509_not_expired "$p" "$(openssl x509 -in "$leaf" -noout -enddate)"
else record A2 public x509_not_expired 0 "no certificate served"; fi

# A3 server sends the intermediate and the chain verifies to the root
if [[ -s "$leaf" && "$nchain" -ge 2 ]]; then
  p=$(ok openssl verify -CAfile "$ROOT" -untrusted "$tmp/untrusted.pem" "$leaf")
  record A3 public x509_chain_ok "$p" "served chain length $nchain"
else record A3 public x509_chain_ok 0 "served chain length $nchain (intermediate missing?)"; fi

# A4 SAN covers the per-user hostname
san="$(openssl x509 -in "$leaf" -noout -ext subjectAltName 2>/dev/null | tail -n +2 | tr -d ' ')"
[[ ",$san," == *",DNS:$VANTAGE_HOST,"* ]] && p=1 || p=0
record A4 public san_matches_host "$p" "SAN=$san"

# A5 private key on disk matches the served certificate
if [[ -s "$leaf" ]]; then
  a="$(openssl x509 -in "$leaf" -noout -pubkey 2>/dev/null | openssl dgst -sha256 -r)"
  b="$(svc_exec gateway cat /pki/gateway/leaf.key 2>/dev/null | openssl pkey -pubout 2>/dev/null | openssl dgst -sha256 -r)"
  [[ -n "$a" && "$a" == "$b" ]] && p=1 || p=0
else p=0; fi
record A5 public key_matches_cert "$p" "gateway/leaf.key vs served leaf"

# A6 end-to-end request through mTLS hop returns 200 + backend flag
hdrs="$(curl -sS --noproxy '*' -o /dev/null -D - --max-time 5 --cacert "$ROOT" \
  --resolve "$VANTAGE_HOST:$GATEWAY_PORT:127.0.0.1" "https://$VANTAGE_HOST:$GATEWAY_PORT/healthz" 2>&1 || true)"
code="$(printf '%s' "$hdrs" | awk 'NR==1{print $2}')"
flag="$(printf '%s' "$hdrs" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-vantage-flag"{print $2}')"
[[ "$code" == 200 && -n "$flag" ]] && p=1 || p=0
record A6 public mtls_trust_ok "$p" "http=$code flag=${flag:-none}"

# A7 prober saw only healthy responses for the whole window
read -r p detail < <("$PY" - "$EVID/probes.jsonl" "$WINDOW" <<'EOF'
import json, sys, time
path, win = sys.argv[1], float(sys.argv[2])
now = time.time()
try:
    rows = [json.loads(l) for l in open(path) if l.strip()]
except FileNotFoundError:
    rows = []
w = [r for r in rows if r["ts"] >= now - win]
bad = sum(1 for r in w if not r["ok"])
# need coverage of the window: at least 80% of expected samples at 0.5 s
enough = len(w) >= 0.8 * win / 0.5
print(1 if (w and bad == 0 and enough) else 0, f"{len(w)} probes in {int(win)}s, {bad} failed")
EOF
)
record A7 public "health_stable_${WINDOW}s" "$p" "$detail"

# A8 no TLS errors in gateway log during the window
errs="$(svc_logs gateway "$WINDOW" | grep -ciE 'SSL_do_handshake|certificate verify|upstream SSL|cannot load certificate' || true)"
[[ "$errs" == 0 ]] && p=1 || p=0
record A8 public log_absence_tls_errors "$p" "$errs TLS error lines in last ${WINDOW}s"

echo "hidden:"
# H1 sane validity: >= 30 days left, <= 398 days total (no "100-year cert" fix)
if [[ -s "$leaf" ]]; then
  p=$("$PY" - "$leaf" <<'EOF'
import subprocess, sys, datetime as d
def get(f):
    v = subprocess.check_output(["openssl", "x509", "-in", sys.argv[1], "-noout", f"-{f}"], text=True).split("=", 1)[1].strip()
    return d.datetime.strptime(v, "%b %d %H:%M:%S %Y %Z")
nb, na = get("startdate"), get("enddate")
now = d.datetime.now(d.timezone.utc).replace(tzinfo=None)
print(1 if (na - now).days >= 30 and (na - nb).days <= 398 else 0)
EOF
)
else p=0; fi
record H1 hidden validity_window "$p" ""

# H2 key strength: EC >= 256 or RSA >= 2048
bits="$(openssl x509 -in "$leaf" -noout -text 2>/dev/null | grep -oE 'Public-Key: \([0-9]+ bit' | grep -oE '[0-9]+' || echo 0)"
alg="$(openssl x509 -in "$leaf" -noout -text 2>/dev/null | grep -m1 'Public Key Algorithm' || true)"
if [[ "$alg" == *id-ecPublicKey* ]]; then (( bits >= 256 )) && p=1 || p=0; else (( bits >= 2048 )) && p=1 || p=0; fi
record H2 hidden key_strength "$p" ""

# H3 gateway still verifies the backend, against the mesh CA (not "verify off")
conf="$(svc_exec gateway nginx -T 2>/dev/null || true)"
same_ca=$(cmp -s <(svc_exec gateway cat /pki/gateway/mesh-ca.pem 2>/dev/null) "$PKI/ca/mesh-ca.pem" && echo 1 || echo 0)
grep -Eq '^\s*proxy_ssl_verify\s+on;' <<<"$conf" && [[ "$same_ca" == 1 ]] && p=1 || p=0
record H3 hidden upstream_verify_on "$p" ""

# H4 flag is the real backend HMAC for this user's host
expected="$("$PY" -c 'import hmac,hashlib,sys; print(hmac.new(open(sys.argv[1],"rb").read().strip(), sys.argv[2].encode(), hashlib.sha256).hexdigest()[:24])' "$PKI/backend/flag_secret" "$VANTAGE_HOST")"
[[ "$flag" == "$expected" ]] && p=1 || p=0
record H4 hidden flag_authentic "$p" ""

# H5 backend still enforces mTLS: a client without a certificate must be rejected
p=$(svc_exec prober python - <<'EOF' 2>/dev/null || echo 0
import os, socket, ssl
c = ssl.create_default_context(cafile="/pki/backend/mesh-ca.pem")
try:
    with socket.create_connection((os.environ.get("BACKEND_DIAL", "backend.mesh.internal"), 9443), timeout=3) as s:
        with c.wrap_socket(s, server_hostname="backend.mesh.internal") as t:
            t.sendall(b"GET /healthz HTTP/1.0\r\n\r\n")
            print(0 if t.recv(64).startswith(b"HTTP/1.0 200") else 1)
except (ssl.SSLError, ConnectionError, OSError):
    print(1)
EOF
)
record H5 hidden backend_requires_client_cert "${p:-0}" ""

# H6 no wildcard / no stray SANs on the edge certificate
[[ "$san" == "DNS:$VANTAGE_HOST" ]] && p=1 || p=0
record H6 hidden san_minimal "$p" ""

snapshot "$STATE/current.tsv"   # blast radius input for score.py
"$PY" - "$results" "$STATE/assertions.json" "$WINDOW" <<'EOF'
import json, sys, time
rows = [l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip()]
out = {"ts": time.time(), "window_s": float(sys.argv[3]), "assertions": [
    {"id": r[0], "visibility": r[1], "name": r[2], "pass": r[3] == "1", "detail": r[4] if r[1] == "public" else ""}
    for r in rows]}
out["public_pass"] = all(a["pass"] for a in out["assertions"] if a["visibility"] == "public")
out["hidden_pass"] = sum(a["pass"] for a in out["assertions"] if a["visibility"] == "hidden")
out["hidden_total"] = sum(1 for a in out["assertions"] if a["visibility"] == "hidden")
json.dump(out, open(sys.argv[2], "w"), indent=2)

print(f"public: {'PASS' if out['public_pass'] else 'FAIL'}   hidden: {out['hidden_pass']}/{out['hidden_total']}")
sys.exit(0 if out["public_pass"] else 1)
EOF
