#!/usr/bin/env bash
# Graded run: flush the last probes, stop the agent, let the grader score and sign.
#   framework/submit.sh <scenario_dir>      (run `make assert` first)
SCN_DIR="$(cd "${1:?scenario dir}" && pwd)"
source "$SCN_DIR/scripts/lib.sh"
require_state
grader_enabled || die "GRADER_URL is not set: this is a practice run, use 'make score'"
[[ -f "$STATE/attempt.json" ]] || die "no graded attempt: run 'make clean' and start again with GRADER_URL set"
[[ -f "$STATE/assertions.json" ]] || die "run 'make assert' first"
evidence_sync
grader push "$STATE"
grader_agent_stop
grader submit "$SCN_DIR"
