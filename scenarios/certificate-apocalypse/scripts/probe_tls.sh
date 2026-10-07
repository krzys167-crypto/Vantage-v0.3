#!/usr/bin/env bash
# Diagnostic tool for the trainee: what does the gateway actually serve?
#   probe_tls.sh            -> public edge (host:port from scenario)
#   probe_tls.sh mesh       -> internal mTLS hop, from inside the gateway container
source "$(dirname "$0")/lib.sh"
require_state

if [[ "${1:-edge}" == mesh ]]; then
  # nginx images ship without openssl, so replay the gateway's mTLS handshake from
  # the prober (python) using the gateway's live client cert + trust bundle.
  log "gateway -> backend mTLS, replayed with the gateway's own client cert + trust bundle"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  for f in client.pem client.key mesh-ca.pem; do svc_exec gateway cat "/pki/gateway/$f" > "$tmp/$f"; done
  echo "  gateway client cert: $(openssl x509 -in "$tmp/client.pem" -noout -subject -enddate | tr '\n' ' ')"
  echo "  gateway trust bundle: $(openssl x509 -in "$tmp/mesh-ca.pem" -noout -subject -fingerprint -sha256 | tr '\n' ' ')"
  "$PY" -c 'import json,sys; print(json.dumps({f: open(sys.argv[1]+"/"+f).read() for f in ("client.pem","client.key","mesh-ca.pem")}))' "$tmp" \
  | svc_exec prober python -c '
import json, os, socket, ssl, sys, tempfile
pem = json.load(sys.stdin)
d = tempfile.mkdtemp()
for k, v in pem.items():
    open(os.path.join(d, k), "w").write(v)
c = ssl.create_default_context(cafile=os.path.join(d, "mesh-ca.pem"))
c.load_cert_chain(os.path.join(d, "client.pem"), os.path.join(d, "client.key"))
host = os.environ.get("BACKEND_DIAL", "backend.mesh.internal")
try:
    with socket.create_connection((host, 9443), timeout=3) as s, c.wrap_socket(s, server_hostname="backend.mesh.internal") as t:
        t.sendall(b"GET /healthz HTTP/1.0\r\nHost: backend\r\n\r\n")
        print("  handshake OK, backend says:", t.recv(200).split(b"\r\n")[0].decode())
except ssl.SSLCertVerificationError as e:
    print("  FAIL verifying backend certificate:", e.verify_message)
except (ssl.SSLError, OSError) as e:
    print("  FAIL", type(e).__name__, e)
'
  exit 0
fi
edge_open

log "edge: $VANTAGE_HOST via 127.0.0.1:$GATEWAY_PORT (trust = public root only)"
out="$(echo | openssl s_client -connect "127.0.0.1:$GATEWAY_PORT" -servername "$VANTAGE_HOST" \
  -CAfile "$PKI/clients/root-ca.pem" -showcerts 2>&1 || true)"
echo "$out" | grep -E "^ *[0-9] s:|^ *i:|Verify return code" || true
printf '%s\n' "$out" | awk '/BEGIN CERT/{f=1} f{print} /END CERT/{exit}' \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName 2>/dev/null || warn "no certificate served"
