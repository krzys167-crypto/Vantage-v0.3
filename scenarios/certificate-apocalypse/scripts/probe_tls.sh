#!/usr/bin/env bash
# Diagnostic tool for the trainee: what does the gateway actually serve?
#   probe_tls.sh            -> public edge (host:port from scenario)
#   probe_tls.sh mesh       -> internal mTLS hop, from inside the gateway container
source "$(dirname "$0")/lib.sh"
require_state

if [[ "${1:-edge}" == mesh ]]; then
  log "gateway -> backend.mesh.internal:9443 (using the gateway's own client cert + trust bundle)"
  "${COMPOSE[@]}" exec -T gateway sh -c '
    apk info -e openssl >/dev/null 2>&1 || apk add -q openssl >/dev/null 2>&1
    echo | openssl s_client -connect backend.mesh.internal:9443 -servername backend.mesh.internal \
      -cert /pki/gateway/client.pem -key /pki/gateway/client.key \
      -CAfile /pki/gateway/mesh-ca.pem -verify_return_error 2>&1 | grep -E "verify|Verify|alert|error|subject=|issuer=" | head -20'
  exit 0
fi

log "edge: $VANTAGE_HOST via 127.0.0.1:$GATEWAY_PORT (trust = public root only)"
out="$(echo | openssl s_client -connect "127.0.0.1:$GATEWAY_PORT" -servername "$VANTAGE_HOST" \
  -CAfile "$PKI/clients/root-ca.pem" -showcerts 2>&1 || true)"
echo "$out" | grep -E "^ *[0-9] s:|^ *i:|Verify return code" || true
printf '%s\n' "$out" | awk '/BEGIN CERT/{f=1} f{print} /END CERT/{exit}' \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName 2>/dev/null || warn "no certificate served"
