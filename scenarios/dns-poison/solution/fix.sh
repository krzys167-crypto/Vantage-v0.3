#!/usr/bin/env bash
# SPOILER: reference remediation, used by CI to prove the scenario is solvable.
# It diagnoses instead of reading the fault list, so it works for every seed.
source "$(dirname "$0")/../scripts/lib.sh"
require_state

# 1. Source of truth: drop static overrides, they bypass DNS entirely.
if [[ "$(tr -d ' \n' < "$CONF/hosts.json")" != "{}" ]]; then
  log "hosts.json carries overrides -> remove"
  printf '{}\n' > "$CONF/hosts.json"
  config_apply
fi

# 2. Zone: payments to the live instance with a sane TTL, fx present and spelled
#    right, nothing pointing at the legacy box, serial bumped so the dns accepts it.
"$PY" - "$ZONE" "$PAY_IP" "$FX_IP" "$LEGACY_IP" <<'PY'
import re, sys
path, pay, fx, legacy = sys.argv[1:]
lines = [l for l in open(path).read().splitlines()
         if not re.match(r"^(payments|fx)\.inter\w*\s", l) and legacy not in l]
lines += [f"payments.internal   300  A  {pay}", f"fx.internal         300  A  {fx}"]
z = "\n".join(lines) + "\n"
z = re.sub(r"^\$SERIAL (\d+)", lambda m: f"$SERIAL {int(m.group(1)) + 1}", z, flags=re.M)
open(path, "w").write(z)
PY
log "zone fixed, serial bumped -> reload"
dns_reload

# 3. The api still holds the poisoned answer and the NXDOMAIN in its cache.
log "flush api resolver cache"; api_flush
timeline "fix (reference solution)"
