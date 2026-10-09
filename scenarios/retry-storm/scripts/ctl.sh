#!/usr/bin/env bash
# Operator commands used by the Makefile.
#   up | down | status | logs <svc> [s] | call | metrics [window_s] | apply
source "$(dirname "$0")/lib.sh"
case "${1:-status}" in
  up)      scenario_up ;;
  down)    scenario_down ;;
  status)  scenario_status ;;
  logs)    require_state; svc_logs "${2:?service: ${SERVICES[*]}}" "${3:-600}" ;;
  call)    require_state; in_net <<'PY'
import time, urllib.request, urllib.error
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
t0 = time.time()
try:
    r = op.open("http://api:8080/checkout", timeout=10); print(r.status, r.read().decode(), end=" ")
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode(), end=" ")
print(f"({(time.time() - t0) * 1000:.0f} ms)")
PY
  ;;
  metrics) require_state; metrics "${2:-30}" | "$PY" -m json.tool ;;
  apply)   require_state; config_apply; timeline "apply config"
           log "$(is_k8s && echo 'svc-config applied, inventory+api rolled' || echo 'docker: config files are live (re-read twice a second)')" ;;
  *) die "usage: ctl.sh up|down|status|logs|call|metrics [window_s]|apply" ;;
esac
