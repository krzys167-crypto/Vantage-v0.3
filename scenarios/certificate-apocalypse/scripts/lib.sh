# Certificate Apocalypse: scenario-specific helpers on top of framework/lib.sh.
SCN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="vantage-ca"
SERVICES=(backend gateway prober)
EDGE_SVC="gateway"; EDGE_TARGET_PORT=8443
# shellcheck source=../../../framework/lib.sh
source "$SCN_DIR/../../framework/lib.sh"
PKI="$STATE/pki"

# Push edited gateway PKI into the running gateway.
#   docker: files are bind-mounted -> nginx -t && nginx -s reload (zero downtime)
#   k3d:    re-create the Secret, then rolling restart (2 replicas, maxUnavailable 0)
gateway_apply() {
  if is_k8s; then
    k8s_apply create secret generic gateway-pki --from-file="$PKI/gateway"
    k8s_rollout gateway
  else
    svc_exec gateway nginx -t -q && svc_exec gateway nginx -s reload 2>&1 | grep -v 'signal process started' || true
  fi
}
