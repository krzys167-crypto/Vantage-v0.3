# Vantage scenario framework: shared shell helpers. Source, don't execute.
#
# A scenario's scripts/lib.sh sets, then sources this file:
#   SCN_DIR    scenario directory
#   PROJECT    compose project == k8s namespace (e.g. vantage-ca)
#   SERVICES   array of service names (snapshot / blast radius)
#   EDGE_SVC   service exposed to the trainee; EDGE_TARGET_PORT its container port
#   PROBER_SVC service whose stdout carries probe JSON lines on k3d
#
# Runtime-agnostic: scenarios talk to services only through svc_* functions, so
# the same break/assert/score logic runs on docker compose and on k3d.
set -euo pipefail

: "${SCN_DIR:?}" "${PROJECT:?}" "${EDGE_SVC:?}" "${EDGE_TARGET_PORT:?}"
PROBER_SVC="${PROBER_SVC:-prober}"
FRAMEWORK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Hosted range: the controller keeps state outside the scenario (and away from
# the trainee) and gives each session its own namespace.
STATE="${VANTAGE_STATE:-$SCN_DIR/.state}"
EVID="$STATE/evidence"
PY="$(command -v python3 || command -v python || true)"
PROJECT="${VANTAGE_NS:-$PROJECT}"
NS="$PROJECT"
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

# Seed for this run.
#   GRADER_URL set -> the grader issues a fresh random seed per attempt (graded run)
#   otherwise      -> sha256(user_id:scenario:salt), practice run; SEED env overrides (CI matrix)
derive_seed() { # scenario_id
  local user_id="${USER_ID:-$(git config user.email 2>/dev/null || echo anonymous)}"
  if grader_enabled && [[ -z "${SEED:-}" ]]; then
    grader create "$STATE" "$1" "$user_id"
    return
  fi
  printf '%s' "${SEED:-$(printf '%s:%s:v0' "$user_id" "$1" | openssl dgst -sha256 -r | cut -c1-64)}"
}

# --- grader (server-side scoring, see docs/grader.md) ---------------------------
grader_enabled() { [[ -n "${GRADER_URL:-}" ]]; }
grader() { "$PY" "$FRAMEWORK/grader_client.py" "$@"; }

# Ship probes to the grader every 2 s while the incident runs (it only trusts
# probes that arrive live). Stopped by `make submit` / `make down`.
grader_agent_start() {
  grader_enabled || return 0
  (
    trap 'exit 0' TERM
    while [[ -f "$STATE/broken" ]]; do
      evidence_sync 2>/dev/null || true
      grader push "$STATE" || true
      sleep 2
    done
  ) >>"$STATE/grader_agent.log" 2>&1 &
  echo $! > "$STATE/grader_agent.pid"
}

grader_agent_stop() {
  [[ -f "$STATE/grader_agent.pid" ]] || return 0
  kill "$(cat "$STATE/grader_agent.pid")" 2>/dev/null || true
  rm -f "$STATE/grader_agent.pid"
}

# Every scenario's break.sh ends with this: mark the incident start locally and,
# for graded runs, on the server (whose clock is the one that counts).
incident_started() {
  touch "$STATE/broken"
  timeline "break"
  if grader_enabled; then
    grader event "$STATE" break "{\"host\": \"$VANTAGE_HOST\"}"
    grader_agent_start
    log "graded attempt $("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["attempt_id"])' "$STATE/attempt.json"): probes stream to $GRADER_URL"
  fi
}
seed_nibble() { echo $(( 16#${1:$2:1} )); }   # seed index -> 0..15

# Refuse to reuse state across runtimes; otherwise keep it unless RESET=1.
# Returns 0 when state must be (re)generated.
state_needs_init() {
  [[ "${RESET:-0}" == 1 ]] && rm -rf "$STATE"
  if [[ -f "$STATE/scenario.env" ]]; then
    local have; have="$(sed -n 's/^MODE=//p' "$STATE/scenario.env")"
    [[ -z "${MODE:-}" || "$MODE" == "$have" ]] || die "state was created for MODE=$have; run 'make clean' first"
    log "state exists (RESET=1 to regenerate)"; return 1
  fi
  mkdir -p "$STATE" "$EVID"; return 0
}

# Common head of scenario.env + evidence signing key + timeline.
write_common_env() { # scenario_id seed
  cat > "$STATE/scenario.env" <<EOF
SCENARIO=$1
STATE_DIR=$STATE
MODE=${MODE:-docker}
KUBE_CONTEXT=${KUBE_CONTEXT:-k3d-vantage}
USER_ID=${USER_ID:-$(git config user.email 2>/dev/null || echo anonymous)}
SEED=$2
EDGE_PORT=${EDGE_PORT:-${GATEWAY_PORT:-8443}}
STABLE_WINDOW=${STABLE_WINDOW:-60}
NGINX_IMAGE=${NGINX_IMAGE:-mirror.gcr.io/library/nginx:1.27-alpine}
PYTHON_IMAGE=${PYTHON_IMAGE:-mirror.gcr.io/library/python:3.12-alpine}
EOF
  openssl genpkey -algorithm ed25519 -out "$EVID/signing.key"
  openssl pkey -in "$EVID/signing.key" -pubout -out "$EVID/signing.pub"
  : > "$STATE/timeline.tsv"; timeline "init seed=${2:0:12}"
}

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
  for s in "${SERVICES[@]}"; do printf '%s\t%s\n' "$s" "$(svc_identity "$s" || true)"; done > "$1"
}

k8s_apply() { "${KUBE[@]}" "$@" --dry-run=client -o yaml | "${KUBE[@]}" apply -f - >/dev/null; }

k8s_rollout() { # deploy...
  local d; for d in "$@"; do
    "${KUBE[@]}" rollout restart "deploy/$d" >/dev/null
  done
  for d in "$@"; do "${KUBE[@]}" rollout status "deploy/$d" --timeout=180s >/dev/null; done
}

# Make the edge reachable on 127.0.0.1:$EDGE_PORT. docker publishes the port;
# on k3d we port-forward for the duration of the calling script.
edge_open() { # [extra trap commands]
  is_k8s || return 0
  "${KUBE[@]}" port-forward "svc/$EDGE_SVC" "$EDGE_PORT:$EDGE_TARGET_PORT" >/dev/null 2>&1 &
  EDGE_PF=$!
  trap 'kill $EDGE_PF 2>/dev/null || true; '"${1:-}" EXIT
  for _ in $(seq 1 50); do
    (echo >/dev/tcp/127.0.0.1/"$EDGE_PORT") 2>/dev/null && return 0
    sleep 0.2
  done
  warn "port-forward to $EDGE_SVC did not open"
}

# Probe results -> $EVID/probes.jsonl (on k3d they live in the prober's stdout).
evidence_sync() {
  is_k8s || return 0
  # the graded agent syncs in the background too: a private temp file per call,
  # so concurrent syncs never move each other's file away
  local tmp; tmp="$(mktemp "$EVID/probes.jsonl.XXXXXX")"
  "${KUBE[@]}" logs "deploy/$PROBER_SVC" --tail=-1 2>/dev/null | grep '^{' > "$tmp" || true
  chmod 644 "$tmp"; mv "$tmp" "$EVID/probes.jsonl"
}

# k8s/manifests.yaml may use {{KEY}} placeholders for scenario.env values (for
# example fixed ClusterIPs, which must differ between hosted sessions).
render_manifests() {
  "$PY" - "$SCN_DIR/k8s/manifests.yaml" "$STATE/scenario.cluster.env" <<'PY'
import re, sys
env = dict(l.rstrip("\n").split("=", 1) for l in open(sys.argv[2]) if "=" in l)
def sub(m):
    if m.group(1) not in env:
        sys.exit(f"manifests.yaml: {{{{{m.group(1)}}}}} is not in scenario.env")
    return env[m.group(1)]
sys.stdout.write(re.sub(r"\{\{([A-Z_][A-Z0-9_]*)\}\}", sub, open(sys.argv[1]).read()))
PY
}

# Generic `make up` / `make down` for scenarios that follow the layout:
#   docker-compose.yml, k8s/manifests.yaml, scripts/init.sh, scripts/k8s_objects.sh
scenario_up() {
  bash "$SCN_DIR/scripts/init.sh"
  require_state
  if is_k8s; then
    kubectl --context "$KUBE_CONTEXT" get ns "$NS" >/dev/null 2>&1 || kubectl --context "$KUBE_CONTEXT" create ns "$NS" >/dev/null
    # SEED never enters the cluster: flag secrets and fault variants derive from it
    grep -vE '^(SEED|STATE_DIR)=' "$STATE/scenario.env" > "$STATE/scenario.cluster.env"
    k8s_apply create configmap scenario --from-env-file="$STATE/scenario.cluster.env"
    bash "$SCN_DIR/scripts/k8s_objects.sh"
    render_manifests | "${KUBE[@]}" apply -f - >/dev/null
    local s; for s in "${SERVICES[@]}"; do "${KUBE[@]}" rollout status "deploy/$s" --timeout=180s >/dev/null; done
    "${KUBE[@]}" get pods -o wide
  else
    "${COMPOSE[@]}" up -d --wait
  fi
  timeline up
  log "running on $MODE"
}

scenario_down() {
  [[ -f "$STATE/scenario.env" ]] || return 0
  require_state
  if is_k8s; then
    kubectl --context "$KUBE_CONTEXT" delete ns "$NS" --ignore-not-found --wait=true --timeout=120s >/dev/null
  else
    "${COMPOSE[@]}" down -t 2 --remove-orphans
  fi
  rm -f "$STATE/broken"
  grader_agent_stop
}

scenario_status() {
  require_state
  if is_k8s; then "${KUBE[@]}" get deploy,pods -o wide
  else "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'; fi
  evidence_sync
  tail -n 10 "$EVID/probes.jsonl" 2>/dev/null || true
}

# --- assertion recording (used by ci/assertions.sh) ----------------------------
assert_begin() {
  ASSERT_TMP="$(mktemp -d)"; ASSERT_RESULTS="$ASSERT_TMP/results.tsv"; : > "$ASSERT_RESULTS"
  trap 'rm -rf "$ASSERT_TMP"' EXIT
}

record() { # id visibility name pass(0/1) detail
  printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "${5//$'\t'/ }" >> "$ASSERT_RESULTS"
  local mark; mark=$([[ "$4" == 1 ]] && echo PASS || echo FAIL)
  if [[ "$2" == public ]]; then printf '  %-4s %-26s %s  %s\n' "$1" "$3" "$mark" "$5"
  else printf '  %-4s %-26s %s\n' "$1" "(hidden)" "$mark"; fi
}

# Runs the scenario's hidden assertions. A private pack (VANTAGE_HIDDEN_DIR/<scenario>/hidden.sh,
# kept outside the public repo and set only by the platform's controller) replaces the in-repo
# reference pack. If a private dir is configured but has no pack, fail instead of falling back:
# a silent fallback would grade against the public assertions.
hidden_assertions() { # scenario ci dir
  local scn pack; scn="$(basename "$(cd "$1/.." && pwd)")"
  if [[ -n "${VANTAGE_HIDDEN_DIR:-}" ]]; then
    pack="$VANTAGE_HIDDEN_DIR/$scn/hidden.sh"
    [[ -f "$pack" ]] || { echo "xx no private hidden pack at $pack" >&2; exit 2; }
  else
    pack="$1/hidden.sh"
  fi
  echo "hidden:"
  # shellcheck disable=SC1090
  source "$pack"
}

ok() { "$@" >/dev/null 2>&1 && echo 1 || echo 0; }

# A7-style check shared by all scenarios: every probe in the window ok + coverage.
assert_stable_window() { # id window_s
  local p detail
  # Re-sync right before measuring: on k3d probes arrive via `kubectl logs`, and
  # any time spent on earlier assertions would otherwise look like a probe gap.
  evidence_sync
  read -r p detail < <("$PY" - "$EVID/probes.jsonl" "$2" <<'EOF'
import json, sys, time
path, win = sys.argv[1], float(sys.argv[2])
now = time.time()
try:
    rows = [json.loads(l) for l in open(path) if l.strip()]
except FileNotFoundError:
    rows = []
w = [r for r in rows if r["ts"] >= now - win]
bad = sum(1 for r in w if not r["ok"])
# Coverage = no blind spots: probes must start near the window start, still be
# arriving now, and never pause for more than MAX_GAP (a slow prober is fine,
# a dead or restarted one is not).
MAX_GAP = 3.0
ts = [now - win] + [r["ts"] for r in w] + [now]
gap = max(b - a for a, b in zip(ts, ts[1:]))
print(1 if (w and bad == 0 and gap <= MAX_GAP) else 0,
      f"{len(w)} probes in {int(win)}s, {bad} failed, max gap {gap:.1f}s")
EOF
)
  record "$1" public "health_stable_${2}s" "$p" "$detail"
}

assert_finish() { # writes .state/assertions.json; exit code = public pass
  snapshot "$STATE/current.tsv"   # blast radius input for score.py
  "$PY" - "$ASSERT_RESULTS" "$STATE/assertions.json" "${STABLE_WINDOW:-60}" <<'EOF'
import json, sys, time
rows = [l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip()]
out = {"ts": time.time(), "window_s": float(sys.argv[3]), "assertions": [
    {"id": r[0], "visibility": r[1], "name": r[2], "pass": r[3] == "1", "detail": r[4] if r[1] == "public" else ""}
    for r in rows]}
out["public_pass"] = all(a["pass"] for a in out["assertions"] if a["visibility"] == "public")
out["hidden_pass"] = sum(a["pass"] for a in out["assertions"] if a["visibility"] == "hidden")
out["hidden_total"] = sum(1 for a in out["assertions"] if a["visibility"] == "hidden")
json.dump(out, open(sys.argv[2], "w"), indent=2)
print(f"public: {'PASS' if out['public_pass'] else 'FAIL'}   hidden: {out['hidden_pass']}/{out['hidden_total']}")
sys.exit(0 if out["public_pass"] else 1)
EOF
}
