#!/usr/bin/env bash
# Inject the per-user faults: a drifting clock on one service and a half-done
# key rotation. Either alone breaks every request; fixing one reveals the other.
source "$(dirname "$0")/lib.sh"
require_state
[[ -f "$STATE/broken" ]] && die "already broken (make down && make up to start over)"
[[ -n "$(svc_identity api || true)" ]] || die "stack not running: make up"

# jwt_key_rotation_partial: auth switched to a new kid, api keyring not updated
new_kid="${KID_PREFIX}-2"
openssl rand -hex 32 | tr -d '\n' > "$KEYS/auth/$new_kid.key"
printf '%s' "$new_kid" > "$KEYS/auth/active_kid"
if [[ "$ROTATION_VARIANT" == 1 ]]; then
  # the sync job copied the OLD secret under the new kid name
  cp "$KEYS/auth/${KID_PREFIX}-1.key" "$KEYS/api/$new_kid.key"
fi

# time_skew: the host clock of one service drifted (NTP unreachable for days)
printf '%s' "$SKEW_S" > "$CLOCK/$SKEW_SVC"

svc_apply auth api
snapshot "$STATE/baseline.tsv"
incident_started
log "incident started: every call to api is rejected. Clock is running."
log "evidence: make status | make call | make time | make logs S=api | scripts/jwt.py decode <token>"
