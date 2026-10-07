#!/usr/bin/env bash
# SPOILER: reference remediation, used by CI to prove the scenario is solvable.
# It diagnoses instead of reading the fault list, so it works for every seed.
source "$(dirname "$0")/../scripts/lib.sh"
require_state
g="$SCN_DIR/scripts/gen_good_cert.sh"
gw="$PKI/gateway"

# Edge: leaf must be valid and the bundle must carry the intermediate.
if ! openssl x509 -in "$gw/leaf.pem" -noout -checkend $((30*86400)) >/dev/null; then
  log "edge leaf expired -> re-issue with the same key"
  "$g" server "$gw/leaf" "$PKI/ca/int-ca" "$VANTAGE_HOST" 90 >/dev/null
fi
[[ "$(grep -c 'BEGIN CERT' "$gw/fullchain.pem")" -lt 2 ]] && log "bundle missing intermediate -> rebuild fullchain"
cat "$gw/leaf.pem" "$PKI/ca/int-ca.pem" > "$gw/fullchain.pem"

# Mesh: trust bundle must be the mesh CA, client cert must be valid.
if ! cmp -s "$gw/mesh-ca.pem" "$PKI/ca/mesh-ca.pem"; then
  log "gateway trust bundle is not the mesh CA -> restore"
  cp "$PKI/ca/mesh-ca.pem" "$gw/mesh-ca.pem"
fi
if ! openssl x509 -in "$gw/client.pem" -noout -checkend $((30*86400)) >/dev/null; then
  log "mesh client cert expired -> re-issue with the same key"
  "$g" client "$gw/client" "$PKI/ca/mesh-ca" "gateway.mesh.internal" 90 >/dev/null
fi

"${COMPOSE[@]}" exec -T gateway nginx -t -q && "${COMPOSE[@]}" exec -T gateway nginx -s reload
timeline "fix (reference solution)"
log "reloaded gateway (zero-downtime, no restarts)"
