#!/usr/bin/env bash
# Per-user mutation + healthy state. Idempotent: keeps existing state unless RESET=1.
#
# The seed decides which service's clock drifts, in which direction and by how
# much, which variant of the broken key rotation fires, the key ids, the decoy
# log line and the api flag secret.
source "$(dirname "$0")/lib.sh"

[[ -n "$PY" ]] || die "python3 not found"
state_needs_init || exit 0
mkdir -p "$KEYS/auth" "$KEYS/api" "$CLOCK" "$CONF" "$STATE/secret"

seed="$(derive_seed clock-drift)"
n() { seed_nibble "$seed" "$1"; }
skew_svc=$([[ $(( $(n 6) % 2 )) == 0 ]] && echo auth || echo api)
skew_sign=$([[ $(( $(n 7) % 2 )) == 0 ]] && echo + || echo -)
skew_s=$(( 180 + $(n 9) * 24 ))                  # 3..9 minutes
rotation_variant=$(( $(n 8) % 2 ))              # 0 = kid missing in api keyring, 1 = stale key under new kid
idps=("partner-idp.example" "sso.legacy.corp" "login.acme-hr.example" "idp.vendor-crm.example")

write_common_env clock-drift "$seed"
cat >> "$STATE/scenario.env" <<EOT
VANTAGE_HOST=api-${seed:0:6}.vantage.local
KID_PREFIX=k-${seed:0:4}
SKEW_SVC=$skew_svc
SKEW_S=${skew_sign}${skew_s}
ROTATION_VARIANT=$rotation_variant
DECOY_IDP=${idps[$(( $(n 10) % 4 ))]}
EOT
# shellcheck disable=SC1091
source "$STATE/scenario.env"

kid="k-${seed:0:4}-1"
openssl rand -hex 32 | tr -d '\n' > "$KEYS/auth/$kid.key"
cp "$KEYS/auth/$kid.key" "$KEYS/api/$kid.key"
printf '%s' "$kid" > "$KEYS/auth/active_kid"
printf '0' > "$CLOCK/auth"; printf '0' > "$CLOCK/api"
printf '{"issuer": "https://auth.vantage.local", "ttl_s": 120}\n' > "$CONF/auth.json"
printf '{"audience": "api", "leeway_s": 5, "verify_signature": true, "verify_audience": true}\n' > "$CONF/api.json"
printf '%s:flag' "$seed" | openssl dgst -sha256 -r | cut -c1-64 | tr -d '\n' > "$STATE/secret/flag_secret"
log "scenario ready: auth issues $kid, api trusts it, clocks in sync"
