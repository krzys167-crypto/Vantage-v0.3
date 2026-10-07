#!/usr/bin/env bash
# Per-user mutation + healthy PKI. Idempotent: keeps existing state unless RESET=1.
#
# Seed = sha256(USER_ID + salt). The seed decides the public hostname, which
# frontend/backend faults fire, the decoy log noise and the backend flag secret,
# so two users never get the same incident and a pasted answer doesn't transfer.
source "$(dirname "$0")/lib.sh"

[[ -n "$PY" ]] || die "python3 not found"
[[ "${RESET:-0}" == 1 ]] && rm -rf "$STATE"
if [[ -f "$STATE/scenario.env" ]]; then
  have="$(sed -n 's/^MODE=//p' "$STATE/scenario.env")"
  [[ -z "${MODE:-}" || "$MODE" == "$have" ]] || die "state was created for MODE=$have; run 'make clean' first"
  log "state exists (RESET=1 to regenerate)"; exit 0
fi
mkdir -p "$PKI"/{ca,gateway,backend,clients} "$EVID"

user_id="${USER_ID:-$(git config user.email 2>/dev/null || echo anonymous)}"
seed="${SEED:-$(printf '%s:certificate-apocalypse:v0' "$user_id" | openssl dgst -sha256 -r | cut -c1-64)}"

host="api-${seed:0:6}.vantage.local"
front_fault=$(( 16#${seed:6:1} % 2 ))   # 0 = tls_cert_expired, 1 = x509_chain_incomplete
back_fault=$((  16#${seed:7:1} % 2 ))   # 0 = invalid_truststore, 1 = mtls_client_cert_expired
decoys=("redis.cache.internal" "kafka-0.mesh.internal" "ldap.corp.internal" "metrics.mesh.internal")
decoy="${decoys[$(( 16#${seed:8:1} % 4 ))]}"
flag_secret="$(printf '%s:flag' "$seed" | openssl dgst -sha256 -r | cut -c1-64)"

cat > "$STATE/scenario.env" <<EOF
SCENARIO=certificate-apocalypse
MODE=${MODE:-docker}
KUBE_CONTEXT=${KUBE_CONTEXT:-k3d-vantage}
USER_ID=$user_id
SEED=$seed
VANTAGE_HOST=$host
PROBE_TARGET=https://$host:8443/healthz
GATEWAY_PORT=${GATEWAY_PORT:-8443}
FRONT_FAULT=$front_fault
BACK_FAULT=$back_fault
DECOY_HOST=$decoy
NGINX_IMAGE=${NGINX_IMAGE:-mirror.gcr.io/library/nginx:1.27-alpine}
PYTHON_IMAGE=${PYTHON_IMAGE:-mirror.gcr.io/library/python:3.12-alpine}
STABLE_WINDOW=${STABLE_WINDOW:-60}
EOF
printf '%s' "$flag_secret" > "$PKI/backend/flag_secret"

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

log "evidence signing key (ed25519)"
openssl genpkey -algorithm ed25519 -out "$EVID/signing.key"
openssl pkey -in "$EVID/signing.key" -pubout -out "$EVID/signing.pub"

: > "$STATE/timeline.tsv"; timeline "init seed=${seed:0:12} host=$host"
log "scenario ready for $user_id -> https://$host:${GATEWAY_PORT:-8443}"
