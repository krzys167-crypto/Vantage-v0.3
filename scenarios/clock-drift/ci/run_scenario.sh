#!/usr/bin/env bash
# Scenario self-test for CI: up -> break -> verify it is broken -> reference fix
# -> wait for the stability window -> assertions -> score -> down.
source "$(dirname "$0")/../scripts/lib.sh"
cd "$SCN_DIR"
export STABLE_WINDOW="${STABLE_WINDOW:-20}" RESET=1
trap 'make -s down >/dev/null 2>&1 || true' EXIT

make -s up
sleep 3
make -s break
sleep 5
log "expect public assertions to FAIL while broken"
if bash ci/assertions.sh >/dev/null; then die "scenario not broken: assertions pass after break"; fi
sleep 10   # simulated diagnosis time
bash solution/fix.sh
log "waiting ${STABLE_WINDOW}s + margin for the stability window"
sleep $(( STABLE_WINDOW + 8 ))   # +margin: on k3d the old api pod drains after the rollout
bash ci/assertions.sh
"$PY" ../../framework/score.py .
