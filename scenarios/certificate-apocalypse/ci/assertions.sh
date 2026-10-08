#!/usr/bin/env bash
# Public assertions (the trainee sees names and details) + hidden assertions
# (only an ID and pass/fail). Writes .state/assertions.json.
# Exit 0 only when every public assertion passes.
source "$(dirname "$0")/../scripts/lib.sh"
require_state

WINDOW="${STABLE_WINDOW:-60}"
ROOT="$PKI/clients/root-ca.pem"
assert_begin; tmp="$ASSERT_TMP"
edge_open 'rm -rf "$ASSERT_TMP"'
evidence_sync

# --- capture what the edge serves -------------------------------------------
echo | openssl s_client -connect "127.0.0.1:$EDGE_PORT" -servername "$VANTAGE_HOST" \
  -CAfile "$ROOT" -verify_return_error -showcerts > "$tmp/sclient.txt" 2>&1 || true
awk '/BEGIN CERT/{n++} /BEGIN CERT/,/END CERT/{print > (dir "/chain-" n ".pem")}' dir="$tmp" "$tmp/sclient.txt"
# (find, not ls: with pipefail an empty match must not abort the run - a gateway
# serving nothing is a FAIL to record, not a crash)
leaf="$tmp/chain-1.pem"; nchain=$(find "$tmp" -name 'chain-*.pem' | wc -l | tr -d ' ')
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
san="$(openssl x509 -in "$leaf" -noout -ext subjectAltName 2>/dev/null | tail -n +2 | tr -d ' ' || true)"
[[ ",$san," == *",DNS:$VANTAGE_HOST,"* ]] && p=1 || p=0
record A4 public san_matches_host "$p" "SAN=$san"

# A5 private key on disk matches the served certificate
if [[ -s "$leaf" ]]; then
  a="$(openssl x509 -in "$leaf" -noout -pubkey 2>/dev/null | openssl dgst -sha256 -r || true)"
  b="$(svc_exec gateway cat /pki/gateway/leaf.key 2>/dev/null | openssl pkey -pubout 2>/dev/null | openssl dgst -sha256 -r || true)"
  [[ -n "$a" && "$a" == "$b" ]] && p=1 || p=0
else p=0; fi
record A5 public key_matches_cert "$p" "gateway/leaf.key vs served leaf"

# A6 end-to-end request through mTLS hop returns 200 + backend flag
hdrs="$(curl -sS --noproxy '*' -o /dev/null -D - --max-time 5 --cacert "$ROOT" \
  --resolve "$VANTAGE_HOST:$EDGE_PORT:127.0.0.1" "https://$VANTAGE_HOST:$EDGE_PORT/healthz" 2>&1 || true)"
code="$(printf '%s' "$hdrs" | awk 'NR==1{print $2}')"
flag="$(printf '%s' "$hdrs" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-vantage-flag"{print $2}')"
[[ "$code" == 200 && -n "$flag" ]] && p=1 || p=0
record A6 public mtls_trust_ok "$p" "http=$code flag=${flag:-none}"

# A7 prober saw only healthy responses for the whole window
assert_stable_window A7 "$WINDOW"

# A8 no TLS errors in gateway log during the window
errs="$(svc_logs gateway "$WINDOW" 2>/dev/null | grep -ciE 'SSL_do_handshake|certificate verify|upstream SSL|cannot load certificate' || true)"
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

assert_finish
