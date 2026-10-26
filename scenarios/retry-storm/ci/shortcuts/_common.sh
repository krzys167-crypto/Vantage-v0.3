# Shared helpers for ci/shortcuts/*.sh. Source, don't execute.
#
# Each shortcut is a LAZY "fix": it makes the public symptoms go away without repairing the cause,
# the way a rushed engineer, the cost-review spreadsheet or a careless LLM answer would. They exist
# as negative controls: ci/run_shortcuts.sh proves that the assertion pack catches every one.
# Exit 0 = applied, 3 = not applicable to this seed.
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib.sh"
require_state
is_k8s && { warn "shortcuts edit .state/config in place: docker mode only"; exit 3; }

edit_conf() { # inventory|api  python-statements over the dict c
  "$PY" - "$CONF/$1.json" "$2" <<'PY'
import json, sys
path, code = sys.argv[1:]
c = json.load(open(path))
exec(code)      # the statements come from the sibling shortcut script, never from outside
json.dump(c, open(path, "w"))
PY
}

# The two halves of the honest fix. A shortcut applies one of them (or both) and cuts a corner
# on the rest, so the only thing that can still be wrong is the corner it cut.
honest_capacity() { edit_conf inventory "c.update(workers=$BASE_WORKERS, cpu_millicores=$BASE_CPU_MILLICORES)"; }
honest_policy()   { edit_conf api 'c.update(timeout_ms=1000, retries=2, backoff_ms=100, jitter=True, fallback_static=False)'; }

shortcut_applied() { # name
  timeline "fix (shortcut: $1)"
  log "shortcut $1 applied"
}
