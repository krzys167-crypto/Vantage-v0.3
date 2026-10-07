#!/usr/bin/env bash
# Initialise the per-user scenario and start it on the selected runtime.
#   MODE=docker (default) -> docker compose
#   MODE=k3d              -> namespace vantage-ca in context $KUBE_CONTEXT (default k3d-vantage)
source "$(dirname "$0")/lib.sh"
bash "$SCN_DIR/scripts/init.sh"
require_state

if is_k8s; then
  kubectl --context "$KUBE_CONTEXT" get ns "$NS" >/dev/null 2>&1 || kubectl --context "$KUBE_CONTEXT" create ns "$NS" >/dev/null
  apply() { "${KUBE[@]}" "$@" --dry-run=client -o yaml | "${KUBE[@]}" apply -f - >/dev/null; }
  apply create configmap scenario --from-env-file="$STATE/scenario.env"
  apply create configmap app-code \
    --from-file="$SCN_DIR/backend/server.py" --from-file="$SCN_DIR/prober/probe.py" \
    --from-file="$SCN_DIR/gateway/default.conf.template"
  apply create secret generic gateway-pki --from-file="$PKI/gateway"
  apply create secret generic backend-pki --from-file="$PKI/backend"
  apply create secret generic clients-ca  --from-file="$PKI/clients"
  "${KUBE[@]}" apply -f "$SCN_DIR/k8s/manifests.yaml" >/dev/null
  for d in backend gateway prober; do "${KUBE[@]}" rollout status "deploy/$d" --timeout=180s >/dev/null; done
  "${KUBE[@]}" get pods -o wide
else
  "${COMPOSE[@]}" up -d --wait
fi
timeline up
log "running on $MODE"
