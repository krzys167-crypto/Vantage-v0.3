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

hidden_assertions "$(dirname "$0")"

assert_finish
