#!/usr/bin/env bash
# Per-user mutation + healthy PKI. Idempotent: keeps existing state unless RESET=1.
#
# The seed decides the public hostname, which edge/mesh faults fire, the decoy
# log noise and the backend flag secret, so two users never get the same
# incident and a pasted answer doesn't transfer.
source "$(dirname "$0")/lib.sh"

[[ -n "$PY" ]] || die "python3 not found"
state_needs_init || exit 0
mkdir -p "$PKI"/{ca,gateway,backend,clients}

seed="$(derive_seed certificate-apocalypse)"
host="api-${seed:0:6}.vantage.local"
front_fault=$(( $(seed_nibble "$seed" 6) % 2 ))   # 0 = tls_cert_expired, 1 = x509_chain_incomplete
back_fault=$((  $(seed_nibble "$seed" 7) % 2 ))   # 0 = invalid_truststore, 1 = mtls_client_cert_expired
decoys=("redis.cache.internal" "kafka-0.mesh.internal" "ldap.corp.internal" "metrics.mesh.internal")
decoy="${decoys[$(( $(seed_nibble "$seed" 8) % 4 ))]}"

write_common_env certificate-apocalypse "$seed"
cat >> "$STATE/scenario.env" <<EOF
VANTAGE_HOST=$host
PROBE_TARGET=https://$host:8443/healthz
FRONT_FAULT=$front_fault
BACK_FAULT=$back_fault
DECOY_HOST=$decoy
EOF
printf '%s:flag' "$seed" | openssl dgst -sha256 -r | cut -c1-64 | tr -d '\n' > "$PKI/backend/flag_secret"

g="$(dirname "$0")/gen_good_cert.sh"
log "public PKI: root -> intermediate -> $host"
"$g" ca     "$PKI/ca/root-ca" "Vantage Public Root" >/dev/null
"$g" ca     "$PKI/ca/int-ca"  "Vantage Public Issuing CA" "$PKI/ca/root-ca" >/dev/null
"$g" server "$PKI/gateway/leaf" "$PKI/ca/int-ca" "$host" 90 >/dev/null
cat "$PKI/gateway/leaf.pem" "$PKI/ca/int-ca.pem" > "$PKI/gateway/fullchain.pem"

log "mesh PKI (mTLS gateway <-> backend)"
"$g" ca     "$PKI/ca/mesh-ca" "Vantage Mesh CA" >/dev/null
"$g" server "$PKI/backend/server" "$PKI/ca/mesh-ca" "backend.mesh.internal" 90 >/dev/null
"$g" client "$PKI/gateway/client" "$PKI/ca/mesh-ca" "gateway.mesh.internal" 90 >/dev/null
cp "$PKI/ca/mesh-ca.pem" "$PKI/gateway/mesh-ca.pem"
cp "$PKI/ca/mesh-ca.pem" "$PKI/backend/mesh-ca.pem"
cp "$PKI/ca/root-ca.pem" "$PKI/clients/root-ca.pem"

log "scenario ready -> https://$host:${EDGE_PORT:-8443}"
