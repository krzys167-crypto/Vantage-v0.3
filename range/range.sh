#!/usr/bin/env bash
# Hosted range controller: runs scenarios on the platform's k3d cluster so the
# trainee never holds the state, the prober, the flag secret or the assertions.
#
#   range.sh start <scenario> [user]   -> session id + trainee kubeconfig
#   range.sh grade <session>           -> assertions (platform creds) + graded submit
#   range.sh stop  <session>           -> delete namespace, keep evidence
#
# Needs: kubectl with an admin context ($KUBE_CONTEXT, default k3d-vantage),
# GRADER_URL (the grader), python3, openssl. The scenario must ship
# k8s/trainee-role.yaml and may ship scripts/range_trainee_objects.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SESSIONS="${RANGE_SESSIONS:-$ROOT/range/.sessions}"
export MODE=k3d KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-vantage}"
: "${GRADER_URL:?GRADER_URL must point at the grader: hosted runs are always graded}"
export GRADER_URL

die() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }
log() { printf '\033[36m==>\033[0m %s\n' "$*"; }

session_env() { # id -> exports for the scenario scripts
  local id="$1" dir="$SESSIONS/$1"
  [[ -f "$dir/session.env" ]] || die "unknown session $id"
  # shellcheck disable=SC1091
  source "$dir/session.env"
  export VANTAGE_STATE="$dir/state" VANTAGE_NS="vr-$id" EDGE_PORT VANTAGE_SVC_NET
  SCN="$ROOT/scenarios/$SCENARIO"
}

free_svc_net() { # a /24 in k3s' service CIDR that no Service uses yet (fixed ClusterIPs)
  local used n
  used="$(kubectl --context "$KUBE_CONTEXT" get svc -A -o jsonpath='{range .items[*]}{.spec.clusterIP}{"\n"}{end}' \
          | awk -F. '{print $3}' | sort -u)"
  for n in $(seq 200 249 | shuf); do
    grep -qx "$n" <<<"$used" || { echo "10.43.$n"; return; }
  done
  die "no free /24 left in 10.43.200-249 for fixed ClusterIPs"
}

trainee_kubeconfig() { # ns out
  local ns="$1" out="$2" server ca token
  kubectl --context "$KUBE_CONTEXT" -n "$ns" create serviceaccount trainee >/dev/null
  kubectl --context "$KUBE_CONTEXT" -n "$ns" apply -f "$SCN/k8s/trainee-role.yaml" >/dev/null
  kubectl --context "$KUBE_CONTEXT" -n "$ns" create rolebinding trainee --role=trainee \
    --serviceaccount="$ns:trainee" >/dev/null
  token="$(kubectl --context "$KUBE_CONTEXT" -n "$ns" create token trainee --duration="${RANGE_TTL:-4h}")"
  server="$(kubectl --context "$KUBE_CONTEXT" config view --minify --raw -o jsonpath='{.clusters[0].cluster.server}')"
  ca="$(kubectl --context "$KUBE_CONTEXT" config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"
  umask 077
  cat > "$out" <<EOT
apiVersion: v1
kind: Config
clusters: [{name: range, cluster: {server: "$server", certificate-authority-data: "$ca"}}]
users: [{name: trainee, user: {token: "$token"}}]
contexts: [{name: range, context: {cluster: range, user: trainee, namespace: "$ns"}}]
current-context: range
EOT
}

cmd="${1:-}"; shift || true
case "$cmd" in
  start)
    scenario="${1:?scenario}"; user="${2:-anonymous}"
    SCN="$ROOT/scenarios/$scenario"
    [[ -f "$SCN/k8s/trainee-role.yaml" ]] || die "$scenario has no k8s/trainee-role.yaml: not available as a hosted range yet"
    id="$(openssl rand -hex 4)"; dir="$SESSIONS/$id"
    mkdir -p "$dir/state" && chmod 700 "$dir"
    net="$(free_svc_net)"
    printf 'SCENARIO=%s\nUSER_ID=%s\nEDGE_PORT=%s\nVANTAGE_SVC_NET=%s\n' "$scenario" "$user" \
      "$(( 20000 + 16#${id:0:4} % 20000 ))" "$net" > "$dir/session.env"
    session_env "$id"
    export USER_ID="$user"
    log "session $id: $scenario for $user in namespace $VANTAGE_NS"
    bash "$SCN/scripts/ctl.sh" up >/dev/null
    [[ -x "$SCN/scripts/range_trainee_objects.sh" ]] && bash "$SCN/scripts/range_trainee_objects.sh"
    bash "$SCN/scripts/break.sh"
    trainee_kubeconfig "$VANTAGE_NS" "$dir/trainee.kubeconfig"
    log "trainee kubeconfig: $dir/trainee.kubeconfig (namespace $VANTAGE_NS)"
    echo "$id" ;;
  grade)
    session_env "${1:?session}"
    export USER_ID
    bash "$SCN/ci/assertions.sh" || true
    bash "$ROOT/framework/submit.sh" "$SCN" ;;
  stop)
    session_env "${1:?session}"
    ( cd "$SCN" && bash scripts/ctl.sh down ) || true
    log "session $1 stopped; evidence kept in $SESSIONS/$1/state/evidence" ;;
  *) die "usage: range.sh start <scenario> [user] | grade <session> | stop <session>" ;;
esac
