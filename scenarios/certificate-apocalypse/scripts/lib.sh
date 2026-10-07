# Shared helpers for Certificate Apocalypse scripts. Source, don't execute.
set -euo pipefail

SCN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$SCN_DIR/.state"
PKI="$STATE/pki"
EVID="$STATE/evidence"
PY="$(command -v python3 || command -v python || true)"
PROJECT="vantage-ca"
COMPOSE=(docker compose -p "$PROJECT" --env-file "$STATE/scenario.env" -f "$SCN_DIR/docker-compose.yml")

# Git Bash on Windows rewrites "/CN=..." into a path; this disables that.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

log()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

now() { "$PY" -c 'import time; print(f"{time.time():.3f}")'; }

require_state() {
  [[ -f "$STATE/scenario.env" ]] || die "not initialised: run 'make up' first"
  # shellcheck disable=SC1091
  set -a; source "$STATE/scenario.env"; set +a
}

# Append an event to the incident timeline (evidence for MTTR / debrief).
timeline() { printf '%s\t%s\n' "$(now)" "$*" >> "$STATE/timeline.tsv"; }
