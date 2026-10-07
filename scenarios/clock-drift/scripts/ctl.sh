#!/usr/bin/env bash
# Operator commands used by the Makefile:
#   up | down | status | logs <svc> [since_s] | apply | time
source "$(dirname "$0")/lib.sh"
case "${1:-status}" in
  up)     scenario_up ;;
  down)   scenario_down ;;
  status) scenario_status ;;
  logs)   require_state; svc_logs "${2:?service: ${SERVICES[*]}}" "${3:-600}" ;;
  apply)  require_state; svc_apply auth api; timeline "apply"
          log "$(is_k8s && echo 'ConfigMaps/Secrets updated, auth+api rolled' || echo 'docker: files are live, nothing to reload')" ;;
  time)   require_state
          for s in auth api; do echo "[$s]"; bash "$SCN_DIR/scripts/chronyc.sh" "$s" tracking | sed -n 2,3p; done ;;
  *) die "usage: ctl.sh up|down|status|logs <svc> [since_s]|apply|time" ;;
esac
