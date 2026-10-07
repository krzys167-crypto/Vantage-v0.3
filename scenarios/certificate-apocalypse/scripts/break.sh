#!/usr/bin/env bash
# Inject the per-user faults: one on the public edge, one on the internal mTLS hop.
# Fixing only the first one still leaves the service down (multi-step incident).
source "$(dirname "$0")/lib.sh"
require_state

[[ -f "$STATE/broken" ]] && die "already broken (make down && make up to start over)"
"${COMPOSE[@]}" ps --status running -q gateway | grep -q . || die "stack not running: make up"

# Baseline for blast radius: container start times before the incident.
for svc in backend gateway prober; do
  id="$("${COMPOSE[@]}" ps -q "$svc")"
  printf '%s\t%s\n' "$svc" "$(docker inspect -f '{{.State.StartedAt}}' "$id")"
done > "$STATE/baseline.tsv"

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

"${COMPOSE[@]}" exec -T gateway nginx -s reload >/dev/null 2>&1
touch "$STATE/broken"
timeline "break"
log "incident started: https://$VANTAGE_HOST:$GATEWAY_PORT/healthz is failing. Clock is running."
log "evidence: make status | ./scripts/probe_tls.sh | docker compose logs | .state/evidence/probes.jsonl"
