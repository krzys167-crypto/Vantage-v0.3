#!/usr/bin/env bash
# k3d: ConfigMaps + Secrets consumed by k8s/manifests.yaml.
source "$(dirname "$0")/lib.sh"
require_state
k8s_apply create configmap app-code --from-file="$SCN_DIR/app/server.py" --from-file="$SCN_DIR/prober/probe.py"
k8s_apply create configmap svc-config --from-file="$CONF/inventory.json" --from-file="$CONF/api.json"
k8s_apply create configmap change-history --from-file="$HIST"
k8s_apply create secret generic keys --from-file="$STATE/secret"
