# Retry Storm: scenario-specific helpers on top of framework/lib.sh.
SCN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="vantage-rs"
SERVICES=(inventory api loadgen prober)
EDGE_SVC="api"; EDGE_TARGET_PORT=8080
# shellcheck source=../../../framework/lib.sh
source "$SCN_DIR/../../framework/lib.sh"
CONF="$STATE/config"          # config/{inventory,api}.json, read live by the services
HIST="$STATE/config/history"  # last known good versions + change log

# Run python inside the prober (it sits on the service network in both modes).
in_net() { svc_exec prober python - "$@"; }

# Load edited config into the running services.
#   docker: bind mount, read twice a second -> nothing to do
#   k3d:    re-create the ConfigMap, rolling restart of the given services
config_apply() { # [svc...]
  is_k8s || return 0
  local svcs=("$@"); (( ${#svcs[@]} )) || svcs=(inventory api)
  bash "$SCN_DIR/scripts/k8s_objects.sh"
  k8s_rollout "${svcs[@]}"
}

metrics() { # window_s -> {"inventory": {...}, "api": {...}}
  in_net "${1:-60}" <<'PY'
import json, sys, urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
w = sys.argv[1]
out = {}
for svc, port in (("inventory", 8090), ("api", 8080)):
    try:
        out[svc] = json.load(op.open(f"http://{svc}:{port}/metrics?window={w}", timeout=5))
    except Exception as e:
        out[svc] = {"error": str(e)}
print(json.dumps(out))
PY
}
