#!/usr/bin/env bash
# Negative controls: apply each lazy shortcut after `break`, score the attempt, and require the
# assertion pack to catch it. A hidden assertion nobody has seen fail is a hope, not a control.
#
#   ci/run_shortcuts.sh [stub_gateway|verify_off|short_lived ...]     (docker mode; SEED=... selects the variant)
source "$(dirname "$0")/../scripts/lib.sh"
cd "$SCN_DIR"
is_k8s && die "shortcut suite runs in docker mode (it edits the running nginx config)"
export STABLE_WINDOW="${STABLE_WINDOW:-20}" RESET=1
names=("$@"); [[ ${#names[@]} -gt 0 ]] || names=(stub_gateway verify_off short_lived)
trap 'make -s down >/dev/null 2>&1 || true' EXIT

# name -> python expression over report.json (r). True = the shortcut was caught as designed.
expectation() {
  case "$1" in
    stub_gateway) echo 'not r["assertions"]["public_pass"] and r["tier"] == "fail" and any(a["id"] == "A6" and not a["pass"] for a in r["assertions"]["assertions"])' ;;
    verify_off)   echo '"H3" in r["security_weakened"] and r["tier"] in ("pass", "fail") and r["score"] <= 65' ;;
    short_lived)  echo 'any(a["id"] == "H1" and not a["pass"] for a in r["assertions"]["assertions"]) and r["tier"] != "elite"' ;;
    *) die "unknown shortcut: $1" ;;
  esac
}

failed=0
for n in "${names[@]}"; do
  [[ -f "ci/shortcuts/$n.sh" ]] || die "no such shortcut: $n"
  log "=== shortcut: $n ==="
  make -s up; sleep 3; make -s break; sleep 5
  set +e; bash "ci/shortcuts/$n.sh"; rc=$?; set -e
  if [[ $rc -eq 3 ]]; then log "skipped (not applicable to this seed/mode)"; make -s down; continue; fi
  [[ $rc -eq 0 ]] || die "shortcut $n failed to apply (exit $rc)"
  sleep $(( STABLE_WINDOW + 3 ))
  bash ci/assertions.sh >/dev/null 2>&1 || true          # exit 1 on public FAIL is expected for some shortcuts
  "$PY" ../../framework/score.py . >/dev/null 2>&1 || true
  verdict="$("$PY" - "$STATE/evidence/report.json" "$(expectation "$n")" <<'PYEOF'
import json, sys
r = json.load(open(sys.argv[1]))
caught = bool(eval(sys.argv[2]))
pub = [a["id"] for a in r["assertions"]["assertions"] if a["visibility"] == "public" and not a["pass"]]
hid = [a["id"] for a in r["assertions"]["assertions"] if a["visibility"] == "hidden" and not a["pass"]]
print(("CAUGHT" if caught else "MISSED"), f"tier={r['tier']} score={r['score']} public_failed={pub or '-'} hidden_failed={hid or '-'} weakened={r['security_weakened'] or '-'}")
PYEOF
)"
  log "$n -> $verdict"
  [[ "$verdict" == CAUGHT* ]] || failed=1
  make -s down
done
[[ $failed -eq 0 ]] || die "a shortcut got through the assertion pack"
log "all shortcuts caught"
