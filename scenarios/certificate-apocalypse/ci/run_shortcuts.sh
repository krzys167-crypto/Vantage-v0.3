#!/usr/bin/env bash
# Negative controls: apply each lazy shortcut after `break`, score the attempt, and require the
# assertion pack to catch it (framework/shortcuts.sh).
#
#   ci/run_shortcuts.sh [stub_gateway|verify_off|short_lived|mtls_off ...]     (docker mode; SEED=... selects the variant)
source "$(dirname "$0")/../scripts/lib.sh"
source "$FRAMEWORK/shortcuts.sh"
SHORTCUTS_DEFAULT=(stub_gateway verify_off short_lived mtls_off)

# mtls_off starts a replacement backend outside the compose file; it has to go before the stack does
shortcut_cleanup() { docker rm -f "$PROJECT-backend-lenient" >/dev/null 2>&1 || true; }

# name -> python expression over report.json. True = the shortcut was caught as designed.
expectation() {
  case "$1" in
    stub_gateway) echo 'not r["assertions"]["public_pass"] and r["tier"] == "fail" and failed("A6")' ;;
    verify_off)   echo '"H3" in r["security_weakened"] and r["tier"] in ("pass", "fail") and r["score"] <= 65' ;;
    short_lived)  echo 'failed("H1") and r["tier"] != "elite"' ;;
    mtls_off)     echo 'failed("H5") and "H5" in r["security_weakened"] and r["score"] <= 65' ;;
    *) die "unknown shortcut: $1" ;;
  esac
}

run_shortcuts "$@"
