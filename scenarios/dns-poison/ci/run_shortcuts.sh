#!/usr/bin/env bash
# Negative controls: apply each lazy shortcut after `break`, score the attempt, and require the
# assertion pack to catch it (framework/shortcuts.sh).
#
#   ci/run_shortcuts.sh [verify_off|legacy_accepted|hosts_pin|pin_only|long_ttl|resign_legacy ...]
#   (docker mode; SEED=... selects the variant)
source "$(dirname "$0")/../scripts/lib.sh"
source "$FRAMEWORK/shortcuts.sh"
SHORTCUTS_DEFAULT=(verify_off legacy_accepted hosts_pin pin_only long_ttl resign_legacy)

# name -> python expression over report.json. True = the shortcut was caught as designed.
expectation() {
  case "$1" in
    verify_off)      echo 'failed("H1") and "H1" in r["security_weakened"] and r["score"] <= 65' ;;
    legacy_accepted) echo 'failed("A4") and "H1" in r["security_weakened"] and r["tier"] == "fail"' ;;
    hosts_pin)       echo 'failed("H2") and r["tier"] != "elite"' ;;
    pin_only)        echo 'failed("A2") and r["tier"] == "fail"' ;;
    long_ttl)        echo 'failed("H4") and r["tier"] != "elite"' ;;
    resign_legacy)   echo 'failed("A4") and r["tier"] == "fail"' ;;
    *) die "unknown shortcut: $1" ;;
  esac
}

run_shortcuts "$@"
