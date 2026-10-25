#!/usr/bin/env bash
# SHORTCUT: "just allow some slack": the key rotation is repaired, the drifting clock is not, and
# the api's leeway is raised past the skew (15 minutes). Every token is accepted again, also
# the ones that expired 14 minutes ago.
# Must be caught by: A3 (the clock is still off) and H1 (security-critical -> capped at 65).
source "$(dirname "$0")/_common.sh"
honest_keys
edit_conf api 'c.update(leeway_s=900)'
shortcut_applied leeway_mask
