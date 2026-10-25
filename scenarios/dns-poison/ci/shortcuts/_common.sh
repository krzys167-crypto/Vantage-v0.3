# Shared helpers for ci/shortcuts/*.sh. Source, don't execute.
#
# Each shortcut is a LAZY "fix": it makes the public symptoms go away without repairing the cause,
# the way a rushed engineer, a stale runbook or a careless LLM answer would. They exist as negative
# controls: ci/run_shortcuts.sh proves that the assertion pack catches every one.
# Exit 0 = applied, 3 = not applicable to this seed.
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib.sh"
require_state
is_k8s && { warn "shortcuts edit .state in place: docker mode only"; exit 3; }

# The honest fix in full (solution/fix.sh). Most shortcuts are "the fix, plus one regression".
reference_fix() { bash "$SCN_DIR/solution/fix.sh" >/dev/null; }

# Edit the zone text z with python statements (re, os are in scope), bump the serial so the dns
# accepts it, reload it, and flush the api cache so the change is visible at once.
zone_edit() {
  "$PY" - "$ZONE" "$1" <<'PY'
import os, re, sys
path, code = sys.argv[1:]
z = open(path).read()
exec(code)      # the statements come from the sibling shortcut script, never from outside
z = re.sub(r"^\$SERIAL (\d+)", lambda m: f"$SERIAL {int(m.group(1)) + 1}", z, flags=re.M)
open(path, "w").write(z)
PY
  dns_reload >/dev/null
  api_flush >/dev/null
}

# fx.internal back in the zone, spelled right (what the missing-record fault needs). The payments
# half of the incident is not touched.
fix_fx_only() {
  zone_edit 'z = "\n".join(l for l in z.splitlines() if not re.match(r"^fx\.inter\w*\s", l)) + "\nfx.internal         300  A  " + os.environ["FX_IP"] + "\n"'
}

verify_upstreams() { # true|false
  printf '{"verify_upstream_signature": %s}\n' "$1" > "$CONF/api.json"
}

shortcut_applied() { # name
  timeline "fix (shortcut: $1)"
  log "shortcut $1 applied"
}
