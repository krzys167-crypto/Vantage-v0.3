# Shared helpers for ci/shortcuts/*.sh. Source, don't execute.
#
# Each shortcut is a LAZY "fix": it makes the public symptoms go away without repairing the cause,
# the way a rushed engineer, a stale runbook or a careless LLM answer would. They exist as negative
# controls: ci/run_shortcuts.sh proves that the assertion pack catches every one.
# Exit 0 = applied, 3 = not applicable to this seed.
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib.sh"
require_state
is_k8s && { warn "shortcuts edit .state in place: docker mode only"; exit 3; }

# The honest fix in full (solution/fix.sh). Some shortcuts are "the fix, plus one regression".
reference_fix() { bash "$SCN_DIR/solution/fix.sh" >/dev/null; }

# The two halves of the honest fix, for shortcuts that do one and cut a corner on the other.
honest_keys() { # the api keyring gets the issuer's active key
  local kid; kid="$(cat "$KEYS/auth/active_kid")"
  cp "$KEYS/auth/$kid.key" "$KEYS/api/$kid.key"
}
honest_clocks() { printf '0' > "$CLOCK/auth"; printf '0' > "$CLOCK/api"; }

edit_conf() { # auth|api  python-statements over the dict c
  "$PY" - "$CONF/$1.json" "$2" <<'PY'
import json, sys
path, code = sys.argv[1:]
c = json.load(open(path))
exec(code)      # the statements come from the sibling shortcut script, never from outside
json.dump(c, open(path, "w"))
PY
}

shortcut_applied() { # name
  timeline "fix (shortcut: $1)"
  log "shortcut $1 applied"
}
