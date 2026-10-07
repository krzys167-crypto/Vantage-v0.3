#!/usr/bin/env bash
# Stop the scenario. State (.state/) is kept for the debrief; `make clean` removes it.
source "$(dirname "$0")/lib.sh"
[[ -f "$STATE/scenario.env" ]] || exit 0
require_state
if is_k8s; then
  kubectl --context "$KUBE_CONTEXT" delete ns "$NS" --ignore-not-found --wait=true --timeout=120s >/dev/null
else
  "${COMPOSE[@]}" down -t 2 --remove-orphans
fi
rm -f "$STATE/broken"
