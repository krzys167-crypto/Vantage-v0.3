#!/usr/bin/env bash
# CI only: turn the tail of a failed self-test log (plus the cluster's view on
# k3d) into a GitHub error annotation. Annotations are readable from the check
# run itself, so a failure can be diagnosed even when the job log is not
# downloadable.
#   bash framework/ci_annotate.sh <log> [title]
log="${1:?log}"; title="${2:-self-test failed}"
{
  tail -n 40 "$log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g'
  if command -v kubectl >/dev/null && kubectl config current-context >/dev/null 2>&1; then
    echo "--- pods"
    kubectl get pods -A --no-headers 2>/dev/null | grep -v kube-system | head -20
    echo "--- warning events"
    kubectl get events -A --field-selector type=Warning --no-headers 2>/dev/null | tail -10
  fi
} > "${log}.summary"
# one annotation, newlines encoded as GitHub expects (%, CR, LF)
msg="$(sed -e 's/%/%25/g' -e 's/\r/%0D/g' "${log}.summary" | awk '{printf "%s%%0A", $0}')"
echo "::error title=${title}::${msg}"
