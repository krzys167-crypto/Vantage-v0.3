#!/usr/bin/env bash
# Runtime-agnostic operator commands used by the Makefile.
#   ctl.sh status | logs <svc> [since_s] | apply
source "$(dirname "$0")/lib.sh"
require_state
case "${1:-status}" in
  status)
    if is_k8s; then "${KUBE[@]}" get deploy,pods -o wide
    else "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'; fi
    evidence_sync
    tail -n 10 "$EVID/probes.jsonl" 2>/dev/null || true ;;
  logs)  svc_logs "${2:?service: gateway|backend|prober}" "${3:-600}" ;;
  apply) gateway_apply; timeline "apply"; log "gateway now serves .state/pki/gateway/*" ;;
  *) die "usage: ctl.sh status|logs <svc> [since_s]|apply" ;;
esac
