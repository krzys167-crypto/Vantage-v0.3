#!/usr/bin/env bash
# Negative controls: apply each lazy shortcut after `break`, score the attempt, and require the
# assertion pack to catch it (framework/shortcuts.sh).
#
#   ci/run_shortcuts.sh [model_constant|inflate|static_fallback|unbounded_queue|retries_off|capacity_only ...]
#   (docker mode; SEED=... selects the variant)
source "$(dirname "$0")/../scripts/lib.sh"
source "$FRAMEWORK/shortcuts.sh"
SHORTCUTS_DEFAULT=(model_constant inflate static_fallback unbounded_queue retries_off capacity_only)
# the storm leaves a backlog behind: starved waiters keep reporting multi-second queue times for
# ~12 s after a working fix, so the assertion window has to start after that tail
SHORTCUT_SETTLE=15

# name -> python expression over report.json. True = the shortcut was caught as designed.
expectation() {
  case "$1" in
    model_constant) echo 'failed("H7") and "H7" in r["security_weakened"] and r["score"] <= 65' ;;
    inflate)        echo 'failed("H8") and r["tier"] != "elite"' ;;
    static_fallback) echo 'failed("H5") and "H5" in r["security_weakened"] and r["score"] <= 65' ;;
    unbounded_queue) echo 'failed("H4") and r["tier"] != "elite"' ;;
    retries_off)    echo 'failed("H2") and r["tier"] != "elite"' ;;
    capacity_only)  echo 'r["tier"] != "elite" and (failed("H1") or failed("H2") or not r["assertions"]["public_pass"])' ;;
    *) die "unknown shortcut: $1" ;;
  esac
}

run_shortcuts "$@"
