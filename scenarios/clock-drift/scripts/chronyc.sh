#!/usr/bin/env bash
# Minimal chronyc for the scenario hosts.
#   chronyc.sh <svc> tracking   offset of the service clock vs reference time
#   chronyc.sh <svc> makestep   step the clock to the reference (fixes drift)
source "$(dirname "$0")/lib.sh"
require_state
svc="${1:?service: auth|api}"; cmd="${2:-tracking}"
[[ "$svc" == auth || "$svc" == api ]] || die "no chrony on $svc"
port=$([[ "$svc" == auth ]] && echo 8081 || echo 8080)

case "$cmd" in
  tracking)
    svc_exec prober python - "$svc" "$port" <<'PY'
import json, sys, time, urllib.request
svc, port = sys.argv[1], sys.argv[2]
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
t0 = time.time(); remote = json.load(op.open(f"http://{svc}:{port}/debug/time", timeout=3))["time"]; t1 = time.time()
off = remote - (t0 + t1) / 2
print(f"Reference ID    : ntp.vantage.internal\n"
      f"System time     : {abs(off):.6f} seconds {'fast' if off > 0 else 'slow'} of NTP time\n"
      f"Leap status     : {'Normal' if abs(off) < 1 else 'Not synchronised'}")
PY
    ;;
  makestep)
    printf '0' > "$CLOCK/$svc"
    svc_apply "$svc"
    timeline "chrony makestep $svc"
    log "$svc: clock stepped to reference time" ;;
  *) die "usage: chronyc.sh <svc> tracking|makestep" ;;
esac
