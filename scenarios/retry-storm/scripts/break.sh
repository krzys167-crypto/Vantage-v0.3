#!/usr/bin/env bash
# Inject the per-user faults, as two "harmless" changes that went out the same day:
#  cpu_throttle         inventory capacity cut to a quarter (worker pool or CPU limit)
#  retry_amplification  api: short timeout, many immediate retries, no jitter
# then a short traffic burst (a marketing push) tips the system over. The
# retries keep it down after the burst ends: a metastable failure.
source "$(dirname "$0")/lib.sh"
require_state
[[ -f "$STATE/broken" ]] && die "already broken (make down && make up to start over)"
[[ -n "$(svc_identity api || true)" ]] || die "stack not running: make up"

cp "$CONF/inventory.json" "$HIST/inventory.json.prev"
cp "$CONF/api.json" "$HIST/api.json.prev"
"$PY" - "$CONF" "$THROTTLE_VARIANT" "$RETRY_VARIANT" <<'PY'
import json, sys
conf, throttle, retry = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
inv = json.load(open(f"{conf}/inventory.json"))
if throttle == 0:
    inv["workers"] = 2                  # "right-sizing" the pool
else:
    inv["cpu_millicores"] = 500         # CPU limit halved: fewer slots, slower work
json.dump(inv, open(f"{conf}/inventory.json", "w"))
api = json.load(open(f"{conf}/api.json"))
if retry == 0:
    api.update(timeout_ms=120, retries=7, backoff_ms=0)
else:
    api.update(timeout_ms=150, retries=6, backoff_ms=0, jitter=False)
json.dump(api, open(f"{conf}/api.json", "w"))
PY
cat > "$HIST/CHANGELOG.md" <<EOT
# Change log (inventory, api)

- CHG-$CHG   inventory: $([[ "$THROTTLE_VARIANT" == 0 ]] && echo "worker pool right-sized 8 -> 2 (cost review, avg utilisation 20%)" || echo "CPU limit 1000m -> 500m (cost review, avg utilisation 20%)")
- CHG-$(( CHG + 1 ))   api: "fail fast, retry harder" - timeout and retry policy tightened after a slow-checkout complaint
- CHG-$(( CHG + 2 ))   marketing push scheduled (short traffic spike, about 3x)

Previous versions: inventory.json.prev, api.json.prev
EOT
config_apply
in_net <<'PY' >/dev/null
import urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
op.open("http://loadgen:8099/burst?seconds=8&factor=3", timeout=5).read()
PY
snapshot "$STATE/baseline.tsv"
incident_started
log "incident started: checkouts time out. Clock is running."
log "evidence: make call | make metrics | make logs S=api|inventory | .state/config/history/"
