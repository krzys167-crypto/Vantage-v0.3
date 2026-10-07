#!/usr/bin/env bash
# Operator commands used by the Makefile: up | down | status | logs <svc> [since_s] | apply
source "$(dirname "$0")/lib.sh"
case "${1:-status}" in
  up)     scenario_up ;;
  down)   scenario_down ;;
  status) scenario_status ;;
  logs)   require_state; svc_logs "${2:?service: ${SERVICES[*]}}" "${3:-600}" ;;
  apply)  require_state; gateway_apply; timeline "apply"; log "gateway now serves .state/pki/gateway/*" ;;
  *) die "usage: ctl.sh up|down|status|logs <svc> [since_s]|apply" ;;
esac
