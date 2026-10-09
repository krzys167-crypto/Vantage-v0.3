#!/usr/bin/env bash
# Plays the trainee in a hosted Retry Storm session, with nothing but the
# trainee kubeconfig and the public repo:
#   1. the RBAC boundary holds (no Secrets, no traffic generator, no exec, no list)
#   2. the incident can be fixed with exactly those rights
#
#   range/tests/trainee_retry.sh <trainee.kubeconfig>
source "$(dirname "$0")/common.sh"

echo "RBAC boundary:"
check no  get secret/keys
check no  list secrets
check no  get configmap/scenario
check no  get configmap/app-code
check no  patch configmap/change-history
check no  patch deployment/loadgen
check no  patch deployment/prober
check no  create pods/exec
check no  delete pods
check yes get configmap/svc-config
check yes patch configmap/svc-config
check yes get configmap/change-history
check yes patch deployment/inventory
check yes patch deployment/api
check yes get pods/log
cannot_read secret/keys
boundary_holds

echo "diagnose + fix with trainee rights only:"
w="$(mktemp -d)"; trap 'rm -rf "$w"' EXIT
cm_get change-history CHANGELOG.md | sed -n 's/^- /  changelog: /p'
cm_get change-history inventory.json.prev > "$w/inventory.prev"
cm_get svc-config inventory.json > "$w/inventory.json"
cm_get svc-config api.json > "$w/api.json"
python3 - "$w" <<'PY'
import json, sys
w = sys.argv[1]
inv, prev = json.load(open(f"{w}/inventory.json")), json.load(open(f"{w}/inventory.prev"))
for k in ("workers", "cpu_millicores"):
    if inv.get(k, 0) < prev.get(k, 0):
        print(f"  inventory {k} {inv[k]} -> {prev[k]} (restore the cut)")
        inv[k] = prev[k]
json.dump(inv, open(f"{w}/inventory.json", "w"))
api = json.load(open(f"{w}/api.json"))
print(f"  api policy {api} -> bounded retries, backoff + jitter, 1 s timeout")
api.update(timeout_ms=1000, retries=2, backoff_ms=100, jitter=True, fallback_static=False)
json.dump(api, open(f"{w}/api.json", "w"))
PY
cm_set svc-config inventory.json "$w/inventory.json"
cm_set svc-config api.json "$w/api.json"
roll inventory api
echo "  applied: svc-config updated, inventory and api rolled"
