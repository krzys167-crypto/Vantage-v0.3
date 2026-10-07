# Shared helpers for Certificate Apocalypse scripts. Source, don't execute.
# Runtime-agnostic: every script talks to services through svc_* functions, so
# the same break/assert/score logic runs on docker compose and on k3d.
set -euo pipefail

SCN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$SCN_DIR/.state"
PKI="$STATE/pki"
EVID="$STATE/evidence"
PY="$(command -v python3 || command -v python || true)"
PROJECT="vantage-ca"
NS="vantage-ca"
COMPOSE=(docker compose -p "$PROJECT" --env-file "$STATE/scenario.env" -f "$SCN_DIR/docker-compose.yml")

# Git Bash on Windows rewrites "/CN=..." into a path; this disables that.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
# Local endpoints must never go through a corporate/agent HTTP proxy.
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost" no_proxy="${no_proxy:+$no_proxy,}127.0.0.1,localhost"

log()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

now() { "$PY" -c 'import time; print(f"{time.time():.3f}")'; }

require_state() {
  [[ -f "$STATE/scenario.env" ]] || die "not initialised: run 'make up' first"
  # shellcheck disable=SC1091
  set -a; source "$STATE/scenario.env"; set +a
  KUBE=(kubectl --context "${KUBE_CONTEXT:-k3d-vantage}" -n "$NS")
}

is_k8s() { [[ "${MODE:-docker}" == k3d ]]; }

# Append an event to the incident timeline (evidence for MTTR / debrief).
timeline() { printf '%s\t%s\n' "$(now)" "$*" >> "$STATE/timeline.tsv"; }

# --- runtime abstraction -------------------------------------------------------
svc_exec() { # svc cmd...   (stdin passed through)
  local s="$1"; shift
  if is_k8s; then "${KUBE[@]}" exec -i "deploy/$s" -- "$@"
  else "${COMPOSE[@]}" exec -T "$s" "$@"; fi
}

svc_logs() { # svc since_seconds
  if is_k8s; then "${KUBE[@]}" logs "deploy/$1" --since="${2}s" 2>&1
  else "${COMPOSE[@]}" logs --no-log-prefix --since "${2}s" "$1" 2>&1; fi
}

# Identity of the running instance; changes when a service is restarted/recreated.
svc_identity() {
  if is_k8s; then
    "${KUBE[@]}" get pods -l "app=$1" --field-selector=status.phase=Running \
      -o jsonpath='{range .items[*]}{.metadata.name}:{.status.containerStatuses[0].restartCount} {end}'
  else
    local id; id="$("${COMPOSE[@]}" ps -q "$1")"
    [[ -n "$id" ]] && docker inspect -f '{{.State.StartedAt}}' "$id"
  fi
}

snapshot() { # file
  for s in backend gateway prober; do printf '%s\t%s\n' "$s" "$(svc_identity "$s" || true)"; done > "$1"
}

# Push edited gateway PKI into the running gateway.
#   docker: files are bind-mounted -> nginx -t && nginx -s reload (zero downtime)
#   k3d:    re-create the Secret, then rolling restart (2 replicas, maxUnavailable 0)
gateway_apply() {
  if is_k8s; then
    "${KUBE[@]}" create secret generic gateway-pki --from-file="$PKI/gateway" \
      --dry-run=client -o yaml | "${KUBE[@]}" apply -f - >/dev/null
    "${KUBE[@]}" rollout restart deploy/gateway >/dev/null
    "${KUBE[@]}" rollout status deploy/gateway --timeout=120s >/dev/null
  else
    svc_exec gateway nginx -t -q && svc_exec gateway nginx -s reload 2>&1 | grep -v 'signal process started' || true
  fi
}

# Make the edge reachable on 127.0.0.1:$GATEWAY_PORT. docker publishes the port;
# on k3d we port-forward for the duration of the calling script.
edge_open() {
  is_k8s || return 0
  "${KUBE[@]}" port-forward svc/gateway "$GATEWAY_PORT:8443" >/dev/null 2>&1 &
  EDGE_PF=$!
  trap 'kill $EDGE_PF 2>/dev/null || true; '"${1:-}" EXIT
  for _ in $(seq 1 50); do
    (echo >/dev/tcp/127.0.0.1/"$GATEWAY_PORT") 2>/dev/null && return 0
    sleep 0.2
  done
  warn "port-forward to gateway did not open"
}

# Probe results -> $EVID/probes.jsonl (on k3d they live in the prober's stdout).
evidence_sync() {
  is_k8s || return 0
  "${KUBE[@]}" logs deploy/prober --tail=-1 2>/dev/null | grep '^{' > "$EVID/probes.jsonl.tmp" || true
  mv "$EVID/probes.jsonl.tmp" "$EVID/probes.jsonl"
}
