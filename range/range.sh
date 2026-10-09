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

with_lock() { # serialise controllers on this host (mkdir is atomic and portable, unlike flock)
  local lock="$SESSIONS/.lock" i
  mkdir -p "$SESSIONS"
  for i in $(seq 1 100); do
    if mkdir "$lock" 2>/dev/null; then
      local rc=0; "$@" || rc=$?
      rmdir "$lock" 2>/dev/null || true
      return $rc
    fi
    # a lock older than 60 s belongs to a crashed controller
    [[ -n "$(find "$lock" -maxdepth 0 -mmin +1 2>/dev/null)" ]] && rmdir "$lock" 2>/dev/null || true
    sleep 0.2
  done
  die "could not take $lock"
}

claim_svc_net() { # id -> prints a /24 no Service uses and no other session has claimed
  local id="$1" used n claims="$SESSIONS/.nets"
  mkdir -p "$claims"
  used="$(kubectl --context "$KUBE_CONTEXT" get svc -A -o jsonpath='{range .items[*]}{.spec.clusterIP}{"\n"}{end}' \
          | awk -F. '{print $3}' | sort -u)"
  for n in $(seq 200 249 | shuf); do
    [[ -e "$claims/$n" ]] && continue
    grep -qx "$n" <<<"$used" && continue
    echo "$id" > "$claims/$n"
    echo "10.43.$n"; return
  done
  die "no free /24 left in 10.43.200-249 for fixed ClusterIPs"
}

free_svc_net() { with_lock claim_svc_net "$1"; } # claim survives until `stop` (or a failed `start`)

release_svc_net() { # id: drop every claim this session holds
  local f
  for f in "$SESSIONS"/.nets/*; do
    [[ -f "$f" && "$(cat "$f")" == "$1" ]] && rm -f "$f"
  done
  return 0
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
    net="$(free_svc_net "$id")"
    started=0; trap '[[ $started == 1 ]] || release_svc_net "$id"' EXIT
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
    started=1
    echo "$id" ;;
  grade)
    session_env "${1:?session}"
    export USER_ID
    # private hidden-assertion pack lives on the platform, never in the repo or the cluster
    [[ -n "${RANGE_PRIVATE_DIR:-}" ]] && export VANTAGE_HIDDEN_DIR="$RANGE_PRIVATE_DIR"
    # a stale result must never be graded: drop it, and treat anything but pass(0)/public-fail(1)
    # (e.g. exit 2: configured private pack missing) as a failed grade, not as "assertions failed"
    rm -f "$VANTAGE_STATE/assertions.json"
    rc=0; bash "$SCN/ci/assertions.sh" || rc=$?
    [[ $rc == 0 || $rc == 1 ]] || die "assertions aborted (exit $rc): not grading"
    [[ -f "$VANTAGE_STATE/assertions.json" ]] || die "assertions wrote no result: not grading"
    bash "$ROOT/framework/submit.sh" "$SCN" ;;
  stop)
    session_env "${1:?session}"
    ( cd "$SCN" && bash scripts/ctl.sh down ) || true
    release_svc_net "$1"
    log "session $1 stopped; evidence kept in $SESSIONS/$1/state/evidence" ;;
  *) die "usage: range.sh start <scenario> [user] | grade <session> | stop <session>" ;;
esac
