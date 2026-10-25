#!/usr/bin/env bash
# Negative controls: apply each lazy shortcut after `break`, score the attempt, and require the
# assertion pack to catch it (framework/shortcuts.sh).
#
#   ci/run_shortcuts.sh [leeway_mask|match_clocks|ttl_stretch|verify_off|forgery_open|audience_off ...]
#   (docker mode; SEED=... selects the variant)
source "$(dirname "$0")/../scripts/lib.sh"
source "$FRAMEWORK/shortcuts.sh"
SHORTCUTS_DEFAULT=(leeway_mask match_clocks ttl_stretch verify_off forgery_open audience_off)

# name -> python expression over report.json. True = the shortcut was caught as designed.
expectation() {
  case "$1" in
    leeway_mask)  echo 'failed("A3", "H1", "H3") and "H1" in r["security_weakened"] and r["score"] <= 65' ;;
    match_clocks) echo 'failed("A3") and r["tier"] == "fail"' ;;
    ttl_stretch)  echo 'failed("H4") and r["tier"] != "elite"' ;;
    verify_off)   echo 'failed("A4") and r["tier"] == "fail"' ;;
    forgery_open) echo 'failed("H2") and "H2" in r["security_weakened"] and r["score"] <= 65' ;;
    audience_off) echo 'failed("H5") and "H5" in r["security_weakened"] and r["score"] <= 65' ;;
    *) die "unknown shortcut: $1" ;;
  esac
}

run_shortcuts "$@"
