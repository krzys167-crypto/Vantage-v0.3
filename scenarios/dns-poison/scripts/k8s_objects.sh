#!/usr/bin/env bash
# k3d: ConfigMaps + Secrets consumed by k8s/manifests.yaml.
source "$(dirname "$0")/lib.sh"
require_state
k8s_apply create configmap app-code --from-file="$SCN_DIR/app/server.py" \
  --from-file="$SCN_DIR/app/dns_server.py" --from-file="$SCN_DIR/app/dnslib.py" --from-file="$SCN_DIR/prober/probe.py"
k8s_apply create configmap zone --from-file="$STATE/zone"
k8s_apply create configmap svc-config --from-file="$CONF"
k8s_apply create secret generic keys --from-file="$STATE/secret"
