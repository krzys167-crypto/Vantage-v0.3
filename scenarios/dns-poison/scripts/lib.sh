# Split-Brain DNS: scenario-specific helpers on top of framework/lib.sh.
SCN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="vantage-dns"
SERVICES=(dns payments legacy fx api prober)
EDGE_SVC="api"; EDGE_TARGET_PORT=8080
# shellcheck source=../../../framework/lib.sh
source "$SCN_DIR/../../framework/lib.sh"
ZONE="$STATE/zone/internal.zone"
CONF="$STATE/config"

# Run python inside the prober (it sits on the service network in both modes).
in_net() { svc_exec prober python - "$@"; }

dns_reload() {
  # docker: the dns re-reads its zone file but, like a secondary, only accepts a
  #         higher serial. k3d: new ConfigMap + rolling restart.
  if is_k8s; then
    k8s_apply create configmap zone --from-file="$STATE/zone"
    k8s_rollout dns
    echo '{"reloaded": true, "message": "k3d: zone ConfigMap applied, dns restarted"}'
  else
    in_net <<'PY'
import urllib.request, urllib.error
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    print(op.open("http://dns:8053/reload", timeout=3).read().decode())
except urllib.error.HTTPError as e:
    print(e.read().decode())
PY
  fi
}

api_flush() {
  in_net <<'PY'
import urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
print(op.open("http://api:8080/admin/dns/flush", timeout=3).read().decode())
PY
}

config_apply() { # k3d only: hosts.json / api.json changed
  is_k8s || return 0
  k8s_apply create configmap svc-config --from-file="$CONF"
  k8s_rollout api
}
