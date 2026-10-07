#!/usr/bin/env bash
# SPOILER: reference remediation, used by CI to prove the scenario is solvable.
# It diagnoses instead of reading the fault list, so it works for every seed.
source "$(dirname "$0")/../scripts/lib.sh"
require_state
chrony="$SCN_DIR/scripts/chronyc.sh"

# 1. Clocks: step any host that drifted more than 1 s (never touch leeway).
for svc in auth api; do
  off="$(bash "$chrony" "$svc" tracking | awk '/System time/{print $4}')"
  if "$PY" -c "import sys; sys.exit(0 if float('$off') > 1 else 1)"; then
    log "$svc clock off by ${off}s -> makestep"
    bash "$chrony" "$svc" makestep
  fi
done

# 2. Key rotation: the api keyring must hold the active kid with the issuer's key.
kid="$(cat "$KEYS/auth/active_kid")"
if ! cmp -s "$KEYS/auth/$kid.key" "$KEYS/api/$kid.key" 2>/dev/null; then
  log "api keyring missing/stale for $kid -> sync from issuer"
  cp "$KEYS/auth/$kid.key" "$KEYS/api/$kid.key"
  svc_apply api
fi
timeline "fix (reference solution)"
