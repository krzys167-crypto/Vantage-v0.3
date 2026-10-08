#!/usr/bin/env bash
# Inject the per-user faults: one on the public edge, one on the internal mTLS hop.
# Fixing only the first one still leaves the service down (multi-step incident).
source "$(dirname "$0")/lib.sh"
require_state

[[ -f "$STATE/broken" ]] && die "already broken (make down && make up to start over)"
[[ -n "$(svc_identity gateway || true)" ]] || die "stack not running: make up"

bad="$(dirname "$0")/gen_bad_cert.sh"
case "$FRONT_FAULT" in
  0) # tls_cert_expired: same key, validity ended yesterday
     "$bad" expired "$PKI/gateway/leaf" "$PKI/ca/int-ca" "$VANTAGE_HOST" server >/dev/null
     cat "$PKI/gateway/leaf.pem" "$PKI/ca/int-ca.pem" > "$PKI/gateway/fullchain.pem" ;;
  1) # x509_chain_incomplete: someone "simplified" the bundle to the leaf only
     cp "$PKI/gateway/leaf.pem" "$PKI/gateway/fullchain.pem" ;;
esac
case "$BACK_FAULT" in
  0) # invalid_truststore: trust bundle replaced by an unrelated CA
     "$bad" rogue-ca "$STATE/rogue-ca" "Vantage Mesh CA" >/dev/null
     cp "$STATE/rogue-ca.pem" "$PKI/gateway/mesh-ca.pem"; rm -f "$STATE/rogue-ca.key" ;;
  1) # mtls_client_cert_expired
     "$bad" expired "$PKI/gateway/client" "$PKI/ca/mesh-ca" "gateway.mesh.internal" client >/dev/null ;;
esac

gateway_apply >/dev/null
# Baseline for blast radius: instance identities right after the incident starts.
snapshot "$STATE/baseline.tsv"
incident_started
log "incident started: https://$VANTAGE_HOST:$EDGE_PORT/healthz is failing. Clock is running."
log "evidence: make status | make probe | make probe MESH=1 | make logs S=gateway"
