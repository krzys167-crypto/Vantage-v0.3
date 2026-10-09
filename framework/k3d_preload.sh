#!/usr/bin/env bash
# Pull the scenario images once on the host (with retries) and import them into
# the k3d cluster, so pods never pull from the registry themselves. A registry
# hiccup inside the cluster shows up as a pod stuck in ImagePullBackOff and a
# rollout that waits for minutes; on the host it is three quick retries.
#   bash framework/k3d_preload.sh [cluster]       (default: vantage)
set -euo pipefail
cluster="${1:-vantage}"
images=("${NGINX_IMAGE:-mirror.gcr.io/library/nginx:1.27-alpine}" "${PYTHON_IMAGE:-mirror.gcr.io/library/python:3.12-alpine}")
for img in "${images[@]}"; do
  for i in 1 2 3 4; do
    docker pull -q "$img" && break
    [[ $i == 4 ]] && { echo "xx could not pull $img" >&2; exit 1; }
    echo "!! pull of $img failed (attempt $i/4), retrying in $(( i * 5 ))s" >&2; sleep $(( i * 5 ))
  done
done
k3d image import -c "$cluster" "${images[@]}"
