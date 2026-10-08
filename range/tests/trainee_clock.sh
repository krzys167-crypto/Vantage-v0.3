#!/usr/bin/env bash
# Plays the trainee in a hosted Clock Drift session, with nothing but the
# trainee kubeconfig and the public repo:
#   1. the RBAC boundary holds (no flag secret, no prober, no exec, no list)
#   2. the incident can be fixed with exactly those rights
#
#   range/tests/trainee_clock.sh <trainee.kubeconfig>
source "$(dirname "$0")/common.sh"

echo "RBAC boundary:"
check no  get secret/api-flag
check no  list secrets
check no  update secret/auth-keys
check no  get configmap/scenario
check no  get configmap/app-code
check no  patch deployment/prober
check no  create pods/exec
check no  delete pods
check no  create deployments
check yes get secret/auth-keys
check yes patch secret/api-keyring
check yes patch configmap/clock
check yes patch configmap/svc-config
check yes patch deployment/api
check yes get pods/log
cannot_read secret/api-flag
boundary_holds

echo "diagnose + fix with trainee rights only:"
# 1. host clocks: step every service whose clock is off (leeway stays as it is)
kubectl get configmap clock -o json | python3 -c '
import json, sys
for svc, off in json.load(sys.stdin)["data"].items():
    if abs(float(off or 0)) > 1:
        print(svc, off)' | while read -r svc off; do
  echo "  $svc clock off by ${off}s -> step to reference"
  kubectl patch configmap clock --type merge -p "{\"data\": {\"$svc\": \"0\"}}" >/dev/null
done

# 2. key rotation: the api keyring must hold the issuer's active key
secret() { kubectl get secret "$1" -o json | python3 -c '
import base64, json, sys
print(base64.b64decode(json.load(sys.stdin)["data"].get(sys.argv[1], "")).decode(), end="")' "$2"; }
kid="$(secret auth-keys active_kid)"
key="$(secret auth-keys "$kid.key")"
if [[ "$(secret api-keyring "$kid.key")" != "$key" ]]; then
  echo "  api keyring missing/stale for $kid -> sync from issuer"
  kubectl patch secret api-keyring --type merge \
    -p "{\"data\": {\"$kid.key\": \"$(printf '%s' "$key" | base64 | tr -d '\n')\"}}" >/dev/null
fi
roll auth api
echo "  applied: clock + api-keyring updated, auth and api rolled"
