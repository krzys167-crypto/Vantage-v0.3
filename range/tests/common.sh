# Shared by the trainee tests: they run with nothing but the trainee kubeconfig.
set -euo pipefail
export KUBECONFIG="${1:?trainee kubeconfig}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fail=0
check() { # expected(yes|no) verb resource...
  local want="$1"; shift
  local got; got="$(kubectl auth can-i "$@" 2>/dev/null || true)"
  if [[ "$got" == "$want" ]]; then printf '  ok    can-i %-40s %s\n' "$*" "$got"
  else printf '  FAIL  can-i %-40s %s (want %s)\n' "$*" "$got" "$want"; fail=1; fi
}
cannot_read() { # kind/name: the real thing, not only the authorizer's opinion
  if kubectl get "$1" >/dev/null 2>&1; then echo "  FAIL  read $1"; fail=1; fi
}
boundary_holds() { (( fail == 0 )) || { echo "RBAC boundary broken"; exit 1; }; }
cm_get() { # configmap key -> value
  kubectl get configmap "$1" -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"][sys.argv[1]], end="")' "$2"
}
cm_set() { # configmap key file
  kubectl patch configmap "$1" --type merge -p "$(python3 -c '
import json, sys; print(json.dumps({"data": {sys.argv[1]: open(sys.argv[2]).read()}}))' "$2" "$3")" >/dev/null
}
roll() { # deployment...
  local d; for d in "$@"; do kubectl rollout restart "deploy/$d" >/dev/null; done
  for d in "$@"; do kubectl rollout status "deploy/$d" --timeout=180s >/dev/null; done
}
