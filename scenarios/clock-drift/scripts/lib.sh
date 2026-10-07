# Clock Drift: scenario-specific helpers on top of framework/lib.sh.
SCN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="vantage-cd"
SERVICES=(auth api prober)
EDGE_SVC="api"; EDGE_TARGET_PORT=8080
# shellcheck source=../../../framework/lib.sh
source "$SCN_DIR/../../framework/lib.sh"
KEYS="$STATE/keys"       # keys/auth: issuer keystore, keys/api: verifier keyring
CLOCK="$STATE/clock"     # clock/<svc>: offset in seconds (the "host clock")
CONF="$STATE/config"     # config/<svc>.json

# Load edited keys/config/clock into the running services.
#   docker: bind mounts, read per request -> nothing to do
#   k3d:    re-create ConfigMaps/Secrets, rolling restart of the given services
svc_apply() { # [svc...]
  is_k8s || return 0
  local svcs=("$@"); (( ${#svcs[@]} )) || svcs=(auth api)
  bash "$SCN_DIR/scripts/k8s_objects.sh"
  k8s_rollout "${svcs[@]}"
}
