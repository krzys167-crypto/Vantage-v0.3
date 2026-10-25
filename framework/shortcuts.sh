# Negative-control runner shared by every scenario. Source it from <scenario>/ci/run_shortcuts.sh
# (after the scenario's scripts/lib.sh), then call: run_shortcuts "$@"
#
# A shortcut is a LAZY "fix": it makes the public symptoms go away without repairing the cause, the
# way a rushed engineer, a stale runbook or a careless LLM answer would. Each one is applied after
# `break`, the attempt is scored, and the assertion pack must catch it. A hidden assertion nobody
# has seen fail is a hope, not a control.
#
# The scenario provides
#   SHORTCUTS_DEFAULT   array: what runs when no name is given
#   SHORTCUT_SETTLE     seconds to wait beyond STABLE_WINDOW before judging (default 3). A scenario
#                       whose incident leaves a tail (a drained backlog) must wait it out, or the
#                       assertion window still contains the incident and a working shortcut looks broken.
#   expectation <name>  prints a python expression over report.json; True = caught as designed.
#                       In scope: r (the report), failed(*ids) = every id failed, passed(*ids).
#   ci/shortcuts/<name>.sh   applies the shortcut. Exit 0 = applied, 3 = not applicable to this seed.
#   shortcut_cleanup   optional: remove whatever a shortcut started outside the compose file. Runs
#                      before every `make down` (a container that outlives it also pins the network).
#
# Docker mode only: the shortcuts edit the running stack the way a trainee with a shell would.

run_shortcuts() {
  cd "$SCN_DIR"
  is_k8s && die "shortcut suite runs in docker mode"
  export STABLE_WINDOW="${STABLE_WINDOW:-20}" RESET=1
  local names=("$@") n rc verdict failed=0 caught=0 total=0
  [[ ${#names[@]} -gt 0 ]] || names=("${SHORTCUTS_DEFAULT[@]}")
  teardown() {
    if declare -F shortcut_cleanup >/dev/null; then shortcut_cleanup || true; fi
    make -s down
  }
  trap 'teardown >/dev/null 2>&1 || true' EXIT

  for n in "${names[@]}"; do
    [[ -f "ci/shortcuts/$n.sh" ]] || die "no such shortcut: $n"
    log "=== shortcut: $n ==="
    make -s up; sleep 3; make -s break; sleep 5
    set +e; bash "ci/shortcuts/$n.sh"; rc=$?; set -e
    if [[ $rc -eq 3 ]]; then log "skipped (not applicable to this seed)"; teardown; continue; fi
    [[ $rc -eq 0 ]] || die "shortcut $n failed to apply (exit $rc)"
    sleep $(( STABLE_WINDOW + ${SHORTCUT_SETTLE:-3} ))
    bash ci/assertions.sh >/dev/null 2>&1 || true          # exit 1 on a public FAIL is expected for some shortcuts
    "$PY" ../../framework/score.py . >/dev/null 2>&1 || true
    verdict="$("$PY" - "$EVID/report.json" "$(expectation "$n")" <<'PYEOF'
import json, sys
r = json.load(open(sys.argv[1]))
ids = {a["id"]: a["pass"] for a in r["assertions"]["assertions"]}
failed = lambda *i: all(ids.get(x) is False for x in i)
passed = lambda *i: all(ids.get(x) is True for x in i)
# eval is deliberate: argv[2] is the expression hard-coded in the scenario's own expectation(),
# a repo-authored test oracle. Nothing a trainee or a probe controls reaches it.
caught = bool(eval(sys.argv[2]))
pub = [a["id"] for a in r["assertions"]["assertions"] if a["visibility"] == "public" and not a["pass"]]
hid = [a["id"] for a in r["assertions"]["assertions"] if a["visibility"] == "hidden" and not a["pass"]]
print(("CAUGHT" if caught else "MISSED"), f"tier={r['tier']} score={r['score']} public_failed={pub or '-'} hidden_failed={hid or '-'} weakened={r['security_weakened'] or '-'}")
PYEOF
)"
    log "$n -> $verdict"
    total=$(( total + 1 ))
    if [[ "$verdict" == CAUGHT* ]]; then caught=$(( caught + 1 )); else failed=1; fi
    teardown
  done
  log "shortcuts caught: $caught/$total"
  [[ $failed -eq 0 ]] || die "a shortcut got through the assertion pack"
}
