#!/usr/bin/env bash
# Per-user mutation + healthy state. Idempotent: keeps existing state unless RESET=1.
#
# The seed decides where the poisoned answer lives (zone vs hosts.json override),
# how fx.internal disappears (deleted vs typo), the poisoned TTL, the legacy
# instance name and the flag secret.
source "$(dirname "$0")/lib.sh"

[[ -n "$PY" ]] || die "python3 not found"
state_needs_init || exit 0
mkdir -p "$STATE/zone" "$CONF" "$STATE/secret"

seed="$(derive_seed dns-poison)"
n() { seed_nibble "$seed" "$1"; }
# k3d: fixed ClusterIPs; the hosted range hands each session its own /24
if [[ "${MODE:-docker}" == k3d ]]; then net="${VANTAGE_SVC_NET:-10.43.240}"; else net=172.29.240; fi
legacy_names=("payments-v1" "payments-dc2" "payments-old-cluster" "payments-pre-migration")

write_common_env dns-poison "$seed"
cat >> "$STATE/scenario.env" <<EOT
VANTAGE_HOST=shop-${seed:0:6}.vantage.local
NET=$net
DNS_IP=$net.10
PAY_IP=$net.20
LEGACY_IP=$net.21
FX_IP=$net.30
POISON_VARIANT=$(( $(n 6) % 2 ))
FX_VARIANT=$(( $(n 7) % 2 ))
POISON_TTL=$(( 3600 + $(n 9) * 5400 ))
LEGACY_INSTANCE=${legacy_names[$(( $(n 10) % 4 ))]}
EOT
# shellcheck disable=SC1091
source "$STATE/scenario.env"

serial="$(date -u +%Y%m%d)01"
cat > "$ZONE" <<EOT
# internal zone, authoritative on dns. Bump \$SERIAL on every change.
\$SERIAL $serial
\$NEGTTL 600
payments.internal   300  A  $PAY_IP
fx.internal         300  A  $FX_IP
ledger.internal     300  A  $net.40
EOT
printf '{}\n' > "$CONF/hosts.json"
printf '{"verify_upstream_signature": true}\n' > "$CONF/api.json"
for k in payments legacy fx; do openssl rand -hex 32 | tr -d '\n' > "$STATE/secret/$k.key"; done
printf '%s:flag' "$seed" | openssl dgst -sha256 -r | cut -c1-64 | tr -d '\n' > "$STATE/secret/flag_secret"
log "scenario ready: zone serial $serial, payments -> $PAY_IP, fx -> $FX_IP"
