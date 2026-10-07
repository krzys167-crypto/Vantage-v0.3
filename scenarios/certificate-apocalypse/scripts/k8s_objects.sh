#!/usr/bin/env bash
# k3d: ConfigMaps + Secrets consumed by k8s/manifests.yaml (called by scenario_up).
source "$(dirname "$0")/lib.sh"
require_state
k8s_apply create configmap app-code \
  --from-file="$SCN_DIR/backend/server.py" --from-file="$SCN_DIR/prober/probe.py" \
  --from-file="$SCN_DIR/gateway/default.conf.template"
k8s_apply create secret generic gateway-pki --from-file="$PKI/gateway"
k8s_apply create secret generic backend-pki --from-file="$PKI/backend"
k8s_apply create secret generic clients-ca  --from-file="$PKI/clients"
