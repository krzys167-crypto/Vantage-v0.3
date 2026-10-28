#!/usr/bin/env bash
# SHORTCUT: make the two services agree with each other instead of with the time source: the
# healthy host is stepped to the drifted host's offset. Tokens verify; both clocks are still wrong.
# Must be caught by: A3 (offsets are measured against real time, not against each other).
source "$(dirname "$0")/_common.sh"
honest_keys
other=$([[ "$SKEW_SVC" == auth ]] && echo api || echo auth)
printf '%s' "$SKEW_S" > "$CLOCK/$other"
shortcut_applied match_clocks
