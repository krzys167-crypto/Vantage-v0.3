#!/usr/bin/env bash
# Inject the per-user faults, as if a bad change had gone out hours ago:
#  dns_poison          payments.internal -> the decommissioned instance, long TTL
#                      (in the zone, or as a forgotten hosts.json override)
#  dns_record_missing  fx.internal deleted from the zone, or renamed with a typo
source "$(dirname "$0")/lib.sh"
require_state
[[ -f "$STATE/broken" ]] && die "already broken (make down && make up to start over)"
[[ -n "$(svc_identity api || true)" ]] || die "stack not running: make up"

"$PY" - "$ZONE" "$POISON_VARIANT" "$FX_VARIANT" "$POISON_TTL" "$LEGACY_IP" <<'PY'
import re, sys
path, poison, fxv, ttl, legacy = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
z = open(path).read()
if poison == 0:
    z = re.sub(r"^payments\.internal\s+\d+\s+A\s+\S+", f"payments.internal   {ttl}  A  {legacy}   # migration rollback, see CHG-4411", z, flags=re.M)
if fxv == 0:
    z = re.sub(r"^fx\.internal.*\n", "", z, flags=re.M)
else:
    z = re.sub(r"^fx\.internal", "fx.interal ", z, flags=re.M)
z = re.sub(r"^\$SERIAL (\d+)", lambda m: f"$SERIAL {int(m.group(1)) + 1}", z, flags=re.M)
open(path, "w").write(z)
PY
if [[ "$POISON_VARIANT" == 1 ]]; then
  printf '{"payments.internal": "%s"}\n' "$LEGACY_IP" > "$CONF/hosts.json"
fi
sed -n 's/^\$SERIAL //p' "$ZONE" > "$STATE/break_serial"

dns_reload >/dev/null
config_apply
api_flush >/dev/null   # pretend the old answers expired long ago
snapshot "$STATE/baseline.tsv"
touch "$STATE/broken"
timeline "break"
log "incident started: checkout fails. Clock is running."
log "evidence: make call | make dig N=<name> | make resolve N=<name> | make zone | make logs S=api|dns"
