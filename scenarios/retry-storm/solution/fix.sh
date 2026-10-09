#!/usr/bin/env bash
# SPOILER: reference remediation, used by CI to prove the scenario is solvable.
# It diagnoses instead of reading the fault list, so it works for every seed.
source "$(dirname "$0")/../scripts/lib.sh"
require_state

# 1. Capacity: whatever the change log says was cut (pool size or CPU limit),
#    restore it from the last known good version.
# 2. Retry policy: a bounded number of retries with exponential backoff and
#    jitter, and a timeout above the service's real latency. Retrying faster
#    than the server recovers is what keeps the storm alive.
"$PY" - "$CONF" "$HIST" <<'PY'
import json, sys
conf, hist = sys.argv[1], sys.argv[2]
inv, prev = json.load(open(f"{conf}/inventory.json")), json.load(open(f"{hist}/inventory.json.prev"))
for k in ("workers", "cpu_millicores"):
    if inv.get(k, 0) < prev.get(k, 0):
        print(f"inventory {k} {inv[k]} -> {prev[k]} (restored)")
        inv[k] = prev[k]
json.dump(inv, open(f"{conf}/inventory.json", "w"))
api = json.load(open(f"{conf}/api.json"))
api.update(timeout_ms=1000, retries=2, backoff_ms=100, jitter=True, fallback_static=False)
print(f"api retry policy -> {api}")
json.dump(api, open(f"{conf}/api.json", "w"))
PY
config_apply
timeline "fix (reference solution)"
