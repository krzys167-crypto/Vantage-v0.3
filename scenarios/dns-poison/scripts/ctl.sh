#!/usr/bin/env bash
# Operator commands used by the Makefile.
#   up | down | status | logs <svc> [s] | call | dig <name> | resolve <name> | zone | reload | flush | apply
source "$(dirname "$0")/lib.sh"
q() { in_net "$@"; }
case "${1:-status}" in
  up)     scenario_up ;;
  down)   scenario_down ;;
  status) scenario_status ;;
  logs)   require_state; svc_logs "${2:?service: ${SERVICES[*]}}" "${3:-600}" ;;
  call)   require_state; q <<'PY'
import urllib.request, urllib.error
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    r = op.open("http://api:8080/checkout", timeout=5); print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
PY
  ;;
  dig)    require_state; q "${2:?name}" <<'PY'
import sys
sys.path.insert(0, "/app")
import dnslib
r = dnslib.query("dns", sys.argv[1])
print(f"{sys.argv[1]}  rcode={'NOERROR' if r['rcode'] == 0 else 'NXDOMAIN'}  A={r['ips']}  ttl={r['ttl']}")
PY
  ;;
  resolve) require_state; q "${2:?name}" <<'PY'
import sys, urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
print(op.open(f"http://api:8080/debug/resolve?name={sys.argv[1]}", timeout=3).read().decode())
PY
  ;;
  zone)   require_state; q <<'PY'
import json, urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
print(json.dumps(json.load(op.open("http://dns:8053/zone", timeout=3)), indent=1))
PY
  ;;
  reload) require_state; dns_reload; timeline "dns reload" ;;
  flush)  require_state; api_flush; timeline "api dns flush" ;;
  apply)  require_state; config_apply; timeline "apply config"
          log "$(is_k8s && echo 'svc-config applied, api rolled' || echo 'docker: config files are live')" ;;
  *) die "usage: ctl.sh up|down|status|logs|call|dig|resolve|zone|reload|flush|apply" ;;
esac
