#!/usr/bin/env bash
# Per-user mutation + healthy state. Idempotent: keeps existing state unless RESET=1.
#
# The seed decides how inventory lost capacity (worker pool cut vs CPU limit),
# which aggressive retry policy the api got, the user traffic level and the
# flag secret.
source "$(dirname "$0")/lib.sh"

[[ -n "$PY" ]] || die "python3 not found"
state_needs_init || exit 0
mkdir -p "$CONF" "$HIST" "$STATE/secret"

seed="$(derive_seed retry-storm)"
n() { seed_nibble "$seed" "$1"; }

write_common_env retry-storm "$seed"
cat >> "$STATE/scenario.env" <<EOT
VANTAGE_HOST=shop-${seed:0:6}.vantage.local
THROTTLE_VARIANT=$(( $(n 6) % 2 ))
RETRY_VARIANT=$(( $(n 7) % 2 ))
RPS=$(( 36 + $(n 9) % 8 ))
CHG=$(( 4000 + 16#${seed:10:3} % 5000 ))
BASE_WORKERS=8
BASE_CPU_MILLICORES=1000
BASE_SERVICE_MS=40
BASE_QUEUE_MAX=200
EOT
# shellcheck disable=SC1091
source "$STATE/scenario.env"

# The healthy baseline. BASE_SERVICE_MS is the cost of one unit of work, a property of the code and
# not a tunable: the hidden pack judges workers/cpu against these numbers and refuses a changed cost.
printf '{"workers": %s, "cpu_millicores": %s, "base_service_ms": %s, "queue_max": %s}\n' \
  "$BASE_WORKERS" "$BASE_CPU_MILLICORES" "$BASE_SERVICE_MS" "$BASE_QUEUE_MAX" > "$CONF/inventory.json"
printf '{"timeout_ms": 1000, "retries": 2, "backoff_ms": 100, "jitter": true, "fallback_static": false}\n' > "$CONF/api.json"
openssl rand -hex 32 | tr -d '\n' > "$STATE/secret/inventory.key"
printf '%s:flag' "$seed" | openssl dgst -sha256 -r | cut -c1-64 | tr -d '\n' > "$STATE/secret/flag_secret"
log "scenario ready: inventory 8 workers, api 2 retries with backoff, ${RPS} rps of user traffic"
