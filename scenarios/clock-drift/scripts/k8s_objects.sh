#!/usr/bin/env bash
# k3d: ConfigMaps + Secrets consumed by k8s/manifests.yaml.
source "$(dirname "$0")/lib.sh"
require_state
k8s_apply create configmap app-code --from-file="$SCN_DIR/app/server.py" --from-file="$SCN_DIR/prober/probe.py"
k8s_apply create configmap clock --from-file="$CLOCK"
k8s_apply create configmap svc-config --from-file="$CONF"
k8s_apply create secret generic auth-keys --from-file="$KEYS/auth"
k8s_apply create secret generic api-keyring --from-file="$KEYS/api"
k8s_apply create secret generic api-flag --from-file="$STATE/secret"
