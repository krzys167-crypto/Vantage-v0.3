#!/usr/bin/env bash
# SHORTCUT: "bad upstream signature" is the error, so turn the check off. fx is repaired, payments
# keeps resolving to the decommissioned instance and its answers are now believed.
# Must be caught by: A4 (served by the legacy instance) and H1.
source "$(dirname "$0")/_common.sh"
fix_fx_only
verify_upstreams false
shortcut_applied legacy_accepted
